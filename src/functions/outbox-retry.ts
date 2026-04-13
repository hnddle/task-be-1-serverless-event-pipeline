/**
 * Outbox Retry — 발행 실패 문서 재시도.
 *
 * failed_publish 상태의 문서를 주기적으로 조회하여
 * pending으로 재갱신함으로써 Change Feed를 재발화시킨다.
 *
 * SPEC.md §4.4 (Transactional Outbox 패턴) 참조.
 */

import { app, type InvocationContext, type Timer } from '@azure/functions';
import type { Settings } from '../shared/config';
import { getSettings } from '../shared/config';
import { getLogger, logWithContext } from '../shared/logger';
import { getEventsContainer } from '../services/cosmos-client';

const logger = getLogger('outbox-retry');

let _settings: Settings | null = null;
function _getSettings(): Settings {
  if (!_settings) _settings = getSettings();
  return _settings;
}

/** 테스트용 오버라이드 */
export function _setSettingsForTest(settings: Settings): void {
  _settings = settings;
}

const QUERY_FAILED_PUBLISH =
  "SELECT c.id, c.clinic_id FROM c WHERE c._outbox_status = 'failed_publish'";

export async function outboxRetry(timer: Timer, _context: InvocationContext): Promise<void> {
  const settings = _getSettings();
  const container = getEventsContainer(settings);

  let updated = 0;
  let errors = 0;

  const { resources: items } = await container.items
    .query(QUERY_FAILED_PUBLISH)
    .fetchAll();

  for (const item of items) {
    const eventId = item.id as string;
    const clinicId = item.clinic_id as string;

    try {
      await container.item(eventId, clinicId).patch([
        { op: 'set', path: '/_outbox_status', value: 'pending' },
      ]);
      updated++;
    } catch (err: unknown) {
      logger.error(`Outbox Retry 갱신 실패: ${eventId}`, { error: String(err) });
      errors++;
    }
  }

  logWithContext(logger, 'INFO', 'Outbox Retry 배치 완료', {
    updated,
    errors,
    past_due: timer.isPastDue,
  });
}

app.timer('outboxRetry', {
  schedule: '0 */1 * * * *',
  handler: outboxRetry,
});
