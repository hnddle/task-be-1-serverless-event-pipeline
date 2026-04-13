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
  const database = getDatabase(settings);

  // logs 컨테이너가 존재하지 않으면 생성 후 initLogStore 호출
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
    .then(() => {
      initLogStore(getLogsContainer(settings));
      // eslint-disable-next-line no-console
      console.log('[index] logs 컨테이너 초기화 완료');
    })
    .catch((err: unknown) => {
      // eslint-disable-next-line no-console
      console.warn(`[index] logs 컨테이너 생성/초기화 실패: ${String(err)}`);
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
