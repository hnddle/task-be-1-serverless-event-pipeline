/**
 * Notification Strategy 팩토리 및 Strategy 테스트.
 */

import type { Settings } from '@src/shared/config';
import { EmailStrategy } from '@src/services/notification/email-strategy';
import { SmsStrategy } from '@src/services/notification/sms-strategy';
import { WebhookStrategy } from '@src/services/notification/webhook-strategy';
import { NotificationFactory } from '@src/services/notification/notification-factory';

function makeSettings(overrides: Partial<Settings> = {}): Settings {
  return {
    QUEUE_SERVICE_TYPE: 'EVENT_GRID',
    NOTIFICATION_EMAIL_PROVIDER: 'sendgrid',
    NOTIFICATION_SMS_PROVIDER: 'twilio',
    WEBHOOK_URL: 'https://example.com/webhook',
    COSMOS_DB_ENDPOINT: 'https://localhost:8081',
    COSMOS_DB_KEY: 'test-key',
    COSMOS_DB_DATABASE: 'test-db',
    CB_FAILURE_THRESHOLD: 5,
    CB_COOLDOWN_MS: 30000,
    CB_SUCCESS_THRESHOLD: 2,
    MAX_RETRY_COUNT: 3,
    RETRY_BASE_DELAY_MS: 1000,
    RETRY_BACKOFF_MULTIPLIER: 2,
    RATE_LIMIT_EMAIL_PER_SEC: 10,
    RATE_LIMIT_SMS_PER_SEC: 5,
    RATE_LIMIT_WEBHOOK_PER_SEC: 20,
    RATE_LIMIT_MAX_WAIT_MS: 10000,
    MOCK_DELAY_MIN_MS: 10,
    MOCK_DELAY_MAX_MS: 20,
    EVENT_GRID_TOPIC_ENDPOINT: 'https://test-topic.koreacentral-1.eventgrid.azure.net/api/events',
    EVENT_GRID_TOPIC_KEY: 'test-key',
    ...overrides,
  };
}

const SAMPLE_NOTIFICATION = { event_id: 'test-evt-1', patient_id: 'P-001' };

const settings = makeSettings();

describe('NotificationFactory', () => {
  const factory = new NotificationFactory(settings);

  it('email 채널로 EmailStrategy를 생성한다', () => {
    const strategy = factory.create('email');
    expect(strategy).toBeInstanceOf(EmailStrategy);
  });

  it('sms 채널로 SmsStrategy를 생성한다', () => {
    const strategy = factory.create('sms');
    expect(strategy).toBeInstanceOf(SmsStrategy);
  });

  it('webhook 채널로 WebhookStrategy를 생성한다', () => {
    const strategy = factory.create('webhook');
    expect(strategy).toBeInstanceOf(WebhookStrategy);
  });

  it('지원하지 않는 채널이면 에러가 발생한다', () => {
    expect(() => factory.create('push')).toThrow('지원하지 않는 채널');
  });

  it('3개 채널 전달 시 3개 Strategy 각각 실행된다', async () => {
    const results = [];
    for (const channel of ['email', 'sms', 'webhook']) {
      const result = await factory.sendNotification(channel, SAMPLE_NOTIFICATION);
      results.push(result);
    }

    expect(results).toHaveLength(3);
    expect(results.every((r) => r.success)).toBe(true);
    const channels = new Set(results.map((r) => r.channel));
    expect(channels).toEqual(new Set(['email', 'sms', 'webhook']));
  });

  it('지원하지 않는 채널은 failed 결과를 반환한다', async () => {
    const result = await factory.sendNotification('push', SAMPLE_NOTIFICATION);
    expect(result.success).toBe(false);
    expect(result.channel).toBe('push');
    expect(result.message).toContain('Unsupported');
  });
});

describe('EmailStrategy', () => {
  const strategy = new EmailStrategy(settings);

  it('Email 발송이 성공 결과를 반환한다', async () => {
    const result = await strategy.send(SAMPLE_NOTIFICATION);
    expect(result.success).toBe(true);
    expect(result.channel).toBe('email');
    expect(result.provider).toBe('sendgrid');
  });

  it('Mock 딜레이가 환경 변수 범위 내이다', async () => {
    const result = await strategy.send(SAMPLE_NOTIFICATION);
    expect(result.duration_ms).toBeGreaterThanOrEqual(10);
    expect(result.duration_ms).toBeLessThan(100);
  });

  it('getChannelName이 email을 반환한다', () => {
    expect(strategy.getChannelName()).toBe('email');
  });

  it('getProviderName이 sendgrid를 반환한다', () => {
    expect(strategy.getProviderName()).toBe('sendgrid');
  });
});

describe('SmsStrategy', () => {
  const strategy = new SmsStrategy(settings);

  it('SMS 발송이 성공 결과를 반환한다', async () => {
    const result = await strategy.send(SAMPLE_NOTIFICATION);
    expect(result.success).toBe(true);
    expect(result.channel).toBe('sms');
    expect(result.provider).toBe('twilio');
  });

  it('Mock 딜레이가 환경 변수 범위 내이다', async () => {
    const result = await strategy.send(SAMPLE_NOTIFICATION);
    expect(result.duration_ms).toBeGreaterThanOrEqual(10);
  });

  it('getChannelName이 sms를 반환한다', () => {
    expect(strategy.getChannelName()).toBe('sms');
  });

  it('getProviderName이 twilio를 반환한다', () => {
    expect(strategy.getProviderName()).toBe('twilio');
  });
});

describe('WebhookStrategy', () => {
  const strategy = new WebhookStrategy(settings);

  it('Webhook 발송이 성공 결과를 반환한다', async () => {
    const result = await strategy.send(SAMPLE_NOTIFICATION);
    expect(result.success).toBe(true);
    expect(result.channel).toBe('webhook');
    expect(result.provider).toBe('webhook');
  });

  it('Mock 딜레이가 환경 변수 범위 내이다', async () => {
    const result = await strategy.send(SAMPLE_NOTIFICATION);
    expect(result.duration_ms).toBeGreaterThanOrEqual(10);
  });

  it('getChannelName이 webhook을 반환한다', () => {
    expect(strategy.getChannelName()).toBe('webhook');
  });

  it('getProviderName이 webhook을 반환한다', () => {
    expect(strategy.getProviderName()).toBe('webhook');
  });
});
