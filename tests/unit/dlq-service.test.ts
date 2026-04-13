/**
 * DLQ 서비스 테스트.
 */

import type { Settings } from '@src/shared/config';

const mockCreate = jest.fn().mockResolvedValue({});
const mockContainerObj = {
  items: { create: mockCreate },
};

jest.mock('@src/services/cosmos-client', () => ({
  getDlqContainer: jest.fn(() => mockContainerObj),
}));

jest.mock('@src/shared/correlation', () => ({
  getCorrelationId: jest.fn(() => 'corr-123'),
  getLogContext: jest.fn(() => ({})),
}));

import { DlqService } from '@src/services/dlq-service';
import * as correlation from '@src/shared/correlation';

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

const SAMPLE_PAYLOAD = {
  id: 'evt-1',
  clinic_id: 'clinic-1',
  event_type: 'appointment_confirmed',
  patient_id: 'P-001',
  notifications: [],
};

beforeEach(() => {
  jest.clearAllMocks();
});

describe('sendToDlq 메서드', () => {
  it('DLQ 문서가 올바른 필드로 생성된다', async () => {
    const service = new DlqService(makeSettings());
    const result = await service.sendToDlq({
      originalEventId: 'evt-1',
      clinicId: 'clinic-1',
      channel: 'email',
      provider: 'sendgrid',
      eventType: 'appointment_confirmed',
      patientId: 'P-001',
      payload: SAMPLE_PAYLOAD,
      failureReason: 'persistent error',
      retryCount: 3,
    });

    expect(mockCreate).toHaveBeenCalledTimes(1);
    const saved = mockCreate.mock.calls[0][0];

    expect(saved.original_event_id).toBe('evt-1');
    expect(saved.clinic_id).toBe('clinic-1');
    expect(saved.channel).toBe('email');
    expect(saved.provider).toBe('sendgrid');
    expect(saved.event_type).toBe('appointment_confirmed');
    expect(saved.patient_id).toBe('P-001');
    expect(saved.payload).toEqual(SAMPLE_PAYLOAD);
    expect(saved.failure_reason).toBe('persistent error');
    expect(saved.retry_count).toBe(3);
    expect(saved.correlation_id).toBe('corr-123');
    expect(saved.replay_status).toBe('pending');
    expect(saved.replayed_at).toBeNull();
    expect(saved).toHaveProperty('id');
    expect(saved).toHaveProperty('created_at');

    expect(result).toEqual(saved);
  });

  it('correlation_id가 None이면 빈 문자열로 저장된다', async () => {
    (correlation.getCorrelationId as jest.Mock).mockReturnValue(null);

    const service = new DlqService(makeSettings());
    await service.sendToDlq({
      originalEventId: 'evt-2',
      clinicId: 'clinic-2',
      channel: 'sms',
      provider: 'twilio',
      eventType: 'claim_completed',
      patientId: 'P-002',
      payload: {},
      failureReason: 'timeout',
      retryCount: 2,
    });

    const saved = mockCreate.mock.calls[0][0];
    expect(saved.correlation_id).toBe('');
  });

  it('DLQ 문서 ID가 UUID v4 형식이다', async () => {
    (correlation.getCorrelationId as jest.Mock).mockReturnValue('corr-456');

    const service = new DlqService(makeSettings());
    const result = await service.sendToDlq({
      originalEventId: 'evt-3',
      clinicId: 'clinic-3',
      channel: 'webhook',
      provider: 'webhook',
      eventType: 'insurance_approved',
      patientId: 'P-003',
      payload: {},
      failureReason: 'connection refused',
      retryCount: 3,
    });

    const dlqId = result.id as string;
    // UUID v4 형식 검증
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    expect(dlqId).toMatch(uuidRegex);
  });

  it('retry_count=0인 경우도 정상 저장된다 (Circuit Open 즉시 실패)', async () => {
    (correlation.getCorrelationId as jest.Mock).mockReturnValue('corr-789');

    const service = new DlqService(makeSettings());
    const result = await service.sendToDlq({
      originalEventId: 'evt-4',
      clinicId: 'clinic-4',
      channel: 'email',
      provider: 'sendgrid',
      eventType: 'appointment_confirmed',
      patientId: 'P-004',
      payload: {},
      failureReason: 'Circuit open: email:sendgrid',
      retryCount: 0,
    });

    expect(result.retry_count).toBe(0);
    expect(result.failure_reason).toBe('Circuit open: email:sendgrid');
  });
});
