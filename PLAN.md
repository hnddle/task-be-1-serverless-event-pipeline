# Implementation Plan

## Overview
- Total Phases: 7 (Phase 0–6)
- Total Steps: 20
- Estimated scope: 치과 보험 청구 시스템의 이벤트 기반 알림 파이프라인 — Azure Functions v4 (Python) + Cosmos DB + Event Grid 기반 Serverless 아키텍처

## 디렉토리 구조

```
/
├── function_app.py                   # Azure Functions v2 모델 진입점 (Blueprint 등록)
├── src/
│   ├── __init__.py
│   ├── functions/                    # Azure Functions Blueprint 모듈
│   │   ├── __init__.py
│   │   ├── event_api.py              # HTTP: POST /events, GET /events, GET /events/:id
│   │   ├── dlq_api.py                # HTTP: GET /dlq, POST /dlq/:id/replay, POST /dlq/replay-batch
│   │   ├── outbox_publisher.py       # Cosmos DB Change Feed Trigger
│   │   ├── outbox_retry.py           # Timer Trigger (1분 간격)
│   │   └── event_consumer.py         # Event Grid Trigger
│   ├── services/
│   │   ├── __init__.py
│   │   ├── cosmos_client.py          # Cosmos DB 클라이언트 싱글턴 + 컨테이너 초기화
│   │   ├── message_broker/
│   │   │   ├── __init__.py
│   │   │   ├── message_broker.py     # MessageBroker ABC (인터페이스)
│   │   │   ├── message_broker_factory.py
│   │   │   └── event_grid_adapter.py
│   │   ├── notification/
│   │   │   ├── __init__.py
│   │   │   ├── notification_strategy.py  # NotificationStrategy ABC (인터페이스)
│   │   │   ├── notification_factory.py
│   │   │   ├── email_strategy.py
│   │   │   ├── sms_strategy.py
│   │   │   └── webhook_strategy.py
│   │   ├── circuit_breaker.py
│   │   ├── rate_limiter.py
│   │   ├── retry_service.py
│   │   └── dlq_service.py
│   ├── shared/
│   │   ├── __init__.py
│   │   ├── config.py                 # pydantic-settings 기반 환경 변수 로드 + Fail-fast 검증
│   │   ├── logger.py                 # 구조화 JSON 로거
│   │   ├── validator.py              # Pydantic 입력 검증
│   │   ├── correlation.py            # contextvars 기반 Correlation ID 컨텍스트 관리
│   │   └── errors.py                 # 공통 에러 타입
│   └── models/
│       ├── __init__.py
│       ├── events.py                 # NotificationEvent Pydantic 모델
│       ├── dlq.py                    # DLQ Pydantic 모델
│       ├── circuit_breaker.py        # Circuit Breaker 상태 모델
│       └── rate_limiter.py           # Rate Limiter 상태 모델
├── tests/
│   ├── __init__.py
│   ├── conftest.py                   # pytest fixtures (Cosmos DB Emulator 등)
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_config.py
│   │   ├── test_validator.py
│   │   ├── test_logger.py
│   │   ├── test_circuit_breaker.py
│   │   ├── test_rate_limiter.py
│   │   ├── test_retry.py
│   │   ├── test_notification_factory.py
│   │   ├── test_message_broker_factory.py
│   │   └── test_event_status.py
│   └── integration/
│       ├── __init__.py
│       ├── test_event_api.py
│       ├── test_outbox_flow.py
│       ├── test_consumer_flow.py
│       ├── test_dlq_flow.py
│       └── test_replay_flow.py
├── host.json
├── local.settings.json               # .gitignore 대상
├── local.settings.sample.json        # 커밋 대상 — 환경 변수 템플릿
├── requirements.txt                  # 프로덕션 의존성
├── requirements-dev.txt              # 개발 의존성 (pytest, ruff, mypy)
├── pyproject.toml                    # ruff, mypy, pytest 설정
├── .python-version                   # Python 버전 고정 (3.11)
├── .gitignore
├── SPEC.md
├── PLAN.md
└── CLAUDE.md
```

---

## Phase 0: 프로젝트 초기화 및 인프라

프로젝트 뼈대, 테스트/린트/타입체크 환경, Azure Functions 기본 구성을 세팅한다.

### Step 0-1: 프로젝트 스캐폴딩 및 빌드 환경
**Objective:** Python 3.11 + Azure Functions v4 (Python v2 programming model) 프로젝트 초기화.
**Feature Branch:** `feature/step-0-1-project-scaffold`
**Files to Create/Modify:**
- `requirements.txt` — 프로덕션 의존성 (azure-functions, azure-cosmos, azure-eventgrid, pydantic, pydantic-settings)
- `requirements-dev.txt` — 개발 의존성 (pytest, pytest-asyncio, ruff, mypy)
- `pyproject.toml` — ruff, mypy, pytest 통합 설정
- `.python-version` — `3.11`
- `host.json` — Azure Functions 호스트 설정
- `local.settings.sample.json` — 로컬 개발용 환경 변수 템플릿 (SPEC §11 전체 변수 + placeholder)
- `function_app.py` — Azure Functions v2 모델 진입점 (빈 Blueprint 등록)
- `.gitignore` — `__pycache__`, `.venv`, `local.settings.json`, `.mypy_cache` 등 제외
- `src/__init__.py`, `src/functions/__init__.py` 등 — 패키지 초기화
**Dependencies:** None
**Implementation Details:**
- Azure Functions Python v2 programming model 사용 (`azure.functions` v4)
- `azure-cosmos`, `azure-eventgrid`, `azure-identity` SDK 설치
- mypy strict mode 설정 (`pyproject.toml`에서 `strict = true`)
- ruff로 lint + format 통합 (line-length 120, isort 포함)
- pytest 설정: `tests/` 디렉토리, asyncio_mode = "auto"
- `local.settings.sample.json`에 SPEC §11의 모든 환경 변수를 placeholder 값과 함께 기록
- `local.settings.json`은 `.gitignore`에 포함
**Acceptance Criteria:**
- [x] `pip install -r requirements.txt -r requirements-dev.txt` 성공
- [x] `pytest` 성공 (테스트 0개, 에러 없음)
- [x] `ruff check .` 성공
- [x] `mypy src/` 성공
- [x] `local.settings.sample.json`에 SPEC §11 전체 환경 변수가 포함됨

### Step 0-2: 공통 모델 정의 및 환경 변수 설정
**Objective:** 전체 시스템에서 사용하는 Pydantic 모델과 환경 변수 로드/검증 모듈 구현.
**Feature Branch:** `feature/step-0-2-models-and-config`
**Files to Create/Modify:**
- `src/models/events.py` — NotificationEvent, NotificationChannel, EventStatus 등 Pydantic 모델
- `src/models/dlq.py` — DLQ 문서 Pydantic 모델
- `src/models/circuit_breaker.py` — Circuit Breaker 상태 모델
- `src/models/rate_limiter.py` — Rate Limiter 상태 모델
- `src/shared/config.py` — pydantic-settings 기반 환경 변수 로드, 필수 변수 Fail-fast 검증, 기본값 적용
- `src/shared/errors.py` — 공통 예외 클래스 (ValidationError, NotFoundError, ConflictError)
- `tests/unit/test_config.py` — 환경 변수 로드/검증 테스트
**Dependencies:** Step 0-1
**Implementation Details:**
- SPEC.md §3 (데이터 모델) 및 §11 (환경 변수) 참조
- pydantic-settings의 `BaseSettings`로 환경 변수 로드 — 필수 변수 누락 시 `ValidationError` → 에러 로그 출력 후 `sys.exit(1)` (Fail-fast)
- 선택 환경 변수는 Pydantic Field(default=...) 로 기본값 적용
- Pydantic 모델은 Cosmos DB 문서 구조와 1:1 대응
- `NOTIFICATION_EMAIL_PROVIDER`, `NOTIFICATION_SMS_PROVIDER` 환경 변수가 notifications[].provider 필드에 매핑됨을 docstring으로 명시
**Acceptance Criteria:**
- [x] 모든 SPEC.md 데이터 모델이 Pydantic 모델로 정의됨
- [x] 필수 환경 변수 누락 시 명확한 에러 메시지와 함께 프로세스 종료
- [x] 선택 환경 변수 누락 시 기본값 적용 확인
- [x] Tests pass

### Step 0-3: 구조화 로거 및 Correlation ID 컨텍스트
**Objective:** JSON 구조화 로깅과 Correlation ID 전파 메커니즘 구현.
**Feature Branch:** `feature/step-0-3-logger-and-correlation`
**Files to Create/Modify:**
- `src/shared/logger.py` — 구조화 JSON 로거 (stdout 출력, `logging` 모듈 기반, correlation_id 자동 포함)
- `src/shared/correlation.py` — `contextvars` 기반 Correlation ID 컨텍스트 관리
- `tests/unit/test_logger.py` — 로거 출력 형식 및 correlation_id 포함 검증
**Dependencies:** Step 0-2
**Implementation Details:**
- SPEC.md §10 (분산 트레이싱 및 구조화 로깅) 참조
- Python `contextvars.ContextVar`를 사용하여 함수 실행 컨텍스트에 correlation_id 바인딩
- `logging` 모듈에 JSON Formatter 커스텀 구현
- 로그 형식: `{ timestamp, level, correlation_id, message, ...contextFields }`
- 파일 로깅 금지 — stdout/stderr만 사용 (12-Factor XI: Logs)
- Application Insights SDK (`opencensus-ext-azure`) 연동 (`correlation_id` → `operation_id` 매핑)
**Acceptance Criteria:**
- [x] 로그가 JSON 형식으로 stdout에 출력됨
- [x] correlation_id가 설정된 컨텍스트 내 모든 로그에 자동 포함됨
- [x] Application Insights operation_id 매핑 구현
- [x] Tests pass

---

## Phase 1: 데이터 계층 및 서비스 인터페이스

Cosmos DB 클라이언트, 입력 검증, Message Broker 추상화, Notification Strategy를 구현한다.
이 Phase의 Step들은 Phase 0 완료 후 **병렬 진행 가능**하다.

### Step 1-1: Cosmos DB 클라이언트 및 컨테이너 초기화
**Objective:** Cosmos DB 연결 싱글턴, 5개 컨테이너 접근 모듈, 컨테이너 자동 생성 유틸 구현.
**Feature Branch:** `feature/step-1-1-cosmos-client`
**Files to Create/Modify:**
- `src/services/cosmos_client.py` — Cosmos DB 클라이언트 싱글턴, 컨테이너 참조 제공, `init_containers()` 함수
**Dependencies:** Step 0-2
**Implementation Details:**
- SPEC.md §3.5 (Cosmos DB 구성) 참조
- 5개 컨테이너: `events`, `dead-letter-queue`, `circuit-breaker`, `rate-limiter`, `leases`
- Partition Key 설정: events(`/clinic_id`), dlq(`/clinic_id`), cb(`/id`), rl(`/id`)
- `rate-limiter` 컨테이너 TTL: 60초
- Session consistency level
- `events` 컨테이너에 복합 인덱스 추가: `status`, `event_type`, `created_at` (SPEC §3.5)
- `init_containers()`: 로컬 개발/Emulator 환경에서 컨테이너가 없으면 자동 생성하는 유틸리티 함수
- `azure-cosmos` Python SDK 사용 (비동기: `aio` 모듈)
**Acceptance Criteria:**
- [x] Cosmos DB 클라이언트가 싱글턴으로 생성됨
- [x] 5개 컨테이너에 대한 참조를 제공하는 함수 존재
- [x] `events` 컨테이너에 `status`, `event_type`, `created_at` 복합 인덱스가 설정됨
- [x] `init_containers()` 호출 시 누락된 컨테이너를 올바른 Partition Key/TTL로 생성
- [x] 환경 변수 기반으로 연결 설정됨

### Step 1-2: 입력 검증 모듈
**Objective:** POST /events 요청 바디 검증 로직 구현.
**Feature Branch:** `feature/step-1-2-validator`
**Files to Create/Modify:**
- `src/shared/validator.py` — Pydantic 기반 이벤트 입력 검증 (UUID v4, event_type enum, channels 배열 등)
- `tests/unit/test_validator.py` — 검증 로직 단위 테스트
**Dependencies:** Step 0-2
**Implementation Details:**
- SPEC.md §8.1 입력 검증 규칙 참조
- Pydantic `BaseModel`로 요청 스키마 정의 + `field_validator` 사용
- `id`: UUID v4 형식 검증
- `event_type`: `Literal["appointment_confirmed", "insurance_approved", "claim_completed"]`
- `clinic_id`, `patient_id`: 비어 있지 않은 문자열 (`min_length=1`)
- `channels`: 1개 이상 배열, `Literal["email", "sms", "webhook"]`만 허용, 중복 불가
- 에러 응답 형식: `{ error: "VALIDATION_ERROR", message, details: [{ field, message }] }` (SPEC §8.4)
**Acceptance Criteria:**
- [x] 유효한 요청은 통과
- [x] 각 필드별 검증 실패 시 해당 필드명과 메시지가 details에 포함됨
- [x] channels 중복 시 에러
- [x] 지원하지 않는 event_type 시 에러
- [x] Tests pass

### Step 1-3: Message Broker 추상화 (Adapter + Factory)
**Objective:** Message Broker 인터페이스, Event Grid 어댑터, 팩토리 구현.
**Feature Branch:** `feature/step-1-3-message-broker`
**Files to Create/Modify:**
- `src/services/message_broker/message_broker.py` — `MessageBroker` ABC (인터페이스)
- `src/services/message_broker/event_grid_adapter.py` — Event Grid SDK 래핑 어댑터
- `src/services/message_broker/message_broker_factory.py` — `QUEUE_SERVICE_TYPE` 기반 팩토리
- `tests/unit/test_message_broker_factory.py` — 팩토리 및 어댑터 테스트
**Dependencies:** Step 0-2
**Implementation Details:**
- SPEC.md §4.1 (Adapter + Factory 패턴) 참조
- `MessageBroker` ABC: `async publish(event) -> None`, `get_broker_name() -> str`
- `MessageBrokerFactory.create()`: 환경 변수 `QUEUE_SERVICE_TYPE`에 따라 어댑터 반환
- 지원하지 않는 타입 → `ValueError` raise
- Event Grid 어댑터: `azure-eventgrid` Python SDK 사용
**Acceptance Criteria:**
- [x] `QUEUE_SERVICE_TYPE=EVENT_GRID` → EventGridAdapter 인스턴스 반환
- [x] 지원하지 않는 타입 → ValueError raise
- [x] `get_broker_name()` 정확히 반환
- [x] 어댑터가 MessageBroker ABC를 준수
- [x] Tests pass

### Step 1-4: Notification Strategy (Mock 발송)
**Objective:** 채널별 알림 전략 인터페이스와 Mock 구현체 구현.
**Feature Branch:** `feature/step-1-4-notification-strategy`
**Files to Create/Modify:**
- `src/services/notification/notification_strategy.py` — `NotificationStrategy` ABC
- `src/services/notification/notification_factory.py` — 채널 → Strategy 매핑 팩토리
- `src/services/notification/email_strategy.py` — Email Mock 발송 (랜덤 딜레이)
- `src/services/notification/sms_strategy.py` — SMS Mock 발송
- `src/services/notification/webhook_strategy.py` — Webhook Mock 발송
- `tests/unit/test_notification_factory.py` — 팩토리 및 Strategy 테스트
**Dependencies:** Step 0-2, Step 0-3
**Implementation Details:**
- SPEC.md §4.2 (Strategy 패턴) 참조
- `NotificationStrategy.send(notification) -> NotificationResult` (async)
- Mock: `asyncio.sleep()` — `MOCK_DELAY_MIN_MS` ~ `MOCK_DELAY_MAX_MS` 범위 랜덤 딜레이 후 성공 반환
- 결과를 구조화 로그로 기록
- 지원하지 않는 채널 → `failed` 처리 + 에러 로그
- provider 필드는 `NOTIFICATION_EMAIL_PROVIDER`, `NOTIFICATION_SMS_PROVIDER` 환경 변수에서 결정 (webhook은 고정 `"webhook"`)
**Acceptance Criteria:**
- [x] 3개 채널 전달 시 3개 Strategy 각각 실행
- [x] 지원하지 않는 채널 → failed 처리 + 에러 로그
- [x] Mock 딜레이가 환경 변수 범위 내
- [x] Mock 결과가 구조화 로그로 출력
- [x] Tests pass

---

## Phase 2: 이벤트 API 및 Outbox 패턴

### Step 2-1: Event API — 이벤트 수신, 저장, 조회
**Objective:** POST /events (Cosmos DB 저장 + Idempotency) 및 GET /events, GET /events/:id 구현.
**Feature Branch:** `feature/step-2-1-event-api`
**Files to Create/Modify:**
- `src/functions/event_api.py` — Blueprint: POST /events, GET /events/{event_id}, GET /events
- `function_app.py` — event_api Blueprint 등록
- `tests/unit/test_event_status.py` — 이벤트 status 결정 로직 테스트
**Dependencies:** Step 1-1, Step 1-2, Step 0-3
**Implementation Details:**
- SPEC.md §7 (Idempotency), §8.1 (이벤트 발행 API), §8.2 (조회 API) 참조
- **POST /events 흐름:** Pydantic 입력 검증 → correlation_id 생성 → Cosmos DB 저장 시도
  - 저장 시 `status: "queued"`, `_outbox_status: "pending"` 초기화
  - `notifications[]` 배열을 channels 기반으로 초기 생성 (`status: "pending"`, `provider` 환경 변수에서 결정)
  - 409 Conflict 발생 시 기존 문서 조회 후 200 반환
  - 저장 성공 시 201 반환
  - Message Broker를 직접 호출하지 않음 (Outbox 패턴)
- **GET /events/{event_id}:** `clinic_id` 쿼리 파라미터 필수 (없으면 400), 문서 없으면 404
- **GET /events:** `clinic_id` 필수, `status`/`event_type` 필터, `continuation_token` 페이지네이션, `page_size` 최대 100 클램핑
**Acceptance Criteria:**
- [x] 유효한 POST 요청 시 201 + `{ event_id, status: "queued", correlation_id }` 반환
- [x] 동일 id 재요청 시 200 + 기존 문서 상태 반환
- [x] 검증 실패 시 400 + 에러 상세 반환
- [x] DB에 `_outbox_status: "pending"`으로 저장됨
- [x] `GET /events/{event_id}` — clinic_id 없으면 400, 문서 없으면 404
- [x] `GET /events` — clinic_id 필수, 페이지네이션 동작, page_size > 100 → 100 클램핑
- [x] Tests pass

### Step 2-2: Outbox Publisher (Change Feed Trigger)
**Objective:** Change Feed 기반 Outbox Publisher Function 구현.
**Feature Branch:** `feature/step-2-2-outbox-publisher`
**Files to Create/Modify:**
- `src/functions/outbox_publisher.py` — Blueprint: Change Feed Trigger, pending 문서 필터링 후 Event Grid 발행
- `function_app.py` — outbox_publisher Blueprint 등록
**Dependencies:** Step 1-3, Step 1-1
**Implementation Details:**
- SPEC.md §4.4 (Transactional Outbox 패턴) 참조
- Change Feed에서 수신된 문서 중 `_outbox_status: "pending"`만 처리
- `"published"` 또는 기타 상태 문서는 무시 (무한 루프 방지)
- 발행 성공 → `_outbox_status: "published"` 갱신
- 발행 실패 → `_outbox_status: "failed_publish"` 갱신 + 에러 로그
- 이벤트의 `id`를 발행 메시지에 포함 (Consumer Idempotency)
- leases 컨테이너를 Change Feed 체크포인트로 사용
**Acceptance Criteria:**
- [x] pending 문서만 처리하고 published 문서는 무시
- [x] 발행 성공 시 published로 갱신
- [x] 발행 실패 시 failed_publish로 갱신
- [x] 무한 루프 없음 (published 갱신에 의한 재트리거 필터링)
- [x] Tests pass

### Step 2-3: Outbox Retry (Timer Trigger)
**Objective:** 발행 실패 문서를 주기적으로 재시도하는 Timer Function 구현.
**Feature Branch:** `feature/step-2-3-outbox-retry`
**Files to Create/Modify:**
- `src/functions/outbox_retry.py` — Blueprint: Timer Trigger (1분 간격), failed_publish → pending 재갱신
- `function_app.py` — outbox_retry Blueprint 등록
**Dependencies:** Step 2-2
**Implementation Details:**
- SPEC.md §4.4 참조
- 1분 간격 Timer Trigger (`schedule="0 */1 * * * *"`)
- `_outbox_status: "failed_publish"` 문서를 쿼리
- `_outbox_status: "pending"`으로 재갱신하여 Change Feed 재발화
- 처리 건수 로그 기록
**Acceptance Criteria:**
- [x] 1분 간격으로 실행됨
- [x] failed_publish 문서를 pending으로 재갱신
- [x] 재갱신 후 Change Feed가 다시 트리거됨
- [x] Tests pass

---

## Phase 3: Event Consumer (기본 흐름)

### Step 3-1: Event Consumer — 채널별 발송 및 상태 갱신
**Objective:** Event Grid 트리거로 이벤트를 수신하여 채널별 알림을 발송하는 Consumer 구현.
**Feature Branch:** `feature/step-3-1-event-consumer`
**Files to Create/Modify:**
- `src/functions/event_consumer.py` — Blueprint: Event Grid Trigger, 채널 순회 + Strategy 호출 + 상태 갱신
- `function_app.py` — event_consumer Blueprint 등록
**Dependencies:** Step 1-4, Step 1-1, Step 0-3
**Implementation Details:**
- SPEC.md §9 (Event Consumer) 참조
- 처리 흐름:
  1. correlation_id 컨텍스트 바인딩 (`contextvars`)
  2. Cosmos DB에서 이벤트 조회 (Idempotency 확인)
  3. status → `"processing"` 갱신
  4. channels 순회: 이미 success인 채널 스킵 → Strategy.send() 호출
  5. 결과 집계: completed / partially_completed / failed 결정
  6. Cosmos DB에 최종 상태 기록
- 이 Step에서는 Circuit Breaker, Rate Limiter, 재시도는 제외 (Phase 4에서 통합)
**Acceptance Criteria:**
- [ ] Event Grid 메시지 수신 시 자동 트리거
- [ ] 이미 success인 채널은 스킵
- [ ] 전체 성공 → completed, 일부 성공 → partially_completed, 전체 실패 → failed
- [ ] 처리 결과가 Cosmos DB에 기록됨
- [ ] Tests pass

---

## Phase 4: 복원력 패턴 — Circuit Breaker, Rate Limiter, 재시도

### Step 4-1: Circuit Breaker 구현
**Objective:** Cosmos DB 기반 Circuit Breaker 상태 머신 구현.
**Feature Branch:** `feature/step-4-1-circuit-breaker`
**Files to Create/Modify:**
- `src/services/circuit_breaker.py` — Circuit Breaker 로직 (상태 전이, ETag 동시성 제어)
- `tests/unit/test_circuit_breaker.py` — 상태 전이 및 동시성 테스트
**Dependencies:** Step 1-1, Step 0-2
**Implementation Details:**
- SPEC.md §4.3 (Circuit Breaker 패턴) 참조
- 상태 머신: Closed → Open → Half-Open → Closed/Open
- `{channel}:{provider}` 조합별 독립 Circuit Breaker
- Cosmos DB `circuit-breaker` 컨테이너에 상태 저장
- ETag 기반 낙관적 동시성 제어 — 412 충돌 시 최신 상태 재읽기 후 재판정
- 환경 변수: `CB_FAILURE_THRESHOLD`, `CB_COOLDOWN_MS`, `CB_SUCCESS_THRESHOLD`
- 상태 변경 시 `from_state`, `to_state` 포함 구조화 로그
**Acceptance Criteria:**
- [ ] 연속 실패 >= CB_FAILURE_THRESHOLD → Open 전환
- [ ] Open 상태에서 CB_COOLDOWN_MS 경과 → Half-Open 전환
- [ ] Half-Open에서 CB_SUCCESS_THRESHOLD 연속 성공 → Closed 복귀
- [ ] Half-Open에서 1회 실패 → Open 재전환
- [ ] Open 상태 요청 → 외부 호출 없이 즉시 실패
- [ ] 상태 변경 시 구조화 로그 출력
- [ ] ETag 충돌 시 안전하게 재시도
- [ ] Tests pass

### Step 4-2: Rate Limiter 구현 (Token Bucket)
**Objective:** Token Bucket 알고리즘 기반 Rate Limiter 구현.
**Feature Branch:** `feature/step-4-2-rate-limiter`
**Files to Create/Modify:**
- `src/services/rate_limiter.py` — Token Bucket 로직 (Cosmos DB 저장, ETag 동시성 제어)
- `tests/unit/test_rate_limiter.py` — 토큰 소비/리필 및 대기 로직 테스트
**Dependencies:** Step 1-1, Step 0-2
**Implementation Details:**
- SPEC.md §5 (Backpressure 제어) 참조
- `{channel}:{provider}` 조합별 독립 Rate Limiter
- Cosmos DB `rate-limiter` 컨테이너 (TTL 60초)
- 토큰 부족 시 `asyncio.sleep()` 지수 백오프로 `RATE_LIMIT_MAX_WAIT_MS` 이내 대기 후 재시도
- 대기 초과 시 실패 처리
- 429 응답 시 Circuit Breaker 실패 카운트에 미포함
- 429의 Retry-After 헤더 준수
- ETag 기반 낙관적 동시성 제어
**Acceptance Criteria:**
- [ ] 초당 발송량이 설정 한도 초과하지 않음
- [ ] 토큰 부족 시 RATE_LIMIT_MAX_WAIT_MS 이내 대기 후 재시도
- [ ] 대기 초과 시 실패 처리
- [ ] 429 → Circuit Breaker 미포함
- [ ] 429 Retry-After 준수
- [ ] ETag 기반 정합성 유지
- [ ] Tests pass

### Step 4-3: 재시도 서비스 (지수 백오프)
**Objective:** 알림 발송 실패 시 지수 백오프 재시도 로직 구현.
**Feature Branch:** `feature/step-4-3-retry-service`
**Files to Create/Modify:**
- `src/services/retry_service.py` — 지수 백오프 재시도 로직
- `tests/unit/test_retry.py` — 딜레이 계산, 최대 재시도 초과 테스트
**Dependencies:** Step 0-2
**Implementation Details:**
- SPEC.md §6.1 (재시도 정책) 참조
- 재시도 간격: `RETRY_BASE_DELAY_MS * (RETRY_BACKOFF_MULTIPLIER ** retry_count)`
- 최대 재시도: `MAX_RETRY_COUNT`
- in-process 재시도 (`asyncio.sleep()` 사용, 별도 큐 없음)
- 각 재시도마다 `retry_count`, `last_error` 갱신
- 재시도 시 Idempotency 확인
**Acceptance Criteria:**
- [ ] MAX_RETRY_COUNT까지 자동 재시도
- [ ] 지수 백오프 간격 정확히 계산
- [ ] 각 재시도마다 retry_count, last_error 갱신
- [ ] 환경 변수 변경 시 재시도 동작 변경
- [ ] Tests pass

### Step 4-4: Event Consumer에 복원력 패턴 통합
**Objective:** Event Consumer에 Circuit Breaker, Rate Limiter, 재시도를 통합하고 SPEC §10.3 필수 로그를 검증.
**Feature Branch:** `feature/step-4-4-consumer-resilience`
**Files to Create/Modify:**
- `src/functions/event_consumer.py` — Circuit Breaker → Rate Limiter → send → 재시도 흐름 통합
**Dependencies:** Step 3-1, Step 4-1, Step 4-2, Step 4-3
**Implementation Details:**
- SPEC.md §9 전체 흐름 참조
- 채널별 처리 순서: Idempotency → Circuit Breaker → Rate Limiter → Strategy.send() → 재시도
- Circuit Open → 즉시 실패 (재시도 없이 DLQ 후보)
- Rate Limit 대기 초과 → 실패 → 재시도 정책으로 넘어감
- 발송 실패 → 재시도 (in-process, 지수 백오프)
- SPEC §10.3 필수 로그 이벤트 13개 중 Consumer 관련 항목을 모두 구현:
  - 채널별 발송 시작/성공/실패 (INFO/INFO/WARN)
  - 재시도 수행 (WARN: event_id, channel, retry_count, next_delay_ms)
  - Circuit Breaker 상태 변경 (WARN: channel, provider, from_state, to_state)
  - Rate limit 도달/대기 (WARN/INFO: channel, provider)
**Acceptance Criteria:**
- [ ] Circuit Breaker Open 채널 → 즉시 실패
- [ ] Rate Limiter 토큰 부족 → 대기 후 재시도
- [ ] 발송 실패 → 지수 백오프 재시도
- [ ] 전체 흐름이 순서대로 동작
- [ ] SPEC §10.3의 Consumer 관련 필수 로그 이벤트가 모두 출력됨
- [ ] Tests pass

---

## Phase 5: Dead Letter Queue 및 Replay

### Step 5-1: DLQ 서비스 및 Consumer 통합
**Objective:** 최대 재시도 초과 시 DLQ 저장, 원본 이벤트 상태 갱신, Consumer에 통합.
**Feature Branch:** `feature/step-5-1-dlq-service`
**Files to Create/Modify:**
- `src/services/dlq_service.py` — DLQ 저장, 원본 이벤트 상태 갱신
- `src/functions/event_consumer.py` — DLQ 서비스 통합 (최대 재시도 초과 시 호출)
**Dependencies:** Step 4-4, Step 1-1
**Implementation Details:**
- SPEC.md §6.2 (Dead Letter Queue) 참조
- DLQ 문서: original_event_id, clinic_id, channel, provider, payload(원본 전체), failure_reason, retry_count, correlation_id
- DLQ 저장 후 원본 문서의 해당 채널 `notifications[].status` → `"failed"`
- 이벤트 최종 status 결정: completed / partially_completed / failed
- DLQ 이동 시 구조화 로그 출력 (SPEC §10.3: ERROR — event_id, channel, failure_reason, total_retry_count)
**Acceptance Criteria:**
- [ ] MAX_RETRY_COUNT 초과 → DLQ 컨테이너에 저장
- [ ] DLQ 문서에 원본 페이로드, 실패 사유, 재시도 횟수, correlation_id 포함
- [ ] DLQ 이동 후 원본 채널 status → failed
- [ ] 2/3 성공, 1/3 실패 → partially_completed
- [ ] 전체 실패 → failed
- [ ] Tests pass

### Step 5-2: DLQ API — 조회 및 Replay
**Objective:** DLQ 조회, 단건 Replay, 배치 Replay API 구현.
**Feature Branch:** `feature/step-5-2-dlq-api`
**Files to Create/Modify:**
- `src/functions/dlq_api.py` — Blueprint: GET /dlq, POST /dlq/{dlq_id}/replay, POST /dlq/replay-batch
- `function_app.py` — dlq_api Blueprint 등록
**Dependencies:** Step 5-1, Step 2-2
**Implementation Details:**
- SPEC.md §6.3 (Replay 프로세스) 참조
- **GET /dlq:**
  - `clinic_id` 필수 (없으면 400)
  - 선택 필터: `replay_status`, `event_type`, `date_from`, `date_to`
  - 페이지네이션: `continuation_token`, `page_size` (기본 20, 최대 100)
  - 응답: `{ items, continuation_token, total_count }`
- **POST /dlq/{dlq_id}/replay:**
  - `replay_status` → `"replayed"`, `replayed_at` 기록
  - 새 `correlation_id` 발급, 원본 `correlation_id` 로그 기록
  - 원본 `payload` 기반 Outbox 패턴으로 재발행
  - 이미 replayed → 409
- **POST /dlq/replay-batch:**
  - `clinic_id` 필수, `event_type`/`date_from`/`date_to` 선택
  - `max_count` 기본 100, 최대 500 클램핑
  - 응답: `{ replayed_count, failed_count, skipped_count }`
- Replay 구조화 로그 (SPEC §10.3: INFO — dlq_id, original_event_id, original_correlation_id, new_correlation_id)
**Acceptance Criteria:**
- [ ] `GET /dlq` — clinic_id 없으면 400, 필터/페이지네이션 동작
- [ ] 단건 replay 시 Outbox 패턴으로 재발행
- [ ] 이미 replayed → 409
- [ ] 새 correlation_id 발급 + 원본 correlation_id 로그 기록
- [ ] 배치 replay에서 max_count > 500 → 500 클램핑
- [ ] 배치 결과 카운트 정확
- [ ] Tests pass

---

## Phase 6: 통합 테스트

### Step 6-1: Event API 통합 테스트
**Objective:** POST /events → Cosmos DB 저장 → 중복 처리 → 조회 흐름 통합 테스트.
**Feature Branch:** `feature/step-6-1-event-api-integration`
**Files to Create/Modify:**
- `tests/integration/test_event_api.py` — 이벤트 생성, 중복 처리, 조회 통합 테스트
**Dependencies:** Step 2-1
**Implementation Details:**
- SPEC.md §13.2 통합 테스트 참조
- Cosmos DB Emulator 사용, `conftest.py`에서 fixture 제공
- POST → 201, 중복 POST → 200, GET 조회 검증
**Acceptance Criteria:**
- [ ] POST /events → 201 + DB 저장 확인
- [ ] 중복 POST → 200 + 기존 상태 반환
- [ ] GET /events/{event_id} → 상세 조회 확인
- [ ] GET /events → 목록 조회 + 페이지네이션 확인
- [ ] Tests pass

### Step 6-2: Outbox 흐름 통합 테스트
**Objective:** POST → Change Feed → Event Grid 발행 흐름 통합 테스트.
**Feature Branch:** `feature/step-6-2-outbox-integration`
**Files to Create/Modify:**
- `tests/integration/test_outbox_flow.py` — Outbox 발행 + 재시도 흐름 테스트
**Dependencies:** Step 2-3
**Implementation Details:**
- Change Feed → outbox_publisher → Event Grid 발행 확인
- 발행 실패 → failed_publish → outbox_retry → pending 복원 확인
**Acceptance Criteria:**
- [ ] pending 문서가 Event Grid로 발행됨
- [ ] 발행 실패 → failed_publish → retry 후 재발행
- [ ] Tests pass

### Step 6-3: Consumer + DLQ + Replay 흐름 통합 테스트
**Objective:** Consumer 전체 흐름 + DLQ + Replay 통합 테스트.
**Feature Branch:** `feature/step-6-3-consumer-dlq-integration`
**Files to Create/Modify:**
- `tests/integration/test_consumer_flow.py` — Consumer 채널별 발송 + 상태 갱신 테스트
- `tests/integration/test_dlq_flow.py` — 재시도 → DLQ 이동 흐름 테스트
- `tests/integration/test_replay_flow.py` — DLQ Replay → 재발행 흐름 테스트
**Dependencies:** Step 5-2
**Implementation Details:**
- SPEC.md §13.2 통합 테스트 참조
- Consumer: 정상 발송 → completed, 일부 실패 → partially_completed
- DLQ: 최대 재시도 초과 → DLQ 저장 확인
- Replay: DLQ replay → Outbox 재발행 → Consumer 재처리 확인
**Acceptance Criteria:**
- [ ] Consumer 정상 흐름 → completed 상태
- [ ] 일부 채널 실패 → partially_completed + DLQ 저장
- [ ] DLQ replay → 재발행 → 재처리 성공
- [ ] 중복 replay → 409
- [ ] Tests pass

---

## Step 의존성 테이블

| Step | 의존 대상 | 비고 |
|------|-----------|------|
| 0-1 | — | 최초 시작점 |
| 0-2 | 0-1 | |
| 0-3 | 0-2 | |
| 1-1 | 0-2 | Phase 1 내 병렬 가능 |
| 1-2 | 0-2 | Phase 1 내 병렬 가능 |
| 1-3 | 0-2 | Phase 1 내 병렬 가능 |
| 1-4 | 0-2, 0-3 | Phase 1 내 병렬 가능 (0-3 완료 후) |
| 2-1 | 1-1, 1-2, 0-3 | Event API (POST + GET 통합) |
| 2-2 | 1-3, 1-1 | Outbox Publisher |
| 2-3 | 2-2 | Outbox Retry |
| 3-1 | 1-4, 1-1, 0-3 | Consumer 기본 흐름 |
| 4-1 | 1-1, 0-2 | Phase 4 내 4-1/4-2/4-3 병렬 가능 |
| 4-2 | 1-1, 0-2 | Phase 4 내 4-1/4-2/4-3 병렬 가능 |
| 4-3 | 0-2 | Phase 4 내 4-1/4-2/4-3 병렬 가능 |
| 4-4 | 3-1, 4-1, 4-2, 4-3 | Consumer에 복원력 통합 |
| 5-1 | 4-4, 1-1 | DLQ 서비스 + Consumer 통합 |
| 5-2 | 5-1, 2-2 | DLQ API (조회 + Replay 통합) |
| 6-1 | 2-1 | 통합 테스트 |
| 6-2 | 2-3 | 통합 테스트 |
| 6-3 | 5-2 | 통합 테스트 |

### Critical Path

```
0-1 → 0-2 → 0-3 → 1-4 → 3-1 → 4-4 → 5-1 → 5-2 → 6-3
                 ↘ 1-1 ↗        ↑
                   1-2 → 2-1     │
                   1-3 → 2-2     │
                         4-1 ────┘
                         4-2 ────┘
                         4-3 ────┘
```
