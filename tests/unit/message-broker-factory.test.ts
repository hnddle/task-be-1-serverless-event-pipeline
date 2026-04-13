/**
 * Message Broker 팩토리 및 어댑터 테스트.
 */

import type { Settings } from '@src/shared/config';

jest.mock('@azure/eventgrid', () => {
  const mockSend = jest.fn().mockResolvedValue({});
  const MockClient = jest.fn(() => ({ send: mockSend, close: jest.fn() }));
  const MockCredential = jest.fn();

  return {
    EventGridPublisherClient: MockClient,
    AzureKeyCredential: MockCredential,
    __mockSend: mockSend,
  };
});

import { EventGridAdapter } from '@src/services/message-broker/event-grid-adapter';
import { MessageBrokerFactory } from '@src/services/message-broker/message-broker-factory';
import { AzureKeyCredential } from '@azure/eventgrid';

const eventgrid = jest.requireMock('@azure/eventgrid') as { __mockSend: jest.Mock };

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
    MOCK_DELAY_MIN_MS: 100,
    MOCK_DELAY_MAX_MS: 500,
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe('MessageBrokerFactory', () => {
  it('EVENT_GRID 타입으로 EventGridAdapter를 생성한다', () => {
    const broker = MessageBrokerFactory.create(makeSettings());
    expect(broker).toBeInstanceOf(EventGridAdapter);
  });

  it('QUEUE_SERVICE_TYPE 비교가 대소문자를 구분하지 않는다', () => {
    const broker = MessageBrokerFactory.create(
      makeSettings({ QUEUE_SERVICE_TYPE: 'event_grid' }),
    );
    expect(broker).toBeInstanceOf(EventGridAdapter);
  });

  it('지원하지 않는 QUEUE_SERVICE_TYPE이면 에러가 발생한다', () => {
    expect(() =>
      MessageBrokerFactory.create(makeSettings({ QUEUE_SERVICE_TYPE: 'KAFKA' })),
    ).toThrow('지원하지 않는 QUEUE_SERVICE_TYPE');
  });

  it('에러 메시지에 지원하는 타입 목록이 포함된다', () => {
    expect(() =>
      MessageBrokerFactory.create(makeSettings({ QUEUE_SERVICE_TYPE: 'SNS' })),
    ).toThrow('EVENT_GRID');
  });
});

describe('EventGridAdapter', () => {
  it('getBrokerName이 EventGrid를 반환한다', () => {
    const credential = new AzureKeyCredential('test-key');
    const adapter = new EventGridAdapter('https://example.com', credential);
    expect(adapter.getBrokerName()).toBe('EventGrid');
  });

  it('publish가 Event Grid 클라이언트에 이벤트를 전달한다', async () => {
    const credential = new AzureKeyCredential('test-key');
    const adapter = new EventGridAdapter('https://example.com', credential);

    const event = { id: 'test-id-123', event_type: 'appointment_confirmed' };
    await adapter.publish(event);

    expect(eventgrid.__mockSend).toHaveBeenCalledTimes(1);
    const sentEvents = eventgrid.__mockSend.mock.calls[0][0];
    expect(sentEvents).toHaveLength(1);
  });

  it('발행된 이벤트의 event_type이 올바르다', async () => {
    const credential = new AzureKeyCredential('test-key');
    const adapter = new EventGridAdapter('https://example.com', credential);

    const event = { id: 'test-id-456', event_type: 'claim_completed' };
    await adapter.publish(event);

    const sentEvents = eventgrid.__mockSend.mock.calls[0][0];
    const egEvent = sentEvents[0];
    expect(egEvent.eventType).toBe('NotificationPipeline.EventCreated');
    expect(egEvent.subject).toBe('/events/test-id-456');
    expect(egEvent.data).toEqual(event);
  });

  it('adapter가 publish와 getBrokerName 메서드를 가진다', () => {
    expect(EventGridAdapter.prototype).toHaveProperty('publish');
    expect(EventGridAdapter.prototype).toHaveProperty('getBrokerName');
  });
});
