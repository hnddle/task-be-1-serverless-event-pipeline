# 치과 보험 청구 시스템 - 이벤트 기반 알림 파이프라인 개발 요건 정의서

## 1. 개요

치과 보험 청구 시스템의 이벤트 기반 알림 파이프라인을 구축한다. 12-Factor App 방법론과 Serverless 아키텍처를 엄격히 준수하며, 시스템 간 결합도를 낮추고 확장성을 보장하기 위해 이벤트 기반 아키텍처로 구현한다.

---

## 2. 기술 스택

| 구분 | 기술 |
|------|------|
| Runtime | Python 3.11+ |
| Framework | Azure Functions v4 (Python v2 programming model) |
| Database | Azure Cosmos DB (NoSQL API) |
| Message Broker | Azure Event Grid |
| Monitoring / Tracing | Azure Monitor + Application Insights |
| Dead Letter Queue | Azure Cosmos DB (별도 컨테이너) |
| 패키지 매니저 | pip (requirements.txt) |
| Validation | Pydantic v2 |
| 테스트 | pytest + pytest-asyncio |
| Linter / Formatter | ruff |
| Type Checker | mypy (strict mode) |

---

## 3. 데이터 모델

### 3.1. Notification Event Document (Cosmos DB - `events` 컨테이너)

```json
{
  "id": "uuid-v4-string",
  "clinic_id": "string",
  "status": "queued | processing | completed | partially_completed | failed",
  "event_type": "string",
  "patient_id": "string",
  "channels": ["email", "sms", "webhook"],
  "correlation_id": "string",
  "notifications": [
    {
      "channel": "string",
      "provider": "string",
      "status": "pending | success | failed",
      "sent_at": "timestamp | null",
      "retry_count": 0,
      "last_error": "string | null"
    }
  ],
  "created_at": "timestamp",
  "updated_at": "timestamp",
  "_outbox_status": "pending | published"
}
```

| 필드 | 설명 |
|------|------|
| `id` | UUID v4. 클라이언트가 생성하여 전달. Idempotency Key를 겸한다. |
| `clinic_id` | Partition Key. |
| `status` | `queued`(초기) → `processing`(처리중) → `completed`(전체 성공) / `partially_completed`(일부 성공) / `failed`(전체 실패). |
| `correlation_id` | 서버에서 자동 생성하는 분산 트레이싱 ID. 클라이언트가 지정하지 않는다. |
| `_outbox_status` | Transactional Outbox용 내부 필드. `pending`(발행 대기) / `published`(발행 완료). |

> **Note:** `id`가 곧 Idempotency Key이다. 별도 `idempotency_key` 필드를 두지 않는다.

### 3.2. Dead Letter Queue Document (Cosmos DB - `dead-letter-queue` 컨테이너)

```json
{
  "id": "uuid-v4-string",
  "original_event_id": "string",
  "clinic_id": "string",
  "channel": "string",
  "provider": "string",
  "event_type": "string",
  "patient_id": "string",
  "payload": {},
  "failure_reason": "string",
  "retry_count": 0,
  "correlation_id": "string",
  "created_at": "timestamp",
  "replay_status": "pending | replayed | permanently_failed",
  "replayed_at": "timestamp | null"
}
```

| 필드 | 설명 |
|------|------|
| `id` | DLQ 문서 고유 ID (UUID v4, 서버 생성). |
| `clinic_id` | Partition Key. 원본 이벤트의 clinic_id를 그대로 복사. |
| `payload` | 원본 이벤트 전체 문서의 스냅샷. 재처리 시 이 데이터를 사용. |
| `replay_status` | `pending`(재처리 대기) / `replayed`(재처리 완료) / `permanently_failed`(수동 포기). |

### 3.3. Circuit Breaker State Document (Cosmos DB - `circuit-breaker` 컨테이너)

```json
{
  "id": "email:sendgrid",
  "state": "closed | open | half-open",
  "failure_count": 0,
  "success_count": 0,
  "last_failure_at": "timestamp | null",
  "opened_at": "timestamp | null",
  "updated_at": "timestamp",
  "_etag": "string"
}
```

| 필드 | 설명 |
|------|------|
| `id` | `{channel}:{provider}` 형식. Partition Key를 겸한다. |
| `_etag` | Cosmos DB ETag. 낙관적 동시성 제어에 사용. |

### 3.4. Rate Limiter State Document (Cosmos DB - `rate-limiter` 컨테이너)

```json
{
  "id": "email:sendgrid",
  "tokens": 10,
  "max_tokens": 10,
  "last_refill_at": "timestamp",
  "updated_at": "timestamp",
  "_etag": "string"
}
```

| 필드 | 설명 |
|------|------|
| `id` | `{channel}:{provider}` 형식. Partition Key를 겸한다. |
| `_etag` | Cosmos DB ETag. 낙관적 동시성 제어에 사용. |

### 3.5. Cosmos DB 구성

| 항목 | 설정 |
|------|------|
| Consistency Level | Session |
| `events` 컨테이너 Partition Key | `/clinic_id` |
| `dead-letter-queue` 컨테이너 Partition Key | `/clinic_id` |
| `circuit-breaker` 컨테이너 Partition Key | `/id` |
| `rate-limiter` 컨테이너 Partition Key | `/id` |
| `leases` 컨테이너 | Change Feed Processor 체크포인트 전용 |
| Indexing Policy | 기본 자동 인덱싱 사용. `events` 컨테이너에서 `status`, `event_type`, `created_at` 필드에 복합 인덱스 추가. |
| TTL | `rate-limiter` 컨테이너: 60초. 나머지: 비활성화 (데이터 영구 보관). |

---

## 4. 디자인 패턴 구현

### 4.1. Adapter 패턴 + Factory 패턴 - Message Broker 추상화

메시지 큐(Event Grid, SNS, Pub/Sub 등)를 교체 가능한 Backing Service로 취급한다. 환경 변수 변경만으로 큐 서비스를 교체할 수 있어야 한다.

- **인터페이스**: `MessageBroker` (`publish(event): Promise<void>` 메서드 포함)
- **팩토리**: `MessageBrokerFactory` - 환경 변수 `QUEUE_SERVICE_TYPE`에 따라 적절한 어댑터 인스턴스를 생성
- **어댑터**: `MessageBrokerAdapter` - 각 벤더 SDK를 래핑
- **식별**: `getBrokerName(): string`으로 현재 활성 브로커(EventGrid, PubSub 등)를 식별

**Acceptance Criteria:**

- [ ] `QUEUE_SERVICE_TYPE` 환경 변수를 변경하는 것만으로 브로커가 교체된다
- [ ] 지원하지 않는 `QUEUE_SERVICE_TYPE` 값이 들어오면 팩토리에서 명확한 에러를 throw한다
- [ ] `getBrokerName()`이 현재 활성 브로커 이름을 정확히 반환한다
- [ ] 어댑터 구현체가 `MessageBroker` 인터페이스를 준수한다

### 4.2. Strategy 패턴 - 알림 프로바이더 라우팅

알림 프로바이더를 단일 진입점에서 채널 값에 따라 동적으로 라우팅한다.

- **인터페이스**: `NotificationStrategy` (`send(notification): Promise<NotificationResult>` 메서드 포함)
- **구현체**: 채널(email, sms, webhook)별 Strategy 클래스
- **Mocking**: 실제 발송 로직 대신 100~500ms 랜덤 딜레이 처리 후 로그만 기록 (Mock 딜레이 범위는 환경 변수 `MOCK_DELAY_MIN_MS`, `MOCK_DELAY_MAX_MS`로 설정 가능, 기본값 100, 500)

**Acceptance Criteria:**

- [ ] `channels` 배열에 `["email", "sms", "webhook"]`을 전달하면 3개 Strategy가 각각 실행된다
- [ ] 지원하지 않는 채널이 들어오면 해당 채널을 `failed` 처리하고 에러 로그를 남긴다
- [ ] Mock 모드에서 각 발송마다 설정된 범위 내의 랜덤 딜레이가 적용된다
- [ ] Mock 발송 결과가 구조화 로그로 출력된다

### 4.3. Circuit Breaker 패턴 - 외부 API 호출부 보호

외부 알림 프로바이더(SendGrid, Twilio 등) API 호출 시 Circuit Breaker를 적용하여, 장애가 전파되지 않도록 시스템을 보호한다.

**상태 머신:**

```
[Closed] ---(연속 실패 >= CB_FAILURE_THRESHOLD)---> [Open]
[Open] ---(현재시간 - opened_at >= CB_COOLDOWN_MS)---> [Half-Open]
[Half-Open] ---(연속 성공 >= CB_SUCCESS_THRESHOLD)---> [Closed]
[Half-Open] ---(1회 실패)---> [Open]
```

**구현 요건:**

- 각 `{channel}:{provider}` 조합별로 독립적인 Circuit Breaker를 운용한다
- 상태는 Cosmos DB `circuit-breaker` 컨테이너에 저장한다
- 상태 읽기/쓰기 시 ETag 기반 낙관적 동시성 제어를 적용한다. ETag 충돌(412) 발생 시 최신 상태를 다시 읽어 판정한다
- 설정값은 환경 변수로 관리한다:

| 환경 변수 | 설명 | 기본값 |
|-----------|------|--------|
| `CB_FAILURE_THRESHOLD` | Open 전환까지의 연속 실패 횟수 | 5 |
| `CB_COOLDOWN_MS` | Open에서 Half-Open 전환까지 대기 시간(ms) | 30000 |
| `CB_SUCCESS_THRESHOLD` | Half-Open에서 Closed 전환까지 필요한 연속 성공 횟수 | 2 |

- Circuit이 Open 상태일 때 해당 채널의 알림 요청은 즉시 실패 처리하고, 로그에 기록한다
- Circuit 상태 변경 시 구조화된 로그를 출력한다

**Acceptance Criteria:**

- [ ] 연속 실패 횟수가 `CB_FAILURE_THRESHOLD`에 도달하면 상태가 Open으로 전환된다
- [ ] Open 상태에서 `CB_COOLDOWN_MS` 경과 후 첫 요청 시 Half-Open으로 전환된다
- [ ] Half-Open 상태에서 `CB_SUCCESS_THRESHOLD`만큼 연속 성공하면 Closed로 복귀한다
- [ ] Half-Open 상태에서 1회 실패 시 즉시 Open으로 재전환된다
- [ ] Open 상태에서 들어오는 요청은 외부 API를 호출하지 않고 즉시 실패 처리된다
- [ ] 상태 변경 시마다 `from_state`, `to_state`가 포함된 구조화 로그가 출력된다
- [ ] 두 함수 인스턴스가 동시에 상태를 갱신해도 ETag 충돌로 인한 데이터 손상이 발생하지 않는다

### 4.4. Transactional Outbox 패턴 - Cosmos DB Change Feed 활용

DB 저장과 메시지 발행 사이의 정합성을 보장한다. 이벤트를 직접 메시지 브로커에 발행하는 대신, DB에 먼저 기록하고 Change Feed를 통해 비동기로 발행한다.

**흐름:**

```
1. POST /events 요청 수신
2. Cosmos DB에 이벤트 저장 (_outbox_status: "pending")
3. 클라이언트에 즉시 응답 반환 (status: "queued")
4. Change Feed Processor (outbox-publisher Function)가 문서 변경 감지
5. _outbox_status가 "pending"인 문서만 필터링하여 처리
6. Message Broker에 이벤트 발행
7. 발행 성공 시 _outbox_status를 "published"로 업데이트
8. 발행 실패 시 _outbox_status를 "failed_publish"로 업데이트하고 에러 로그 기록
```

**구현 요건:**

- Change Feed를 트리거로 하는 별도 Azure Function(`outbox-publisher`)을 구현한다
- **Change Feed 루프 방지**: outbox-publisher는 수신된 문서의 `_outbox_status`가 `"pending"`인 경우에만 처리한다. `"published"` 또는 기타 상태의 문서는 무시한다 (Change Feed는 모든 변경에 대해 발화하므로, `_outbox_status`를 `"published"`로 업데이트하면 다시 트리거된다. 이 재트리거를 반드시 필터링해야 한다)
- **발행 실패 재시도**: 발행 실패 시 `_outbox_status`를 `"failed_publish"`로 갱신한다. 별도 타이머 트리거 Function(`outbox-retry`, 1분 간격)이 `_outbox_status: "failed_publish"`인 문서를 조회하여 `"pending"`으로 재갱신함으로써 Change Feed를 재발화시킨다
- Change Feed Processor의 lease 컨테이너(`leases`)를 별도로 생성하여 체크포인트를 관리한다
- 발행 시 이벤트의 `id`를 포함하여, Consumer 측에서도 Idempotency 확인이 가능하게 한다

**Acceptance Criteria:**

- [ ] POST /events 호출 시 DB 저장만 수행하고 Message Broker를 직접 호출하지 않는다
- [ ] Change Feed가 `_outbox_status: "pending"` 문서를 감지하여 Message Broker에 발행한다
- [ ] 발행 성공 후 `_outbox_status`가 `"published"`로 갱신된다
- [ ] `_outbox_status: "published"` 문서 변경에 의한 Change Feed 재트리거 시 아무 동작도 하지 않는다 (무한 루프 방지)
- [ ] 발행 실패 시 `_outbox_status`가 `"failed_publish"`로 갱신되고, outbox-retry에 의해 재시도된다
- [ ] 동일 이벤트가 중복 발행되어도 Consumer에서 멱등성이 보장된다

---

## 5. Backpressure 제어

외부 프로바이더의 rate limit 문제를 방지하기 위해 Backpressure 메커니즘을 구현한다.

**구현 요건:**

- Token Bucket 알고리즘 기반의 Rate Limiter를 `{channel}:{provider}` 조합별로 적용한다
- Rate limit 상태는 Cosmos DB `rate-limiter` 컨테이너에 저장한다 (TTL 60초로 자동 만료)
- 상태 읽기/쓰기 시 ETag 기반 낙관적 동시성 제어를 적용한다. ETag 충돌(412) 발생 시 최신 상태를 다시 읽어 재시도한다
- 토큰이 부족한 경우, 해당 채널의 발송을 지수 백오프로 대기 후 재시도한다. 이 재시도는 Event Consumer 함수 내부에서 in-process로 수행하며, 별도 큐에 넣지 않는다
- 설정값은 환경 변수로 관리한다:

| 환경 변수 | 설명 | 기본값 |
|-----------|------|--------|
| `RATE_LIMIT_EMAIL_PER_SEC` | 이메일 채널 초당 최대 발송 수 | 10 |
| `RATE_LIMIT_SMS_PER_SEC` | SMS 채널 초당 최대 발송 수 | 5 |
| `RATE_LIMIT_WEBHOOK_PER_SEC` | Webhook 채널 초당 최대 발송 수 | 20 |
| `RATE_LIMIT_MAX_WAIT_MS` | 토큰 대기 최대 시간(ms). 초과 시 실패 처리 | 10000 |

- 프로바이더로부터 429(Too Many Requests) 응답 수신 시:
  - Circuit Breaker 실패 카운트에는 포함하지 않는다 (서비스 장애가 아닌 rate limit이므로)
  - Retry-After 헤더가 있으면 해당 값만큼 대기 후 재시도하고, 없으면 지수 백오프를 적용한다

**Acceptance Criteria:**

- [ ] 초당 발송량이 설정된 한도를 초과하지 않는다
- [ ] 토큰이 부족할 때 즉시 실패하지 않고 `RATE_LIMIT_MAX_WAIT_MS` 이내에서 대기 후 재시도한다
- [ ] `RATE_LIMIT_MAX_WAIT_MS` 초과 시 해당 채널 발송이 실패 처리된다 (재시도 정책으로 넘어감)
- [ ] 429 응답은 Circuit Breaker 실패 카운트에 포함되지 않는다
- [ ] 429 응답의 Retry-After 헤더가 있으면 해당 값을 준수한다
- [ ] 여러 함수 인스턴스가 동시에 토큰을 소비해도 ETag 기반으로 정합성이 유지된다

---

## 6. 재시도 및 Dead Letter Queue (DLQ)

### 6.1. 재시도 정책

알림 발송 실패 시 단순 로그가 아닌, 설정 가능한 재시도를 수행한다.

| 환경 변수 | 설명 | 기본값 |
|-----------|------|--------|
| `MAX_RETRY_COUNT` | 채널별 최대 재시도 횟수 | 3 |
| `RETRY_BASE_DELAY_MS` | 재시도 기본 대기 시간(ms) | 1000 |
| `RETRY_BACKOFF_MULTIPLIER` | 지수 백오프 배수 | 2 |

- 재시도는 Event Consumer 함수 내에서 in-process로 수행한다
- 재시도 간격은 지수 백오프를 적용한다: `base_delay * (multiplier ^ retry_count)`
  - 예: 기본값 기준 1초 → 2초 → 4초
- 각 재시도 시 `notifications[].retry_count`를 갱신하고, `last_error`에 실패 원인을 기록한다
- 재시도 시에도 Idempotency 확인을 수행하여 중복 발송을 방지한다

**Acceptance Criteria:**

- [ ] 발송 실패 시 `MAX_RETRY_COUNT`까지 자동 재시도한다
- [ ] 재시도 간격이 지수 백오프를 정확히 따른다
- [ ] 각 재시도마다 `retry_count`와 `last_error`가 Cosmos DB에 갱신된다
- [ ] `MAX_RETRY_COUNT`를 환경 변수로 변경하면 재시도 횟수가 그에 맞게 변경된다

### 6.2. Dead Letter Queue (DLQ)

최대 재시도 횟수를 초과한 메시지는 DLQ로 이동하여 별도 보관한다.

**구현 요건:**

- DLQ는 Cosmos DB의 별도 컨테이너(`dead-letter-queue`)에 저장한다
- DLQ 문서에는 원본 이벤트 페이로드 전체, 실패 사유, 최종 재시도 횟수, `correlation_id`를 포함한다
- DLQ로 이동한 뒤, 원본 문서의 해당 채널 `notifications[].status`를 `"failed"`로 최종 갱신한다
- 이벤트의 최종 `status` 결정 기준:
  - 전체 채널 성공: `"completed"`
  - 일부 채널 성공, 일부 실패: `"partially_completed"`
  - 전체 채널 실패: `"failed"`

**Acceptance Criteria:**

- [ ] `MAX_RETRY_COUNT` 초과 시 해당 채널의 실패 정보가 DLQ 컨테이너에 저장된다
- [ ] DLQ 문서에 원본 페이로드, 실패 사유, 재시도 횟수, `correlation_id`가 모두 포함된다
- [ ] DLQ 이동 후 원본 이벤트의 해당 채널 status가 `"failed"`로 갱신된다
- [ ] 3개 채널 중 2개 성공, 1개 실패 시 이벤트 status가 `"partially_completed"`이다
- [ ] 3개 채널 전체 실패 시 이벤트 status가 `"failed"`이다

### 6.3. Replay 프로세스 - 실패 메시지 재처리

DLQ에 보관된 메시지를 조회하고 재처리할 수 있는 API를 제공한다.

**API 명세:**

#### `GET /dlq`

DLQ 메시지 목록 조회.

Query Parameters:

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `clinic_id` | string | Y | 병원 ID (Partition Key 필터) |
| `replay_status` | string | N | `pending` / `replayed` / `permanently_failed` |
| `event_type` | string | N | 이벤트 타입 필터 |
| `date_from` | ISO 8601 | N | 생성일 시작 범위 |
| `date_to` | ISO 8601 | N | 생성일 종료 범위 |
| `continuation_token` | string | N | 페이지네이션 토큰 |
| `page_size` | number | N | 페이지 크기 (기본값: 20, 최대: 100) |

Response (200):

```json
{
  "items": [ /* DLQ documents */ ],
  "continuation_token": "string | null",
  "total_count": 0
}
```

#### `POST /dlq/:dlq_id/replay`

특정 DLQ 메시지를 재처리 큐에 발행.

- `replay_status`를 `"replayed"`로 갱신하고, `replayed_at`에 타임스탬프를 기록
- 재처리 시 새로운 `correlation_id`를 발급하되, 원본 `correlation_id`를 로그에 함께 기록하여 추적 가능하게 한다
- 재처리 이벤트는 원본 `payload`를 기반으로 Outbox 패턴을 통해 발행한다

Response (200): `{ "dlq_id": "string", "replay_status": "replayed", "new_correlation_id": "string" }`

Response (409): 이미 `replayed` 상태인 메시지를 다시 replay 시도한 경우.

#### `POST /dlq/replay-batch`

필터 조건에 맞는 DLQ 메시지를 일괄 재처리.

Request Body:

```json
{
  "clinic_id": "string",
  "event_type": "string | null",
  "date_from": "ISO 8601 | null",
  "date_to": "ISO 8601 | null",
  "max_count": 100
}
```

| 필드 | 설명 |
|------|------|
| `clinic_id` | 필수. 병원 ID. |
| `max_count` | 한 번에 재처리할 최대 건수. 기본값 100, 최대값 500. |

Response (200): `{ "replayed_count": 0, "failed_count": 0, "skipped_count": 0 }`

**Acceptance Criteria:**

- [ ] `GET /dlq`에서 `clinic_id`가 필수 파라미터이며, 누락 시 400 에러를 반환한다
- [ ] 페이지네이션이 `continuation_token` 기반으로 동작한다
- [ ] `POST /dlq/:dlq_id/replay` 호출 시 해당 메시지가 Outbox 패턴을 통해 재발행된다
- [ ] 이미 replayed된 메시지를 다시 replay 시도하면 409를 반환한다
- [ ] `POST /dlq/replay-batch`에서 `max_count`를 초과하는 값은 500으로 클램핑된다
- [ ] Replay 시 새 `correlation_id`가 발급되고, 로그에 원본 `correlation_id`도 함께 기록된다

---

## 7. Idempotency (멱등성)

중복 발송을 방지하기 위해 Idempotency Key를 도입한다.

**구현 요건:**

- 클라이언트가 `POST /events` 요청 시 전달하는 `id` 필드가 곧 Idempotency Key이다
- 이벤트 저장 시 Cosmos DB의 `id` 유니크 제약을 활용한다. 동일 `id` + `clinic_id`(Partition Key) 조합의 문서가 이미 존재하면 409(Conflict)가 발생한다
- 409 Conflict 발생 시 기존 문서를 조회하여 현재 상태를 HTTP 200으로 반환한다
- Event Consumer에서 메시지 처리 전 해당 이벤트의 `notifications[].status`를 확인하여, 이미 `"success"`인 채널은 재발송하지 않는다
- Outbox Publisher에서도 `_outbox_status`를 확인하여, 이미 `"published"`인 문서는 재발행하지 않는다

**Acceptance Criteria:**

- [ ] 동일 `id`로 `POST /events`를 2회 호출하면, 첫 번째는 201, 두 번째는 200을 반환한다
- [ ] 두 번째 요청의 응답에 기존 문서의 현재 상태가 포함된다
- [ ] 동일 이벤트가 Event Consumer에 2번 전달되어도 이미 성공한 채널은 재발송되지 않는다
- [ ] Outbox Publisher가 동일 이벤트를 2번 감지해도 Message Broker에 1번만 발행한다

---

## 8. API 명세

### 8.1. 이벤트 발행 API

```
POST /events
```

**Request Body:**

```json
{
  "id": "UUID",
  "event_type": "appointment_confirmed",
  "clinic_id": "CLINIC_123",
  "patient_id": "PATIENT_456",
  "channels": ["email", "sms", "webhook"]
}
```

**입력 검증 규칙:**

| 필드 | 규칙 |
|------|------|
| `id` | 필수. UUID v4 형식. |
| `event_type` | 필수. `appointment_confirmed` / `insurance_approved` / `claim_completed` 중 하나. |
| `clinic_id` | 필수. 비어 있지 않은 문자열. |
| `patient_id` | 필수. 비어 있지 않은 문자열. |
| `channels` | 필수. 1개 이상의 배열. 허용값: `email`, `sms`, `webhook`. 중복 불가. |

**처리 흐름:**

1. 입력 검증
2. Cosmos DB에 이벤트 저장 시도 (`status: "queued"`, `_outbox_status: "pending"`)
3. 409 Conflict 시 기존 문서 조회 후 200 반환
4. 저장 성공 시 201 반환 (Outbox 패턴에 의해 비동기 발행)

**Response (201 Created):**

```json
{
  "event_id": "UUID",
  "status": "queued",
  "correlation_id": "UUID"
}
```

**Response (200 OK - 중복 요청):**

```json
{
  "event_id": "UUID",
  "status": "queued | processing | completed | partially_completed | failed",
  "correlation_id": "UUID",
  "message": "Event already exists"
}
```

**Response (400 Bad Request - 검증 실패):**

```json
{
  "error": "VALIDATION_ERROR",
  "message": "Invalid request body",
  "details": [
    { "field": "event_type", "message": "Must be one of: appointment_confirmed, insurance_approved, claim_completed" }
  ]
}
```

### 8.2. 알림 이력 조회 API

#### `GET /events/:event_id`

특정 이벤트의 채널별 발송 상태 상세 조회.

Query Parameters:

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `clinic_id` | string | Y | Partition Key. 필수. |

Response (200):

```json
{
  "id": "UUID",
  "clinic_id": "CLINIC_123",
  "status": "completed",
  "event_type": "appointment_confirmed",
  "patient_id": "PATIENT_456",
  "channels": ["email", "sms", "webhook"],
  "correlation_id": "UUID",
  "notifications": [
    {
      "channel": "email",
      "provider": "sendgrid",
      "status": "success",
      "sent_at": "2026-04-13T15:24:16Z",
      "retry_count": 0,
      "last_error": null
    }
  ],
  "created_at": "2026-04-13T15:24:00Z",
  "updated_at": "2026-04-13T15:24:16Z"
}
```

Response (404): 해당 `event_id` + `clinic_id` 조합의 문서가 없는 경우.

#### `GET /events`

이벤트 목록 조회.

Query Parameters:

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `clinic_id` | string | Y | Partition Key. 필수. |
| `status` | string | N | 상태 필터 |
| `event_type` | string | N | 이벤트 타입 필터 |
| `continuation_token` | string | N | 페이지네이션 토큰 |
| `page_size` | number | N | 페이지 크기 (기본값: 20, 최대: 100) |

Response (200):

```json
{
  "items": [ /* Event documents (notifications 필드 제외한 요약) */ ],
  "continuation_token": "string | null"
}
```

**Acceptance Criteria:**

- [ ] `GET /events/:event_id` 호출 시 `clinic_id` 쿼리 파라미터가 없으면 400을 반환한다
- [ ] 존재하지 않는 이벤트 조회 시 404를 반환한다
- [ ] `GET /events` 목록 조회 시 `clinic_id`가 필수이며, 페이지네이션이 동작한다
- [ ] `page_size`가 100을 초과하면 100으로 클램핑된다

### 8.3. DLQ 조회 및 Replay API

상세 명세는 [6.3. Replay 프로세스](#63-replay-프로세스---실패-메시지-재처리) 참조.

### 8.4. 공통 에러 응답 형식

모든 API는 에러 시 아래 형식을 따른다:

```json
{
  "error": "ERROR_CODE",
  "message": "Human-readable description",
  "details": []
}
```

| HTTP Status | Error Code | 사용 시점 |
|-------------|-----------|----------|
| 400 | `VALIDATION_ERROR` | 입력 검증 실패 |
| 404 | `NOT_FOUND` | 리소스 없음 |
| 409 | `CONFLICT` | 이미 replayed된 DLQ 메시지 재시도 |
| 500 | `INTERNAL_ERROR` | 서버 내부 오류 |

---

## 9. Event Consumer (Worker Function)

메시지 큐(Event Grid) 트리거로 실행되는 백그라운드 함수이다.

**처리 흐름:**

1. 수신된 메시지의 `correlation_id`를 컨텍스트에 바인딩 (이후 모든 로그에 자동 포함)
2. Idempotency 확인: Cosmos DB에서 해당 이벤트를 조회하여 이미 처리 완료된 채널이 있는지 확인
3. 이벤트의 `status`를 `"processing"`으로 갱신
4. `channels` 배열 순회:
   a. 해당 채널이 이미 `"success"`이면 스킵 (멱등성)
   b. Circuit Breaker 상태 확인 → Open이면 즉시 실패 처리
   c. Rate Limiter 확인 → 토큰 부족 시 `RATE_LIMIT_MAX_WAIT_MS` 이내 대기 후 재시도
   d. `NotificationStrategy`를 통해 채널별 알림 발송 (Mock)
   e. 발송 실패 시 재시도 정책에 따라 in-process 재시도 수행
   f. 최대 재시도 초과 시 해당 채널의 메시지를 DLQ로 이동
5. 모든 채널 처리 완료 후 결과를 Cosmos DB에 기록:
   - 전체 성공: `status: "completed"`
   - 일부 성공, 일부 실패: `status: "partially_completed"`
   - 전체 실패: `status: "failed"`

**Acceptance Criteria:**

- [ ] Event Grid 메시지 수신 시 Consumer가 자동으로 트리거된다
- [ ] 이미 `"success"`인 채널은 재발송하지 않는다
- [ ] Circuit Breaker가 Open인 채널은 외부 호출 없이 즉시 실패 처리된다
- [ ] 모든 채널 처리 후 이벤트 status가 결과에 맞게 갱신된다
- [ ] 처리 중 함수가 crash되어도 이벤트가 유실되지 않는다 (Event Grid 재전달)

---

## 10. 분산 트레이싱 및 구조화 로깅

### 10.1. Correlation ID

모든 로그에 상관관계 ID를 포함하여, 하나의 요청 흐름을 처음부터 끝까지 Azure Monitor에서 추적할 수 있게 한다.

**구현 요건:**

- `POST /events` 진입 시 `correlation_id`(UUID v4)를 생성하여 이벤트 문서에 저장한다
- 이후 Outbox Publisher, Event Consumer, 재시도, DLQ 이동 등 모든 단계에서 동일한 `correlation_id`를 사용한다
- Azure Application Insights SDK를 사용하여 `correlation_id`를 `operation_id`에 매핑한다. 이를 통해 Application Insights의 "End-to-End Transaction" 뷰에서 전체 흐름을 조회할 수 있다
- 모든 함수의 진입점에서 `correlation_id`를 로깅 컨텍스트에 바인딩하는 미들웨어/유틸리티를 구현한다
- Replay 시에는 새로운 `correlation_id`를 발급하되, 로그에 `original_correlation_id` 필드를 추가하여 원본 흐름과 연결한다

**Acceptance Criteria:**

- [ ] 하나의 이벤트 흐름(POST → Outbox → Consumer → 발송)에서 모든 로그가 동일한 `correlation_id`를 가진다
- [ ] Azure Monitor Application Insights에서 `correlation_id`로 검색하면 전체 흐름의 로그가 한 화면에 표시된다
- [ ] Replay 이벤트의 로그에 `original_correlation_id`가 포함되어 원본 흐름을 역추적할 수 있다

### 10.2. 구조화 로그 형식

파일 기반 로깅은 금지하며, 모든 로그는 stdout/stderr를 통해 Azure Monitor로 스트리밍한다. 모든 로그는 아래 JSON 형식을 따른다:

```json
{
  "timestamp": "2026-04-13T15:24:16Z",
  "level": "INFO | WARN | ERROR",
  "correlation_id": "uuid-string",
  "event_id": "uuid-string",
  "event_type": "appointment_confirmed",
  "channel": "email",
  "provider": "sendgrid",
  "status": "success | failed | circuit_open | rate_limited",
  "duration_ms": 150,
  "retry_count": 0,
  "circuit_state": "closed | open | half-open",
  "message": "발송 완료"
}
```

> **Note:** 모든 필드가 매 로그에 포함되는 것은 아니다. `correlation_id`, `timestamp`, `level`, `message`는 필수이며, 나머지는 해당 컨텍스트에서 관련 있는 경우에만 포함한다.

### 10.3. 주요 로그 이벤트

다음 시점에 반드시 구조화 로그를 출력한다:

| 시점 | 로그 레벨 | 필수 포함 정보 |
|------|----------|--------------|
| 이벤트 수신 | INFO | event_id, event_type, channels |
| Outbox 발행 성공 | INFO | event_id, broker_name |
| Outbox 발행 실패 | ERROR | event_id, error |
| 채널별 발송 시작 | INFO | event_id, channel, provider |
| 채널별 발송 성공 | INFO | event_id, channel, provider, duration_ms |
| 채널별 발송 실패 | WARN | event_id, channel, provider, error, retry_count |
| 재시도 수행 | WARN | event_id, channel, retry_count, next_delay_ms |
| DLQ 이동 | ERROR | event_id, channel, failure_reason, total_retry_count |
| Circuit Breaker 상태 변경 | WARN | channel, provider, from_state, to_state |
| Rate limit 도달 | WARN | channel, provider, current_rate |
| Rate limit 대기 | INFO | channel, provider, wait_ms |
| Replay 수행 | INFO | dlq_id, original_event_id, original_correlation_id, new_correlation_id |
| 중복 요청 감지 | INFO | event_id |
| 환경 변수 누락 | ERROR | missing_key → Fail-fast 종료 |

**Acceptance Criteria:**

- [ ] 위 표의 모든 시점에서 구조화 로그가 출력된다
- [ ] 모든 로그에 `correlation_id`가 포함된다
- [ ] 로그가 JSON 형식으로 stdout에 출력된다 (파일 로깅 없음)
- [ ] Azure Monitor에서 `correlation_id`로 쿼리하면 관련 로그가 모두 조회된다

---

## 11. 환경 변수 (Config)

코드 내 하드코딩은 절대 금지한다. 함수 시작 시점(Cold Start)에 필수 환경 변수를 검사하고, 누락 시 에러 로그 출력 후 조기 종료(Fail-fast)한다.

| 환경 변수 | 설명 | 필수 | 기본값 |
|-----------|------|------|--------|
| `QUEUE_SERVICE_TYPE` | 메시지 브로커 타입 (EVENT_GRID, AWS_SNS 등) | Y | - |
| `NOTIFICATION_EMAIL_PROVIDER` | 이메일 프로바이더 (sendgrid 등) | Y | - |
| `NOTIFICATION_SMS_PROVIDER` | SMS 프로바이더 (twilio 등) | Y | - |
| `WEBHOOK_URL` | Webhook Endpoint URL | Y | - |
| `COSMOS_DB_ENDPOINT` | Cosmos DB Endpoint | Y | - |
| `COSMOS_DB_KEY` | Cosmos DB Key | Y | - |
| `COSMOS_DB_DATABASE` | Cosmos DB Database 이름 | Y | - |
| `CB_FAILURE_THRESHOLD` | Circuit Breaker 실패 임계치 | N | 5 |
| `CB_COOLDOWN_MS` | Circuit Breaker 쿨다운 시간(ms) | N | 30000 |
| `CB_SUCCESS_THRESHOLD` | Circuit Breaker Half-Open 성공 임계치 | N | 2 |
| `MAX_RETRY_COUNT` | 최대 재시도 횟수 | N | 3 |
| `RETRY_BASE_DELAY_MS` | 재시도 기본 대기 시간(ms) | N | 1000 |
| `RETRY_BACKOFF_MULTIPLIER` | 지수 백오프 배수 | N | 2 |
| `RATE_LIMIT_EMAIL_PER_SEC` | 이메일 초당 최대 발송 수 | N | 10 |
| `RATE_LIMIT_SMS_PER_SEC` | SMS 초당 최대 발송 수 | N | 5 |
| `RATE_LIMIT_WEBHOOK_PER_SEC` | Webhook 초당 최대 발송 수 | N | 20 |
| `RATE_LIMIT_MAX_WAIT_MS` | Rate limit 토큰 대기 최대 시간(ms) | N | 10000 |
| `MOCK_DELAY_MIN_MS` | Mock 발송 최소 딜레이(ms) | N | 100 |
| `MOCK_DELAY_MAX_MS` | Mock 발송 최대 딜레이(ms) | N | 500 |

**Acceptance Criteria:**

- [ ] 필수 환경 변수가 하나라도 누락되면 함수가 시작되지 않고 에러 로그를 출력한다
- [ ] 선택 환경 변수가 누락되면 기본값이 적용된다
- [ ] 코드 내에 하드코딩된 설정값이 없다

---

## 12. Azure Functions 구성

| Function 이름 | 트리거 | 역할 |
|---------------|--------|------|
| `event-api` | HTTP Trigger | POST /events, GET /events/:event_id, GET /events 처리 |
| `dlq-api` | HTTP Trigger | GET /dlq, POST /dlq/:id/replay, POST /dlq/replay-batch 처리 |
| `outbox-publisher` | Cosmos DB Change Feed Trigger | Outbox 패턴 - pending 문서 감지 후 Event Grid 발행 |
| `outbox-retry` | Timer Trigger (1분 간격) | failed_publish 상태 문서를 pending으로 재갱신 |
| `event-consumer` | Event Grid Trigger | 이벤트 수신 후 채널별 알림 발송 처리 |

---

## 13. 테스트 전략

### 13.1. 단위 테스트

- Circuit Breaker 상태 머신 전이 로직
- Token Bucket Rate Limiter 토큰 계산 로직
- 지수 백오프 딜레이 계산 로직
- 입력 검증 로직
- Idempotency 판정 로직
- 이벤트 status 결정 로직 (completed / partially_completed / failed)

### 13.2. 통합 테스트

- POST /events → Cosmos DB 저장 → Change Feed → Event Grid 발행 흐름
- Event Consumer → 채널별 발송 → 결과 기록 흐름
- 재시도 → DLQ 이동 흐름
- DLQ Replay 흐름
- 중복 요청 처리 (Idempotency) 흐름

**Acceptance Criteria:**

- [ ] 모든 단위 테스트가 외부 의존성 없이 실행 가능하다
- [ ] 통합 테스트는 Cosmos DB Emulator를 사용하여 로컬에서 실행 가능하다
- [ ] `pytest`로 전체 테스트를 실행할 수 있다

---

## 14. 아키텍처 흐름 요약

```
Client
  │
  ▼
[POST /events] ── 입력 검증 ── Idempotency 확인 ──→ Cosmos DB 저장 (_outbox_status: pending)
  │                                                      │
  ▼                                                      ▼
즉시 응답 (201)                                  [Change Feed Trigger]
                                                     │
                                                     ▼
                                              outbox-publisher
                                              (pending만 필터링)
                                                     │
                                              ┌──────┴───────┐
                                              ▼              ▼
                                          발행 성공       발행 실패
                                       (→ published)   (→ failed_publish)
                                              │              │
                                              ▼              ▼
                                     Event Grid 발행    [outbox-retry]
                                              │         (Timer 1분)
                                              │         (→ pending 복원)
                                              ▼
                                      [event-consumer]
                                              │
                                 ┌────────────┼────────────┐
                                 ▼            ▼            ▼
                              [Email]      [SMS]      [Webhook]
                                 │            │            │
                           ┌─────────────────────────────────┐
                           │  1. Idempotency 확인 (skip if done)  │
                           │  2. Circuit Breaker 확인              │
                           │  3. Rate Limiter 확인                 │
                           │  4. NotificationStrategy.send()       │
                           └─────────────────────────────────┘
                                 │            │            │
                           성공/실패 판정
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
                성공 기록   재시도        Circuit Open
                              (지수 백오프)    즉시 실패
                                 │
                           ┌─────┴──────┐
                           ▼            ▼
                      재시도 성공    MAX 초과
                                       │
                                       ▼
                                   DLQ 저장
                                       │
                              ┌────────┴────────┐
                              ▼                 ▼
                       [GET /dlq] 조회   [POST /dlq/:id/replay]
                                                │
                                                ▼
                                        Outbox 통해 재발행
```
