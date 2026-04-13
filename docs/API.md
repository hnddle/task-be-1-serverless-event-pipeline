# API Reference

Base URL: `http://localhost:7071/api` (로컬) / `https://{function-app-name}.azurewebsites.net/api` (운영)

---

## Event API

### POST /events

알림 이벤트를 생성한다. Outbox 패턴에 의해 비동기로 Event Grid에 발행된다.

**Request Body**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "event_type": "appointment_confirmed",
  "clinic_id": "CLINIC_123",
  "patient_id": "PATIENT_456",
  "channels": ["email", "sms", "webhook"]
}
```

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `id` | string | Yes | UUID v4. Idempotency Key를 겸한다 |
| `event_type` | string | Yes | `appointment_confirmed` \| `insurance_approved` \| `claim_completed` |
| `clinic_id` | string | Yes | 비어 있지 않은 문자열 |
| `patient_id` | string | Yes | 비어 있지 않은 문자열 |
| `channels` | string[] | Yes | 1개 이상. 허용값: `email`, `sms`, `webhook`. 중복 불가 |

**Response**

`201 Created` - 이벤트 생성 성공

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "correlation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

`200 OK` - 동일 ID 이벤트가 이미 존재 (멱등성 보장)

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "correlation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message": "Event already exists"
}
```

`400 Bad Request` - 입력 검증 실패

```json
{
  "error": "VALIDATION_ERROR",
  "message": "Invalid request body",
  "details": [
    { "field": "event_type", "message": "Must be one of: appointment_confirmed, insurance_approved, claim_completed" }
  ]
}
```

---

### GET /events/{event_id}

특정 이벤트의 채널별 발송 상태를 조회한다.

**Query Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `clinic_id` | string | Yes | Partition Key |

**Response**

`200 OK`

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
    },
    {
      "channel": "sms",
      "provider": "twilio",
      "status": "success",
      "sent_at": "2026-04-13T15:24:17Z",
      "retry_count": 0,
      "last_error": null
    },
    {
      "channel": "webhook",
      "provider": "webhook",
      "status": "success",
      "sent_at": "2026-04-13T15:24:17Z",
      "retry_count": 0,
      "last_error": null
    }
  ],
  "created_at": "2026-04-13T15:24:00Z",
  "updated_at": "2026-04-13T15:24:17Z"
}
```

`400 Bad Request` - `clinic_id` 누락

`404 Not Found` - 해당 이벤트 없음

---

### GET /events

이벤트 목록을 조회한다.

**Query Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `clinic_id` | string | Yes | Partition Key |
| `status` | string | No | `queued` \| `processing` \| `completed` \| `partially_completed` \| `failed` |
| `event_type` | string | No | `appointment_confirmed` \| `insurance_approved` \| `claim_completed` |
| `continuation_token` | string | No | 페이지네이션 토큰 |
| `page_size` | number | No | 기본값 20, 최대 100 |

**Response**

`200 OK`

```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "clinic_id": "CLINIC_123",
      "status": "completed",
      "event_type": "appointment_confirmed",
      "patient_id": "PATIENT_456",
      "channels": ["email", "sms", "webhook"],
      "correlation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "created_at": "2026-04-13T15:24:00Z",
      "updated_at": "2026-04-13T15:24:17Z"
    }
  ],
  "continuation_token": null
}
```

`400 Bad Request` - `clinic_id` 누락

---

## DLQ API

### GET /dlq

Dead Letter Queue 메시지 목록을 조회한다.

**Query Parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `clinic_id` | string | Yes | Partition Key |
| `replay_status` | string | No | `pending` \| `replayed` \| `permanently_failed` |
| `event_type` | string | No | 이벤트 타입 필터 |
| `date_from` | string | No | ISO 8601 시작일 |
| `date_to` | string | No | ISO 8601 종료일 |
| `continuation_token` | string | No | 페이지네이션 토큰 |
| `page_size` | number | No | 기본값 20, 최대 100 |

**Response**

`200 OK`

```json
{
  "items": [
    {
      "id": "dlq-uuid",
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
  ],
  "continuation_token": null,
  "total_count": 1
}
```

`400 Bad Request` - `clinic_id` 누락

---

### POST /dlq/{dlq_id}/replay

특정 DLQ 메시지를 재처리한다. Outbox 패턴을 통해 재발행된다.

**Response**

`200 OK`

```json
{
  "dlq_id": "dlq-uuid",
  "replay_status": "replayed",
  "new_correlation_id": "new-uuid"
}
```

`404 Not Found` - 해당 DLQ 메시지 없음

`409 Conflict` - 이미 replay된 메시지

---

### POST /dlq/replay-batch

필터 조건에 맞는 DLQ 메시지를 일괄 재처리한다.

**Request Body**

```json
{
  "clinic_id": "CLINIC_123",
  "event_type": "appointment_confirmed",
  "date_from": "2026-04-01T00:00:00Z",
  "date_to": "2026-04-13T23:59:59Z",
  "max_count": 100
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `clinic_id` | string | Yes | 병원 ID |
| `event_type` | string | No | 이벤트 타입 필터 |
| `date_from` | string | No | ISO 8601 시작일 |
| `date_to` | string | No | ISO 8601 종료일 |
| `max_count` | number | No | 최대 처리 건수 (기본 100, 최대 500) |

**Response**

`200 OK`

```json
{
  "replayed_count": 5,
  "failed_count": 1,
  "skipped_count": 2
}
```

`400 Bad Request` - `clinic_id` 누락

---

## Error Response

모든 API는 에러 시 동일한 형식을 따른다.

```json
{
  "error": "ERROR_CODE",
  "message": "Human-readable description",
  "details": []
}
```

| HTTP Status | Error Code | Description |
|-------------|-----------|-------------|
| 400 | `VALIDATION_ERROR` | 입력 검증 실패 |
| 404 | `NOT_FOUND` | 리소스 없음 |
| 409 | `CONFLICT` | 중복 요청 (이미 replay된 DLQ 메시지) |
| 500 | `INTERNAL_ERROR` | 서버 내부 오류 |
