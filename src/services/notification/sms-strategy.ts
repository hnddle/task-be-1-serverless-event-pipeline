/**
 * SMS 알림 Mock 발송 Strategy.
 *
 * 실제 발송 대신 랜덤 딜레이 후 성공을 반환한다.
 * SPEC.md §4.2 참조.
 */

import type { Settings } from '../../shared/config';
import { getLogger, logWithContext } from '../../shared/logger';
import type { NotificationResult, NotificationStrategy } from './notification-strategy';

const logger = getLogger('sms-strategy');

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

export class SmsStrategy implements NotificationStrategy {
  private readonly provider: string;
  private readonly delayMinMs: number;
  private readonly delayMaxMs: number;

  constructor(settings: Settings) {
    this.provider = settings.NOTIFICATION_SMS_PROVIDER;
    this.delayMinMs = settings.MOCK_DELAY_MIN_MS;
    this.delayMaxMs = settings.MOCK_DELAY_MAX_MS;
  }

  async send(notification: Record<string, unknown>): Promise<NotificationResult> {
    const delayMs = randomInt(this.delayMinMs, this.delayMaxMs);
    const start = performance.now();

    await sleep(delayMs);

    const durationMs = Math.round((performance.now() - start) * 100) / 100;

    logWithContext(logger, 'INFO', 'SMS Mock 발송 완료', {
      channel: 'sms',
      provider: this.provider,
      delay_ms: delayMs,
      duration_ms: durationMs,
      event_id: (notification.event_id as string) ?? 'unknown',
    });

    return {
      success: true,
      channel: 'sms',
      provider: this.provider,
      message: `Mock SMS sent (delay: ${delayMs}ms)`,
      duration_ms: durationMs,
    };
  }

  getChannelName(): string {
    return 'sms';
  }

  getProviderName(): string {
    return this.provider;
  }
}
