/**
 * 재시도 서비스 테스트.
 */

import type { Settings } from '@src/shared/config';
import { calculateDelayMs, MaxRetryExceededError, RetryService } from '@src/services/retry-service';

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

// setTimeout을 fake로 교체하여 실제 대기 없이 테스트
beforeEach(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  jest.useRealTimers();
});

describe('calculateDelayMs 함수', () => {
  it('첫 번째 재시도는 base_delay 그대로', () => {
    expect(calculateDelayMs(0, 1000, 2)).toBe(1000);
  });

  it('두 번째 재시도는 base * 2', () => {
    expect(calculateDelayMs(1, 1000, 2)).toBe(2000);
  });

  it('세 번째 재시도는 base * 4', () => {
    expect(calculateDelayMs(2, 1000, 2)).toBe(4000);
  });

  it('커스텀 배수 적용', () => {
    expect(calculateDelayMs(2, 500, 3)).toBe(4500);
  });

  it('retry_count=0이면 base_delay 반환', () => {
    expect(calculateDelayMs(0, 100, 5)).toBe(100);
  });
});

describe('RetryService', () => {
  it('첫 번째 시도에서 성공하면 재시도 없음', async () => {
    jest.useRealTimers();
    const service = new RetryService(makeSettings());
    const fn = jest.fn().mockResolvedValue('ok');

    const result = await service.executeWithRetry(fn);

    expect(result).toBe('ok');
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('실패 후 재시도에서 성공', async () => {
    const service = new RetryService(
      makeSettings({ MAX_RETRY_COUNT: 3, RETRY_BASE_DELAY_MS: 100 }),
    );
    const fn = jest
      .fn()
      .mockRejectedValueOnce(new Error('fail'))
      .mockRejectedValueOnce(new Error('fail'))
      .mockResolvedValue('ok');

    const promise = service.executeWithRetry(fn);

    // 첫 번째 재시도 대기 (100ms)
    await jest.advanceTimersByTimeAsync(100);
    // 두 번째 재시도 대기 (200ms)
    await jest.advanceTimersByTimeAsync(200);

    const result = await promise;
    expect(result).toBe('ok');
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it('최대 재시도 초과 시 MaxRetryExceededError 발생', async () => {
    const service = new RetryService(
      makeSettings({ MAX_RETRY_COUNT: 2, RETRY_BASE_DELAY_MS: 100 }),
    );
    const fn = jest.fn().mockRejectedValue(new Error('persistent error'));

    let caughtError: unknown;
    const promise = service.executeWithRetry(fn).catch((err) => { caughtError = err; });

    // 2번의 재시도 대기
    await jest.advanceTimersByTimeAsync(100);
    await jest.advanceTimersByTimeAsync(200);

    await promise;

    expect(caughtError).toBeInstanceOf(MaxRetryExceededError);
    expect((caughtError as MaxRetryExceededError).retryCount).toBe(2);
    expect((caughtError as MaxRetryExceededError).lastError).toContain('persistent error');

    // 초기 시도(1) + 재시도(2) = 3번 호출
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it('지수 백오프 딜레이가 정확히 계산된다', async () => {
    const sleepSpy = jest.spyOn(global, 'setTimeout');
    const service = new RetryService(
      makeSettings({ MAX_RETRY_COUNT: 3, RETRY_BASE_DELAY_MS: 1000, RETRY_BACKOFF_MULTIPLIER: 2 }),
    );
    const fn = jest
      .fn()
      .mockRejectedValueOnce(new Error('e'))
      .mockRejectedValueOnce(new Error('e'))
      .mockRejectedValueOnce(new Error('e'))
      .mockResolvedValue('ok');

    const promise = service.executeWithRetry(fn);

    await jest.advanceTimersByTimeAsync(1000);
    await jest.advanceTimersByTimeAsync(2000);
    await jest.advanceTimersByTimeAsync(4000);

    await promise;

    // setTimeout이 1000, 2000, 4000 으로 호출되었는지 확인
    const timerCalls = sleepSpy.mock.calls
      .filter((c) => typeof c[1] === 'number' && c[1] >= 1000)
      .map((c) => c[1]);
    expect(timerCalls).toContain(1000);
    expect(timerCalls).toContain(2000);
    expect(timerCalls).toContain(4000);
  });

  it('MAX_RETRY_COUNT=0이면 재시도 없이 즉시 실패', async () => {
    jest.useRealTimers();
    const service = new RetryService(makeSettings({ MAX_RETRY_COUNT: 0 }));
    const fn = jest.fn().mockRejectedValue(new Error('fail'));

    await expect(service.executeWithRetry(fn)).rejects.toThrow(MaxRetryExceededError);

    try {
      await service.executeWithRetry(fn);
    } catch (err) {
      expect((err as MaxRetryExceededError).retryCount).toBe(0);
    }
  });

  it('context가 전달되어도 정상 동작한다', async () => {
    const service = new RetryService(
      makeSettings({ MAX_RETRY_COUNT: 1, RETRY_BASE_DELAY_MS: 100 }),
    );
    const fn = jest.fn().mockRejectedValueOnce(new Error('err')).mockResolvedValue('ok');

    const promise = service.executeWithRetry(fn, { event_id: 'evt-1', channel: 'email' });

    await jest.advanceTimersByTimeAsync(100);

    const result = await promise;
    expect(result).toBe('ok');
  });
});
