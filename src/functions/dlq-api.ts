/**
 * DLQ API — Dead Letter Queue 조회 및 Replay.
 *
 * GET /dlq: DLQ 메시지 목록 조회 (필터/페이지네이션)
 * POST /dlq/{dlq_id}/replay: 단건 DLQ Replay
 * POST /dlq/replay-batch: 배치 DLQ Replay
 *
 * SPEC.md §6.3, §8.3 참조.
 */

import { app, type HttpRequest, type HttpResponseInit, type InvocationContext } from '@azure/functions';
import { v4 as uuidv4 } from 'uuid';
import type { Settings } from '../shared/config';
import { getSettings } from '../shared/config';
import { clearContext, generateCorrelationId, runWithContext, setCorrelationId, setLogContext } from '../shared/correlation';
import { getLogger, logWithContext } from '../shared/logger';
import { getDlqContainer, getEventsContainer } from '../services/cosmos-client';

const logger = getLogger('dlq-api');

let _settings: Settings | null = null;
function _getSettings(): Settings {
  if (!_settings) _settings = getSettings();
  return _settings;
}

/** 테스트용 오버라이드 */
export function _setSettingsForTest(settings: Settings): void {
  _settings = settings;
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

async function replaySingle(
  dlqContainer: { item: (id: string, pk: string) => { read: () => Promise<{ resource: Record<string, unknown> }> }; items: { upsert: (doc: Record<string, unknown>) => Promise<unknown> } },
  eventsContainer: { items: { create: (doc: Record<string, unknown>) => Promise<unknown> } },
  dlqDoc: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const newCorrelationId = generateCorrelationId();
  const now = new Date().toISOString();
  const originalCorrelationId = (dlqDoc.correlation_id as string) ?? '';

  logWithContext(logger, 'INFO', 'DLQ Replay', {
    dlq_id: dlqDoc.id,
    original_event_id: dlqDoc.original_event_id,
    original_correlation_id: originalCorrelationId,
    new_correlation_id: newCorrelationId,
  });

  // 1. DLQ 문서 갱신
  dlqDoc.replay_status = 'replayed';
  dlqDoc.replayed_at = now;
  await dlqContainer.items.upsert(dlqDoc);

  // 2. 원본 payload 기반 새 이벤트 생성 (Outbox 패턴)
  const payload = (dlqDoc.payload as Record<string, unknown>) ?? {};
  const newEventId = uuidv4();

  const newEvent: Record<string, unknown> = {
    id: newEventId,
    clinic_id: (dlqDoc.clinic_id as string) ?? (payload.clinic_id as string) ?? '',
    status: 'queued',
    event_type: (dlqDoc.event_type as string) ?? (payload.event_type as string) ?? '',
    patient_id: (dlqDoc.patient_id as string) ?? (payload.patient_id as string) ?? '',
    channels: [dlqDoc.channel ?? ''],
    correlation_id: newCorrelationId,
    notifications: [
      {
        channel: dlqDoc.channel ?? '',
        provider: dlqDoc.provider ?? '',
        status: 'pending',
        sent_at: null,
        retry_count: 0,
        last_error: null,
      },
    ],
    created_at: now,
    updated_at: now,
    _outbox_status: 'pending',
  };

  await eventsContainer.items.create(newEvent);

  return {
    dlq_id: dlqDoc.id as string,
    replay_status: 'replayed',
    new_correlation_id: newCorrelationId,
  };
}

export async function getDlq(
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

    const replayStatus = req.query.get('replay_status');
    const eventType = req.query.get('event_type');
    const dateFrom = req.query.get('date_from');
    const dateTo = req.query.get('date_to');
    const continuationToken = req.query.get('continuation_token') ?? undefined;
    const pageSize = Math.min(parseInt(req.query.get('page_size') ?? '20', 10) || 20, 100);

    const settings = _getSettings();
    const container = getDlqContainer(settings);

    const conditions = ['c.clinic_id = @clinic_id'];
    const parameters: { name: string; value: string }[] = [
      { name: '@clinic_id', value: clinicId },
    ];

    if (replayStatus) {
      conditions.push('c.replay_status = @replay_status');
      parameters.push({ name: '@replay_status', value: replayStatus });
    }
    if (eventType) {
      conditions.push('c.event_type = @event_type');
      parameters.push({ name: '@event_type', value: eventType });
    }
    if (dateFrom) {
      conditions.push('c.created_at >= @date_from');
      parameters.push({ name: '@date_from', value: dateFrom });
    }
    if (dateTo) {
      conditions.push('c.created_at <= @date_to');
      parameters.push({ name: '@date_to', value: dateTo });
    }

    const whereClause = conditions.join(' AND ');
    const query = `SELECT * FROM c WHERE ${whereClause} ORDER BY c.created_at DESC`;

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
      const items = (response.resources ?? []).map((item: Record<string, unknown>) => {
        const result = { ...item };
        for (const key of ['_rid', '_self', '_etag', '_attachments', '_ts']) {
          delete result[key];
        }
        return result;
      });
      const newContinuationToken = response.continuationToken ?? null;

      return jsonResponse({
        items,
        continuation_token: newContinuationToken,
        total_count: items.length,
      });
    } catch (err: unknown) {
      logger.error('DLQ 목록 조회 실패', { error: String(err) });
      return errorResponse('INTERNAL_ERROR', 'Internal server error', 500);
    }
  });
}

export async function postDlqReplay(
  req: HttpRequest,
  _context: InvocationContext,
): Promise<HttpResponseInit> {
  return runWithContext(async () => {
    clearContext();
    const dlqId = req.params.dlq_id ?? '';
    const clinicId = req.query.get('clinic_id');

    if (!clinicId) {
      return errorResponse('VALIDATION_ERROR', 'clinic_id query parameter is required', 400);
    }

    setLogContext({ dlq_id: dlqId, clinic_id: clinicId });

    const settings = _getSettings();
    const dlqContainer = getDlqContainer(settings);
    const eventsContainer = getEventsContainer(settings);

    let dlqDoc: Record<string, unknown>;
    try {
      const { resource } = await dlqContainer.item(dlqId, clinicId).read();
      if (!resource) return errorResponse('NOT_FOUND', `DLQ item ${dlqId} not found`, 404);
      dlqDoc = resource as Record<string, unknown>;
    } catch (err: unknown) {
      if (typeof err === 'object' && err !== null && 'code' in err && (err as { code: number }).code === 404) {
        return errorResponse('NOT_FOUND', `DLQ item ${dlqId} not found`, 404);
      }
      logger.error('DLQ 조회 실패', { error: String(err) });
      return errorResponse('INTERNAL_ERROR', 'Internal server error', 500);
    }

    if (dlqDoc.replay_status === 'replayed') {
      return errorResponse('CONFLICT', `DLQ item ${dlqId} already replayed`, 409);
    }

    try {
      const result = await replaySingle(dlqContainer as never, eventsContainer as never, dlqDoc);
      return jsonResponse(result);
    } catch (err: unknown) {
      logger.error('DLQ Replay 실패', { error: String(err) });
      return errorResponse('INTERNAL_ERROR', 'Internal server error', 500);
    }
  });
}

export async function postDlqReplayBatch(
  req: HttpRequest,
  _context: InvocationContext,
): Promise<HttpResponseInit> {
  return runWithContext(async () => {
    clearContext();

    let body: Record<string, unknown>;
    try {
      body = (await req.json()) as Record<string, unknown>;
    } catch {
      return errorResponse('VALIDATION_ERROR', 'Invalid JSON body', 400);
    }

    const clinicId = body.clinic_id as string | undefined;
    if (!clinicId) {
      return errorResponse('VALIDATION_ERROR', 'clinic_id is required', 400);
    }

    const correlationId = generateCorrelationId();
    setCorrelationId(correlationId);
    setLogContext({ clinic_id: clinicId });

    const eventType = body.event_type as string | undefined;
    const dateFrom = body.date_from as string | undefined;
    const dateTo = body.date_to as string | undefined;
    const maxCount = Math.min(parseInt(String(body.max_count ?? '100'), 10) || 100, 500);

    const settings = _getSettings();
    const dlqContainer = getDlqContainer(settings);
    const eventsContainer = getEventsContainer(settings);

    const conditions = ['c.clinic_id = @clinic_id', "c.replay_status = 'pending'"];
    const parameters: { name: string; value: string }[] = [
      { name: '@clinic_id', value: clinicId },
    ];

    if (eventType) {
      conditions.push('c.event_type = @event_type');
      parameters.push({ name: '@event_type', value: eventType });
    }
    if (dateFrom) {
      conditions.push('c.created_at >= @date_from');
      parameters.push({ name: '@date_from', value: dateFrom });
    }
    if (dateTo) {
      conditions.push('c.created_at <= @date_to');
      parameters.push({ name: '@date_to', value: dateTo });
    }

    const whereClause = conditions.join(' AND ');
    const query = `SELECT * FROM c WHERE ${whereClause}`;

    let replayedCount = 0;
    let failedCount = 0;
    let skippedCount = 0;

    try {
      const { resources: docs } = await dlqContainer.items
        .query({ query, parameters }, { partitionKey: clinicId })
        .fetchAll();

      let processed = 0;
      for (const doc of docs) {
        if (processed >= maxCount) break;

        if ((doc as Record<string, unknown>).replay_status !== 'pending') {
          skippedCount++;
          processed++;
          continue;
        }

        try {
          await replaySingle(
            dlqContainer as never,
            eventsContainer as never,
            doc as Record<string, unknown>,
          );
          replayedCount++;
        } catch (err: unknown) {
          logger.error(`배치 Replay 개별 실패: ${(doc as Record<string, unknown>).id ?? 'unknown'}`, {
            error: String(err),
          });
          failedCount++;
        }

        processed++;
      }

      return jsonResponse({ replayed_count: replayedCount, failed_count: failedCount, skipped_count: skippedCount });
    } catch (err: unknown) {
      logger.error('DLQ 배치 Replay 실패', { error: String(err) });
      return errorResponse('INTERNAL_ERROR', 'Internal server error', 500);
    }
  });
}

// Azure Functions v4 HTTP 등록
app.http('getDlq', {
  methods: ['GET'],
  route: 'dlq',
  authLevel: 'anonymous',
  handler: getDlq,
});

app.http('postDlqReplay', {
  methods: ['POST'],
  route: 'dlq/{dlq_id}/replay',
  authLevel: 'anonymous',
  handler: postDlqReplay,
});

app.http('postDlqReplayBatch', {
  methods: ['POST'],
  route: 'dlq/replay-batch',
  authLevel: 'anonymous',
  handler: postDlqReplayBatch,
});
