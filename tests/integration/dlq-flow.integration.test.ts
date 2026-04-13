/**
 * DLQ 이동 흐름 통합 테스트.
 *
 * 재시도 초과 -> DLQ 저장 흐름을 Cosmos DB Emulator로 검증한다.
 * Emulator 미실행 시 자동 스킵.
 */

import type { EventGridEvent, HttpRequest, InvocationContext } from '@azure/functions';

jest.mock('@azure/functions', () => ({
  app: { http: jest.fn(), cosmosDB: jest.fn(), timer: jest.fn(), eventGrid: jest.fn() },
}));

import { postEvents, _setSettingsForTest as setEventApiSettings } from '@src/functions/event-api';
import { eventConsumer, _setSettingsForTest as setConsumerSettings } from '@src/functions/event-consumer';
import { getDlqContainer, getEventsContainer, initContainers, resetClient } from '@src/services/cosmos-client';
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
    event_type: 'claim_completed',
    clinic_id: clinicId,
    patient_id: 'P-002',
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

beforeAll(async () => {
  emulatorUp = await isEmulatorAvailable();
  if (!emulatorUp) return;

  settings = makeIntegrationSettings({
    MAX_RETRY_COUNT: 0,
    MOCK_DELAY_MIN_MS: 9999,
    MOCK_DELAY_MAX_MS: 10000,
  });
  resetClient();
  await initContainers(settings);
  setEventApiSettings(settings);
  setConsumerSettings(settings);
}, 30000);

afterAll(() => {
  resetClient();
});

describe('DLQ 이동 흐름 통합 테스트', () => {
  it('SKIP: Cosmos DB Emulator 미실행 시 스킵', () => {
    if (!emulatorUp) {
      console.log('Cosmos DB Emulator가 실행 중이지 않아 통합 테스트를 스킵합니다.');
    }
    expect(true).toBe(true);
  });

  it('최대 재시도 초과 -> DLQ 컨테이너에 저장', async () => {
    if (!emulatorUp) return;

    const clinicId = uniqueClinicId();
    const body = makeEventBody(clinicId);
    const eventId = body.id as string;

    // 1. 이벤트 생성
    const req = makeRequest(body);
    const resp = await postEvents(req, mockContext);
    const result = JSON.parse(resp.body as string);
    const correlationId = result.correlation_id;

    // 2. Consumer 실행 — MAX_RETRY_COUNT=0, 높은 딜레이로 Mock이 타임아웃하게 설정
    // 실제로는 Mock Strategy가 성공하므로, 재시도 초과를 테스트하려면
    // CB를 OPEN으로 설정해서 CircuitOpenError를 발생시킴
    const { getCircuitBreakerContainer } = await import('@src/services/cosmos-client');
    const cbContainer = getCircuitBreakerContainer(settings);
    const cbDoc = {
      id: 'email:sendgrid',
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

    // 3. events 컨테이너에서 failed 확인
    const eventsContainer = getEventsContainer(settings);
    const { resource: doc } = await eventsContainer.item(eventId, clinicId).read();
    expect(doc.status).toBe('failed');

    // 4. DLQ 컨테이너에서 문서 조회
    const dlqContainer = getDlqContainer(settings);
    const { resources: items } = await dlqContainer.items
      .query({
        query: 'SELECT * FROM c WHERE c.original_event_id = @event_id AND c.clinic_id = @clinic_id',
        parameters: [
          { name: '@event_id', value: eventId },
          { name: '@clinic_id', value: clinicId },
        ],
      })
      .fetchAll();

    expect(items.length).toBe(1);
    const dlqDoc = items[0];
    expect(dlqDoc.original_event_id).toBe(eventId);
    expect(dlqDoc.clinic_id).toBe(clinicId);
    expect(dlqDoc.channel).toBe('email');
    expect(dlqDoc.replay_status).toBe('pending');
    expect(dlqDoc.correlation_id).toBe(correlationId);

    // 정리
    try {
      await cbContainer.item('email:sendgrid', 'email:sendgrid').delete();
    } catch {
      // ignore
    }
  }, 30000);
});
