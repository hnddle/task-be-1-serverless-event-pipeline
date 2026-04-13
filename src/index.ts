// Azure Functions v4 Node.js entry point
// Each function file self-registers via @azure/functions app object
import './functions/event-api';
import './functions/dlq-api';
import './functions/outbox-publisher';
import './functions/outbox-retry';
import './functions/event-consumer';
