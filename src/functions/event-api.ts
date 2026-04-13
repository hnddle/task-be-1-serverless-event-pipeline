/**
 * Event API — 이벤트 수신, 저장, 조회.
 *
 * POST /events: 이벤트 생성 (Cosmos DB 저장 + Idempotency)
 * GET /events/{event_id}: 이벤트 상세 조회
 * GET /events: 이벤트 목록 조회 (페이지네이션)
 *
 * SPEC.md §7, §8.1, §8.2 참조.
 */

import { app, type HttpRequest, type HttpResponseInit, type InvocationContext } from '@azure/functions';
import type { NotificationChannel, NotificationChannelType, NotificationEvent } from '../models/events';
import { EventStatus, NotificationStatus, OutboxStatus } from '../models/events';
import type { Settings } from '../shared/config';
import { getSettings } from '../shared/config';
import { clearContext, generateCorrelationId, runWithContext, setCorrelationId, setLogContext } from '../shared/correlation';
import { ValidationError } from '../shared/errors';
import { getLogger, logWithContext } from '../shared/logger';
import { validateCreateEvent } from '../shared/validator';
import { getEventsContainer } from '../services/cosmos-client';

const logger = getLogger('event-api');

let _settings: Settings | null = null;
function _getSettings(): Settings {
  if (!_settings) _settings = getSettings();
  return _settings;
}

/** 테스트용 settings 오버라이드 */
export function _setSettingsForTest(settings: Settings): void {
  _settings = settings;
}

function buildNotifications(
  channels: NotificationChannelType[],
  settings: Settings,
): NotificationChannel[] {
  return channels.map((ch) => {
    let provider: string;
    if (ch === 'email') provider = settings.NOTIFICATION_EMAIL_PROVIDER;
    else if (ch === 'sms') provider = settings.NOTIFICATION_SMS_PROVIDER;
    else provider = 'webhook';

    return {
      channel: ch,
      provider,
      status: NotificationStatus.PENDING,
      sent_at: null,
      retry_count: 0,
      last_error: null,
    };
  });
}

function jsonResponse(body: Record<string, unknown>, status: number = 200): HttpResponseInit {
  return {
    status,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

function errorResponse(
  errorCode: string,
  message: string,
  status: number,
  details: unknown[] = [],
): HttpResponseInit {
  return jsonResponse({ error: errorCode, message, details }, status);
}

export async function postEvents(
  req: HttpRequest,
  _context: InvocationContext,
): Promise<HttpResponseInit> {
  return runWithContext(async () => {
    clearContext();
    const correlationId = generateCorrelationId();
    setCorrelationId(correlationId);

    let body: unknown;
    try {
      body = await req.json();
    } catch {
      return errorResponse('VALIDATION_ERROR', 'Invalid JSON body', 400);
    }

    let validated;
    try {
      validated = validateCreateEvent(body);
    } catch (err: unknown) {
      if (err instanceof ValidationError) {
        return jsonResponse(err.toDict() as Record<string, unknown>, 400);
      }
      return errorResponse('VALIDATION_ERROR', 'Invalid request body', 400);
    }

    setLogContext({ event_id: validated.id, clinic_id: validated.clinic_id });

    const settings = _getSettings();
    const now = new Date().toISOString();

    const eventDoc: NotificationEvent = {
      id: validated.id,
      clinic_id: validated.clinic_id,
      status: EventStatus.QUEUED,
      event_type: validated.event_type as NotificationEvent['event_type'],
      patient_id: validated.patient_id,
      channels: validated.channels as NotificationChannelType[],
      correlation_id: correlationId,
      notifications: buildNotifications(validated.channels as NotificationChannelType[], settings),
      created_at: now,
      updated_at: now,
      _outbox_status: OutboxStatus.PENDING,
    };

    const container = getEventsContainer(settings);

    try {
      await container.items.create(eventDoc);
      logWithContext(logger, 'INFO', '이벤트 생성 완료', { status: 'queued' });

      return jsonResponse(
        { event_id: validated.id, status: 'queued', correlation_id: correlationId },
        201,
      );
    } catch (err: unknown) {
      // Idempotency: 409 Conflict → 기존 문서 반환
      if (typeof err === 'object' && err !== null && 'code' in err && (err as { code: number }).code === 409) {
        logWithContext(logger, 'INFO', '중복 이벤트 요청', { event_id: validated.id });
        try {
          const { resource: existing } = await container.item(validated.id, validated.clinic_id).read();
          if (existing) {
            return jsonResponse({
              event_id: existing.id as string,
              status: (existing.status as string) ?? 'queued',
              correlation_id: (existing.correlation_id as string) ?? correlationId,
              message: 'Event already exists',
            }, 200);
          }
        } catch {
          return errorResponse('NOT_FOUND', 'Event not found', 404);
        }
      }
      logger.error('이벤트 생성 실패', { error: String(err) });
      return errorResponse('INTERNAL_ERROR', 'Internal server error', 500);
    }
  });
}

export async function getEventById(
  req: HttpRequest,
  _context: InvocationContext,
): Promise<HttpResponseInit> {
  return runWithContext(async () => {
    clearContext();
    const eventId = req.params.event_id ?? '';
    const clinicId = req.query.get('clinic_id');

    setLogContext({ event_id: eventId, clinic_id: clinicId ?? '' });

    const settings = _getSettings();
    const container = getEventsContainer(settings);

    try {
      let doc: Record<string, unknown> | undefined;

      if (clinicId) {
        // 파티션 키가 있으면 point read (빠름)
        const { resource } = await container.item(eventId, clinicId).read();
        doc = resource as Record<string, unknown> | undefined;
      } else {
        // 파티션 키 없으면 cross-partition query
        const { resources } = await container.items.query({
          query: 'SELECT * FROM c WHERE c.id = @id',
          parameters: [{ name: '@id', value: eventId }],
        }).fetchAll();
        doc = resources[0] as Record<string, unknown> | undefined;
      }

      if (!doc) return errorResponse('NOT_FOUND', `Event ${eventId} not found`, 404);

      // 내부 필드 제거
      const result = { ...doc };
      delete result._outbox_status;
      for (const key of ['_rid', '_self', '_etag', '_attachments', '_ts']) {
        delete result[key];
      }

      return jsonResponse(result);
    } catch (err: unknown) {
      if (typeof err === 'object' && err !== null && 'code' in err && (err as { code: number }).code === 404) {
        return errorResponse('NOT_FOUND', `Event ${eventId} not found`, 404);
      }
      logger.error('이벤트 조회 실패', { error: String(err) });
      return errorResponse('INTERNAL_ERROR', 'Internal server error', 500);
    }
  });
}

export async function getEvents(
  req: HttpRequest,
  _context: InvocationContext,
): Promise<HttpResponseInit> {
  return runWithContext(async () => {
    clearContext();
    const clinicId = req.query.get('clinic_id');

    if (!clinicId) {
      return errorResponse('VALIDATION_ERROR', 'clinic_id query parameter is required', 400);
    }

    setLogContext({ clinic_id: clinicId });

    const statusFilter = req.query.get('status');
    const eventTypeFilter = req.query.get('event_type');
    const continuationToken = req.query.get('continuation_token') ?? undefined;
    const pageSize = Math.min(parseInt(req.query.get('page_size') ?? '20', 10) || 20, 100);

    const settings = _getSettings();
    const container = getEventsContainer(settings);

    const conditions = ['c.clinic_id = @clinic_id'];
    const parameters: { name: string; value: string }[] = [
      { name: '@clinic_id', value: clinicId },
    ];

    if (statusFilter) {
      conditions.push('c.status = @status');
      parameters.push({ name: '@status', value: statusFilter });
    }

    if (eventTypeFilter) {
      conditions.push('c.event_type = @event_type');
      parameters.push({ name: '@event_type', value: eventTypeFilter });
    }

    const selectFields =
      'c.id, c.clinic_id, c.status, c.event_type, c.patient_id, ' +
      'c.channels, c.correlation_id, c.created_at, c.updated_at';
    const whereClause = conditions.join(' AND ');
    const query = `SELECT ${selectFields} FROM c WHERE ${whereClause} ORDER BY c.created_at DESC`;

    try {
      const queryIterator = container.items.query(
        { query, parameters },
        {
          partitionKey: clinicId,
          maxItemCount: pageSize,
          continuationToken,
        },
      );

      const response = await queryIterator.fetchNext();
      const items = response.resources ?? [];
      const newContinuationToken = response.continuationToken ?? null;

      return jsonResponse({ items, continuation_token: newContinuationToken });
    } catch (err: unknown) {
      logger.error('이벤트 목록 조회 실패', { error: String(err) });
      return errorResponse('INTERNAL_ERROR', 'Internal server error', 500);
    }
  });
}

// Azure Functions v4 HTTP 등록
app.http('postEvents', {
  methods: ['POST'],
  route: 'events',
  authLevel: 'anonymous',
  handler: postEvents,
});

app.http('getEventById', {
  methods: ['GET'],
  route: 'events/{event_id}',
  authLevel: 'anonymous',
  handler: getEventById,
});

app.http('getEvents', {
  methods: ['GET'],
  route: 'events',
  authLevel: 'anonymous',
  handler: getEvents,
});
