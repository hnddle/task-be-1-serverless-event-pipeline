/**
 * Outbox Publisher — Change Feed 기반 이벤트 발행.
 *
 * Cosmos DB Change Feed에서 _outbox_status: "pending" 문서를 감지하여
 * Message Broker에 발행한다.
 *
 * SPEC.md §4.4 (Transactional Outbox 패턴) 참조.
 */

import { app, type InvocationContext } from '@azure/functions';
import type { Settings } from '../shared/config';
import { getSettings } from '../shared/config';
import { clearContext, runWithContext, setCorrelationId, setLogContext } from '../shared/correlation';
import { getLogger, logWithContext } from '../shared/logger';
import { getEventsContainer } from '../services/cosmos-client';
import type { MessageBroker } from '../services/message-broker/message-broker';
import { MessageBrokerFactory } from '../services/message-broker/message-broker-factory';

const logger = getLogger('outbox-publisher');

let _settings: Settings | null = null;
let _broker: MessageBroker | null = null;

function _getSettings(): Settings {
  if (!_settings) _settings = getSettings();
  return _settings;
}

function _getBroker(): MessageBroker {
  if (!_broker) _broker = MessageBrokerFactory.create(_getSettings());
  return _broker;
}

/** 테스트용 오버라이드 */
export function _setSettingsForTest(settings: Settings): void {
  _settings = settings;
}
export function _setBrokerForTest(broker: MessageBroker): void {
  _broker = broker;
}

export async function outboxPublisher(
  documents: unknown[],
  _context: InvocationContext,
): Promise<void> {
  await runWithContext(async () => {
    if (!documents || documents.length === 0) return;

    const settings = _getSettings();
    const broker = _getBroker();
    const container = getEventsContainer(settings);

    let processed = 0;
    let skipped = 0;

    for (const rawDoc of documents) {
      const doc = rawDoc as Record<string, unknown>;
      const outboxStatus = doc._outbox_status as string ?? '';
      const eventId = doc.id as string ?? 'unknown';
      const clinicId = doc.clinic_id as string ?? 'unknown';

      // 무한 루프 방지: pending만 처리
      if (outboxStatus !== 'pending') {
        skipped++;
        continue;
      }

      clearContext();
      const correlationId = doc.correlation_id as string ?? '';
      const eventType = doc.event_type as string ?? '';
      if (correlationId) setCorrelationId(correlationId);
      setLogContext({ event_id: eventId, clinic_id: clinicId, event_type: eventType });

      logWithContext(logger, 'INFO', 'Change Feed 감지 — pending 문서 발행 시작', {
        _outbox_status: 'pending',
      });

      try {
        await broker.publish(doc);

        await container.item(eventId, clinicId).patch([
          { op: 'set', path: '/_outbox_status', value: 'published' },
        ]);

        logWithContext(logger, 'INFO', 'Outbox 발행 완료', {
          status: 'published',
          broker_name: broker.getBrokerName(),
        });
        processed++;
      } catch (err: unknown) {
        logger.error(`Outbox 발행 실패: ${eventId}`, { error: String(err) });

        try {
          await container.item(eventId, clinicId).patch([
            { op: 'set', path: '/_outbox_status', value: 'failed_publish' },
          ]);
        } catch (patchErr: unknown) {
          logger.error(`failed_publish 갱신 실패: ${eventId}`, { error: String(patchErr) });
        }
      }
    }

    logWithContext(logger, 'INFO', 'Outbox Publisher 배치 완료', {
      processed,
      skipped,
      total: documents.length,
    });
  });
}

app.cosmosDB('outboxPublisher', {
  connection: 'CosmosDBConnection',
  databaseName: '%COSMOS_DB_DATABASE%',
  containerName: 'events',
  leaseContainerName: 'leases',
  createLeaseContainerIfNotExists: true,
  handler: outboxPublisher,
});
