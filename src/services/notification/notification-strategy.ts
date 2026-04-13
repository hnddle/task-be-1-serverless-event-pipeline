/**
 * 알림 발송 Strategy 인터페이스.
 *
 * 채널(email, sms, webhook)별 발송 전략을 추상화한다.
 * SPEC.md §4.2 참조.
 */

export interface NotificationResult {
  success: boolean;
  channel: string;
  provider: string;
  message: string;
  duration_ms: number;
}

export interface NotificationStrategy {
  send(notification: Record<string, unknown>): Promise<NotificationResult>;
  getChannelName(): string;
  getProviderName(): string;
}
