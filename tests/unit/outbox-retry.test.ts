/**
 * Outbox Retry 테스트.
 */

import type { InvocationContext, Timer } from '@azure/functions';

const mockPatch = jest.fn();
const mockItem = jest.fn().mockReturnValue({ patch: mockPatch });
const mockFetchAll = jest.fn();
const mockQueryFn = jest.fn().mockReturnValue({ fetchAll: mockFetchAll });
const mockContainerObj = {
  item: mockItem,
  items: { query: mockQueryFn },
};

jest.mock('@azure/functions', () => ({
  app: { http: jest.fn(), cosmosDB: jest.fn(), timer: jest.fn(), eventGrid: jest.fn() },
}));

jest.mock('@src/services/cosmos-client', () => ({
  getEventsContainer: jest.fn(() => mockContainerObj),
}));

import { outboxRetry, _setSettingsForTest } from '@src/functions/outbox-retry';
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
  };
}

function makeTimer(isPastDue: boolean = false): Timer {
  return { isPastDue } as Timer;
}

const mockContext = {} as InvocationContext;

beforeEach(() => {
  jest.clearAllMocks();
  _setSettingsForTest(makeSettings());
});

describe('Outbox Retry Function', () => {
  it('failed_publish 문서가 pending으로 재갱신된다', async () => {
    const items = [
      { id: 'evt-1', clinic_id: 'CLINIC_A' },
      { id: 'evt-2', clinic_id: 'CLINIC_B' },
    ];
    mockFetchAll.mockResolvedValue({ resources: items });
    mockPatch.mockResolvedValue({});

    await outboxRetry(makeTimer(), mockContext);

    expect(mockPatch).toHaveBeenCalledTimes(2);

    // 각 호출에서 pending 값으로 패치하는지 확인
    for (const call of mockPatch.mock.calls) {
      const ops = call[0];
      expect(ops[0].value).toBe('pending');
    }
  });

  it('failed_publish 문서가 없으면 아무 작업도 하지 않는다', async () => {
    mockFetchAll.mockResolvedValue({ resources: [] });

    await outboxRetry(makeTimer(), mockContext);

    expect(mockPatch).not.toHaveBeenCalled();
  });

  it('하나의 문서 갱신 실패가 나머지 문서 처리를 중단하지 않는다', async () => {
    const items = [
      { id: 'evt-1', clinic_id: 'CLINIC_A' },
      { id: 'evt-2', clinic_id: 'CLINIC_B' },
      { id: 'evt-3', clinic_id: 'CLINIC_C' },
    ];
    mockFetchAll.mockResolvedValue({ resources: items });
    mockPatch
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce(new Error('DB error'))
      .mockResolvedValueOnce({});

    await outboxRetry(makeTimer(), mockContext);

    // 3건 모두 시도됨
    expect(mockPatch).toHaveBeenCalledTimes(3);
  });

  it('past_due 타이머도 정상 처리된다', async () => {
    const items = [{ id: 'evt-1', clinic_id: 'CLINIC_A' }];
    mockFetchAll.mockResolvedValue({ resources: items });
    mockPatch.mockResolvedValue({});

    await outboxRetry(makeTimer(true), mockContext);

    expect(mockPatch).toHaveBeenCalledTimes(1);
  });
});
