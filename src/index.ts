// Azure Functions v4 Node.js entry point

// Application Insights 초기화 (다른 모듈보다 먼저 실행)
import { setupApplicationInsights } from './shared/logger';
setupApplicationInsights(process.env.APPLICATIONINSIGHTS_CONNECTION_STRING);

// Cosmos DB logs 컨테이너 초기화
import type { PartitionKeyDefinition } from '@azure/cosmos';
import { getSettings } from './shared/config';
import { getDatabase, getLogsContainer } from './services/cosmos-client';
import { initLogStore } from './services/log-store';
try {
  const settings = getSettings();

  // 컨테이너 참조를 즉시 주입 (네트워크 호출 없음)
  initLogStore(getLogsContainer(settings));
  // eslint-disable-next-line no-console
  console.log('[index] logs 컨테이너 참조 초기화 완료');

  // 컨테이너 자동 생성은 백그라운드로 (이미 존재하면 no-op)
  const database = getDatabase(settings);
  database.containers
    .createIfNotExists({
      id: 'logs',
      partitionKey: { paths: ['/correlation_id'] } as PartitionKeyDefinition,
      defaultTtl: 604800,
      indexingPolicy: {
        automatic: true,
        indexingMode: 'consistent',
        includedPaths: [{ path: '/*' }],
        excludedPaths: [{ path: '/"_etag"/?' }],
        compositeIndexes: [
          [
            { path: '/correlation_id', order: 'ascending' },
            { path: '/timestamp', order: 'descending' },
          ],
        ],
      },
    })
    .catch((err: unknown) => {
      // eslint-disable-next-line no-console
      console.warn(`[index] logs 컨테이너 생성 실패 (이미 존재할 수 있음): ${String(err)}`);
    });
} catch {
  // eslint-disable-next-line no-console
  console.warn('[index] logs 컨테이너 초기화 실패 — stdout 로깅만 사용');
}

// Each function file self-registers via @azure/functions app object
import './functions/event-api';
import './functions/dlq-api';
import './functions/outbox-publisher';
import './functions/outbox-retry';
import './functions/event-consumer';
