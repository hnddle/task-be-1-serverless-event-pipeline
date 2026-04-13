/**
 * Event API 테스트.
 */

import type { Settings } from '@src/shared/config';
import type { HttpRequest, InvocationContext } from '@azure/functions';

const mockCreate = jest.fn();
const mockRead = jest.fn();
const mockItem = jest.fn().mockReturnValue({ read: mockRead });
const mockQuery = jest.fn();
const mockContainerObj = {
  items: { create: mockCreate, query: mockQuery },
  item: mockItem,
};

jest.mock('@src/services/cosmos-client', () => ({
  getEventsContainer: jest.fn(() => mockContainerObj),
}));

jest.mock('@src/shared/config', () => {
  const actual: Record<string, unknown> = {};
  return {
    ...actual,
    getSettings: jest.fn(),
    resetSettings: jest.fn(),
  };
});

// Prevent app.http registration from running
jest.mock('@azure/functions', () => ({
  app: {
    http: jest.fn(),
    cosmosDB: jest.fn(),
    timer: jest.fn(),
    eventGrid: jest.fn(),
  },
}));

import { postEvents, getEventById, getEvents, _setSettingsForTest } from '@src/functions/event-api';

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

const VALID_EVENT_BODY = {
  id: '550e8400-e29b-41d4-a716-446655440000',
  event_type: 'appointment_confirmed',
  clinic_id: 'CLINIC_123',
  patient_id: 'PATIENT_456',
  channels: ['email', 'sms'],
};

const mockContext = {} as InvocationContext;

function makeRequest(options: {
  method?: string;
  body?: Record<string, unknown> | null;
  params?: Record<string, string>;
  query?: Record<string, string>;
}): HttpRequest {
  const queryMap = new Map(Object.entries(options.query ?? {}));

  return {
    method: options.method ?? 'POST',
    url: 'http://localhost/api/events',
    params: options.params ?? {},
    query: {
      get: (key: string) => queryMap.get(key) ?? null,
      has: (key: string) => queryMap.has(key),
    },
    json: jest.fn().mockResolvedValue(options.body ?? {}),
  } as unknown as HttpRequest;
}

beforeEach(() => {
  jest.clearAllMocks();
  _setSettingsForTest(makeSettings());
});

describe('POST /events', () => {
  it('유효한 POST 요청 시 201을 반환한다', async () => {
    mockCreate.mockResolvedValue({});

    const req = makeRequest({ method: 'POST', body: VALID_EVENT_BODY });
    const resp = await postEvents(req, mockContext);

    expect(resp.status).toBe(201);
    const body = JSON.parse(resp.body as string);
    expect(body.event_id).toBe(VALID_EVENT_BODY.id);
    expect(body.status).toBe('queued');
    expect(body).toHaveProperty('correlation_id');
  });

  it('DB에 _outbox_status: pending으로 저장된다', async () => {
    mockCreate.mockResolvedValue({});

    const req = makeRequest({ method: 'POST', body: VALID_EVENT_BODY });
    await postEvents(req, mockContext);

    expect(mockCreate).toHaveBeenCalledTimes(1);
    const savedDoc = mockCreate.mock.calls[0][0];
    expect(savedDoc._outbox_status).toBe('pending');
    expect(savedDoc.status).toBe('queued');
  });

  it('동일 id 재요청 시 200을 반환한다', async () => {
    mockCreate.mockRejectedValue({ code: 409 });
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({
        resource: {
          id: VALID_EVENT_BODY.id,
          status: 'processing',
          correlation_id: 'existing-cid',
        },
      }),
    });

    const req = makeRequest({ method: 'POST', body: VALID_EVENT_BODY });
    const resp = await postEvents(req, mockContext);

    expect(resp.status).toBe(200);
    const body = JSON.parse(resp.body as string);
    expect(body.message).toBe('Event already exists');
    expect(body.status).toBe('processing');
  });

  it('유효하지 않은 JSON 바디는 400을 반환한다', async () => {
    const req = {
      method: 'POST',
      url: 'http://localhost/api/events',
      params: {},
      query: { get: () => null, has: () => false },
      json: jest.fn().mockRejectedValue(new Error('Invalid JSON')),
    } as unknown as HttpRequest;

    const resp = await postEvents(req, mockContext);
    expect(resp.status).toBe(400);
  });

  it('검증 실패 시 400 + 에러 상세를 반환한다', async () => {
    const req = makeRequest({ method: 'POST', body: { channels: [] } });
    const resp = await postEvents(req, mockContext);

    expect(resp.status).toBe(400);
    const body = JSON.parse(resp.body as string);
    expect(body.error).toBe('VALIDATION_ERROR');
    expect(body.details.length).toBeGreaterThan(0);
  });
});

describe('GET /events/{event_id}', () => {
  it('clinic_id 없이도 cross-partition query로 조회된다', async () => {
    mockQuery.mockReturnValue({
      fetchAll: jest.fn().mockResolvedValue({
        resources: [{
          id: 'some-id',
          clinic_id: 'CLINIC_A',
          status: 'queued',
          notifications: [],
        }],
      }),
    });

    const req = makeRequest({
      method: 'GET',
      params: { event_id: 'some-id' },
    });
    const resp = await getEventById(req, mockContext);
    expect(resp.status).toBe(200);
    const body = JSON.parse(resp.body as string);
    expect(body.id).toBe('some-id');
  });

  it('존재하는 이벤트 조회 시 200을 반환한다', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockResolvedValue({
        resource: {
          id: 'evt-1',
          clinic_id: 'CLINIC_123',
          status: 'completed',
          _outbox_status: 'published',
          _rid: 'xxx',
          _self: 'xxx',
          _etag: 'xxx',
          _attachments: 'xxx',
          _ts: 123,
        },
      }),
    });

    const req = makeRequest({
      method: 'GET',
      params: { event_id: 'evt-1' },
      query: { clinic_id: 'CLINIC_123' },
    });
    const resp = await getEventById(req, mockContext);

    expect(resp.status).toBe(200);
    const body = JSON.parse(resp.body as string);
    expect(body.id).toBe('evt-1');
    expect(body).not.toHaveProperty('_outbox_status');
    expect(body).not.toHaveProperty('_rid');
  });

  it('존재하지 않는 이벤트 조회 시 404를 반환한다', async () => {
    mockItem.mockReturnValue({
      read: jest.fn().mockRejectedValue({ code: 404 }),
    });

    const req = makeRequest({
      method: 'GET',
      params: { event_id: 'nonexistent' },
      query: { clinic_id: 'CLINIC_123' },
    });
    const resp = await getEventById(req, mockContext);
    expect(resp.status).toBe(404);
  });
});

describe('GET /events', () => {
  it('clinic_id가 없으면 400을 반환한다', async () => {
    const req = makeRequest({ method: 'GET' });
    const resp = await getEvents(req, mockContext);
    expect(resp.status).toBe(400);
  });

  it('이벤트 목록을 items 배열로 반환한다', async () => {
    mockQuery.mockReturnValue({
      fetchNext: jest.fn().mockResolvedValue({
        resources: [{ id: 'evt-1', status: 'queued' }],
        continuationToken: null,
      }),
    });

    const req = makeRequest({
      method: 'GET',
      query: { clinic_id: 'CLINIC_123' },
    });
    const resp = await getEvents(req, mockContext);

    expect(resp.status).toBe(200);
    const body = JSON.parse(resp.body as string);
    expect(body).toHaveProperty('items');
    expect(body).toHaveProperty('continuation_token');
  });

  it('page_size > 100이면 100으로 클램핑된다', async () => {
    mockQuery.mockReturnValue({
      fetchNext: jest.fn().mockResolvedValue({
        resources: [],
        continuationToken: null,
      }),
    });

    const req = makeRequest({
      method: 'GET',
      query: { clinic_id: 'CLINIC_123', page_size: '200' },
    });
    await getEvents(req, mockContext);

    const queryCall = mockQuery.mock.calls[0];
    expect(queryCall[1].maxItemCount).toBe(100);
  });
});
