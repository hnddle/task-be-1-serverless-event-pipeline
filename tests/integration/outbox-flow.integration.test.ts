/**
 * Outbox 흐름 통합 테스트.
 *
 * POST -> Change Feed -> outbox_publisher -> Event Grid 발행,
 * 발행 실패 -> failed_publish -> outbox_retry -> pending 복원 흐름을 검증한다.
 * Cosmos DB Emulator 필수 — Emulator 미실행 시 자동 스킵.
 */

import type { HttpRequest, InvocationContext, Timer } from '@azure/functions';

jest.mock('@azure/functions', () => ({
  app: { http: jest.fn(), cosmosDB: jest.fn(), timer: jest.fn(), eventGrid: jest.fn() },
}));

import { postEvents, _setSettingsForTest as setEventApiSettings } from '@src/functions/event-api';
import {
  outboxPublisher,
  _setSettingsForTest as setPublisherSettings,
  _setBrokerForTest,
} from '@src/functions/outbox-publisher';
import {
  outboxRetry,
  _setSettingsForTest as setRetrySettings,
} from '@src/functions/outbox-retry';
import { getEventsContainer, initContainers, resetClient } from '@src/services/cosmos-client';
import { isEmulatorAvailable, makeIntegrationSettings, uniqueClinicId } from './setup';
import type { Settings } from '@src/shared/config';
import { v4 as uuidv4 } from 'uuid';

process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

let settings: Settings;
let emulatorUp = false;

function makeRequest(body: Record<string, unknown>): HttpRequest {
  return {
    method: 'POST',
    url: 'http://localhost/api/events',
    params: {},
    query: { get: () => null, has: () => false },
    json: jest.fn().mockResolvedValue(body),
  } as unknown as HttpRequest;
}

function makeEventBody(clinicId: string): Record<string, unknown> {
  return {
    id: uuidv4(),
    event_type: 'appointment_confirmed',
    clinic_id: clinicId,
    patient_id: 'P-001',
    channels: ['email'],
  };
}

const mockContext = {} as InvocationContext;

beforeAll(async () => {
  emulatorUp = await isEmulatorAvailable();
  if (!emulatorUp) return;

  settings = makeIntegrationSettings();
  resetClient();
  await initContainers(settings);
  setEventApiSettings(settings);
}, 30000);

afterAll(() => {
  resetClient();
});

describe('Outbox Publisher 통합 테스트', () => {
  it('SKIP: Cosmos DB Emulator 미실행 시 스킵', () => {
    if (!emulatorUp) {
      console.log('Cosmos DB Emulator가 실행 중이지 않아 통합 테스트를 스킵합니다.');
    }
    expect(true).toBe(true);
  });

  it('pending 문서가 Event Grid로 발행되고 published로 갱신된다', async () => {
    if (!emulatorUp) return;

    const clinicId = uniqueClinicId();
    const body = makeEventBody(clinicId);
    const eventId = body.id as string;

    // 1. POST /events로 이벤트 생성 (pending 상태)
    const req = makeRequest(body);
    const resp = await postEvents(req, mockContext);
    expect(resp.status).toBe(201);

    // 2. Cosmos DB에서 문서 조회하여 pending 확인
    const container = getEventsContainer(settings);
    const { resource: doc } = await container.item(eventId, clinicId).read();
    expect(doc._outbox_status).toBe('pending');

    // 3. outbox_publisher 실행 (broker는 mock)
    const mockBroker = {
      publish: jest.fn().mockResolvedValue(undefined),
      getBrokerName: jest.fn().mockReturnValue('EventGrid'),
    };
    setPublisherSettings(settings);
    _setBrokerForTest(mockBroker);

    await outboxPublisher([doc], mockContext);

    // 4. broker.publish가 호출됨
    expect(mockBroker.publish).toHaveBeenCalledTimes(1);

    // 5. Cosmos DB에서 published로 갱신 확인
    const { resource: updated } = await container.item(eventId, clinicId).read();
    expect(updated._outbox_status).toBe('published');
  });

  it('발행 실패 시 failed_publish로 갱신된다', async () => {
    if (!emulatorUp) return;

    const clinicId = uniqueClinicId();
    const body = makeEventBody(clinicId);
    const eventId = body.id as string;

    const req = makeRequest(body);
    await postEvents(req, mockContext);

    const container = getEventsContainer(settings);
    const { resource: doc } = await container.item(eventId, clinicId).read();

    // broker 발행 실패
    const mockBroker = {
      publish: jest.fn().mockRejectedValue(new Error('Event Grid unavailable')),
      getBrokerName: jest.fn().mockReturnValue('EventGrid'),
    };
    setPublisherSettings(settings);
    _setBrokerForTest(mockBroker);

    await outboxPublisher([doc], mockContext);

    const { resource: updated } = await container.item(eventId, clinicId).read();
    expect(updated._outbox_status).toBe('failed_publish');
  });
});

describe('Outbox Retry 통합 테스트', () => {
  it('failed_publish -> outbox_retry -> pending 복원', async () => {
    if (!emulatorUp) return;

    const clinicId = uniqueClinicId();
    const body = makeEventBody(clinicId);
    const eventId = body.id as string;

    const req = makeRequest(body);
    await postEvents(req, mockContext);

    // 강제로 failed_publish 설정
    const container = getEventsContainer(settings);
    await container.item(eventId, clinicId).patch([
      { op: 'set', path: '/_outbox_status', value: 'failed_publish' },
    ]);

    // outbox_retry 실행
    setRetrySettings(settings);
    const timer = { isPastDue: false } as Timer;
    await outboxRetry(timer, mockContext);

    // pending으로 복원 확인
    const { resource: updated } = await container.item(eventId, clinicId).read();
    expect(updated._outbox_status).toBe('pending');
  });
});
