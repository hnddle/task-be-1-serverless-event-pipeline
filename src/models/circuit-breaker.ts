/**
 * Circuit Breaker 상태 타입.
 *
 * Cosmos DB `circuit-breaker` 컨테이너 문서 구조와 1:1 대응.
 * SPEC.md §3.3 참조.
 */

export const CircuitState = {
  CLOSED: 'closed',
  OPEN: 'open',
  HALF_OPEN: 'half-open',
} as const;
export type CircuitState = (typeof CircuitState)[keyof typeof CircuitState];

export interface CircuitBreakerDocument {
  id: string;
  state: CircuitState;
  failure_count: number;
  success_count: number;
  last_failure_at: string | null;
  opened_at: string | null;
  updated_at: string;
  _etag?: string;
}
