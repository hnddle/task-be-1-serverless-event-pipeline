/**
 * Notification Strategy 팩토리.
 *
 * 채널 이름에 따라 적절한 NotificationStrategy 구현체를 생성한다.
 * SPEC.md §4.2 참조.
 */

import type { Settings } from '../../shared/config';
import { getLogger } from '../../shared/logger';
import { EmailStrategy } from './email-strategy';
import type { NotificationResult, NotificationStrategy } from './notification-strategy';
import { SmsStrategy } from './sms-strategy';
import { WebhookStrategy } from './webhook-strategy';

const logger = getLogger('notification-factory');

const SUPPORTED_CHANNELS = new Set(['email', 'sms', 'webhook']);

export class NotificationFactory {
  private readonly settings: Settings;

  constructor(settings: Settings) {
    this.settings = settings;
  }

  create(channel: string): NotificationStrategy {
    if (channel === 'email') return new EmailStrategy(this.settings);
    if (channel === 'sms') return new SmsStrategy(this.settings);
    if (channel === 'webhook') return new WebhookStrategy(this.settings);

    const supported = [...SUPPORTED_CHANNELS].sort().join(', ');
    throw new Error(`지원하지 않는 채널: '${channel}'. 지원: ${supported}`);
  }

  async sendNotification(
    channel: string,
    notification: Record<string, unknown>,
  ): Promise<NotificationResult> {
    try {
      const strategy = this.create(channel);
      return await strategy.send(notification);
    } catch {
      logger.error(`지원하지 않는 채널: ${channel}`);
      return {
        success: false,
        channel,
        provider: 'unknown',
        message: `Unsupported channel: ${channel}`,
        duration_ms: 0,
      };
    }
  }
}
