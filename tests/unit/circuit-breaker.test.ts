/**
 * Circuit Breaker 테스트.
 */

import type { Settings } from '@src/shared/config';
import { CircuitState } from '@src/models/circuit-breaker';
import type { CircuitBreakerDocument } from '@src/models/circuit-breaker';

const mockItem = jest.fn();
const mockUpsert = jest.fn();
const mockContainerObj = {
  item: mockItem,
  items: { upsert: mockUpsert },
};

jest.mock('@src/services/cosmos-client', () => ({
  getCircuitBreakerContainer: jest.fn(() => mockContainerObj),
}));

import { CircuitBreaker, CircuitOpenError } from '@src/services/circuit-breaker';

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

function makeDoc(overrides: Partial<CircuitBreakerDocument> = {}): CircuitBreakerDocument {
  return {
    id: 'email:sendgrid',
    state: CircuitState.CLOSED,
    failure_count: 0,
    success_count: 0,
    last_failure_at: null,
    opened_at: null,
    updated_at: new Date().toISOString(),
    _etag: 'etag-1',
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe('checkState 메서드', () => {
  it('Closed 상태 → Closed 반환', async () => {
    mockItem.mockReturnValue({ read: jest.fn().mockResolvedValue({ resource: makeDoc() }) });

    const cb = new CircuitBreaker(makeSettings());
    const state = await cb.checkState('email', 'sendgrid');
    expect(state).toBe(CircuitState.CLOSED);
  });

  it('Half-Open 상태 → Half-Open 반환', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({ resource: makeDoc({ state: CircuitState.HALF_OPEN }) }),
    });

    const cb = new CircuitBreaker(makeSettings());
    const state = await cb.checkState('email', 'sendgrid');
    expect(state).toBe(CircuitState.HALF_OPEN);
  });

  it('Open + cooldown 미만료 → CircuitOpenError 발생', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({
        resource: makeDoc({ state: CircuitState.OPEN, opened_at: new Date().toISOString() }),
      }),
    });

    const cb = new CircuitBreaker(makeSettings({ CB_COOLDOWN_MS: 30000 }));
    await expect(cb.checkState('email', 'sendgrid')).rejects.toThrow(CircuitOpenError);
  });

  it('Open + cooldown 만료 → Half-Open 전환', async () => {
    const pastTime = new Date(Date.now() - 60000).toISOString();
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({
        resource: makeDoc({ state: CircuitState.OPEN, opened_at: pastTime }),
      }),
    });
    mockUpsert.mockResolvedValue({
      resource: makeDoc({ state: CircuitState.HALF_OPEN }),
    });

    const cb = new CircuitBreaker(makeSettings({ CB_COOLDOWN_MS: 30000 }));
    const state = await cb.checkState('email', 'sendgrid');
    expect(state).toBe(CircuitState.HALF_OPEN);
    expect(mockUpsert).toHaveBeenCalledTimes(1);
  });

  it('문서가 없으면 Closed 반환', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockRejectedValue({ code: 404 }),
    });

    const cb = new CircuitBreaker(makeSettings());
    const state = await cb.checkState('email', 'sendgrid');
    expect(state).toBe(CircuitState.CLOSED);
  });
});

describe('recordFailure 메서드', () => {
  it('실패 횟수가 threshold 미만이면 Closed 유지', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({ resource: makeDoc({ failure_count: 2 }) }),
    });
    mockUpsert.mockImplementation(async (body: CircuitBreakerDocument) => ({
      resource: body,
    }));

    const cb = new CircuitBreaker(makeSettings({ CB_FAILURE_THRESHOLD: 5 }));
    await cb.recordFailure('email', 'sendgrid');

    const upsertBody = mockUpsert.mock.calls[0][0];
    expect(upsertBody.state).toBe('closed');
    expect(upsertBody.failure_count).toBe(3);
  });

  it('실패 횟수가 threshold에 도달하면 Open 전환', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({ resource: makeDoc({ failure_count: 4 }) }),
    });
    mockUpsert.mockImplementation(async (body: CircuitBreakerDocument) => ({
      resource: body,
    }));

    const cb = new CircuitBreaker(makeSettings({ CB_FAILURE_THRESHOLD: 5 }));
    await cb.recordFailure('email', 'sendgrid');

    const upsertBody = mockUpsert.mock.calls[0][0];
    expect(upsertBody.state).toBe('open');
    expect(upsertBody.failure_count).toBe(5);
  });

  it('Half-Open에서 1회 실패 → Open 재전환', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({
        resource: makeDoc({ state: CircuitState.HALF_OPEN, success_count: 1 }),
      }),
    });
    mockUpsert.mockImplementation(async (body: CircuitBreakerDocument) => ({
      resource: body,
    }));

    const cb = new CircuitBreaker(makeSettings());
    await cb.recordFailure('email', 'sendgrid');

    const upsertBody = mockUpsert.mock.calls[0][0];
    expect(upsertBody.state).toBe('open');
  });

  it('문서가 없는 상태에서 실패 기록 시 새 문서 생성', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockRejectedValue({ code: 404 }),
    });
    mockUpsert.mockImplementation(async (body: CircuitBreakerDocument) => ({
      resource: body,
    }));

    const cb = new CircuitBreaker(makeSettings({ CB_FAILURE_THRESHOLD: 5 }));
    await cb.recordFailure('email', 'sendgrid');

    const upsertBody = mockUpsert.mock.calls[0][0];
    expect(upsertBody.failure_count).toBe(1);
    expect(upsertBody.state).toBe('closed');
  });
});

describe('recordSuccess 메서드', () => {
  it('Closed 상태에서 성공 시 failure_count 리셋', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({ resource: makeDoc({ failure_count: 3 }) }),
    });
    mockUpsert.mockImplementation(async (body: CircuitBreakerDocument) => ({
      resource: body,
    }));

    const cb = new CircuitBreaker(makeSettings());
    await cb.recordSuccess('email', 'sendgrid');

    const upsertBody = mockUpsert.mock.calls[0][0];
    expect(upsertBody.failure_count).toBe(0);
  });

  it('Half-Open에서 성공이 threshold 미만이면 Half-Open 유지', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({
        resource: makeDoc({ state: CircuitState.HALF_OPEN, success_count: 0 }),
      }),
    });
    mockUpsert.mockImplementation(async (body: CircuitBreakerDocument) => ({
      resource: body,
    }));

    const cb = new CircuitBreaker(makeSettings({ CB_SUCCESS_THRESHOLD: 2 }));
    await cb.recordSuccess('email', 'sendgrid');

    const upsertBody = mockUpsert.mock.calls[0][0];
    expect(upsertBody.state).toBe('half-open');
    expect(upsertBody.success_count).toBe(1);
  });

  it('Half-Open에서 연속 성공이 threshold에 도달하면 Closed 복귀', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({
        resource: makeDoc({ state: CircuitState.HALF_OPEN, success_count: 1 }),
      }),
    });
    mockUpsert.mockImplementation(async (body: CircuitBreakerDocument) => ({
      resource: body,
    }));

    const cb = new CircuitBreaker(makeSettings({ CB_SUCCESS_THRESHOLD: 2 }));
    await cb.recordSuccess('email', 'sendgrid');

    const upsertBody = mockUpsert.mock.calls[0][0];
    expect(upsertBody.state).toBe('closed');
    expect(upsertBody.failure_count).toBe(0);
    expect(upsertBody.success_count).toBe(0);
  });

  it('Closed + failure_count=0이면 DB 쓰기 안 함', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({ resource: makeDoc({ failure_count: 0 }) }),
    });

    const cb = new CircuitBreaker(makeSettings());
    await cb.recordSuccess('email', 'sendgrid');

    expect(mockUpsert).not.toHaveBeenCalled();
  });
});

describe('ETag 충돌 재시도', () => {
  it('ETag 충돌 시 재읽기 후 재시도한다', async () => {
    let readCount = 0;
    mockItem.mockReturnValue({
      read: jest.fn().mockImplementation(async () => {
        readCount++;
        return {
          resource: makeDoc({
            failure_count: 4,
            _etag: readCount === 1 ? 'etag-old' : 'etag-new',
          }),
        };
      }),
    });

    let upsertCount = 0;
    mockUpsert.mockImplementation(async () => {
      upsertCount++;
      if (upsertCount === 1) throw { code: 412 };
      return { resource: makeDoc({ state: CircuitState.OPEN, failure_count: 5 }) };
    });

    const cb = new CircuitBreaker(makeSettings({ CB_FAILURE_THRESHOLD: 5 }));
    await cb.recordFailure('email', 'sendgrid');

    expect(mockUpsert).toHaveBeenCalledTimes(2);
  });

  it('최대 재시도 초과 시 예외가 전파된다', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({ resource: makeDoc({ failure_count: 4 }) }),
    });
    mockUpsert.mockRejectedValue({ code: 412 });

    const cb = new CircuitBreaker(makeSettings({ CB_FAILURE_THRESHOLD: 5 }));
    await expect(cb.recordFailure('email', 'sendgrid')).rejects.toEqual({ code: 412 });
  });
});
