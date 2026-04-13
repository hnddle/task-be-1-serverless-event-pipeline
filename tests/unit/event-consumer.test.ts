/**
 * Event Consumer 테스트.
 */

import type { EventGridEvent, InvocationContext } from '@azure/functions';

const mockPatch = jest.fn();
const mockItemRead = jest.fn();
const mockItem = jest.fn().mockReturnValue({ read: mockItemRead, patch: mockPatch });
const mockEventsContainerObj = { item: mockItem };

jest.mock('@azure/functions', () => ({
  app: { http: jest.fn(), cosmosDB: jest.fn(), timer: jest.fn(), eventGrid: jest.fn() },
}));

jest.mock('@src/services/cosmos-client', () => ({
  getEventsContainer: jest.fn(() => mockEventsContainerObj),
}));

const mockCheckState = jest.fn();
const mockRecordSuccess = jest.fn();
const mockRecordFailure = jest.fn();

jest.mock('@src/services/circuit-breaker', () => ({
  CircuitBreaker: jest.fn().mockImplementation(() => ({
    checkState: mockCheckState,
    recordSuccess: mockRecordSuccess,
    recordFailure: mockRecordFailure,
  })),
  CircuitOpenError: class CircuitOpenError extends Error {
    constructor(msg: string) {
      super(`Circuit open: ${msg}`);
      this.name = 'CircuitOpenError';
    }
  },
}));

const mockRateLimiterAcquire = jest.fn();

jest.mock('@src/services/rate-limiter', () => ({
  RateLimiter: jest.fn().mockImplementation(() => ({
    acquire: mockRateLimiterAcquire,
  })),
  RateLimitExceededError: class RateLimitExceededError extends Error {
    constructor(msg: string) {
      super(`Rate limit exceeded: ${msg}`);
      this.name = 'RateLimitExceededError';
    }
  },
}));

const mockExecuteWithRetry = jest.fn();

jest.mock('@src/services/retry-service', () => ({
  RetryService: jest.fn().mockImplementation(() => ({
    executeWithRetry: mockExecuteWithRetry,
  })),
  MaxRetryExceededError: class MaxRetryExceededError extends Error {
    retryCount: number;
    lastError: string;
    constructor(retryCount: number, lastError: string) {
      super(`Max retries (${retryCount}) exceeded: ${lastError}`);
      this.name = 'MaxRetryExceededError';
      this.retryCount = retryCount;
      this.lastError = lastError;
    }
  },
}));

const mockSendNotification = jest.fn();

jest.mock('@src/services/notification/notification-factory', () => ({
  NotificationFactory: jest.fn().mockImplementation(() => ({
    sendNotification: mockSendNotification,
  })),
}));

const mockSendToDlq = jest.fn();

jest.mock('@src/services/dlq-service', () => ({
  DlqService: jest.fn().mockImplementation(() => ({
    sendToDlq: mockSendToDlq,
  })),
}));

import {
  eventConsumer,
  determineFinalStatus,
  _setSettingsForTest,
} from '@src/functions/event-consumer';
import { CircuitOpenError } from '@src/services/circuit-breaker';
import { MaxRetryExceededError } from '@src/services/retry-service';
import { RateLimitExceededError } from '@src/services/rate-limiter';
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

function makeEventGridEvent(overrides: Record<string, unknown> = {}): EventGridEvent {
  const data = {
    id: 'evt-001',
    clinic_id: 'CLINIC_123',
    correlation_id: 'cid-001',
    ...overrides,
  };
  return { data } as unknown as EventGridEvent;
}

const mockContext = {} as InvocationContext;

beforeEach(() => {
  jest.clearAllMocks();
  _setSettingsForTest(makeSettings());
  mockPatch.mockResolvedValue({});
  mockCheckState.mockResolvedValue('closed');
  mockRecordSuccess.mockResolvedValue(undefined);
  mockRecordFailure.mockResolvedValue(undefined);
  mockRateLimiterAcquire.mockResolvedValue(undefined);
  mockSendToDlq.mockResolvedValue({});
});

describe('determineFinalStatus 헬퍼', () => {
  it('all success → completed', () => {
    expect(determineFinalStatus([{ status: 'success' }, { status: 'success' }])).toBe('completed');
  });

  it('partial success → partially_completed', () => {
    expect(determineFinalStatus([{ status: 'success' }, { status: 'failed' }])).toBe('partially_completed');
  });

  it('all failed → failed', () => {
    expect(determineFinalStatus([{ status: 'failed' }, { status: 'failed' }])).toBe('failed');
  });

  it('single success → completed', () => {
    expect(determineFinalStatus([{ status: 'success' }])).toBe('completed');
  });

  it('single failed → failed', () => {
    expect(determineFinalStatus([{ status: 'failed' }])).toBe('failed');
  });
});

describe('Event Consumer Function', () => {
  it('전체 채널 성공 시 completed로 갱신된��', async () => {
    mockItemRead.mockResolvedValue({
      resource: {
        id: 'evt-001',
        clinic_id: 'CLINIC_123',
        status: 'queued',
        notifications: [
          { channel: 'email', provider: 'sendgrid', status: 'pending' },
          { channel: 'sms', provider: 'twilio', status: 'pending' },
        ],
      },
    });

    mockExecuteWithRetry.mockImplementation(async (fn: () => Promise<unknown>) => {
      // execute the fn to trigger sendNotification
      const result = await fn();
      return result;
    });

    mockSendNotification.mockResolvedValue({
      success: true,
      channel: 'email',
      provider: 'sendgrid',
      duration_ms: 50.0,
      message: '',
    });

    mockRateLimiterAcquire.mockResolvedValue(undefined);

    await eventConsumer(makeEventGridEvent(), mockContext);

    const lastPatch = mockPatch.mock.calls[mockPatch.mock.calls.length - 1][0];
    const statusOp = lastPatch.find((op: Record<string, unknown>) => op.path === '/status');
    expect(statusOp.value).toBe('completed');
  });

  it('Circuit Open → 즉시 실패 + DLQ 이동', async () => {
    mockItemRead.mockResolvedValue({
      resource: {
        id: 'evt-001',
        clinic_id: 'CLINIC_123',
        status: 'queued',
        event_type: 'appointment_confirmed',
        patient_id: 'P-001',
        notifications: [
          { channel: 'email', provider: 'sendgrid', status: 'pending' },
        ],
      },
    });

    mockCheckState.mockRejectedValue(new CircuitOpenError('email:sendgrid'));

    await eventConsumer(makeEventGridEvent(), mockContext);

    expect(mockExecuteWithRetry).not.toHaveBeenCalled();
    expect(mockSendToDlq).toHaveBeenCalledTimes(1);
    const dlqCall = mockSendToDlq.mock.calls[0][0];
    expect(dlqCall.channel).toBe('email');
    expect(dlqCall.provider).toBe('sendgrid');

    const lastPatch = mockPatch.mock.calls[mockPatch.mock.calls.length - 1][0];
    const statusOp = lastPatch.find((op: Record<string, unknown>) => op.path === '/status');
    expect(statusOp.value).toBe('failed');
  });

  it('Rate Limit 초과 → 실패 (DLQ 미이동)', async () => {
    mockItemRead.mockResolvedValue({
      resource: {
        id: 'evt-001',
        clinic_id: 'CLINIC_123',
        status: 'queued',
        notifications: [
          { channel: 'email', provider: 'sendgrid', status: 'pending' },
        ],
      },
    });

    mockExecuteWithRetry.mockImplementation(async (fn: () => Promise<unknown>) => {
      const result = await fn();
      return result;
    });

    mockRateLimiterAcquire.mockRejectedValue(new RateLimitExceededError('email:sendgrid'));

    await eventConsumer(makeEventGridEvent(), mockContext);

    expect(mockRecordFailure).not.toHaveBeenCalled();
    expect(mockSendToDlq).not.toHaveBeenCalled();

    const lastPatch = mockPatch.mock.calls[mockPatch.mock.calls.length - 1][0];
    const statusOp = lastPatch.find((op: Record<string, unknown>) => op.path === '/status');
    expect(statusOp.value).toBe('failed');
  });

  it('재시도 초과 → Circuit Breaker 실패 기록 + DLQ 이동', async () => {
    mockItemRead.mockResolvedValue({
      resource: {
        id: 'evt-001',
        clinic_id: 'CLINIC_123',
        status: 'queued',
        event_type: 'claim_completed',
        patient_id: 'P-002',
        notifications: [
          { channel: 'email', provider: 'sendgrid', status: 'pending' },
        ],
      },
    });

    mockExecuteWithRetry.mockRejectedValue(new MaxRetryExceededError(3, 'Timeout'));

    await eventConsumer(makeEventGridEvent(), mockContext);

    expect(mockRecordFailure).toHaveBeenCalledWith('email', 'sendgrid');
    expect(mockSendToDlq).toHaveBeenCalledTimes(1);
    const dlqCall = mockSendToDlq.mock.calls[0][0];
    expect(dlqCall.originalEventId).toBe('evt-001');
    expect(dlqCall.clinicId).toBe('CLINIC_123');
    expect(dlqCall.channel).toBe('email');
    expect(dlqCall.failureReason).toBe('Timeout');
    expect(dlqCall.retryCount).toBe(3);
  });

  it('발송 성공 → Circuit Breaker 성공 기록', async () => {
    mockItemRead.mockResolvedValue({
      resource: {
        id: 'evt-001',
        clinic_id: 'CLINIC_123',
        status: 'queued',
        notifications: [
          { channel: 'email', provider: 'sendgrid', status: 'pending' },
        ],
      },
    });

    mockExecuteWithRetry.mockImplementation(async (fn: () => Promise<unknown>) => {
      const result = await fn();
      return result;
    });

    mockSendNotification.mockResolvedValue({
      success: true,
      channel: 'email',
      provider: 'sendgrid',
      duration_ms: 50.0,
      message: '',
    });

    await eventConsumer(makeEventGridEvent(), mockContext);

    expect(mockRecordSuccess).toHaveBeenCalledWith('email', 'sendgrid');
  });

  it('이미 success인 채널은 재발송하지 않는다', async () => {
    mockItemRead.mockResolvedValue({
      resource: {
        id: 'evt-001',
        clinic_id: 'CLINIC_123',
        status: 'queued',
        notifications: [
          { channel: 'email', provider: 'sendgrid', status: 'success' },
          { channel: 'sms', provider: 'twilio', status: 'pending' },
        ],
      },
    });

    mockExecuteWithRetry.mockImplementation(async (fn: () => Promise<unknown>) => {
      const result = await fn();
      return result;
    });

    mockSendNotification.mockResolvedValue({
      success: true,
      channel: 'sms',
      provider: 'twilio',
      duration_ms: 30.0,
      message: '',
    });

    await eventConsumer(makeEventGridEvent(), mockContext);

    // checkState는 sms에 대해서만 호출
    expect(mockCheckState).toHaveBeenCalledTimes(1);
    expect(mockCheckState).toHaveBeenCalledWith('sms', 'twilio');
  });

  it('이미 완료된 이벤트는 재처리하지 않는다', async () => {
    mockItemRead.mockResolvedValue({
      resource: {
        id: 'evt-001',
        clinic_id: 'CLINIC_123',
        status: 'completed',
        notifications: [{ channel: 'email', provider: 'sendgrid', status: 'success' }],
      },
    });

    await eventConsumer(makeEventGridEvent(), mockContext);

    expect(mockPatch).not.toHaveBeenCalled();
  });

  it('이벤트 조회 실패 시 조기 리턴', async () => {
    mockItemRead.mockRejectedValue(new Error('DB unavailable'));

    await eventConsumer(makeEventGridEvent(), mockContext);

    expect(mockPatch).not.toHaveBeenCalled();
  });

  it('발송 전 status가 processing으로 갱신된다', async () => {
    mockItemRead.mockResolvedValue({
      resource: {
        id: 'evt-001',
        clinic_id: 'CLINIC_123',
        status: 'queued',
        notifications: [{ channel: 'email', provider: 'sendgrid', status: 'pending' }],
      },
    });

    mockExecuteWithRetry.mockImplementation(async (fn: () => Promise<unknown>) => {
      const result = await fn();
      return result;
    });

    mockSendNotification.mockResolvedValue({
      success: true,
      channel: 'email',
      provider: 'sendgrid',
      duration_ms: 10.0,
      message: '',
    });

    await eventConsumer(makeEventGridEvent(), mockContext);

    const firstPatch = mockPatch.mock.calls[0][0];
    const statusOp = firstPatch.find((op: Record<string, unknown>) => op.path === '/status');
    expect(statusOp.value).toBe('processing');
  });

  it('2/3 성공, 1/3 실패 → partially_completed + DLQ 1건', async () => {
    mockItemRead.mockResolvedValue({
      resource: {
        id: 'evt-001',
        clinic_id: 'CLINIC_123',
        status: 'queued',
        event_type: 'appointment_confirmed',
        patient_id: 'P-001',
        notifications: [
          { channel: 'email', provider: 'sendgrid', status: 'pending' },
          { channel: 'sms', provider: 'twilio', status: 'pending' },
          { channel: 'webhook', provider: 'webhook', status: 'pending' },
        ],
      },
    });

    let callIdx = 0;
    mockExecuteWithRetry.mockImplementation(async (fn: () => Promise<unknown>) => {
      callIdx++;
      if (callIdx === 2) {
        throw new MaxRetryExceededError(3, 'SMS gateway down');
      }
      const result = await fn();
      return result;
    });

    mockSendNotification.mockResolvedValue({
      success: true,
      channel: 'email',
      provider: 'sendgrid',
      duration_ms: 50.0,
      message: '',
    });

    await eventConsumer(makeEventGridEvent(), mockContext);

    expect(mockSendToDlq).toHaveBeenCalledTimes(1);
    const dlqCall = mockSendToDlq.mock.calls[0][0];
    expect(dlqCall.channel).toBe('sms');
    expect(dlqCall.failureReason).toBe('SMS gateway down');

    const lastPatch = mockPatch.mock.calls[mockPatch.mock.calls.length - 1][0];
    const statusOp = lastPatch.find((op: Record<string, unknown>) => op.path === '/status');
    expect(statusOp.value).toBe('partially_completed');
  });

  it('전체 채널 실패 → failed + DLQ 2건', async () => {
    mockItemRead.mockResolvedValue({
      resource: {
        id: 'evt-001',
        clinic_id: 'CLINIC_123',
        status: 'queued',
        event_type: 'claim_completed',
        patient_id: 'P-003',
        notifications: [
          { channel: 'email', provider: 'sendgrid', status: 'pending' },
          { channel: 'sms', provider: 'twilio', status: 'pending' },
        ],
      },
    });

    let callIdx = 0;
    mockExecuteWithRetry.mockImplementation(async () => {
      callIdx++;
      if (callIdx === 1) throw new MaxRetryExceededError(3, 'Email error');
      throw new MaxRetryExceededError(3, 'SMS error');
    });

    await eventConsumer(makeEventGridEvent(), mockContext);

    expect(mockSendToDlq).toHaveBeenCalledTimes(2);

    const lastPatch = mockPatch.mock.calls[mockPatch.mock.calls.length - 1][0];
    const statusOp = lastPatch.find((op: Record<string, unknown>) => op.path === '/status');
    expect(statusOp.value).toBe('failed');
  });
});
