// Azure Functions v4 Node.js entry point

// Application Insights 초기화 (다른 모듈보다 먼저 실행)
import { setupApplicationInsights } from './shared/logger';
setupApplicationInsights(process.env.APPLICATIONINSIGHTS_CONNECTION_STRING);

// Each function file self-registers via @azure/functions app object
import './functions/event-api';
import './functions/dlq-api';
import './functions/outbox-publisher';
import './functions/outbox-retry';
import './functions/event-consumer';
