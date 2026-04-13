/**
 * 재시도 서비스 — 지수 백오프.
 *
 * 알림 발송 실패 시 in-process 지수 백오프 재시도를 수행한다.
 * 재시도 간격: RETRY_BASE_DELAY_MS * (RETRY_BACKOFF_MULTIPLIER ** retry_count)
 *
 * SPEC.md §6.1 참조.
 */

import type { Settings } from '../shared/config';
import { getLogger, logWithContext } from '../shared/logger';

const logger = getLogger('retry-service');

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class MaxRetryExceededError extends Error {
  readonly retryCount: number;
  readonly lastError: string;

  constructor(retryCount: number, lastError: string) {
    super(`Max retries (${retryCount}) exceeded: ${lastError}`);
    this.name = 'MaxRetryExceededError';
    this.retryCount = retryCount;
    this.lastError = lastError;
  }
}

export function calculateDelayMs(
  retryCount: number,
  baseDelayMs: number,
  backoffMultiplier: number,
): number {
  return Math.floor(baseDelayMs * Math.pow(backoffMultiplier, retryCount));
}

export class RetryService {
  private readonly maxRetries: number;
  private readonly baseDelayMs: number;
  private readonly backoffMultiplier: number;

  constructor(settings: Settings) {
    this.maxRetries = settings.MAX_RETRY_COUNT;
    this.baseDelayMs = settings.RETRY_BASE_DELAY_MS;
    this.backoffMultiplier = settings.RETRY_BACKOFF_MULTIPLIER;
  }

  async executeWithRetry<T>(
    fn: () => Promise<T>,
    context?: Record<string, string>,
  ): Promise<T> {
    const ctx = context ?? {};
    let lastError = '';

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        return await fn();
      } catch (err: unknown) {
        lastError = err instanceof Error ? err.message : String(err);

        if (attempt >= this.maxRetries) break;

        const delayMs = calculateDelayMs(attempt, this.baseDelayMs, this.backoffMultiplier);

        logWithContext(logger, 'WARNING', '재시도 수행', {
          retry_count: attempt + 1,
          next_delay_ms: delayMs,
          error: lastError,
          ...ctx,
        });

        await sleep(delayMs);
      }
    }

    throw new MaxRetryExceededError(this.maxRetries, lastError);
  }
}
