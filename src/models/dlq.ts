/**
 * Dead Letter Queue 관련 타입.
 *
 * Cosmos DB `dead-letter-queue` 컨테이너 문서 구조와 1:1 대응.
 * SPEC.md §3.2 참조.
 */

export const ReplayStatus = {
  PENDING: 'pending',
  REPLAYED: 'replayed',
  PERMANENTLY_FAILED: 'permanently_failed',
} as const;
export type ReplayStatus = (typeof ReplayStatus)[keyof typeof ReplayStatus];

export interface DeadLetterDocument {
  id: string;
  original_event_id: string;
  clinic_id: string;
  channel: string;
  provider: string;
  event_type: string;
  patient_id: string;
  payload: Record<string, unknown>;
  failure_reason: string;
  retry_count: number;
  correlation_id: string;
  created_at: string;
  replay_status: ReplayStatus;
  replayed_at: string | null;
}
