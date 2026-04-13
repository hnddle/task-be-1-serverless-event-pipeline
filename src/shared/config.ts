/**
 * 환경 변수 로드 및 Fail-fast 검증.
 *
 * 필수 환경 변수 누락 시 에러 로그 출력 후 프로세스 종료.
 * SPEC.md §11 참조.
 */

import { getLogger } from './logger';

const logger = getLogger('config');

export interface Settings {
  // 필수 — Message Broker
  QUEUE_SERVICE_TYPE: string;

  // 필수 — Notification Providers
  NOTIFICATION_EMAIL_PROVIDER: string;
  NOTIFICATION_SMS_PROVIDER: string;
  WEBHOOK_URL: string;

  // 필수 — Cosmos DB
  COSMOS_DB_ENDPOINT: string;
  COSMOS_DB_KEY: string;
  COSMOS_DB_DATABASE: string;

  // 선택 — Circuit Breaker
  CB_FAILURE_THRESHOLD: number;
  CB_COOLDOWN_MS: number;
  CB_SUCCESS_THRESHOLD: number;

  // 선택 — Retry
  MAX_RETRY_COUNT: number;
  RETRY_BASE_DELAY_MS: number;
  RETRY_BACKOFF_MULTIPLIER: number;

  // 선택 — Rate Limiter
  RATE_LIMIT_EMAIL_PER_SEC: number;
  RATE_LIMIT_SMS_PER_SEC: number;
  RATE_LIMIT_WEBHOOK_PER_SEC: number;
  RATE_LIMIT_MAX_WAIT_MS: number;

  // 선택 — Mock Delay
  MOCK_DELAY_MIN_MS: number;
  MOCK_DELAY_MAX_MS: number;
}

const REQUIRED_VARS = [
  'QUEUE_SERVICE_TYPE',
  'NOTIFICATION_EMAIL_PROVIDER',
  'NOTIFICATION_SMS_PROVIDER',
  'WEBHOOK_URL',
  'COSMOS_DB_ENDPOINT',
  'COSMOS_DB_KEY',
  'COSMOS_DB_DATABASE',
] as const;

function getEnvInt(key: string, defaultValue: number): number {
  const val = process.env[key];
  if (val === undefined || val === '') return defaultValue;
  const parsed = parseInt(val, 10);
  return isNaN(parsed) ? defaultValue : parsed;
}

function getEnvStr(key: string, defaultValue?: string): string {
  const val = process.env[key];
  if (val !== undefined && val !== '') return val;
  if (defaultValue !== undefined) return defaultValue;
  return '';
}

export function loadSettings(): Settings {
  const missing: string[] = [];

  for (const key of REQUIRED_VARS) {
    const val = process.env[key];
    if (val === undefined || val === '') {
      missing.push(key);
    }
  }

  if (missing.length > 0) {
    logger.error(`필수 환경 변수 누락: ${missing.join(', ')}`);
    process.exit(1);
  }

  return {
    QUEUE_SERVICE_TYPE: getEnvStr('QUEUE_SERVICE_TYPE'),
    NOTIFICATION_EMAIL_PROVIDER: getEnvStr('NOTIFICATION_EMAIL_PROVIDER'),
    NOTIFICATION_SMS_PROVIDER: getEnvStr('NOTIFICATION_SMS_PROVIDER'),
    WEBHOOK_URL: getEnvStr('WEBHOOK_URL'),

    COSMOS_DB_ENDPOINT: getEnvStr('COSMOS_DB_ENDPOINT'),
    COSMOS_DB_KEY: getEnvStr('COSMOS_DB_KEY'),
    COSMOS_DB_DATABASE: getEnvStr('COSMOS_DB_DATABASE'),

    CB_FAILURE_THRESHOLD: getEnvInt('CB_FAILURE_THRESHOLD', 5),
    CB_COOLDOWN_MS: getEnvInt('CB_COOLDOWN_MS', 30000),
    CB_SUCCESS_THRESHOLD: getEnvInt('CB_SUCCESS_THRESHOLD', 2),

    MAX_RETRY_COUNT: getEnvInt('MAX_RETRY_COUNT', 3),
    RETRY_BASE_DELAY_MS: getEnvInt('RETRY_BASE_DELAY_MS', 1000),
    RETRY_BACKOFF_MULTIPLIER: getEnvInt('RETRY_BACKOFF_MULTIPLIER', 2),

    RATE_LIMIT_EMAIL_PER_SEC: getEnvInt('RATE_LIMIT_EMAIL_PER_SEC', 10),
    RATE_LIMIT_SMS_PER_SEC: getEnvInt('RATE_LIMIT_SMS_PER_SEC', 5),
    RATE_LIMIT_WEBHOOK_PER_SEC: getEnvInt('RATE_LIMIT_WEBHOOK_PER_SEC', 20),
    RATE_LIMIT_MAX_WAIT_MS: getEnvInt('RATE_LIMIT_MAX_WAIT_MS', 10000),

    MOCK_DELAY_MIN_MS: getEnvInt('MOCK_DELAY_MIN_MS', 100),
    MOCK_DELAY_MAX_MS: getEnvInt('MOCK_DELAY_MAX_MS', 500),
  };
}

let _settings: Settings | null = null;

export function getSettings(): Settings {
  if (!_settings) {
    _settings = loadSettings();
  }
  return _settings;
}

/** 테스트용 — 싱글턴 리셋 */
export function resetSettings(): void {
  _settings = null;
}
