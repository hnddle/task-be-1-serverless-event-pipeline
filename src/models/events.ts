/**
 * Notification Event 관련 타입.
 *
 * Cosmos DB `events` 컨테이너 문서 구조와 1:1 대응.
 * SPEC.md §3.1 참조.
 */

export const EventStatus = {
  QUEUED: 'queued',
  PROCESSING: 'processing',
  COMPLETED: 'completed',
  PARTIALLY_COMPLETED: 'partially_completed',
  FAILED: 'failed',
} as const;
export type EventStatus = (typeof EventStatus)[keyof typeof EventStatus];

export const NotificationChannelType = {
  EMAIL: 'email',
  SMS: 'sms',
  WEBHOOK: 'webhook',
} as const;
export type NotificationChannelType =
  (typeof NotificationChannelType)[keyof typeof NotificationChannelType];

export const NotificationStatus = {
  PENDING: 'pending',
  SUCCESS: 'success',
  FAILED: 'failed',
} as const;
export type NotificationStatus = (typeof NotificationStatus)[keyof typeof NotificationStatus];

export const OutboxStatus = {
  PENDING: 'pending',
  PUBLISHED: 'published',
  FAILED_PUBLISH: 'failed_publish',
} as const;
export type OutboxStatus = (typeof OutboxStatus)[keyof typeof OutboxStatus];

export const EventType = {
  APPOINTMENT_CONFIRMED: 'appointment_confirmed',
  INSURANCE_APPROVED: 'insurance_approved',
  CLAIM_COMPLETED: 'claim_completed',
} as const;
export type EventType = (typeof EventType)[keyof typeof EventType];

export const EVENT_TYPES: readonly string[] = Object.values(EventType);
export const CHANNEL_TYPES: readonly string[] = Object.values(NotificationChannelType);

export interface NotificationChannel {
  channel: NotificationChannelType;
  provider: string;
  status: NotificationStatus;
  sent_at: string | null;
  retry_count: number;
  last_error: string | null;
}

export interface NotificationEvent {
  id: string;
  clinic_id: string;
  status: EventStatus;
  event_type: EventType;
  patient_id: string;
  channels: NotificationChannelType[];
  correlation_id: string;
  notifications: NotificationChannel[];
  created_at: string;
  updated_at: string;
  _outbox_status: OutboxStatus;
}
