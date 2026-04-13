/**
 * 환경 변수 로드/검증 테스트.
 */

import { loadSettings, resetSettings } from '@src/shared/config';

const REQUIRED_ENV: Record<string, string> = {
  QUEUE_SERVICE_TYPE: 'EVENT_GRID',
  NOTIFICATION_EMAIL_PROVIDER: 'sendgrid',
  NOTIFICATION_SMS_PROVIDER: 'twilio',
  WEBHOOK_URL: 'https://example.com/webhook',
  COSMOS_DB_ENDPOINT: 'https://localhost:8081',
  COSMOS_DB_KEY: 'test-key',
  COSMOS_DB_DATABASE: 'test-db',
};

const originalEnv = process.env;

beforeEach(() => {
  resetSettings();
  process.env = { ...originalEnv };
});

afterEach(() => {
  process.env = originalEnv;
  resetSettings();
});

describe('Settings 필수 환경 변수 검증', () => {
  it('모든 필수 변수가 있으면 정상 로드', () => {
    Object.assign(process.env, REQUIRED_ENV);
    const settings = loadSettings();
    expect(settings.QUEUE_SERVICE_TYPE).toBe('EVENT_GRID');
    expect(settings.COSMOS_DB_ENDPOINT).toBe('https://localhost:8081');
    expect(settings.COSMOS_DB_DATABASE).toBe('test-db');
  });

  it('필수 변수 누락 시 process.exit(1) 호출', () => {
    const mockExit = jest.spyOn(process, 'exit').mockImplementation(() => {
      throw new Error('process.exit called');
    });

    // COSMOS_DB_KEY 제외
    const incomplete = { ...REQUIRED_ENV };
    delete incomplete.COSMOS_DB_KEY;
    process.env = { ...incomplete };

    expect(() => loadSettings()).toThrow('process.exit called');
    expect(mockExit).toHaveBeenCalledWith(1);
  });

  it('여러 필수 변수 누락 시에도 process.exit(1) 호출', () => {
    const mockExit = jest.spyOn(process, 'exit').mockImplementation(() => {
      throw new Error('process.exit called');
    });

    process.env = {};

    expect(() => loadSettings()).toThrow('process.exit called');
    expect(mockExit).toHaveBeenCalledWith(1);
  });
});

describe('Settings 기본값 테스트', () => {
  beforeEach(() => {
    Object.assign(process.env, REQUIRED_ENV);
  });

  it('Circuit Breaker 기본값 확인', () => {
    const settings = loadSettings();
    expect(settings.CB_FAILURE_THRESHOLD).toBe(5);
    expect(settings.CB_COOLDOWN_MS).toBe(30000);
    expect(settings.CB_SUCCESS_THRESHOLD).toBe(2);
  });

  it('Retry 기본값 확인', () => {
    const settings = loadSettings();
    expect(settings.MAX_RETRY_COUNT).toBe(3);
    expect(settings.RETRY_BASE_DELAY_MS).toBe(1000);
    expect(settings.RETRY_BACKOFF_MULTIPLIER).toBe(2);
  });

  it('Rate Limiter 기본값 확인', () => {
    const settings = loadSettings();
    expect(settings.RATE_LIMIT_EMAIL_PER_SEC).toBe(10);
    expect(settings.RATE_LIMIT_SMS_PER_SEC).toBe(5);
    expect(settings.RATE_LIMIT_WEBHOOK_PER_SEC).toBe(20);
    expect(settings.RATE_LIMIT_MAX_WAIT_MS).toBe(10000);
  });

  it('Mock Delay 기본값 확인', () => {
    const settings = loadSettings();
    expect(settings.MOCK_DELAY_MIN_MS).toBe(100);
    expect(settings.MOCK_DELAY_MAX_MS).toBe(500);
  });

  it('선택 변수를 환경 변수로 덮어쓸 수 있다', () => {
    process.env.CB_FAILURE_THRESHOLD = '10';
    process.env.MAX_RETRY_COUNT = '5';
    const settings = loadSettings();
    expect(settings.CB_FAILURE_THRESHOLD).toBe(10);
    expect(settings.MAX_RETRY_COUNT).toBe(5);
  });
});
