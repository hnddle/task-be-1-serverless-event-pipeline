/**
 * Dead Letter Queue 서비스.
 *
 * 최대 재시도 초과 메시지를 DLQ 컨테이너에 저장한다.
 * SPEC.md §6.2 (Dead Letter Queue) 참조.
 */

import { v4 as uuidv4 } from 'uuid';
import type { Settings } from '../shared/config';
import { getCorrelationId } from '../shared/correlation';
import { getLogger, logWithContext } from '../shared/logger';
import { getDlqContainer } from './cosmos-client';

const logger = getLogger('dlq-service');

export interface SendToDlqParams {
  originalEventId: string;
  clinicId: string;
  channel: string;
  provider: string;
  eventType: string;
  patientId: string;
  payload: Record<string, unknown>;
  failureReason: string;
  retryCount: number;
}

export class DlqService {
  private readonly settings: Settings;

  constructor(settings: Settings) {
    this.settings = settings;
  }

  async sendToDlq(params: SendToDlqParams): Promise<Record<string, unknown>> {
    const dlqId = uuidv4();
    const now = new Date().toISOString();
    const correlationId = getCorrelationId() ?? '';

    const dlqDoc: Record<string, unknown> = {
      id: dlqId,
      original_event_id: params.originalEventId,
      clinic_id: params.clinicId,
      channel: params.channel,
      provider: params.provider,
      event_type: params.eventType,
      patient_id: params.patientId,
      payload: params.payload,
      failure_reason: params.failureReason,
      retry_count: params.retryCount,
      correlation_id: correlationId,
      created_at: now,
      replay_status: 'pending',
      replayed_at: null,
    };

    const container = getDlqContainer(this.settings);
    await container.items.create(dlqDoc);

    logWithContext(logger, 'ERROR', 'DLQ 이동', {
      event_id: params.originalEventId,
      dlq_id: dlqId,
      channel: params.channel,
      provider: params.provider,
      failure_reason: params.failureReason,
      total_retry_count: params.retryCount,
    });

    return dlqDoc;
  }
}
