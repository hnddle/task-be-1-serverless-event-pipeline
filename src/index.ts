// Azure Functions v4 Node.js entry point

// Application Insights 초기화 (다른 모듈보다 먼저 실행)
import { setupApplicationInsights } from './shared/logger';
setupApplicationInsights(process.env.APPLICATIONINSIGHTS_CONNECTION_STRING);

// Cosmos DB logs 컨테이너 초기화
import { getSettings } from './shared/config';
import { getLogsContainer } from './services/cosmos-client';
import { initLogStore } from './services/log-store';
try {
  const settings = getSettings();
  initLogStore(getLogsContainer(settings));
} catch {
  // 환경 변수 누락 등으로 실패 시 stdout 로깅만 사용
  console.warn('[index] logs 컨테이너 초기화 실패 — stdout 로깅만 사용');
}

// Each function file self-registers via @azure/functions app object
import './functions/event-api';
import './functions/dlq-api';
import './functions/outbox-publisher';
import './functions/outbox-retry';
import './functions/event-consumer';
