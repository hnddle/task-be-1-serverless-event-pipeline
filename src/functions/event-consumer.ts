/**
 * Event Consumer — Event Grid 기반 알림 발송.
 *
 * Event Grid 트리거로 이벤트를 수신하여 채널별 알림을 발송하고
 * 결과를 Cosmos DB에 기록한다.
 * 복원력 패턴: Circuit Breaker → Rate Limiter → Strategy.send() → 재시도.
 *
 * SPEC.md §9 (Event Consumer) 참조.
 */

import { app, type EventGridEvent, type InvocationContext } from '@azure/functions';
import type { Settings } from '../shared/config';
import { getSettings } from '../shared/config';
import { clearContext, runWithContext, setCorrelationId, setLogContext } from '../shared/correlation';
import { getLogger, logWithContext } from '../shared/logger';
import { getEventsContainer } from '../services/cosmos-client';
import { CircuitBreaker, CircuitOpenError } from '../services/circuit-breaker';
import { RateLimiter, RateLimitExceededError } from '../services/rate-limiter';
import { MaxRetryExceededError, RetryService } from '../services/retry-service';
import { NotificationFactory } from '../services/notification/notification-factory';
import { DlqService } from '../services/dlq-service';

const logger = getLogger('event-consumer');

let _settings: Settings | null = null;
function _getSettings(): Settings {
  if (!_settings) _settings = getSettings();
  return _settings;
}

/** 테스트용 오버라이드 */
export function _setSettingsForTest(settings: Settings): void {
  _settings = settings;
}

interface SendResult {
  success: boolean;
  provider: string;
  message: string;
  duration_ms: number;
  retry_count?: number;
  circuit_open?: boolean;
}

export function determineFinalStatus(
  notifications: { status: string }[],
): string {
  const successCount = notifications.filter((n) => n.status === 'success').length;
  if (successCount === notifications.length) return 'completed';
  if (successCount > 0) return 'partially_completed';
  return 'failed';
}

async function sendWithResilience(
  channel: string,
  provider: string,
  notificationData: Record<string, unknown>,
  deps: {
    circuitBreaker: CircuitBreaker;
    rateLimiter: RateLimiter;
    retryService: RetryService;
    factory: NotificationFactory;
  },
): Promise<SendResult> {
  // 1. Circuit Breaker 확인
  try {
    await deps.circuitBreaker.checkState(channel, provider);
  } catch (err: unknown) {
    if (err instanceof CircuitOpenError) {
      logWithContext(logger, 'WARNING', 'Circuit Breaker Open — 즉시 실패', {
        channel,
        provider,
      });
      return {
        success: false,
        provider,
        message: `Circuit open: ${channel}:${provider}`,
        duration_ms: 0,
        circuit_open: true,
      };
    }
    throw err;
  }

  // 2. Rate Limiter + Strategy.send() + 재시도
  const attemptSend = async (): Promise<SendResult> => {
    try {
      await deps.rateLimiter.acquire(channel, provider);
    } catch (err: unknown) {
      if (err instanceof RateLimitExceededError) {
        logWithContext(logger, 'WARNING', 'Rate limit 대기 초과', { channel, provider });
      }
      throw err;
    }

    logWithContext(logger, 'INFO', '채널 발송 시작', { channel, provider });

    const result = await deps.factory.sendNotification(channel, notificationData);

    if (!result.success) {
      throw new Error(result.message);
    }

    return {
      success: true,
      provider: result.provider,
      message: '',
      duration_ms: result.duration_ms,
    };
  };

  try {
    const sendResult = await deps.retryService.executeWithRetry(attemptSend, {
      channel,
      provider,
    });
    await deps.circuitBreaker.recordSuccess(channel, provider);
    return sendResult as SendResult;
  } catch (err: unknown) {
    if (err instanceof MaxRetryExceededError) {
      await deps.circuitBreaker.recordFailure(channel, provider);
      return {
        success: false,
        provider,
        message: err.lastError,
        duration_ms: 0,
        retry_count: err.retryCount,
      };
    }
    if (err instanceof RateLimitExceededError) {
      return {
        success: false,
        provider,
        message: `Rate limit exceeded: ${channel}:${provider}`,
        duration_ms: 0,
      };
    }
    throw err;
  }
}

export async function eventConsumer(
  event: EventGridEvent,
  _context: InvocationContext,
): Promise<void> {
  await runWithContext(async () => {
    const eventData = event.data as Record<string, unknown> ?? {};
    const eventId = (eventData.id as string) ?? 'unknown';
    const clinicId = (eventData.clinic_id as string) ?? 'unknown';
    const correlationId = (eventData.correlation_id as string) ?? '';

    clearContext();
    if (correlationId) setCorrelationId(correlationId);
    setLogContext({ event_id: eventId, clinic_id: clinicId });

    logWithContext(logger, 'INFO', 'Event Consumer 시작');

    const settings = _getSettings();
    const container = getEventsContainer(settings);
    const factory = new NotificationFactory(settings);
    const circuitBreaker = new CircuitBreaker(settings);
    const rateLimiter = new RateLimiter(settings);
    const retryService = new RetryService(settings);
    const dlqService = new DlqService(settings);

    // Cosmos DB에서 이벤트 조회
    let doc: Record<string, unknown>;
    try {
      const { resource } = await container.item(eventId, clinicId).read();
      if (!resource) {
        logger.error(`이벤트 조회 실패: ${eventId}`);
        return;
      }
      doc = resource as Record<string, unknown>;
    } catch (err: unknown) {
      logger.error(`이벤트 조회 실패: ${eventId}`, { error: String(err) });
      return;
    }

    const notifications = (doc.notifications as Record<string, unknown>[]) ?? [];

    // 이미 최종 상태인 경우 스킵 (Idempotency)
    const currentStatus = doc.status as string ?? '';
    if (['completed', 'partially_completed', 'failed'].includes(currentStatus)) {
      logWithContext(logger, 'INFO', '이미 처리된 이벤트 스킵', {
        current_status: currentStatus,
      });
      return;
    }

    // status → processing 갱신
    await container.item(eventId, clinicId).patch([
      { op: 'set', path: '/status', value: 'processing' },
      { op: 'set', path: '/updated_at', value: new Date().toISOString() },
    ]);

    // channels 순회
    for (const notification of notifications) {
      const channel = notification.channel as string ?? '';
      const provider = notification.provider as string ?? '';

      if (notification.status === 'success') {
        logWithContext(logger, 'INFO', '이미 성공한 채널 스킵', { channel });
        continue;
      }

      setLogContext({ event_id: eventId, clinic_id: clinicId, channel });

      const sendResult = await sendWithResilience(
        channel,
        provider,
        { event_id: eventId, clinic_id: clinicId, channel, provider },
        { circuitBreaker, rateLimiter, retryService, factory },
      );

      const now = new Date().toISOString();

      if (sendResult.success) {
        notification.status = 'success';
        notification.sent_at = now;
        logWithContext(logger, 'INFO', '알림 발송 성공', {
          channel,
          provider: sendResult.provider,
          duration_ms: sendResult.duration_ms,
        });
      } else {
        notification.status = 'failed';
        notification.last_error = sendResult.message;
        notification.retry_count = sendResult.retry_count ?? 0;
        logWithContext(logger, 'WARNING', '알림 발송 실패', {
          channel,
          provider: sendResult.provider,
          error: sendResult.message,
        });

        // 최대 재시도 초과 시 DLQ로 이동
        if ((sendResult.retry_count ?? 0) > 0 || sendResult.circuit_open) {
          await dlqService.sendToDlq({
            originalEventId: eventId,
            clinicId,
            channel,
            provider,
            eventType: (doc.event_type as string) ?? '',
            patientId: (doc.patient_id as string) ?? '',
            payload: doc,
            failureReason: sendResult.message,
            retryCount: sendResult.retry_count ?? 0,
          });
        }
      }
    }

    // 결과 집계 및 Cosmos DB 기록
    const finalStatus = determineFinalStatus(notifications as { status: string }[]);

    await container.item(eventId, clinicId).patch([
      { op: 'set', path: '/status', value: finalStatus },
      { op: 'set', path: '/notifications', value: notifications },
      { op: 'set', path: '/updated_at', value: new Date().toISOString() },
    ]);

    logWithContext(logger, 'INFO', 'Event Consumer 완료', {
      final_status: finalStatus,
      total_channels: notifications.length,
    });
  });
}

app.eventGrid('eventConsumer', {
  handler: eventConsumer,
});
