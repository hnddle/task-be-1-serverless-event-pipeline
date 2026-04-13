# Serverless Event Pipeline

치과 보험 청구 시스템의 이벤트 기반 알림 파이프라인.
Azure Functions + Cosmos DB + Event Grid 기반 Serverless 아키텍처.

> **[API Reference](docs/API.md)** | **[Data Model](docs/DATA_MODEL.md)** | **[Manual Test Guide](MANUAL_TEST.md)**

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        Azure Functions (5 Functions)                      │
│                                                                          │
│  ┌──────────────┐   ┌─────────────────┐   ┌──────────────────────────┐  │
│  │  event-api   │   │ outbox-publisher│   │    event-consumer        │  │
│  │  (HTTP)      │   │ (Change Feed)   │   │    (Event Grid)          │  │
│  │              │   │                 │   │                          │  │
│  │ POST /events │──►│ pending 감지    │──►│  Circuit Breaker         │  │
│  │ GET /events  │   │ → Event Grid    │   │  Rate Limiter            │  │
│  │ GET /events/ │   │   발행          │   │  Retry (지수 백오프)     │  │
│  │   {event_id} │   │                 │   │  DLQ 격리                │  │
│  └──────────────┘   └─────────────────┘   │                          │  │
│                                           │  Notification Strategy   │  │
│  ┌──────────────┐   ┌─────────────────┐   │   ├─ Email (SendGrid)   │  │
│  │   dlq-api    │   │  outbox-retry   │   │   ├─ SMS (Twilio)       │  │
│  │   (HTTP)     │   │  (Timer 1min)   │   │   └─ Webhook (HTTP)     │  │
│  │              │   │                 │   └──────────────────────────┘  │
│  │ GET /dlq     │   │ failed_publish  │                                 │
│  │ POST replay  │   │ → pending 복구  │                                 │
│  └──────────────┘   └─────────────────┘                                 │
│                                                                          │
└──────────────┬──────────────────────────────┬────────────────────────────┘
               │                              │
               ▼                              ▼
      ┌─────────────────┐           ┌─────────────────┐
      │   Cosmos DB     │           │   Event Grid    │
      │   6 Containers  │           │   (Broker)      │
      └─────────────────┘           └─────────────────┘
```

### Event Flow (End-to-End)

```
POST /events → Cosmos DB 저장 (outbox: pending) → 즉시 201 응답
                    │
                    ▼ (Change Feed)
              outbox-publisher (pending만 필터링)
                    │
                    ▼
              Event Grid 발행 → outbox: published
                    │
                    ▼
              event-consumer 트리거
                    │
              ┌─────┼─────┐
              ▼     ▼     ▼
            email  sms  webhook   ← 채널별 순차 처리
              │     │     │
              └─────┼─────┘
                    ▼
              결과 저장 (completed / partially_completed / failed)
```

### Failure & Recovery

```
알림 발송 실패 → retry_count < MAX? ─── Yes ──→ 지수 백오프 재시도
                        │
                       No
                        ▼
                   DLQ 격리 저장
                        │
                   GET /dlq 조회
                        │
                   POST /dlq/:id/replay → Outbox 패턴으로 재발행
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Node.js 22 + TypeScript 5 (strict) |
| Framework | Azure Functions v4 (Node.js model) |
| Database | Azure Cosmos DB (NoSQL API, 6 containers) |
| Message Broker | Azure Event Grid (Custom Topic) |
| Monitoring | Azure Monitor + Application Insights |
| Logging | Cosmos DB `logs` 컨테이너 + Application Insights |
| Validation | Zod |
| Test | Jest + ts-jest (183 unit tests) |
| Linter / Formatter | ESLint + Prettier |

---

## Project Structure

```
src/
├── functions/              # Azure Functions (5)
│   ├── event-api.ts        # HTTP: POST/GET /events
│   ├── dlq-api.ts          # HTTP: GET /dlq, POST replay
│   ├── outbox-publisher.ts # Change Feed → Event Grid
│   ├── outbox-retry.ts     # Timer (1min) → failed_publish 복구
│   └── event-consumer.ts   # Event Grid → 채널별 알림 발송
├── services/
│   ├── cosmos-client.ts    # Cosmos DB 싱글턴 + 6컨테이너 관리
│   ├── log-store.ts        # 구조화 로그 → Cosmos DB 저장 (fire-and-forget)
│   ├── message-broker/     # Adapter + Factory (Event Grid)
│   ├── notification/       # Strategy (Email/SMS/Webhook)
│   ├── circuit-breaker.ts  # CLOSED → OPEN → HALF-OPEN
│   ├── rate-limiter.ts     # Token Bucket (TTL 60s)
│   ├── retry-service.ts    # 지수 백오프
│   └── dlq-service.ts      # DLQ 저장/조회/Replay
├── shared/
│   ├── config.ts           # 환경 변수 로드 (Fail-fast)
│   ├── logger.ts           # 구조화 JSON 로거 + Cosmos DB + Application Insights
│   ├── validator.ts        # Zod 스키마
│   ├── correlation.ts      # Correlation ID 컨텍스트
│   └── errors.ts           # 공통 에러 타입
└── models/                 # TypeScript 인터페이스
```

---

## API Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/events` | 이벤트 생성 (201: 생성, 200: 중복) |
| GET | `/api/events/{event_id}` | 이벤트 상세 조회 |
| GET | `/api/events` | 이벤트 목록 조회 (페이지네이션) |
| GET | `/api/dlq` | DLQ 목록 조회 |
| POST | `/api/dlq/{dlq_id}/replay` | DLQ 단건 재처리 |
| POST | `/api/dlq/replay-batch` | DLQ 일괄 재처리 |

상세 스키마 및 요청/응답 예시: **[docs/API.md](docs/API.md)**

---

## Environment Variables

모든 설정은 환경 변수로 관리한다 (12-Factor III). 필수 변수 누락 시 Fail-fast 종료.

### Required

| Variable | Description |
|----------|-------------|
| `QUEUE_SERVICE_TYPE` | 메시지 브로커 타입. `EVENT_GRID` |
| `NOTIFICATION_EMAIL_PROVIDER` | 이메일 프로바이더. `sendgrid` |
| `NOTIFICATION_SMS_PROVIDER` | SMS 프로바이더. `twilio` |
| `WEBHOOK_URL` | Webhook 엔드포인트 URL |
| `COSMOS_DB_ENDPOINT` | Cosmos DB 엔드포인트 |
| `COSMOS_DB_KEY` | Cosmos DB 인증 키 |
| `COSMOS_DB_DATABASE` | 데이터베이스명. `notification-pipeline` |
| `CosmosDBConnection` | Change Feed용 연결 문자열 |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Application Insights 연결 문자열 |

### Optional (defaults)

| Variable | Default | Description |
|----------|---------|-------------|
| `CB_FAILURE_THRESHOLD` | `5` | CB Open 전환 실패 횟수 |
| `CB_COOLDOWN_MS` | `30000` | CB Open→Half-Open 대기(ms) |
| `CB_SUCCESS_THRESHOLD` | `2` | CB Closed 복귀 성공 횟수 |
| `MAX_RETRY_COUNT` | `3` | 채널별 최대 재시도 횟수 |
| `RETRY_BASE_DELAY_MS` | `1000` | 재시도 기본 대기(ms) |
| `RETRY_BACKOFF_MULTIPLIER` | `2` | 지수 백오프 배수 |
| `RATE_LIMIT_EMAIL_PER_SEC` | `10` | 이메일 초당 한도 |
| `RATE_LIMIT_SMS_PER_SEC` | `5` | SMS 초당 한도 |
| `RATE_LIMIT_WEBHOOK_PER_SEC` | `20` | Webhook 초당 한도 |
| `RATE_LIMIT_MAX_WAIT_MS` | `10000` | 토큰 대기 최대(ms) |
| `MOCK_DELAY_MIN_MS` | `100` | Mock 발송 최소 딜레이(ms) |
| `MOCK_DELAY_MAX_MS` | `500` | Mock 발송 최대 딜레이(ms) |

환경 변수 템플릿: `local.settings.sample.json`

---

## Design Patterns

### Adapter + Factory (Message Broker)

`QUEUE_SERVICE_TYPE` 환경 변수만 변경하면 브로커를 교체할 수 있다.

```
MessageBroker (interface) ←── MessageBrokerFactory.create(type)
    ├── EventGridAdapter      ← EVENT_GRID
    └── (확장 가능)            ← SNS, PUBSUB, ...
```

### Strategy (Notification)

채널별 프로바이더를 동적으로 라우팅한다. Mock 모드에서는 100~500ms 랜덤 딜레이.

```
NotificationStrategy (interface) ←── NotificationFactory.create(channel)
    ├── EmailStrategy   (SendGrid)
    ├── SmsStrategy     (Twilio)
    └── WebhookStrategy (HTTP POST)
```

### Transactional Outbox

DB 저장과 메시지 발행 사이의 정합성 보장. Dual Write 문제 원천 차단.

```
POST /events → DB (pending) → 201
                    ↓ Change Feed
              outbox-publisher → Event Grid → published
              실패 → failed_publish → outbox-retry (1min) → pending 복구
```

### Circuit Breaker

`{channel}:{provider}` 조합별 독립 운용. ETag 동시성 제어.

```
CLOSED ──(failure >= 5)──→ OPEN ──(30s 경과)──→ HALF-OPEN ──(success >= 2)──→ CLOSED
                                                     │
                                                  1회 실패 → OPEN
```

---

## Quick Start

### Prerequisites

- Node.js 22+
- Azure Functions Core Tools v4
- Azurite (로컬 Storage 에뮬레이터)

### Setup

```bash
npm install          # 의존성 설치
npm run build        # TypeScript 빌드
node scripts/init-db.js   # Cosmos DB 초기화 (최초 1회)
```

### Run

```bash
azurite --silent     # 별도 터미널에서 실행
npm start            # Azure Functions 로컬 실행 (http://localhost:7071)
```

### Test

```bash
npx jest                    # 전체 테스트 (183 tests)
npx jest tests/unit         # 단위 테스트
npx jest tests/integration  # 통합 테스트 (Cosmos DB Emulator 필요)
npx tsc --noEmit            # 타입 체크
```

수동 통합 테스트 (curl 명령어 포함): **[MANUAL_TEST.md](MANUAL_TEST.md)**

---

## Provider Switching

환경 변수만 변경하면 프로바이더를 교체할 수 있다.

| Variable | Current | Alternatives |
|----------|---------|-------------|
| `QUEUE_SERVICE_TYPE` | `EVENT_GRID` | `AWS_SNS`, `GCP_PUBSUB` |
| `NOTIFICATION_EMAIL_PROVIDER` | `sendgrid` | `ses`, `mailgun` |
| `NOTIFICATION_SMS_PROVIDER` | `twilio` | `sns`, `vonage` |

테스트용 이벤트 데이터: `test-events/` 디렉토리

```bash
# 이메일 전용
curl.exe -X POST http://localhost:7071/api/events -H "Content-Type: application/json" -d @test-events/test-event-email-only.json

# 전체 채널
curl.exe -X POST http://localhost:7071/api/events -H "Content-Type: application/json" -d @test-events/test-event-all-channels.json
```

---

## Architecture Decisions

| Decision | Why |
|----------|-----|
| **Serverless (Azure Functions)** | 간헐적 트래픽에 비용 효율적. 이벤트 기반 아키텍처와 자연스러운 결합 |
| **Cosmos DB (NoSQL)** | Change Feed 내장으로 Outbox 패턴 무인프라 구현. JSON 문서 기반 유연한 스키마 |
| **TypeScript (Node.js)** | Azure Consumption Plan Windows 제약. Python은 Windows 미지원 |
| **Notification 임베딩** | 이벤트 내부에 알림 결과 임베딩 → 단일 읽기로 전체 상태 조회, DDD 관점 원자성 보장 |
| **Cosmos DB CB/RL** | 프로토타입 범위. 프로덕션에서는 Redis 등 인메모리 DB가 적합 |

---

## Deployment

Azure Portal에서 Function App 생성 후, VS Code Azure Functions 확장 또는 GitHub Actions로 배포.

**Azure Portal 필수 설정:**
1. Function App → Configuration → Application settings에 위 환경 변수 전체 추가
2. Event Grid Topic 생성 → Function App의 event-consumer에 이벤트 구독 연결
3. Application Insights 연결 (자동 생성 또는 수동 연결)

> `local.settings.json`은 로컬 전용이며 Azure에 배포되지 않는다. 운영 환경 변수는 Azure Portal에서 별도 설정해야 한다.

---

## Docs

| Document | Description |
|----------|-------------|
| [docs/API.md](docs/API.md) | API Reference (전체 엔드포인트, 요청/응답 스키마) |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Cosmos DB 컨테이너 스키마, 필드 설명, 관계 |
| [MANUAL_TEST.md](MANUAL_TEST.md) | 수동 통합 테스트 가이드 (curl 명령어) |
| [SPEC.md](SPEC.md) | 기술 명세서 (단일 진실 공급원) |
| [PLAN.md](PLAN.md) | 구현 계획서 |
