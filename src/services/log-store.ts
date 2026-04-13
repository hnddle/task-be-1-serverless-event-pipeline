/**
 * 구조화 로그를 Cosmos DB logs 컨테이너에 저장하는 서비스.
 *
 * 순환 의존성 방지를 위해 logger.ts와 cosmos-client.ts 사이에 위치한다.
 * logger.ts는 이 모듈의 persistLog()만 호출하고,
 * Container 참조는 index.ts에서 initLogStore()로 주입한다.
 *
 * 저장 실패 시 stdout 경고만 출력하고 에러를 전파하지 않는다 (fire-and-forget).
 */

import type { Container } from '@azure/cosmos';
import { v4 as uuidv4 } from 'uuid';

let _logsContainer: Container | null = null;

/** logs 컨테이너 참조를 주입한다. index.ts에서 호출. */
export function initLogStore(container: Container): void {
  _logsContainer = container;
}

export interface LogDocument {
  id: string;
  timestamp: string;
  correlation_id: string;
  message: string;
  logger: string;
  event_id?: string;
  event_type?: string;
  channel?: string;
  provider?: string;
  status?: string;
  duration_ms?: number;
  [key: string]: unknown;
}

/**
 * 로그를 Cosmos DB에 비동기 저장한다 (fire-and-forget).
 * 저장 실패 시 stdout으로 경고만 출력한다.
 */
export function persistLog(entry: Record<string, unknown>): void {
  if (!_logsContainer) return;

  const doc: LogDocument = {
    id: uuidv4(),
    timestamp: (entry.timestamp as string) ?? new Date().toISOString(),
    correlation_id: (entry.correlation_id as string) ?? 'system',
    message: (entry.message as string) ?? '',
    logger: (entry.logger as string) ?? 'unknown',
  };

  // 선택 필드: 존재하는 것만 포함
  const optionalFields = [
    'level', 'event_id', 'event_type', 'channel', 'provider',
    'status', 'duration_ms', 'circuit_state', 'retry_count',
    'error', 'dlq_id', 'original_event_id', 'original_correlation_id',
    'new_correlation_id', 'broker_name', 'from_state', 'to_state',
    'wait_ms', 'current_rate', 'next_delay_ms', 'clinic_id',
    'final_status', 'total_channels', 'processed', 'skipped', 'total',
    'circuit_id', 'limiter_id', 'backoff_ms', 'waited_ms',
    'failure_reason', 'total_retry_count', 'patient_id',
  ];

  for (const field of optionalFields) {
    if (entry[field] != null) {
      (doc as Record<string, unknown>)[field] = entry[field];
    }
  }

  _logsContainer.items.create(doc).catch((err) => {
    // eslint-disable-next-line no-console
    console.warn(`[log-store] Cosmos DB 로그 저장 실패: ${String(err)}`);
  });
}

/** 테스트용 — 컨테이너 참조 리셋 */
export function _resetLogStore(): void {
  _logsContainer = null;
}
