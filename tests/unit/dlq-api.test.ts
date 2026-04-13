/**
 * DLQ API 테스트.
 */

import type { HttpRequest, InvocationContext } from '@azure/functions';

const mockDlqRead = jest.fn();
const mockDlqItem = jest.fn().mockReturnValue({ read: mockDlqRead });
const mockDlqUpsert = jest.fn();
const mockDlqQuery = jest.fn();
const mockDlqContainerObj = {
  item: mockDlqItem,
  items: { upsert: mockDlqUpsert, query: mockDlqQuery },
};

const mockEventsCreate = jest.fn();
const mockEventsContainerObj = {
  items: { create: mockEventsCreate },
};

jest.mock('@azure/functions', () => ({
  app: { http: jest.fn(), cosmosDB: jest.fn(), timer: jest.fn(), eventGrid: jest.fn() },
}));

jest.mock('@src/services/cosmos-client', () => ({
  getDlqContainer: jest.fn(() => mockDlqContainerObj),
  getEventsContainer: jest.fn(() => mockEventsContainerObj),
}));

import { getDlq, postDlqReplay, postDlqReplayBatch, _setSettingsForTest } from '@src/functions/dlq-api';
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

function makeDlqDoc(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'dlq-001',
    original_event_id: 'evt-001',
    clinic_id: 'CLINIC_123',
    channel: 'email',
    provider: 'sendgrid',
    event_type: 'appointment_confirmed',
    patient_id: 'P-001',
    payload: {
      id: 'evt-001',
      clinic_id: 'CLINIC_123',
      event_type: 'appointment_confirmed',
      patient_id: 'P-001',
    },
    failure_reason: 'Timeout',
    retry_count: 3,
    correlation_id: 'old-corr-001',
    created_at: '2026-04-01T00:00:00+00:00',
    replay_status: 'pending',
    replayed_at: null,
    ...overrides,
  };
}

function makeRequest(options: {
  method?: string;
  query?: Record<string, string>;
  params?: Record<string, string>;
  body?: Record<string, unknown> | null;
}): HttpRequest {
  const queryMap = new Map(Object.entries(options.query ?? {}));

  return {
    method: options.method ?? 'GET',
    url: 'http://localhost/api/dlq',
    params: options.params ?? {},
    query: {
      get: (key: string) => queryMap.get(key) ?? null,
      has: (key: string) => queryMap.has(key),
    },
    json: options.body !== undefined
      ? jest.fn().mockResolvedValue(options.body)
      : jest.fn().mockRejectedValue(new Error('No JSON body')),
  } as unknown as HttpRequest;
}

const mockContext = {} as InvocationContext;

beforeEach(() => {
  jest.clearAllMocks();
  _setSettingsForTest(makeSettings());
});

describe('GET /dlq', () => {
  it('clinic_id 누락 시 400 반환', async () => {
    const req = makeRequest({ query: {} });
    const resp = await getDlq(req, mockContext);
    expect(resp.status).toBe(400);
    const body = JSON.parse(resp.body as string);
    expect(body.error).toBe('VALIDATION_ERROR');
  });

  it('정상 조회 시 items, continuation_token, total_count를 반환한다', async () => {
    const doc = makeDlqDoc();
    mockDlqQuery.mockReturnValue({
      fetchNext: jest.fn().mockResolvedValue({
        resources: [doc],
        continuationToken: 'next-token-123',
      }),
    });

    const req = makeRequest({ query: { clinic_id: 'CLINIC_123' } });
    const resp = await getDlq(req, mockContext);

    expect(resp.status).toBe(200);
    const body = JSON.parse(resp.body as string);
    expect(body.items).toHaveLength(1);
    expect(body.items[0].id).toBe('dlq-001');
    expect(body.continuation_token).toBe('next-token-123');
    expect(body.total_count).toBe(1);
  });

  it('replay_status, event_type 필터가 쿼리에 반영된다', async () => {
    mockDlqQuery.mockReturnValue({
      fetchNext: jest.fn().mockResolvedValue({
        resources: [],
        continuationToken: null,
      }),
    });

    const req = makeRequest({
      query: {
        clinic_id: 'CLINIC_123',
        replay_status: 'pending',
        event_type: 'appointment_confirmed',
      },
    });
    await getDlq(req, mockContext);

    const queryCall = mockDlqQuery.mock.calls[0];
    const queryStr = queryCall[0].query;
    expect(queryStr).toContain('replay_status');
    expect(queryStr).toContain('event_type');
  });
});

describe('POST /dlq/{dlq_id}/replay', () => {
  it('정상 Replay 시 200 반환 + replayed 상태', async () => {
    mockDlqItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({ resource: makeDlqDoc() }),
    });
    mockDlqUpsert.mockResolvedValue({});
    mockEventsCreate.mockResolvedValue({});

    const req = makeRequest({
      method: 'POST',
      query: { clinic_id: 'CLINIC_123' },
      params: { dlq_id: 'dlq-001' },
    });
    const resp = await postDlqReplay(req, mockContext);

    expect(resp.status).toBe(200);
    const body = JSON.parse(resp.body as string);
    expect(body.dlq_id).toBe('dlq-001');
    expect(body.replay_status).toBe('replayed');
    expect(body).toHaveProperty('new_correlation_id');
    expect(mockEventsCreate).toHaveBeenCalledTimes(1);
    expect(mockDlqUpsert).toHaveBeenCalledTimes(1);
  });

  it('이미 replayed된 문서 → 409', async () => {
    mockDlqItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({ resource: makeDlqDoc({ replay_status: 'replayed' }) }),
    });

    const req = makeRequest({
      method: 'POST',
      query: { clinic_id: 'CLINIC_123' },
      params: { dlq_id: 'dlq-001' },
    });
    const resp = await postDlqReplay(req, mockContext);

    expect(resp.status).toBe(409);
    const body = JSON.parse(resp.body as string);
    expect(body.error).toBe('CONFLICT');
  });

  it('존재하지 않는 DLQ ID → 404', async () => {
    mockDlqItem.mockReturnValue({
      read: jest.fn().mockRejectedValue({ code: 404 }),
    });

    const req = makeRequest({
      method: 'POST',
      query: { clinic_id: 'CLINIC_123' },
      params: { dlq_id: 'dlq-999' },
    });
    const resp = await postDlqReplay(req, mockContext);

    expect(resp.status).toBe(404);
  });

  it('clinic_id 누락 시 400', async () => {
    const req = makeRequest({
      method: 'POST',
      params: { dlq_id: 'dlq-001' },
    });
    const resp = await postDlqReplay(req, mockContext);

    expect(resp.status).toBe(400);
  });

  it('Replay 시 새 correlation_id가 발급된다', async () => {
    mockDlqItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({ resource: makeDlqDoc() }),
    });
    mockDlqUpsert.mockResolvedValue({});
    mockEventsCreate.mockResolvedValue({});

    const req = makeRequest({
      method: 'POST',
      query: { clinic_id: 'CLINIC_123' },
      params: { dlq_id: 'dlq-001' },
    });
    const resp = await postDlqReplay(req, mockContext);

    const body = JSON.parse(resp.body as string);
    expect(body.new_correlation_id).not.toBe('old-corr-001');
    const createdEvent = mockEventsCreate.mock.calls[0][0];
    expect(createdEvent.correlation_id).toBe(body.new_correlation_id);
  });
});

describe('POST /dlq/replay-batch', () => {
  it('배치 Replay 정상 동작', async () => {
    const docs = [makeDlqDoc({ id: 'dlq-0' }), makeDlqDoc({ id: 'dlq-1' }), makeDlqDoc({ id: 'dlq-2' })];
    mockDlqQuery.mockReturnValue({
      fetchAll: jest.fn().mockResolvedValue({ resources: docs }),
    });
    mockDlqUpsert.mockResolvedValue({});
    mockEventsCreate.mockResolvedValue({});

    const req = makeRequest({
      method: 'POST',
      body: { clinic_id: 'CLINIC_123' },
    });
    const resp = await postDlqReplayBatch(req, mockContext);

    expect(resp.status).toBe(200);
    const body = JSON.parse(resp.body as string);
    expect(body.replayed_count).toBe(3);
    expect(body.failed_count).toBe(0);
    expect(body.skipped_count).toBe(0);
  });

  it('clinic_id 누락 시 400', async () => {
    const req = makeRequest({ method: 'POST', body: {} });
    const resp = await postDlqReplayBatch(req, mockContext);

    expect(resp.status).toBe(400);
  });

  it('배치 결과 카운트가 정확하다 (replayed, failed, skipped)', async () => {
    const docs = [
      makeDlqDoc({ id: 'dlq-ok' }),
      makeDlqDoc({ id: 'dlq-fail' }),
      makeDlqDoc({ id: 'dlq-ok2' }),
    ];
    mockDlqQuery.mockReturnValue({
      fetchAll: jest.fn().mockResolvedValue({ resources: docs }),
    });

    let upsertCount = 0;
    mockDlqUpsert.mockImplementation(async () => {
      upsertCount++;
      if (upsertCount === 2) throw new Error('DB write error');
      return {};
    });
    mockEventsCreate.mockResolvedValue({});

    const req = makeRequest({
      method: 'POST',
      body: { clinic_id: 'CLINIC_123' },
    });
    const resp = await postDlqReplayBatch(req, mockContext);

    const body = JSON.parse(resp.body as string);
    expect(body.replayed_count).toBe(2);
    expect(body.failed_count).toBe(1);
    expect(body.skipped_count).toBe(0);
  });
});
