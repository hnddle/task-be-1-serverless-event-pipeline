# Serverless Event Pipeline

치과 보험 청구 시스템의 이벤트 기반 알림 파이프라인.
Azure Functions v4 + Cosmos DB + Event Grid 기반 Serverless 아키텍처로 구현했다.

---

## 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Azure Functions (Serverless)                      │
│                                                                             │
│  ┌──────────────┐     ┌─────────────────┐     ┌────────────────────────┐   │
│  │  event-api   │     │ outbox-publisher│     │   event-consumer       │   │
│  │  (HTTP)      │     │ (Change Feed)   │     │   (Event Grid)         │   │
│  │              │     │                 │     │                        │   │
│  │ POST /events ├──┐  │ pending 감지    ├──┐  │ ┌──────────────────┐  │   │
│  │ GET /events  │  │  │ → Event Grid    │  │  │ │ Circuit Breaker  │  │   │
│  │ GET /events/ │  │  │   발행          │  │  │ │ Rate Limiter     │  │   │
│  │   {event_id} │  │  │ → published     │  │  │ │ Retry Service    │  │   │
│  └──────────────┘  │  │   상태 갱신     │  │  │ │ DLQ Service      │  │   │
│                    │  └─────────────────┘  │  │ └──────────────────┘  │   │
│  ┌──────────────┐  │                       │  │                        │   │
│  │   dlq-api    │  │  ┌─────────────────┐  │  │ Notification Strategy  │   │
│  │   (HTTP)     │  │  │  outbox-retry   │  │  │  ├─ Email (SendGrid)  │   │
│  │              │  │  │  (Timer 1min)   │  │  │  ├─ SMS (Twilio)      │   │
│  │ GET /dlq     │  │  │                 │  │  │  └─ Webhook           │   │
│  │ POST replay  │  │  │ failed_publish  │  │  └────────────────────────┘   │
│  │ POST batch   │  │  │ → pending 복구  │  │                               │
│  └──────────────┘  │  └─────────────────┘  │                               │
│                    │                       │                               │
└────────────────────┼───────────────────────┼───────────────────────────────┘
                     │                       │
                     ▼                       ▼
            ┌─────────────────┐     ┌─────────────────┐
            │   Cosmos DB     │     │   Event Grid    │
            │   (NoSQL API)   │     │   (Message      │
            │                 │     │    Broker)       │
            │  5 Containers   │     └─────────────────┘
            └─────────────────┘
```

### 이벤트 처리 흐름 (End-to-End)

```
Client                Azure Functions                  Cosmos DB          Event Grid
  │                        │                               │                  │
  │  POST /events          │                               │                  │
  ├───────────────────────►│                               │                  │
  │                        │  저장 (outbox: pending)       │                  │
  │                        ├──────────────────────────────►│                  │
  │                        │                               │                  │
  │  201 { queued }        │                               │                  │
  │◄───────────────────────┤                               │                  │
  │                        │                               │                  │
  │                        │  Change Feed 감지              │                  │
  │                        │◄──────────────────────────────┤                  │
  │                        │                               │                  │
  │                        │  outbox-publisher              │                  │
  │                        │  (pending만 필터링)            │                  │
  │                        │                               │                  │
  │                        │  Event Grid 발행               │                  │
  │                        ├──────────────────────────────────────────────────►│
  │                        │                               │                  │
  │                        │  outbox: published 갱신        │                  │
  │                        ├──────────────────────────────►│                  │
  │                        │                               │                  │
  │                        │  event-consumer 트리거         │                  │
  │                        │◄─────────────────────────────────────────────────┤
  │                        │                               │                  │
  │                        │  채널별 알림 발송               │                  │
  │                        │  ├─ Circuit Breaker 확인       │                  │
  │                        │  ├─ Rate Limiter 확인          │                  │
  │                        │  └─ Strategy.send()           │                  │
  │                        │                               │                  │
  │                        │  결과 저장                     │                  │
  │                        ├──────────────────────────────►│                  │
  │                        │  (completed / failed / DLQ)   │                  │
```

### 실패 시 재시도 흐름

```
알림 발송 실패
      │
      ▼
retry_count < MAX_RETRY_COUNT?
      │
  ┌───┴───┐
  │ Yes   │ No
  ▼       ▼
지수 백오프   DLQ 저장
대기 후       (dead-letter-queue)
재시도             │
                   ▼
            GET /dlq 조회
                   │
                   ▼
            POST /dlq/:id/replay
                   │
                   ▼
            Outbox 패턴으로 재발행
```

---

## Cosmos DB 컨테이너 다이어그램

```
┌─────────────────────────────────────────────────────────────────┐
│                    Cosmos DB Database                            │
│                    (notification-pipeline)                       │
│                                                                  │
│  ┌───────────────────────┐    ┌───────────────────────────────┐ │
│  │      events           │    │     dead-letter-queue          │ │
│  │  Partition: /clinic_id│    │  Partition: /clinic_id         │ │
│  │  TTL: OFF             │    │  TTL: OFF                      │ │
│  │                       │    │                                │ │
│  │  - id (UUID)          │    │  - id (UUID)                   │ │
│  │  - clinic_id          │    │  - original_event_id           │ │
│  │  - status             │    │  - clinic_id                   │ │
│  │  - event_type         │    │  - channel / provider          │ │
│  │  - patient_id         │    │  - payload (원본 스냅샷)       │ │
│  │  - channels[]         │    │  - failure_reason              │ │
│  │  - notifications[]    │    │  - retry_count                 │ │
│  │  - correlation_id     │    │  - replay_status               │ │
│  │  - _outbox_status     │    │  - replayed_at                 │ │
│  │  - created_at         │    │  - created_at                  │ │
│  └───────────────────────┘    └───────────────────────────────┘ │
│                                                                  │
│  ┌───────────────────────┐    ┌───────────────────────────────┐ │
│  │   circuit-breaker     │    │       rate-limiter             │ │
│  │  Partition: /id       │    │  Partition: /id                │ │
│  │  TTL: OFF             │    │  TTL: 60s (자동 만료)          │ │
│  │                       │    │                                │ │
│  │  - id ({ch}:{prov})   │    │  - id ({ch}:{prov})            │ │
│  │  - state              │    │  - tokens                      │ │
│  │    (closed/open/      │    │  - max_tokens                  │ │
│  │     half-open)        │    │  - refill_rate                 │ │
│  │  - failure_count      │    │  - last_refill_at              │ │
│  │  - success_count      │    │  - _etag (동시성 제어)         │ │
│  │  - last_failure_at    │    │                                │ │
│  │  - opened_at          │    │                                │ │
│  │  - _etag (동시성 제어)│    │                                │ │
│  └───────────────────────┘    └───────────────────────────────┘ │
│                                                                  │
│  ┌───────────────────────┐                                      │
│  │       leases          │  Azure Functions 런타임이 관리       │
│  │  (Change Feed용)      │  Change Feed Processor 체크포인트   │
│  │  Partition: /id       │  수동 접근 불필요                    │
│  └───────────────────────┘                                      │
└─────────────────────────────────────────────────────────────────┘
```

### 컨테이너별 설명

| 컨테이너 | Partition Key | TTL | 역할 |
|-----------|--------------|-----|------|
| `events` | `/clinic_id` | OFF | 알림 이벤트 문서. `_outbox_status`로 Transactional Outbox 구현 |
| `dead-letter-queue` | `/clinic_id` | OFF | 최대 재시도 초과한 실패 알림 보관. Replay API로 재처리 가능 |
| `circuit-breaker` | `/id` | OFF | `{channel}:{provider}` 조합별 Circuit Breaker 상태. ETag 동시성 제어 |
| `rate-limiter` | `/id` | 60s | Token Bucket 기반 Rate Limiter. 60초 TTL로 자동 만료/리셋 |
| `leases` | `/id` | - | Change Feed Processor 체크포인트. Azure Functions 런타임이 자동 관리 |

---

## Circuit Breaker 상태 머신

```
                    연속 실패 >= FAILURE_THRESHOLD
    ┌────────┐ ─────────────────────────────────► ┌────────┐
    │ CLOSED │                                     │  OPEN  │
    │        │ ◄───────────────────────────────── │        │
    └────────┘    연속 성공 >= SUCCESS_THRESHOLD    └────────┘
        ▲          (Half-Open 경유)                    │
        │                                              │
        │         ┌─────────────┐                      │
        └─────────┤  HALF-OPEN  │◄─────────────────────┘
          성공 ×2 │             │  COOLDOWN_MS 경과 후
                  └─────────────┘  첫 요청 시 전환
                        │
                        │ 1회 실패
                        ▼
                    ┌────────┐
                    │  OPEN  │ (재전환)
                    └────────┘
```

---

## 기술 스택

| 구분 | 기술 |
|------|------|
| Runtime | Node.js 22+ |
| Language | TypeScript 5 (strict mode) |
| Framework | Azure Functions v4 (Node.js programming model) |
| Database | Azure Cosmos DB (NoSQL API) |
| Message Broker | Azure Event Grid |
| Monitoring | Azure Monitor + Application Insights |
| DLQ | Azure Cosmos DB (별도 컨테이너) |
| Validation | Zod |
| Package Manager | npm |
| Test | Jest + ts-jest |
| Linter / Formatter | ESLint + Prettier |

---

## 프로젝트 구조

```
src/
├── functions/              # Azure Functions (5개)
│   ├── event-api.ts        #   HTTP: POST /events, GET /events, GET /events/{event_id}
│   ├── dlq-api.ts          #   HTTP: GET /dlq, POST /dlq/{id}/replay, POST /dlq/replay-batch
│   ├── outbox-publisher.ts #   Cosmos DB Change Feed → Event Grid 발행
│   ├── outbox-retry.ts     #   Timer (1분) → failed_publish 복구
│   └── event-consumer.ts   #   Event Grid → 채널별 알림 발송
├── services/               # 비즈니스 로직
│   ├── cosmos-client.ts    #   Cosmos DB 클라이언트 싱글턴 + 컨테이너 관리
│   ├── message-broker/     #   Adapter + Factory 패턴
│   │   ├── message-broker.ts
│   │   ├── message-broker-factory.ts
│   │   └── event-grid-adapter.ts
│   ├── notification/       #   Strategy 패턴
│   │   ├── notification-strategy.ts
│   │   ├── notification-factory.ts
│   │   ├── email-strategy.ts
│   │   ├── sms-strategy.ts
│   │   └── webhook-strategy.ts
│   ├── circuit-breaker.ts  #   Circuit Breaker (CLOSED/OPEN/HALF-OPEN)
│   ├── rate-limiter.ts     #   Token Bucket Rate Limiter
│   ├── retry-service.ts    #   지수 백오프 재시도
│   └── dlq-service.ts      #   Dead Letter Queue 저장/조회/Replay
├── shared/                 # 공통 유틸
│   ├── config.ts           #   환경 변수 로드 (12-Factor)
│   ├── logger.ts           #   구조화 JSON 로거
│   ├── validator.ts        #   Zod 기반 입력 검증
│   ├── correlation.ts      #   Correlation ID 컨텍스트 관리
│   └── errors.ts           #   공통 에러 타입
└── models/                 # TypeScript 인터페이스
    ├── events.ts
    ├── dlq.ts
    ├── circuit-breaker.ts
    └── rate-limiter.ts

tests/
├── unit/                   # 단위 테스트 (Jest)
└── integration/            # 통합 테스트 (Cosmos DB Emulator)
```

---

## 디자인 패턴

### Adapter + Factory (Message Broker)

`QUEUE_SERVICE_TYPE` 환경 변수만 변경하면 메시지 브로커(Event Grid, SNS, Pub/Sub 등)를 교체할 수 있다.

```
MessageBroker (interface)
    │
    ├── EventGridAdapter  ← QUEUE_SERVICE_TYPE=EVENT_GRID
    └── (확장 가능)       ← QUEUE_SERVICE_TYPE=SNS, PUBSUB 등

MessageBrokerFactory.create(type) → MessageBroker
```

### Strategy (Notification)

채널 값에 따라 알림 프로바이더를 동적으로 라우팅한다. Mock 모드에서는 100~500ms 랜덤 딜레이 후 로그만 기록한다.

```
NotificationStrategy (interface)
    │
    ├── EmailStrategy   (SendGrid)
    ├── SmsStrategy      (Twilio)
    └── WebhookStrategy  (HTTP POST)

NotificationFactory.create(channel) → NotificationStrategy
```

### Transactional Outbox

DB 저장과 메시지 발행 사이의 정합성을 보장한다. POST /events는 DB에만 저장하고, Change Feed가 비동기로 Event Grid에 발행한다.

```
POST /events → DB 저장 (_outbox_status: pending) → 201 응답
                    │
                    ▼ (Change Feed)
              outbox-publisher
                    │
              ┌─────┴─────┐
              │ pending만  │ published/기타는
              │ 처리       │ 무시 (무한루프 방지)
              └─────┬─────┘
                    │
                    ▼
              Event Grid 발행
                    │
              성공 → published
              실패 → failed_publish → outbox-retry (1분) → pending 복구
```

---

## API 요약

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/events` | 이벤트 생성 (201: 생성, 200: 중복) |
| GET | `/api/events/{event_id}` | 이벤트 상세 조회 (clinic_id 선택) |
| GET | `/api/events` | 이벤트 목록 조회 (clinic_id 필수) |
| GET | `/api/dlq` | DLQ 목록 조회 (clinic_id 필수) |
| POST | `/api/dlq/{dlq_id}/replay` | DLQ 단건 재처리 |
| POST | `/api/dlq/replay-batch` | DLQ 일괄 재처리 |

---

## 환경 변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `QUEUE_SERVICE_TYPE` | 메시지 브로커 타입 | `EVENT_GRID` |
| `NOTIFICATION_EMAIL_PROVIDER` | 이메일 프로바이더 | `sendgrid` |
| `NOTIFICATION_SMS_PROVIDER` | SMS 프로바이더 | `twilio` |
| `WEBHOOK_URL` | Webhook 엔드포인트 | - |
| `COSMOS_DB_ENDPOINT` | Cosmos DB 엔드포인트 | - |
| `COSMOS_DB_KEY` | Cosmos DB 키 | - |
| `COSMOS_DB_DATABASE` | 데이터베이스명 | - |
| `CB_FAILURE_THRESHOLD` | CB Open 전환 실패 횟수 | `5` |
| `CB_COOLDOWN_MS` | CB Open→Half-Open 대기(ms) | `30000` |
| `CB_SUCCESS_THRESHOLD` | CB Closed 복귀 성공 횟수 | `2` |
| `MAX_RETRY_COUNT` | 채널별 최대 재시도 횟수 | `3` |
| `RETRY_BASE_DELAY_MS` | 재시도 기본 대기(ms) | `1000` |
| `RETRY_BACKOFF_MULTIPLIER` | 지수 백오프 배수 | `2` |
| `RATE_LIMIT_EMAIL_PER_SEC` | 이메일 초당 한도 | `10` |
| `RATE_LIMIT_SMS_PER_SEC` | SMS 초당 한도 | `5` |
| `RATE_LIMIT_WEBHOOK_PER_SEC` | Webhook 초당 한도 | `20` |
| `RATE_LIMIT_MAX_WAIT_MS` | 토큰 대기 최대(ms) | `10000` |
| `MOCK_DELAY_MIN_MS` | Mock 발송 최소 딜레이(ms) | `100` |
| `MOCK_DELAY_MAX_MS` | Mock 발송 최대 딜레이(ms) | `500` |

환경 변수 템플릿: `local.settings.sample.json`

---

## 개발 환경 설정

### 사전 요구사항

- Node.js 22+
- Azure Functions Core Tools v4
- Azurite (로컬 Azure Storage 에뮬레이터)

### 설치 및 실행

```bash
# 의존성 설치
npm install

# TypeScript 빌드
npm run build

# Cosmos DB 초기화 (최초 1회)
node scripts/init-db.js

# Azurite 실행 (별도 터미널)
azurite --silent

# Azure Functions 로컬 실행
npm start
```

### 테스트

```bash
npx jest                    # 전체 테스트
npx jest tests/unit         # 단위 테스트
npx jest tests/integration  # 통합 테스트 (Emulator 필요)
npx tsc --noEmit            # 타입 체크
```

---

## 아키텍처 설계 의사결정

### 왜 서버리스(Azure Functions)인가

1. **비용 효율성**: 치과 보험 청구 알림은 24시간 내내 일정한 트래픽이 들어오지 않는다. 서버를 상시 가동하면 유휴 비용이 낭비되지만, 서버리스는 호출된 만큼만 비용을 지불하므로 초기 비용을 크게 줄일 수 있다.
2. **이벤트 기반 아키텍처와의 궁합**: API 호출 → Event Grid → Consumer로 이어지는 흐름에서, 각 단계를 독립적으로 Scale Out할 수 있는 서버리스가 유리하다.
3. **인프라 관리 부담 최소화**: 인프라 관리 대신 비즈니스 로직(코드) 자체에만 집중할 수 있다.

### 왜 Cosmos DB(NoSQL)인가

1. **유연한 스키마**: JSON 기반의 문서 구조로 빠른 반복 개발이 가능하다. 알림 이벤트처럼 채널별 상태가 다양한 구조에 적합하다.
2. **수평적 확장성**: 트래픽이 갑자기 몰려도 파티션 분할이 자동으로 이루어지고, 별도 샤딩 없이 Scale Out이 가능하다.
3. **Change Feed 내장**: Transactional Outbox 패턴을 별도 인프라 없이 Cosmos DB의 Change Feed만으로 구현할 수 있다.

### 왜 Azure인가

AWS와 GCP의 무료 크레딧이 소진된 상태였기 때문에 Azure 무료 평가판을 선택했다. 실무적으로는, Windows 환경이나 MS 생태계를 주로 활용하는 기업에서 AD 연동, Office 통합 등 확장성 측면에서 장점이 있다.

### 왜 TypeScript(Node.js)인가

처음에는 Python으로 구현했으나, 배포 과정에서 다음과 같은 제약을 만났다:

- Azure Functions Consumption Plan에서 Linux가 사라지고 **Windows만 선택 가능**하게 변경됨
- **Python 런타임은 Windows 환경에서 지원되지 않음**
- Flex Plan은 무료 평가판 구독에서 사용 불가

이런 제약 조건 하에서 Windows Consumption Plan에서 동작하는 런타임 중 TypeScript(Node.js)를 선택했다. Java는 JVM Cold Start 문제로 서버리스와 상성이 맞지 않아 제외했다.

---

## 핵심 설계 포인트

### 데이터 모델링

**알림 결과를 Event 문서 내부에 임베딩하는 구조를 채택했다.**

```json
{
  "id": "event-uuid",
  "notifications": [
    { "channel": "email", "status": "success", ... },
    { "channel": "sms", "status": "failed", ... }
  ]
}
```

이 구조의 장점:
- **원자성**: 이벤트 문서 전체가 하나의 트랜잭션으로 관리된다
- **Single-Record-Read**: `/events/{id}` 호출 시 모든 채널의 발송 상태를 한 번에 조회할 수 있다
- **DDD 관점**: 알림은 이벤트에 종속된 데이터이므로, 이벤트 없이 단독으로 존재할 이유가 없다

### 데이터 정합성 보장

**Transactional Outbox 패턴**으로 DB 저장과 메시지 발행 사이의 정합성을 보장한다. "DB 저장은 성공했는데 메시지 발행은 실패"하는 Dual Write 문제를 원천 차단한다. 사용자는 DB 저장 즉시 응답을 받고, 브로커 발행은 Change Feed 기반의 outbox-publisher가 백그라운드에서 처리하여 API Latency를 최소화한다.

**Idempotency(멱등성)** 로직을 통해, 분산 처리 환경에서 발생할 수 있는 이벤트/알림 중복 발송을 차단한다. 클라이언트가 전달하는 `id`가 곧 Idempotency Key이며, 동일한 요청 ID에 대해 항상 동일한 응답을 보장한다.

### 장애 대응

**Circuit Breaker**를 도입하여 외부 알림 프로바이더 장애가 시스템 전체로 전파되는 것을 방지한다. OPEN 상태에서는 외부 API를 호출하지 않고 즉시 실패 처리하여, 무의미한 재시도로 인한 실행 비용 낭비를 막는다. 실제 서비스 환경이라면 인메모리 DB(Redis 등)를 활용하여 상태를 공유하는 것이 더 적합하겠지만, 이 프로젝트에서는 Cosmos DB를 활용하여 ETag 기반 동시성 제어를 구현했다.

**DLQ + Replay 프로세스**로 단순 로그를 넘어, 실패한 메시지를 별도 컨테이너에 격리하고 장애 복구 후 API 호출만으로 재처리할 수 있도록 했다. 일시적 네트워크 오류나 프로바이더 장애 발생 시에도 누락된 알림을 유실 없이 재전송할 수 있는 Self-Healing 구조다.

### 분산 트레이싱

API 호출부터 Change Feed, 브로커, 워커까지 이어지는 전체 흐름을 **Correlation ID** 하나로 추적한다. 알림 실패 시 어떤 요청에서 시작되었는지 디버깅하고 인과관계를 분석할 수 있다.

### 디자인 패턴 적용

- **Adapter + Factory 패턴**: 메시지 큐 구현에 적용. 코드 수정 없이 `QUEUE_SERVICE_TYPE` 환경 변수 하나만 바꾸면 Event Grid를 SNS나 Pub/Sub로 교체할 수 있는 구조다.
- **Strategy 패턴**: 알림 프로바이더 구현에 적용. 채널별 프로바이더를 런타임에 동적으로 라우팅한다.

---

## 배포 과정에서 만난 문제와 해결

| 문제 | 원인 | 해결 |
|------|------|------|
| AWS/GCP 무료 크레딧 소진 | AWS는 +1 이메일 방식의 프리티어 증식을 차단(핸드폰 번호 중복 필터링), GCP도 기존 크레딧 0 | Azure 무료 평가판으로 전환 |
| Python → TypeScript 마이그레이션 | Consumption Plan이 Windows 전용으로 변경, Python은 Windows 미지원 | AI Agent를 활용해 기존 SPEC/PLAN 기반으로 TypeScript로 전환 (약 1시간 소요) |
| Azure Functions Flex Plan 사용 불가 | 무료 평가판 구독은 Flex Plan 미지원 | Consumption Plan(Windows) 사용 |
| Cosmos DB 인스턴스 생성 실패 | Azure 내부 오류 (일시적) | 재시도로 해결 |
| 로컬 실행 시 127.0.0.1:10000 연결 거부 | `AzureWebJobsStorage: "UseDevelopmentStorage=true"` 설정으로 Azurite에 연결 시도하나 미실행 상태 | Azurite 설치 및 실행 |
| Change Feed 트리거 실패 | `CosmosDBConnection` 앱 설정 누락 | 연결 문자열 설정 추가 |
| PowerShell에서 curl POST 400 에러 | PowerShell의 `curl`은 `Invoke-WebRequest` 별칭이라 JSON 인코딩이 달라짐 | `curl.exe` 사용 + JSON을 파일로 분리 (`-d @test-event.json`) |

---

## AI Agent 활용 워크플로우

이 프로젝트에서는 Claude Code를 활용하여 다음과 같은 워크플로우로 개발을 진행했다.

### 개발 프로세스

1. **요건 정의서 수기 작성**: 아키텍처 구조 설계, 기술 세부 구현 방법, 성능/보안 고려사항을 직접 작성
2. **SPEC.md 생성**: 요건 정의서를 기반으로 기술 명세서 자동 생성
3. **SPEC.md 리뷰**: 누락된 섹션, 모호한 요구사항, Acceptance Criteria 검증
4. **개선점 반영**: 리뷰 결과를 SPEC.md에 반영
5. **PLAN.md 생성**: SPEC.md 기반으로 단계별 구현 계획서 자동 생성
6. **PLAN.md 리뷰**: SPEC 커버리지, 의존성 순서, 단계 크기 검증
7. **CLAUDE.md 생성**: 프로젝트 컨벤션과 가이드라인 문서 작성
8. **단계별 구현**: 각 Step을 브랜치 생성 → 구현 → 테스트 → 커밋 → 머지 순서로 반복

### 에이전트 위임 범위에 대한 고민

이 프로젝트를 진행하면서 "에이전트에게 어디까지 위임해야 하는가"에 대한 고민이 생겼다.

- SPEC.md를 기반으로 PLAN.md를 세부 Step으로 나누고, 각 Step을 에이전트에게 위임하는 방식으로 개발했다.
- 모든 Step의 결과를 사람이 검토하고 승인하기 때문에 전통적인 개발 방식보다 빠르면서도 품질을 유지할 수 있었다.
- 다만 Step이 많아질수록 매번 승인하는 과정에 시간이 걸리고, 반복적인 승인 작업에서 사람이 실수할 가능성이 있다는 점도 느꼈다 (피로도에 의한 검토 품질 저하).
- 이론적으로는 "반복적이고 기준이 명확한 결정은 에이전트에게, 맥락이 복잡하고 책임이 큰 결정은 사람에게" 위임하는 것이 맞지만, 그 경계를 어디에 둘지는 프로젝트마다 다를 수밖에 없다.

---

## 시간 부족으로 포기한 부분

- **실제 알림 프로바이더 연동**: SendGrid, Twilio 등 실제 API 연동 대신 Mock 딜레이로 대체. 실서비스라면 각 프로바이더 SDK를 Strategy 구현체에 교체하면 된다.
- **Application Insights 연동**: 로거는 구조화 JSON으로 구현했으나, Azure Monitor/Application Insights에 직접 연동하는 부분은 미구현.
- **CI/CD 파이프라인**: GitHub Actions 등을 통한 자동 빌드/배포 파이프라인 미구성.
- **Redis 기반 Circuit Breaker/Rate Limiter**: Cosmos DB로 구현했으나, 실서비스에서는 지연 시간과 원자성을 고려하면 인메모리 DB가 더 적합하다.

---

## 참고 문서

- `SPEC.md` — 기술 명세서 (단일 진실 공급원)
- `PLAN.md` — 구현 계획서
- `MANUAL_TEST.md` — 수동 통합 테스트 가이드
