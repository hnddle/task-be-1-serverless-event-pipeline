/**
 * Rate Limiter 테스트.
 */

import type { Settings } from '@src/shared/config';

const mockItem = jest.fn();
const mockUpsert = jest.fn();
const mockContainerObj = {
  item: mockItem,
  items: { upsert: mockUpsert },
};

jest.mock('@src/services/cosmos-client', () => ({
  getRateLimiterContainer: jest.fn(() => mockContainerObj),
}));

import { RateLimiter, RateLimitExceededError } from '@src/services/rate-limiter';

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
    EVENT_GRID_TOPIC_ENDPOINT: 'https://test-topic.koreacentral-1.eventgrid.azure.net/api/events',
    EVENT_GRID_TOPIC_KEY: 'test-key',
    ...overrides,
  };
}

function makeBucket(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'email:sendgrid',
    tokens: 10.0,
    max_tokens: 10.0,
    last_refill_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    _etag: 'etag-1',
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe('acquire 메서드', () => {
  it('토큰이 있으면 즉시 소비된다', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({ resource: makeBucket({ tokens: 5.0 }) }),
    });
    mockUpsert.mockImplementation(async (body: Record<string, unknown>) => ({
      resource: body,
    }));

    const rl = new RateLimiter(makeSettings());
    await rl.acquire('email', 'sendgrid');

    expect(mockUpsert).toHaveBeenCalledTimes(1);
    const saved = mockUpsert.mock.calls[0][0];
    expect(saved.tokens).toBeLessThan(5.0);
  });

  it('버킷이 없으면 기본 버킷으로 시작한다', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockRejectedValue({ code: 404 }),
    });
    mockUpsert.mockImplementation(async (body: Record<string, unknown>) => ({
      resource: body,
    }));

    const rl = new RateLimiter(makeSettings({ RATE_LIMIT_EMAIL_PER_SEC: 10 }));
    await rl.acquire('email', 'sendgrid');

    expect(mockUpsert).toHaveBeenCalledTimes(1);
  });

  it('토큰이 없고 대기 시간 초과 시 RateLimitExceededError 발생', async () => {
    // 매번 read 호출 시 fresh한 last_refill_at을 반환하여 토큰 리필 방지
    mockItem.mockReturnValue({
      read: jest.fn().mockImplementation(async () => ({
        resource: makeBucket({
          tokens: 0.0,
          max_tokens: 10.0,
          last_refill_at: new Date().toISOString(),
        }),
      })),
    });

    const rl = new RateLimiter(makeSettings({ RATE_LIMIT_MAX_WAIT_MS: 200 }));

    await expect(rl.acquire('email', 'sendgrid')).rejects.toThrow(RateLimitExceededError);
  }, 10000);

  it('경과 시간에 따라 토큰이 리필된다', async () => {
    const oneSecAgo = new Date(Date.now() - 1000).toISOString();
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({
        resource: makeBucket({ tokens: 0.0, max_tokens: 10.0, last_refill_at: oneSecAgo }),
      }),
    });
    mockUpsert.mockImplementation(async (body: Record<string, unknown>) => ({
      resource: body,
    }));

    const rl = new RateLimiter(makeSettings({ RATE_LIMIT_EMAIL_PER_SEC: 10 }));
    await rl.acquire('email', 'sendgrid');

    const saved = mockUpsert.mock.calls[0][0];
    expect(saved.tokens).toBeGreaterThanOrEqual(8.0);
  });

  it('채널별 다른 rate가 적용된다', async () => {
    // email: 10 per sec, sms: 5 per sec
    mockItem.mockReturnValue({
      read: jest.fn().mockRejectedValue({ code: 404 }),
    });
    mockUpsert.mockImplementation(async (body: Record<string, unknown>) => ({
      resource: body,
    }));

    const settings = makeSettings({ RATE_LIMIT_EMAIL_PER_SEC: 10, RATE_LIMIT_SMS_PER_SEC: 5 });
    const rl = new RateLimiter(settings);

    await rl.acquire('email', 'sendgrid');
    const emailBucket = mockUpsert.mock.calls[0][0];
    const emailMax = emailBucket.max_tokens;

    mockItem.mockReturnValue({
      read: jest.fn().mockRejectedValue({ code: 404 }),
    });

    await rl.acquire('sms', 'twilio');
    const smsBucket = mockUpsert.mock.calls[1][0];
    const smsMax = smsBucket.max_tokens;

    expect(emailMax).toBe(10);
    expect(smsMax).toBe(5);
  });
});

describe('ETag 충돌 재시도', () => {
  it('ETag 충돌 시 재읽기 후 재시도한다', async () => {
    let readCount = 0;
    mockItem.mockReturnValue({
      read: jest.fn().mockImplementation(async () => {
        readCount++;
        return {
          resource: makeBucket({ tokens: 5.0, _etag: readCount === 1 ? 'old' : 'new' }),
        };
      }),
    });

    let upsertCount = 0;
    mockUpsert.mockImplementation(async () => {
      upsertCount++;
      if (upsertCount === 1) throw { code: 412 };
      return { resource: makeBucket({ tokens: 4.0 }) };
    });

    const rl = new RateLimiter(makeSettings());
    await rl.acquire('email', 'sendgrid');

    expect(mockUpsert).toHaveBeenCalledTimes(2);
  });

  it('최대 재시도 초과 시 예외 전파', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({ resource: makeBucket({ tokens: 5.0 }) }),
    });
    mockUpsert.mockRejectedValue({ code: 412 });

    const rl = new RateLimiter(makeSettings());
    await expect(rl.acquire('email', 'sendgrid')).rejects.toEqual({ code: 412 });
  });
});
