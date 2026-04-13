/**
 * 통합 테스트 공통 설정.
 *
 * Cosmos DB Emulator 연결 확인 및 컨테이너 초기화.
 * Emulator 미실행 시 통합 테스트를 스킵한다.
 */

import type { Settings } from '@src/shared/config';
import https from 'https';

// Cosmos DB Emulator 기본 설정
export const EMULATOR_ENDPOINT = 'https://localhost:8081';
export const EMULATOR_KEY =
  'C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw==';
export const TEST_DATABASE = 'test-notification-pipeline';

export function makeIntegrationSettings(overrides: Partial<Settings> = {}): Settings {
  return {
    COSMOS_DB_ENDPOINT: EMULATOR_ENDPOINT,
    COSMOS_DB_KEY: EMULATOR_KEY,
    COSMOS_DB_DATABASE: TEST_DATABASE,
    QUEUE_SERVICE_TYPE: 'EVENT_GRID',
    NOTIFICATION_EMAIL_PROVIDER: 'sendgrid',
    NOTIFICATION_SMS_PROVIDER: 'twilio',
    WEBHOOK_URL: 'https://example.com/webhook',
    MOCK_DELAY_MIN_MS: 10,
    MOCK_DELAY_MAX_MS: 20,
    MAX_RETRY_COUNT: 2,
    RETRY_BASE_DELAY_MS: 100,
    RETRY_BACKOFF_MULTIPLIER: 2,
    CB_FAILURE_THRESHOLD: 3,
    CB_COOLDOWN_MS: 1000,
    CB_SUCCESS_THRESHOLD: 2,
    RATE_LIMIT_EMAIL_PER_SEC: 10,
    RATE_LIMIT_SMS_PER_SEC: 5,
    RATE_LIMIT_WEBHOOK_PER_SEC: 20,
    RATE_LIMIT_MAX_WAIT_MS: 10000,
    ...overrides,
  };
}

export async function isEmulatorAvailable(): Promise<boolean> {
  return new Promise((resolve) => {
    const req = https.get(
      `${EMULATOR_ENDPOINT}/_explorer/emulator.pem`,
      { rejectUnauthorized: false, timeout: 3000 },
      (res) => resolve(res.statusCode === 200),
    );
    req.on('error', () => resolve(false));
    req.on('timeout', () => {
      req.destroy();
      resolve(false);
    });
  });
}

export function uniqueClinicId(): string {
  const hex = Math.random().toString(16).slice(2, 10);
  return `test-clinic-${hex}`;
}
