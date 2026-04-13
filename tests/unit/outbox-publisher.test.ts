/**
 * Outbox Publisher 테스트.
 */

import type { InvocationContext } from '@azure/functions';

const mockPatch = jest.fn();
const mockItem = jest.fn().mockReturnValue({ patch: mockPatch });
const mockContainerObj = { item: mockItem };
const mockPublish = jest.fn();
const mockGetBrokerName = jest.fn().mockReturnValue('EventGrid');

jest.mock('@azure/functions', () => ({
  app: { http: jest.fn(), cosmosDB: jest.fn(), timer: jest.fn(), eventGrid: jest.fn() },
}));

jest.mock('@src/services/cosmos-client', () => ({
  getEventsContainer: jest.fn(() => mockContainerObj),
}));

import {
  outboxPublisher,
  _setSettingsForTest,
  _setBrokerForTest,
} from '@src/functions/outbox-publisher';
import type { Settings } from '@src/shared/config';

function makeSettings(): Settings {
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
    EVENT_GRID_TOPIC_ENDPOINT: 'https://test-topic.koreacentral-1.eventgrid.azure.net/api/events',
    EVENT_GRID_TOPIC_KEY: 'test-key',
  };
}

function makeDocument(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'evt-001',
    clinic_id: 'CLINIC_123',
    correlation_id: 'cid-001',
    _outbox_status: 'pending',
    status: 'queued',
    ...overrides,
  };
}

const mockContext = {} as InvocationContext;

beforeEach(() => {
  jest.clearAllMocks();
  _setSettingsForTest(makeSettings());
  _setBrokerForTest({
    publish: mockPublish,
    getBrokerName: mockGetBrokerName,
  });
});

describe('Outbox Publisher Function', () => {
  it('pending 문서가 발행되고 published로 갱신된다', async () => {
    mockPublish.mockResolvedValue(undefined);
    mockPatch.mockResolvedValue({});

    await outboxPublisher([makeDocument()], mockContext);

    expect(mockPublish).toHaveBeenCalledTimes(1);
    expect(mockPatch).toHaveBeenCalledTimes(1);
    const patchOps = mockPatch.mock.calls[0][0];
    expect(patchOps[0].value).toBe('published');
  });

  it('published 문서는 무시된다 (무한 루프 방지)', async () => {
    await outboxPublisher([makeDocument({ _outbox_status: 'published' })], mockContext);

    expect(mockPublish).not.toHaveBeenCalled();
    expect(mockPatch).not.toHaveBeenCalled();
  });

  it('failed_publish 문서도 무시된다', async () => {
    await outboxPublisher(
      [makeDocument({ _outbox_status: 'failed_publish' })],
      mockContext,
    );

    expect(mockPublish).not.toHaveBeenCalled();
  });

  it('발행 실패 시 failed_publish로 갱신된다', async () => {
    mockPublish.mockRejectedValue(new Error('Network error'));
    mockPatch.mockResolvedValue({});

    await outboxPublisher([makeDocument()], mockContext);

    expect(mockPatch).toHaveBeenCalledTimes(1);
    const patchOps = mockPatch.mock.calls[0][0];
    expect(patchOps[0].value).toBe('failed_publish');
  });

  it('pending과 published가 혼재된 배치에서 pending만 처리한다', async () => {
    mockPublish.mockResolvedValue(undefined);
    mockPatch.mockResolvedValue({});

    const docs = [
      makeDocument({ id: 'evt-1', _outbox_status: 'pending' }),
      makeDocument({ id: 'evt-2', _outbox_status: 'published' }),
      makeDocument({ id: 'evt-3', _outbox_status: 'pending' }),
    ];

    await outboxPublisher(docs, mockContext);

    expect(mockPublish).toHaveBeenCalledTimes(2);
    expect(mockPatch).toHaveBeenCalledTimes(2);
  });

  it('빈 문서 목록은 에러 없이 종료된다', async () => {
    await outboxPublisher([], mockContext);
    // 예외 없이 통과
  });
});
