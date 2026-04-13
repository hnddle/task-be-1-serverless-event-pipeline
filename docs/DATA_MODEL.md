# Data Model

Cosmos DB (NoSQL API) 기반. Database: `notification-pipeline`

---

## Container Overview

| Container | Partition Key | TTL | Description |
|-----------|--------------|-----|-------------|
| `events` | `/clinic_id` | OFF | 알림 이벤트. Transactional Outbox 포함 |
| `dead-letter-queue` | `/clinic_id` | OFF | 최대 재시도 초과 실패 메시지 |
| `circuit-breaker` | `/id` | OFF | 채널:프로바이더별 Circuit Breaker 상태 |
| `rate-limiter` | `/id` | 60s | Token Bucket Rate Limiter 상태 |
| `leases` | `/id` | - | Change Feed Processor 체크포인트 (런타임 관리) |
| `logs` | `/correlation_id` | 7일 | 구조화 JSON 로그 저장. Application Insights 연동 |

---

## events

알림 이벤트의 전체 라이프사이클을 관리한다. 채널별 발송 결과를 `notifications` 배열로 임베딩하여, 단일 문서 조회로 전체 상태를 확인할 수 있다.

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "clinic_id": "CLINIC_123",
  "status": "completed",
  "event_type": "appointment_confirmed",
  "patient_id": "PATIENT_456",
  "channels": ["email", "sms", "webhook"],
  "correlation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
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
  "updated_at": "2026-04-13T15:24:16Z",
  "_outbox_status": "published"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string (UUID v4) | 클라이언트 생성. Idempotency Key 겸용 |
| `clinic_id` | string | **Partition Key**. 병원 식별자 |
| `status` | enum | `queued` → `processing` → `completed` / `partially_completed` / `failed` |
| `event_type` | enum | `appointment_confirmed` \| `insurance_approved` \| `claim_completed` |
| `patient_id` | string | 환자 식별자 |
| `channels` | string[] | 요청된 알림 채널 목록 |
| `correlation_id` | string (UUID v4) | 서버 생성. 분산 트레이싱 ID |
| `notifications` | array | 채널별 발송 결과 (아래 참조) |
| `created_at` | string (ISO 8601) | 생성 시각 |
| `updated_at` | string (ISO 8601) | 최종 수정 시각 |
| `_outbox_status` | enum | `pending` → `published` / `failed_publish`. Outbox 패턴 내부 필드 |

### notifications[] (embedded)

| Field | Type | Description |
|-------|------|-------------|
| `channel` | string | `email` \| `sms` \| `webhook` |
| `provider` | string | 사용된 프로바이더 (`sendgrid`, `twilio`, `webhook`) |
| `status` | enum | `pending` → `success` / `failed` |
| `sent_at` | string \| null | 발송 성공 시각 |
| `retry_count` | number | 재시도 횟수 |
| `last_error` | string \| null | 마지막 실패 원인 |

### Status Lifecycle

```
queued → processing → completed           (전체 채널 성공)
                    → partially_completed  (일부 성공, 일부 실패)
                    → failed               (전체 채널 실패)
```

---

## dead-letter-queue

최대 재시도 초과 후 격리된 실패 메시지. 원본 이벤트 스냅샷을 포함하여 재처리 시 원본 데이터를 그대로 사용한다.

```json
{
  "id": "dlq-uuid-v4",
  "original_event_id": "550e8400-e29b-41d4-a716-446655440000",
  "clinic_id": "CLINIC_123",
  "channel": "sms",
  "provider": "twilio",
  "event_type": "appointment_confirmed",
  "patient_id": "PATIENT_456",
  "payload": { },
  "failure_reason": "Provider timeout after 3 retries",
  "retry_count": 3,
  "correlation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "created_at": "2026-04-13T15:25:00Z",
  "replay_status": "pending",
  "replayed_at": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string (UUID v4) | DLQ 문서 고유 ID. 서버 생성 |
| `original_event_id` | string | 원본 이벤트 ID |
| `clinic_id` | string | **Partition Key**. 원본 이벤트의 clinic_id |
| `channel` | string | 실패한 채널 |
| `provider` | string | 실패한 프로바이더 |
| `event_type` | string | 원본 이벤트 타입 |
| `patient_id` | string | 원본 환자 ID |
| `payload` | object | 원본 이벤트 전체 스냅샷 |
| `failure_reason` | string | 최종 실패 사유 |
| `retry_count` | number | 재시도한 총 횟수 |
| `correlation_id` | string | 원본 correlation ID |
| `created_at` | string (ISO 8601) | DLQ 저장 시각 |
| `replay_status` | enum | `pending` → `replayed` / `permanently_failed` |
| `replayed_at` | string \| null | 재처리 시각 |

---

## circuit-breaker

`{channel}:{provider}` 조합별 독립 운용. ETag 기반 낙관적 동시성 제어.

```json
{
  "id": "email:sendgrid",
  "state": "closed",
  "failure_count": 0,
  "success_count": 0,
  "last_failure_at": null,
  "opened_at": null,
  "updated_at": "2026-04-13T15:24:00Z",
  "_etag": "\"0000abcd-0000-0000-0000-000000000000\""
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | **Partition Key**. `{channel}:{provider}` 형식 |
| `state` | enum | `closed` → `open` → `half-open` → `closed` |
| `failure_count` | number | 연속 실패 횟수 |
| `success_count` | number | Half-Open 상태에서의 연속 성공 횟수 |
| `last_failure_at` | string \| null | 마지막 실패 시각 |
| `opened_at` | string \| null | OPEN 전환 시각. 쿨다운 계산 기준 |
| `updated_at` | string (ISO 8601) | 최종 수정 시각 |
| `_etag` | string | Cosmos DB ETag. 동시성 제어 |

### State Machine

```
CLOSED ──(failure_count >= CB_FAILURE_THRESHOLD)──> OPEN
OPEN   ──(now - opened_at >= CB_COOLDOWN_MS)──────> HALF-OPEN
HALF-OPEN ──(success_count >= CB_SUCCESS_THRESHOLD)──> CLOSED
HALF-OPEN ──(1회 실패)──> OPEN
```

---

## rate-limiter

Token Bucket 알고리즘. TTL 60초로 자동 만료/리셋. ETag 기반 낙관적 동시성 제어.

```json
{
  "id": "email:sendgrid",
  "tokens": 10,
  "max_tokens": 10,
  "refill_rate": 10,
  "last_refill_at": "2026-04-13T15:24:00Z",
  "updated_at": "2026-04-13T15:24:00Z",
  "_etag": "\"0000efgh-0000-0000-0000-000000000000\"",
  "ttl": 60
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | **Partition Key**. `{channel}:{provider}` 형식 |
| `tokens` | number | 현재 사용 가능한 토큰 수 |
| `max_tokens` | number | 최대 토큰 수 (초당 한도와 동일) |
| `refill_rate` | number | 초당 토큰 보충 속도 |
| `last_refill_at` | string (ISO 8601) | 마지막 토큰 보충 시각 |
| `updated_at` | string (ISO 8601) | 최종 수정 시각 |
| `_etag` | string | Cosmos DB ETag. 동시성 제어 |
| `ttl` | number | 60초. Cosmos DB TTL로 자동 만료 |

### Channel Rate Limits (defaults)

| Channel | Tokens/sec | Env Var |
|---------|-----------|---------|
| email | 10 | `RATE_LIMIT_EMAIL_PER_SEC` |
| sms | 5 | `RATE_LIMIT_SMS_PER_SEC` |
| webhook | 20 | `RATE_LIMIT_WEBHOOK_PER_SEC` |

---

## logs

모든 구조화 로그를 저장한다. TTL 7일(604800초)로 자동 만료. Application Insights와 병행 사용.

```json
{
  "id": "auto-generated-uuid",
  "timestamp": "2026-04-13T15:24:16Z",
  "correlation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message": "채널별 발송 성공",
  "logger": "notification-pipeline.event-consumer",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_type": "appointment_confirmed",
  "channel": "email",
  "provider": "sendgrid",
  "status": "success",
  "duration_ms": 245
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string (UUID v4) | 로그 문서 고유 ID. 서버 자동 생성 |
| `timestamp` | string (ISO 8601) | 로그 발생 시각 |
| `correlation_id` | string | **Partition Key**. 이벤트 흐름 추적 ID. 시스템 로그는 `"system"` |
| `message` | string | 로그 메시지 |
| `logger` | string | 로거 이름 (예: `notification-pipeline.event-api`) |
| `event_id` | string | (optional) 이벤트 ID |
| `event_type` | string | (optional) 이벤트 타입 |
| `channel` | string | (optional) 알림 채널 |
| `provider` | string | (optional) 프로바이더 |
| `status` | string | (optional) 처리 상태 |
| `duration_ms` | number | (optional) 처리 소요 시간(ms) |

### Composite Index

`correlation_id` + `timestamp DESC` — 이벤트 흐름별 최신 로그 조회 최적화.

---

## leases

Change Feed Processor 체크포인트 전용. Azure Functions 런타임이 자동 관리하므로 수동 접근 불필요.

---

## Container Relationships

```
events.id ─────────────────────> dead-letter-queue.original_event_id
events.clinic_id ──────────────> dead-letter-queue.clinic_id
events.channels[] ─────────────> circuit-breaker.id ({channel}:{provider})
events.channels[] ─────────────> rate-limiter.id ({channel}:{provider})
events (Change Feed) ──────────> leases (체크포인트)
All Functions ─────────────────> logs (구조화 로그 저장)
```
