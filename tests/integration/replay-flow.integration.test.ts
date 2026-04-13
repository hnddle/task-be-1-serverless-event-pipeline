/**
 * DLQ Replay 흐름 통합 테스트.
 *
 * DLQ Replay -> Outbox 재발행 -> 재처리 흐름을 Cosmos DB Emulator로 검증한다.
 * Emulator 미실행 시 자동 스킵.
 */

import type { EventGridEvent, HttpRequest, InvocationContext } from '@azure/functions';

jest.mock('@azure/functions', () => ({
  app: { http: jest.fn(), cosmosDB: jest.fn(), timer: jest.fn(), eventGrid: jest.fn() },
}));

import { postEvents, _setSettingsForTest as setEventApiSettings } from '@src/functions/event-api';
import { eventConsumer, _setSettingsForTest as setConsumerSettings } from '@src/functions/event-consumer';
import { postDlqReplay, _setSettingsForTest as setDlqApiSettings } from '@src/functions/dlq-api';
import {
  getDlqContainer,
  getEventsContainer,
  getCircuitBreakerContainer,
  initContainers,
  resetClient,
} from '@src/services/cosmos-client';
import { isEmulatorAvailable, makeIntegrationSettings, uniqueClinicId } from './setup';
import type { Settings } from '@src/shared/config';
import { v4 as uuidv4 } from 'uuid';

process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

let settings: Settings;
let emulatorUp = false;

function makeHttpRequest(options: {
  method?: string;
  body?: Record<string, unknown> | null;
  params?: Record<string, string>;
  query?: Record<string, string>;
}): HttpRequest {
  const queryMap = new Map(Object.entries(options.query ?? {}));
  return {
    method: options.method ?? 'POST',
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

function makeEventBody(clinicId: string): Record<string, unknown> {
  return {
    id: uuidv4(),
    event_type: 'insurance_approved',
    clinic_id: clinicId,
    patient_id: 'P-003',
    channels: ['email'],
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

async function createEventAndFailToDlq(clinicId: string): Promise<{ eventId: string; correlationId: string }> {
  const body = makeEventBody(clinicId);
  const eventId = body.id as string;

  const req = makeHttpRequest({ body });
  const resp = await postEvents(req, mockContext);
  const result = JSON.parse(resp.body as string);
  const correlationId = result.correlation_id;

  // CB를 OPEN으로 설정하여 Consumer가 실패하도록
  const cbContainer = getCircuitBreakerContainer(settings);
  await cbContainer.items.upsert({
    id: 'email:sendgrid',
    state: 'OPEN',
    failure_count: 3,
    success_count: 0,
    last_failure_at: new Date().toISOString(),
    last_state_change_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  });

  const egEvent = makeEventGridEvent(eventId, clinicId, correlationId);
  await eventConsumer(egEvent, mockContext);

  // CB 문서 삭제
  try {
    await cbContainer.item('email:sendgrid', 'email:sendgrid').delete();
  } catch {
    // ignore
  }

  return { eventId, correlationId };
}

beforeAll(async () => {
  emulatorUp = await isEmulatorAvailable();
  if (!emulatorUp) return;

  settings = makeIntegrationSettings();
  resetClient();
  await initContainers(settings);
  setEventApiSettings(settings);
  setConsumerSettings(settings);
  setDlqApiSettings(settings);
}, 30000);

afterAll(() => {
  resetClient();
});

describe('DLQ Replay 통합 테스트', () => {
  it('SKIP: Cosmos DB Emulator 미실행 시 스킵', () => {
    if (!emulatorUp) {
      console.log('Cosmos DB Emulator가 실행 중이지 않아 통합 테스트를 스킵합니다.');
    }
    expect(true).toBe(true);
  });

  it('DLQ replay -> 새 이벤트가 Outbox 패턴으로 재발행된다', async () => {
    if (!emulatorUp) return;

    const clinicId = uniqueClinicId();

    // 1. 이벤트 생성 + Consumer 실패 -> DLQ 이동
    const { eventId, correlationId: originalCorr } = await createEventAndFailToDlq(clinicId);

    // 2. DLQ에서 문서 조회
    const dlqContainer = getDlqContainer(settings);
    const { resources: dlqDocs } = await dlqContainer.items
      .query({
        query: 'SELECT * FROM c WHERE c.original_event_id = @event_id AND c.clinic_id = @clinic_id',
        parameters: [
          { name: '@event_id', value: eventId },
          { name: '@clinic_id', value: clinicId },
        ],
      })
      .fetchAll();

    expect(dlqDocs.length).toBe(1);
    const dlqId = dlqDocs[0].id;

    // 3. POST /dlq/{dlq_id}/replay
    const replayReq = makeHttpRequest({
      method: 'POST',
      query: { clinic_id: clinicId },
      params: { dlq_id: dlqId },
    });
    const resp = await postDlqReplay(replayReq, mockContext);

    expect(resp.status).toBe(200);
    const respBody = JSON.parse(resp.body as string);
    expect(respBody.replay_status).toBe('replayed');
    const newCorr = respBody.new_correlation_id;
    expect(newCorr).not.toBe(originalCorr);

    // 4. DLQ 문서가 replayed로 갱신
    const { resource: updatedDlq } = await dlqContainer.item(dlqId, clinicId).read();
    expect(updatedDlq.replay_status).toBe('replayed');
    expect(updatedDlq.replayed_at).not.toBeNull();

    // 5. events 컨테이너에 새 이벤트가 pending 상태로 생성
    const eventsContainer = getEventsContainer(settings);
    const { resources: newEvents } = await eventsContainer.items
      .query({
        query: 'SELECT * FROM c WHERE c.correlation_id = @corr_id AND c.clinic_id = @clinic_id',
        parameters: [
          { name: '@corr_id', value: newCorr },
          { name: '@clinic_id', value: clinicId },
        ],
      })
      .fetchAll();

    expect(newEvents.length).toBe(1);
    expect(newEvents[0].status).toBe('queued');
    expect(newEvents[0]._outbox_status).toBe('pending');
  }, 60000);

  it('이미 replayed된 DLQ -> 409', async () => {
    if (!emulatorUp) return;

    const clinicId = uniqueClinicId();
    const { eventId } = await createEventAndFailToDlq(clinicId);

    const dlqContainer = getDlqContainer(settings);
    const { resources: dlqDocs } = await dlqContainer.items
      .query({
        query: 'SELECT * FROM c WHERE c.original_event_id = @event_id AND c.clinic_id = @clinic_id',
        parameters: [
          { name: '@event_id', value: eventId },
          { name: '@clinic_id', value: clinicId },
        ],
      })
      .fetchAll();

    const dlqId = dlqDocs[0].id;

    // 첫 번째 replay -> 200
    const req1 = makeHttpRequest({
      method: 'POST',
      query: { clinic_id: clinicId },
      params: { dlq_id: dlqId },
    });
    const resp1 = await postDlqReplay(req1, mockContext);
    expect(resp1.status).toBe(200);

    // 두 번째 replay -> 409
    const req2 = makeHttpRequest({
      method: 'POST',
      query: { clinic_id: clinicId },
      params: { dlq_id: dlqId },
    });
    const resp2 = await postDlqReplay(req2, mockContext);
    expect(resp2.status).toBe(409);
  }, 60000);
});
