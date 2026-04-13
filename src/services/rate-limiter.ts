/**
 * Rate Limiter — Token Bucket 알고리즘.
 *
 * {channel}:{provider} 조합별 독립 Rate Limiter를 운용한다.
 * Cosmos DB `rate-limiter` 컨테이너에 상태를 저장하고 (TTL 60초),
 * ETag 기반 낙관적 동시성 제어를 적용한다.
 *
 * SPEC.md §5 참조.
 */

import type { Container } from '@azure/cosmos';
import type { RateLimiterDocument } from '../models/rate-limiter';
import type { Settings } from '../shared/config';
import { getLogger, logWithContext } from '../shared/logger';
import { getRateLimiterContainer } from './cosmos-client';

const logger = getLogger('rate-limiter');

const MAX_ETAG_RETRIES = 3;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isEtagConflict(err: unknown): boolean {
  return (
    typeof err === 'object' &&
    err !== null &&
    (('statusCode' in err && (err as { statusCode: number }).statusCode === 412) ||
      ('code' in err && (err as { code: number }).code === 412))
  );
}

export class RateLimitExceededError extends Error {
  readonly limiterId: string;

  constructor(limiterId: string) {
    super(`Rate limit exceeded: ${limiterId}`);
    this.name = 'RateLimitExceededError';
    this.limiterId = limiterId;
  }
}

export class RateLimiter {
  private readonly settings: Settings;
  private readonly container: Container;

  constructor(settings: Settings) {
    this.settings = settings;
    this.container = getRateLimiterContainer(settings);
  }

  private makeLimiterId(channel: string, provider: string): string {
    return `${channel}:${provider}`;
  }

  private getMaxTokens(channel: string): number {
    if (channel === 'email') return this.settings.RATE_LIMIT_EMAIL_PER_SEC;
    if (channel === 'sms') return this.settings.RATE_LIMIT_SMS_PER_SEC;
    if (channel === 'webhook') return this.settings.RATE_LIMIT_WEBHOOK_PER_SEC;
    return this.settings.RATE_LIMIT_EMAIL_PER_SEC;
  }

  private defaultBucket(limiterId: string, maxTokens: number): RateLimiterDocument {
    const now = new Date().toISOString();
    return {
      id: limiterId,
      tokens: maxTokens,
      max_tokens: maxTokens,
      last_refill_at: now,
      updated_at: now,
    };
  }

  private async readBucket(
    limiterId: string,
    maxTokens: number,
  ): Promise<RateLimiterDocument> {
    try {
      const { resource } = await this.container.item(limiterId, limiterId).read();
      if (!resource) return this.defaultBucket(limiterId, maxTokens);
      return resource as RateLimiterDocument;
    } catch (err: unknown) {
      const statusCode =
        (err as Record<string, unknown>).statusCode ??
        (err as Record<string, unknown>).code;
      if (statusCode === 404) {
        return this.defaultBucket(limiterId, maxTokens);
      }
      throw err;
    }
  }

  private refillTokens(
    bucket: RateLimiterDocument,
    maxTokens: number,
  ): RateLimiterDocument {
    const lastRefill = new Date(bucket.last_refill_at).getTime();
    const now = Date.now();
    const elapsedSec = (now - lastRefill) / 1000;

    if (elapsedSec > 0) {
      bucket.tokens = Math.min(bucket.tokens + elapsedSec * maxTokens, maxTokens);
      bucket.last_refill_at = new Date(now).toISOString();
    }

    return bucket;
  }

  private async saveBucket(bucket: RateLimiterDocument): Promise<RateLimiterDocument> {
    bucket.updated_at = new Date().toISOString();

    const options: Record<string, unknown> = {};
    if (bucket._etag) {
      options.accessCondition = { type: 'IfMatch', condition: bucket._etag };
    }

    const { resource } = await this.container.items.upsert(bucket, options);
    return resource as unknown as RateLimiterDocument;
  }

  async acquire(channel: string, provider: string): Promise<void> {
    const limiterId = this.makeLimiterId(channel, provider);
    const maxTokens = this.getMaxTokens(channel);
    const maxWaitMs = this.settings.RATE_LIMIT_MAX_WAIT_MS;
    const startTime = performance.now();
    let backoffMs = 100;

    // eslint-disable-next-line no-constant-condition
    while (true) {
      let tokenAvailable = false;

      for (let attempt = 0; attempt < MAX_ETAG_RETRIES; attempt++) {
        let bucket = await this.readBucket(limiterId, maxTokens);
        bucket = this.refillTokens(bucket, maxTokens);

        if (bucket.tokens >= 1.0) {
          bucket.tokens -= 1.0;
          try {
            await this.saveBucket(bucket);
            return; // 토큰 소비 성공
          } catch (err: unknown) {
            if (isEtagConflict(err) && attempt < MAX_ETAG_RETRIES - 1) continue;
            throw err;
          }
        } else {
          tokenAvailable = false;
          break;
        }
      }

      if (tokenAvailable) continue;

      // 토큰 부족 — 대기 시간 확인
      const elapsed = performance.now() - startTime;
      if (elapsed >= maxWaitMs) {
        logWithContext(logger, 'WARNING', 'Rate limit 대기 초과', {
          limiter_id: limiterId,
          waited_ms: Math.round(elapsed),
        });
        throw new RateLimitExceededError(limiterId);
      }

      logWithContext(logger, 'INFO', 'Rate limit 대기', {
        limiter_id: limiterId,
        backoff_ms: backoffMs,
      });
      await sleep(backoffMs);
      backoffMs = Math.min(backoffMs * 2, 2000);
    }
  }
}
