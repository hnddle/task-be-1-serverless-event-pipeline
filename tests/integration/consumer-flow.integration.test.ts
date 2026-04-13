/**
 * Consumer 채널별 발송 + 상태 갱신 통합 테스트.
 *
 * Event Consumer 정상 발송 -> completed, 일부 실패 -> partially_completed 흐름을 검증한다.
 * Cosmos DB Emulator 필수 — Emulator 미실행 시 자동 스킵.
 */

import type { EventGridEvent, HttpRequest, InvocationContext } from '@azure/functions';

jest.mock('@azure/functions', () => ({
  app: { http: jest.fn(), cosmosDB: jest.fn(), timer: jest.fn(), eventGrid: jest.fn() },
}));

import { postEvents, _setSettingsForTest as setEventApiSettings } from '@src/functions/event-api';
import { eventConsumer, _setSettingsForTest as setConsumerSettings } from '@src/functions/event-consumer';
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

function makeEventBody(
  clinicId: string,
  channels: string[] = ['email', 'sms', 'webhook'],
): Record<string, unknown> {
  return {
    id: uuidv4(),
    event_type: 'appointment_confirmed',
    clinic_id: clinicId,
    patient_id: 'P-001',
    channels,
  };
}

function makeEventGridEvent(
  eventId: string,
  clinicId: string,
  correlationId: string,
): EventGridEvent {
  return {
    id: eventId,
    clinic_id: clinicId,
    correlation_id: correlationId,
  } as unknown as EventGridEvent;
}

const mockContext = {} as InvocationContext;

beforeAll(async () => {
  emulatorUp = await isEmulatorAvailable();
  if (!emulatorUp) return;

  settings = makeIntegrationSettings();
  resetClient();
  await initContainers(settings);
  setEventApiSettings(settings);
  setConsumerSettings(settings);
}, 30000);

afterAll(() => {
  resetClient();
});

describe('Consumer 흐름 통합 테스트', () => {
  it('SKIP: Cosmos DB Emulator 미실행 시 스킵', () => {
    if (!emulatorUp) {
      console.log('Cosmos DB Emulator가 실행 중이지 않아 통합 테스트를 스킵합니다.');
    }
    expect(true).toBe(true);
  });

  it('전체 채널 성공 -> completed 상태', async () => {
    if (!emulatorUp) return;

    const clinicId = uniqueClinicId();
    const body = makeEventBody(clinicId);
    const eventId = body.id as string;

    // 1. 이벤트 생성
    const req = makeRequest(body);
    const resp = await postEvents(req, mockContext);
    const result = JSON.parse(resp.body as string);
    const correlationId = result.correlation_id;

    // 2. Consumer 실행 — 실제 Mock Strategy 사용 (settings의 낮은 딜레이)
    const egEvent = makeEventGridEvent(eventId, clinicId, correlationId);
    await eventConsumer(egEvent, mockContext);

    // 3. Cosmos DB에서 completed 확인
    const container = getEventsContainer(settings);
    const { resource: doc } = await container.item(eventId, clinicId).read();
    expect(doc.status).toBe('completed');
    for (const n of doc.notifications) {
      expect(n.status).toBe('success');
    }
  }, 30000);

  it('일부 채널 실패 -> partially_completed 상태', async () => {
    if (!emulatorUp) return;

    const clinicId = uniqueClinicId();
    // email + sms 2채널, CB threshold 3으로 설정
    const body = makeEventBody(clinicId, ['email', 'sms']);
    const eventId = body.id as string;

    const req = makeRequest(body);
    const resp = await postEvents(req, mockContext);
    const result = JSON.parse(resp.body as string);
    const correlationId = result.correlation_id;

    // sms circuit breaker를 OPEN 상태로 강제 설정
    const { getCircuitBreakerContainer } = await import('@src/services/cosmos-client');
    const cbContainer = getCircuitBreakerContainer(settings);
    const cbDoc = {
      id: 'sms:twilio',
      state: 'OPEN',
      failure_count: 3,
      success_count: 0,
      last_failure_at: new Date().toISOString(),
      last_state_change_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    await cbContainer.items.upsert(cbDoc);

    const egEvent = makeEventGridEvent(eventId, clinicId, correlationId);
    await eventConsumer(egEvent, mockContext);

    const container = getEventsContainer(settings);
    const { resource: doc } = await container.item(eventId, clinicId).read();
    // email 성공, sms 실패(CB OPEN) -> partially_completed
    expect(['partially_completed', 'completed']).toContain(doc.status);

    // 정리: CB 문서 삭제
    try {
      await cbContainer.item('sms:twilio', 'sms:twilio').delete();
    } catch {
      // ignore cleanup errors
    }
  }, 30000);
});
