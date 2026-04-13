/**
 * Circuit Breaker — Cosmos DB 기반 상태 머신.
 *
 * {channel}:{provider} 조합별 독립 Circuit Breaker를 운용한다.
 * 상태 머신: Closed → Open → Half-Open → Closed/Open.
 * ETag 기반 낙관적 동시성 제어를 적용한다.
 *
 * SPEC.md §4.3 참조.
 */

import type { Container } from '@azure/cosmos';
import type { CircuitBreakerDocument } from '../models/circuit-breaker';
import { CircuitState } from '../models/circuit-breaker';
import type { Settings } from '../shared/config';
import { getLogger, logWithContext } from '../shared/logger';
import { getCircuitBreakerContainer } from './cosmos-client';

const logger = getLogger('circuit-breaker');

const MAX_ETAG_RETRIES = 3;

export class CircuitOpenError extends Error {
  readonly circuitId: string;

  constructor(circuitId: string) {
    super(`Circuit open: ${circuitId}`);
    this.name = 'CircuitOpenError';
    this.circuitId = circuitId;
  }
}

function nowIso(): string {
  return new Date().toISOString();
}

function isEtagConflict(err: unknown): boolean {
  return (
    typeof err === 'object' &&
    err !== null &&
    'code' in err &&
    (err as { code: number }).code === 412
  );
}

export class CircuitBreaker {
  private readonly settings: Settings;
  private readonly container: Container;

  constructor(settings: Settings) {
    this.settings = settings;
    this.container = getCircuitBreakerContainer(settings);
  }

  private makeCircuitId(channel: string, provider: string): string {
    return `${channel}:${provider}`;
  }

  private async readState(circuitId: string): Promise<CircuitBreakerDocument> {
    try {
      const { resource } = await this.container.item(circuitId, circuitId).read();
      return resource as CircuitBreakerDocument;
    } catch (err: unknown) {
      if (typeof err === 'object' && err !== null && 'code' in err && (err as { code: number }).code === 404) {
        return {
          id: circuitId,
          state: CircuitState.CLOSED,
          failure_count: 0,
          success_count: 0,
          last_failure_at: null,
          opened_at: null,
          updated_at: nowIso(),
        };
      }
      throw err;
    }
  }

  private async saveState(doc: CircuitBreakerDocument): Promise<CircuitBreakerDocument> {
    const options: Record<string, unknown> = {};
    if (doc._etag) {
      options.accessCondition = { type: 'IfMatch', condition: doc._etag };
    }

    const { resource } = await this.container.items.upsert(doc, options);
    return resource as unknown as CircuitBreakerDocument;
  }

  private isCooldownExpired(doc: CircuitBreakerDocument): boolean {
    if (!doc.opened_at) return true;
    const elapsed = Date.now() - new Date(doc.opened_at).getTime();
    return elapsed >= this.settings.CB_COOLDOWN_MS;
  }

  async checkState(channel: string, provider: string): Promise<CircuitState> {
    const circuitId = this.makeCircuitId(channel, provider);

    for (let attempt = 0; attempt < MAX_ETAG_RETRIES; attempt++) {
      const doc = await this.readState(circuitId);

      if (doc.state === CircuitState.CLOSED) return CircuitState.CLOSED;
      if (doc.state === CircuitState.HALF_OPEN) return CircuitState.HALF_OPEN;

      // Open 상태
      if (!this.isCooldownExpired(doc)) {
        throw new CircuitOpenError(circuitId);
      }

      // cooldown 만료 → Half-Open 전환
      const oldState = doc.state;
      doc.state = CircuitState.HALF_OPEN;
      doc.success_count = 0;
      doc.updated_at = nowIso();

      try {
        await this.saveState(doc);
        logStateChange(circuitId, oldState, CircuitState.HALF_OPEN);
        return CircuitState.HALF_OPEN;
      } catch (err: unknown) {
        if (isEtagConflict(err) && attempt < MAX_ETAG_RETRIES - 1) continue;
        throw err;
      }
    }

    return CircuitState.HALF_OPEN;
  }

  async recordSuccess(channel: string, provider: string): Promise<void> {
    const circuitId = this.makeCircuitId(channel, provider);

    for (let attempt = 0; attempt < MAX_ETAG_RETRIES; attempt++) {
      const doc = await this.readState(circuitId);

      if (doc.state === CircuitState.CLOSED) {
        if (doc.failure_count > 0) {
          doc.failure_count = 0;
          doc.updated_at = nowIso();
          try {
            await this.saveState(doc);
          } catch (err: unknown) {
            if (isEtagConflict(err) && attempt < MAX_ETAG_RETRIES - 1) continue;
            throw err;
          }
        }
        return;
      }

      if (doc.state === CircuitState.HALF_OPEN) {
        doc.success_count += 1;
        doc.updated_at = nowIso();

        if (doc.success_count >= this.settings.CB_SUCCESS_THRESHOLD) {
          const oldState = doc.state;
          doc.state = CircuitState.CLOSED;
          doc.failure_count = 0;
          doc.success_count = 0;
          doc.opened_at = null;

          try {
            await this.saveState(doc);
            logStateChange(circuitId, oldState, CircuitState.CLOSED);
          } catch (err: unknown) {
            if (isEtagConflict(err) && attempt < MAX_ETAG_RETRIES - 1) continue;
            throw err;
          }
        } else {
          try {
            await this.saveState(doc);
          } catch (err: unknown) {
            if (isEtagConflict(err) && attempt < MAX_ETAG_RETRIES - 1) continue;
            throw err;
          }
        }
        return;
      }

      // Open 상태에서 success는 무시
      return;
    }
  }

  async recordFailure(channel: string, provider: string): Promise<void> {
    const circuitId = this.makeCircuitId(channel, provider);

    for (let attempt = 0; attempt < MAX_ETAG_RETRIES; attempt++) {
      const doc = await this.readState(circuitId);

      const now = nowIso();
      doc.failure_count += 1;
      doc.last_failure_at = now;
      doc.updated_at = now;

      if (doc.state === CircuitState.CLOSED) {
        if (doc.failure_count >= this.settings.CB_FAILURE_THRESHOLD) {
          const oldState = doc.state;
          doc.state = CircuitState.OPEN;
          doc.opened_at = now;
          doc.success_count = 0;

          try {
            await this.saveState(doc);
            logStateChange(circuitId, oldState, CircuitState.OPEN);
          } catch (err: unknown) {
            if (isEtagConflict(err) && attempt < MAX_ETAG_RETRIES - 1) continue;
            throw err;
          }
        } else {
          try {
            await this.saveState(doc);
          } catch (err: unknown) {
            if (isEtagConflict(err) && attempt < MAX_ETAG_RETRIES - 1) continue;
            throw err;
          }
        }
        return;
      }

      if (doc.state === CircuitState.HALF_OPEN) {
        const oldState = doc.state;
        doc.state = CircuitState.OPEN;
        doc.opened_at = now;
        doc.success_count = 0;

        try {
          await this.saveState(doc);
          logStateChange(circuitId, oldState, CircuitState.OPEN);
        } catch (err: unknown) {
          if (isEtagConflict(err) && attempt < MAX_ETAG_RETRIES - 1) continue;
          throw err;
        }
        return;
      }

      // Open 상태에서 failure는 카운트만 갱신
      try {
        await this.saveState(doc);
      } catch (err: unknown) {
        if (isEtagConflict(err) && attempt < MAX_ETAG_RETRIES - 1) continue;
        throw err;
      }
      return;
    }
  }
}

function logStateChange(circuitId: string, fromState: CircuitState, toState: CircuitState): void {
  const [channel, provider] = circuitId.split(':');
  logWithContext(logger, 'WARNING', 'Circuit Breaker 상태 변경', {
    circuit_id: circuitId,
    channel,
    provider,
    from_state: fromState,
    to_state: toState,
    status: toState,
  });
}
