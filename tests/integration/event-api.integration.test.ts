/**
 * Event API 통합 테스트.
 *
 * POST /events -> Cosmos DB 저장 -> 중복 처리 -> 조회 흐름을 검증한다.
 * Cosmos DB Emulator 필수 — Emulator 미실행 시 자동 스킵.
 */

import type { HttpRequest, InvocationContext } from '@azure/functions';

jest.mock('@azure/functions', () => ({
  app: { http: jest.fn(), cosmosDB: jest.fn(), timer: jest.fn(), eventGrid: jest.fn() },
}));

import { postEvents, getEventById, getEvents, _setSettingsForTest } from '@src/functions/event-api';
import { initContainers, resetClient } from '@src/services/cosmos-client';
import { isEmulatorAvailable, makeIntegrationSettings, uniqueClinicId } from './setup';
import type { Settings } from '@src/shared/config';
import { v4 as uuidv4 } from 'uuid';

// Emulator 자체서명 인증서 허용
process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

let settings: Settings;
let emulatorUp = false;

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
    json: options.body !== undefined
      ? jest.fn().mockResolvedValue(options.body)
      : jest.fn().mockRejectedValue(new Error('No JSON body')),
  } as unknown as HttpRequest;
}

function makeEventBody(clinicId: string, eventId?: string): Record<string, unknown> {
  return {
    id: eventId ?? uuidv4(),
    event_type: 'appointment_confirmed',
    clinic_id: clinicId,
    patient_id: 'P-001',
    channels: ['email', 'sms'],
  };
}

const mockContext = {} as InvocationContext;

beforeAll(async () => {
  emulatorUp = await isEmulatorAvailable();
  if (!emulatorUp) return;

  settings = makeIntegrationSettings();
  resetClient();
  await initContainers(settings);
  _setSettingsForTest(settings);
}, 30000);

afterAll(() => {
  resetClient();
});

describe('Event API 통합 테스트', () => {
  beforeEach(() => {
    if (!emulatorUp) return;
  });

  it('SKIP: Cosmos DB Emulator 미실행 시 스킵', () => {
    if (!emulatorUp) {
      console.log('Cosmos DB Emulator가 실행 중이지 않아 통합 테스트를 스킵합니다.');
    }
    expect(true).toBe(true);
  });

  it('POST /events -> 201 + DB에 이벤트 저장', async () => {
    if (!emulatorUp) return;

    const clinicId = uniqueClinicId();
    const body = makeEventBody(clinicId);
    const req = makeRequest({ body });
    const resp = await postEvents(req, mockContext);

    expect(resp.status).toBe(201);
    const result = JSON.parse(resp.body as string);
    expect(result.event_id).toBe(body.id);
    expect(result.status).toBe('queued');
    expect(result).toHaveProperty('correlation_id');
  });

  it('중복 POST -> 200 + 기존 상태 반환', async () => {
    if (!emulatorUp) return;

    const clinicId = uniqueClinicId();
    const body = makeEventBody(clinicId);

    const req1 = makeRequest({ body });
    const resp1 = await postEvents(req1, mockContext);
    expect(resp1.status).toBe(201);

    const req2 = makeRequest({ body });
    const resp2 = await postEvents(req2, mockContext);
    expect(resp2.status).toBe(200);

    const result = JSON.parse(resp2.body as string);
    expect(result.event_id).toBe(body.id);
    expect(result).toHaveProperty('message');
  });

  it('GET /events/{event_id} -> 상세 조회 확인', async () => {
    if (!emulatorUp) return;

    const clinicId = uniqueClinicId();
    const body = makeEventBody(clinicId);

    const createReq = makeRequest({ body });
    await postEvents(createReq, mockContext);

    const getReq = makeRequest({
      method: 'GET',
      query: { clinic_id: clinicId },
      params: { event_id: body.id as string },
    });
    const resp = await getEventById(getReq, mockContext);

    expect(resp.status).toBe(200);
    const result = JSON.parse(resp.body as string);
    expect(result.id).toBe(body.id);
    expect(result.clinic_id).toBe(clinicId);
    expect(result.event_type).toBe('appointment_confirmed');
    expect(result.status).toBe('queued');
    expect(result.notifications).toHaveLength(2);
  });

  it('존재하지 않는 event_id -> 404', async () => {
    if (!emulatorUp) return;

    const clinicId = uniqueClinicId();
    const getReq = makeRequest({
      method: 'GET',
      query: { clinic_id: clinicId },
      params: { event_id: uuidv4() },
    });
    const resp = await getEventById(getReq, mockContext);
    expect(resp.status).toBe(404);
  });

  it('GET /events -> 목록 조회 + 페이지네이션', async () => {
    if (!emulatorUp) return;

    const clinicId = uniqueClinicId();

    for (let i = 0; i < 3; i++) {
      const body = makeEventBody(clinicId);
      const req = makeRequest({ body });
      const resp = await postEvents(req, mockContext);
      expect(resp.status).toBe(201);
    }

    const listReq = makeRequest({
      method: 'GET',
      query: { clinic_id: clinicId, page_size: '2' },
    });
    const resp = await getEvents(listReq, mockContext);

    expect(resp.status).toBe(200);
    const result = JSON.parse(resp.body as string);
    expect(result.items).toHaveLength(2);
    expect(result.continuation_token).not.toBeNull();
  });

  it('clinic_id 없이 목록 조회 -> 400', async () => {
    if (!emulatorUp) return;

    const req = makeRequest({ method: 'GET', query: {} });
    const resp = await getEvents(req, mockContext);
    expect(resp.status).toBe(400);
  });
});
