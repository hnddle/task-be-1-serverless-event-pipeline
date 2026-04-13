# 수동 통합 테스트 가이드

로컬 환경에서 Azure Functions를 실행하고, PowerShell에서 `curl.exe`로 직접 API를 호출하여 전체 파이프라인을 검증하는 가이드.

---

## 사전 준비

### 1. 필수 설치

```bash
npm install                              # 의존성 설치
npm install -g azure-functions-core-tools@4  # Azure Functions Core Tools
npm install -g azurite                   # Azure Storage Emulator
```

### 2. Cosmos DB 초기화 (최초 1회)

```bash
npm run build
node scripts/init-db.js
```

정상 출력:
```
Cosmos DB 초기화 시작...
Endpoint: https://inspline.documents.azure.com:443
Database: notification-pipeline
초기화 완료! 5개 컨테이너가 생성되었습니다.
```

### 3. 서버 실행

터미널 2개를 열어서 각각 실행한다.

**터미널 1 — Azurite:**
```bash
azurite --silent
```

**터미널 2 — Azure Functions:**
```bash
npm start
```

정상 실행 시 출력:
```
Functions:
  getEventById: [GET] http://localhost:7071/api/events/{event_id}
  getEvents: [GET] http://localhost:7071/api/events
  postEvents: [POST] http://localhost:7071/api/events
  getDlqEntries: [GET] http://localhost:7071/api/dlq
  replaySingle: [POST] http://localhost:7071/api/dlq/{dlq_id}/replay
  replayBatch: [POST] http://localhost:7071/api/dlq/replay-batch
  outboxPublisher: cosmosDBTrigger
  outboxRetry: timerTrigger
  eventConsumer: eventGridTrigger
```

### 4. 테스트용 JSON 파일 준비

프로젝트 루트의 `test-event.json`:
```json
{"id":"6b5644ac-8050-4de6-b536-d3acf3acf4d6","event_type":"appointment_confirmed","clinic_id":"CLINIC_A","patient_id":"P-001","channels":["email","sms"]}
```

> PowerShell에서는 `curl`이 `Invoke-WebRequest`의 별칭이라 JSON 인코딩 문제가 발생한다. 반드시 **`curl.exe`**를 사용하고, JSON은 **파일로 분리**(`-d @파일명`)해야 한다.

---

## API 엔드포인트 요약

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/events` | 이벤트 생성 |
| GET | `/api/events/{event_id}` | 이벤트 상세 조회 |
| GET | `/api/events` | 이벤트 목록 조회 |
| GET | `/api/dlq` | DLQ 목록 조회 |
| POST | `/api/dlq/{dlq_id}/replay` | DLQ 단건 재처리 |
| POST | `/api/dlq/replay-batch` | DLQ 일괄 재처리 |

---

## 테스트 1: 이벤트 생성 (POST /events)

### 1-1. 정상 생성

```powershell
curl.exe -X POST http://localhost:7071/api/events -H "Content-Type: application/json" -d @test-event.json
```

**기대 응답 (201 Created):**
```json
{
  "event_id": "6b5644ac-8050-4de6-b536-d3acf3acf4d6",
  "status": "queued",
  "correlation_id": "자동생성된-uuid"
}
```

- `status`가 `"queued"`이면 Cosmos DB에 정상 저장된 것이다.
- `correlation_id`는 서버가 자동 생성하는 분산 트레이싱 ID다.
- 저장 직후 Change Feed → outbox-publisher → Event Grid → event-consumer 흐름이 비동기로 실행된다.

### 1-2. 중복 요청 테스트 (Idempotency)

같은 `test-event.json`을 다시 전송한다:

```powershell
curl.exe -X POST http://localhost:7071/api/events -H "Content-Type: application/json" -d @test-event.json
```

**기대 응답 (200 OK):**
```json
{
  "event_id": "6b5644ac-8050-4de6-b536-d3acf3acf4d6",
  "status": "queued",
  "correlation_id": "a386692e-88f6-4afb-a9ff-5135fdc1bf05",
  "message": "Event already exists"
}
```

- 첫 번째 요청은 **201**, 두 번째 요청은 **200** + `"Event already exists"` 메시지가 나오면 Idempotency가 정상 동작하는 것이다.
- `status`는 이벤트가 처리된 정도에 따라 `queued` / `processing` / `completed` 등으로 변할 수 있다.

### 1-3. 유효성 검증 실패 테스트

잘못된 JSON 파일 `test-invalid.json`을 만들어서 테스트한다:

```json
{"event_type":"invalid_type","clinic_id":"","channels":[]}
```

```powershell
curl.exe -X POST http://localhost:7071/api/events -H "Content-Type: application/json" -d @test-invalid.json
```

**기대 응답 (400 Bad Request):**
```json
{
  "error": "VALIDATION_ERROR",
  "message": "Invalid request body",
  "details": [
    { "field": "id", "message": "Required" },
    { "field": "event_type", "message": "..." },
    { "field": "clinic_id", "message": "..." },
    { "field": "channels", "message": "..." }
  ]
}
```

---

## 테스트 2: 이벤트 상세 조회 (GET /events/{event_id})

### 2-1. clinic_id 포함 조회 (Point Read)

```powershell
curl.exe "http://localhost:7071/api/events/6b5644ac-8050-4de6-b536-d3acf3acf4d6?clinic_id=CLINIC_A"
```

**기대 응답 (200 OK):**
```json
{
  "id": "6b5644ac-8050-4de6-b536-d3acf3acf4d6",
  "clinic_id": "CLINIC_A",
  "status": "completed",
  "event_type": "appointment_confirmed",
  "patient_id": "P-001",
  "channels": ["email", "sms"],
  "correlation_id": "...",
  "notifications": [
    {
      "channel": "email",
      "provider": "sendgrid",
      "status": "success",
      "sent_at": "2026-04-13T...",
      "retry_count": 0,
      "last_error": null
    },
    {
      "channel": "sms",
      "provider": "twilio",
      "status": "success",
      "sent_at": "2026-04-13T...",
      "retry_count": 0,
      "last_error": null
    }
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

- `_outbox_status`, `_rid`, `_self`, `_etag`, `_attachments`, `_ts` 같은 내부 필드는 응답에서 제거된다.
- `clinic_id`를 포함하면 Cosmos DB Point Read로 조회하므로 빠르다.

### 2-2. clinic_id 없이 조회 (Cross-Partition Query)

```powershell
curl.exe "http://localhost:7071/api/events/6b5644ac-8050-4de6-b536-d3acf3acf4d6"
```

- clinic_id를 모를 때 사용한다. 내부적으로 Cross-Partition Query를 실행하므로 Point Read보다 느리다.
- 응답 형식은 2-1과 동일하다.

### 2-3. 존재하지 않는 이벤트 조회

```powershell
curl.exe "http://localhost:7071/api/events/nonexistent-id?clinic_id=CLINIC_A"
```

**기대 응답 (404):**
```json
{
  "error": "NOT_FOUND",
  "message": "Event nonexistent-id not found",
  "details": []
}
```

---

## 테스트 3: 이벤트 목록 조회 (GET /events)

### 3-1. 기본 조회

```powershell
curl.exe "http://localhost:7071/api/events?clinic_id=CLINIC_A"
```

**기대 응답 (200 OK):**
```json
{
  "items": [
    {
      "id": "6b5644ac-...",
      "clinic_id": "CLINIC_A",
      "status": "completed",
      "event_type": "appointment_confirmed",
      "patient_id": "P-001",
      "channels": ["email", "sms"],
      "correlation_id": "...",
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "continuation_token": null
}
```

### 3-2. 필터링 조회

```powershell
# 상태 필터
curl.exe "http://localhost:7071/api/events?clinic_id=CLINIC_A&status=completed"

# 이벤트 타입 필터
curl.exe "http://localhost:7071/api/events?clinic_id=CLINIC_A&event_type=appointment_confirmed"

# 페이지 크기 지정 (최대 100)
curl.exe "http://localhost:7071/api/events?clinic_id=CLINIC_A&page_size=5"
```

### 3-3. clinic_id 누락 시

```powershell
curl.exe "http://localhost:7071/api/events"
```

**기대 응답 (400):**
```json
{
  "error": "VALIDATION_ERROR",
  "message": "clinic_id query parameter is required",
  "details": []
}
```

---

## 테스트 4: 여러 이벤트 생성

다양한 이벤트를 생성하여 목록 조회, 필터링을 검증한다.

`test-event-2.json`:
```json
{"id":"a1b2c3d4-e5f6-7890-abcd-ef1234567890","event_type":"insurance_approved","clinic_id":"CLINIC_A","patient_id":"P-002","channels":["email"]}
```

`test-event-3.json`:
```json
{"id":"b2c3d4e5-f6a7-8901-bcde-f12345678901","event_type":"claim_completed","clinic_id":"CLINIC_B","patient_id":"P-003","channels":["email","sms","webhook"]}
```

```powershell
curl.exe -X POST http://localhost:7071/api/events -H "Content-Type: application/json" -d @test-event-2.json
curl.exe -X POST http://localhost:7071/api/events -H "Content-Type: application/json" -d @test-event-3.json
```

이후 목록 조회로 검증:

```powershell
# CLINIC_A 이벤트만
curl.exe "http://localhost:7071/api/events?clinic_id=CLINIC_A"

# CLINIC_B 이벤트만
curl.exe "http://localhost:7071/api/events?clinic_id=CLINIC_B"

# insurance_approved 타입만
curl.exe "http://localhost:7071/api/events?clinic_id=CLINIC_A&event_type=insurance_approved"
```

---

## 테스트 5: DLQ 조회 (GET /dlq)

DLQ에는 최대 재시도 횟수를 초과하여 실패한 알림이 저장된다.

```powershell
curl.exe "http://localhost:7071/api/dlq?clinic_id=CLINIC_A"
```

**기대 응답 (200 OK):**
```json
{
  "items": [],
  "continuation_token": null,
  "total_count": 0
}
```

정상 환경에서는 DLQ가 비어 있다. DLQ에 항목이 쌓이는 것을 보려면 Circuit Breaker를 강제로 OPEN 상태로 만들어야 한다 (테스트 7 참조).

### DLQ 필터링

```powershell
# replay_status 필터
curl.exe "http://localhost:7071/api/dlq?clinic_id=CLINIC_A&replay_status=pending"

# 이벤트 타입 필터
curl.exe "http://localhost:7071/api/dlq?clinic_id=CLINIC_A&event_type=appointment_confirmed"

# 날짜 범위 필터
curl.exe "http://localhost:7071/api/dlq?clinic_id=CLINIC_A&date_from=2026-04-01T00:00:00Z&date_to=2026-04-30T23:59:59Z"
```

---

## 테스트 6: Outbox 패턴 동작 확인

이벤트를 생성한 후 Azure Functions 로그를 관찰한다.

```powershell
curl.exe -X POST http://localhost:7071/api/events -H "Content-Type: application/json" -d @test-event.json
```

**서버 로그에서 확인할 내용 (순서대로):**

```
1. [event-api]      이벤트 생성 완료  { status: 'queued' }
2. [outbox-publisher] Change Feed 수신: N건
3. [outbox-publisher] pending 문서 처리: {event_id}
4. [outbox-publisher] Event Grid 발행 완료
5. [outbox-publisher] outbox 상태 갱신: published
6. [event-consumer]  이벤트 수신: {event_id}
7. [event-consumer]  채널 처리: email (sendgrid)
8. [event-consumer]  채널 처리: sms (twilio)
9. [event-consumer]  이벤트 처리 완료: completed
```

이벤트 생성 후 수 초 내에 위 로그가 출력되면 전체 파이프라인이 정상 동작하는 것이다.

---

## 테스트 7: Circuit Breaker 테스트

Circuit Breaker를 강제로 OPEN 상태로 만들어서, 알림이 실패 → DLQ로 이동하는 흐름을 검증한다.

### 7-1. Circuit Breaker 강제 OPEN

Azure Portal의 Cosmos DB Data Explorer에서 `circuit-breaker` 컨테이너에 다음 문서를 직접 삽입한다:

```json
{
  "id": "email:sendgrid",
  "state": "open",
  "failure_count": 5,
  "success_count": 0,
  "last_failure_at": "2026-04-13T12:00:00Z",
  "opened_at": "2026-04-13T12:00:00Z",
  "updated_at": "2026-04-13T12:00:00Z"
}
```

```json
{
  "id": "sms:twilio",
  "state": "open",
  "failure_count": 5,
  "success_count": 0,
  "last_failure_at": "2026-04-13T12:00:00Z",
  "opened_at": "2026-04-13T12:00:00Z",
  "updated_at": "2026-04-13T12:00:00Z"
}
```

> `opened_at`을 현재 시간으로 설정하면 COOLDOWN_MS(기본 30초) 동안 OPEN 상태가 유지된다.

### 7-2. 이벤트 생성

```powershell
curl.exe -X POST http://localhost:7071/api/events -H "Content-Type: application/json" -d @test-event-cb.json
```

`test-event-cb.json`:
```json
{"id":"cb-test-0001-0000-0000-000000000001","event_type":"appointment_confirmed","clinic_id":"CLINIC_A","patient_id":"P-CB-TEST","channels":["email","sms"]}
```

### 7-3. 결과 확인

서버 로그에서 Circuit Breaker OPEN으로 인한 즉시 실패를 확인한다:
```
[circuit-breaker] Circuit OPEN for email:sendgrid — 요청 차단
[circuit-breaker] Circuit OPEN for sms:twilio — 요청 차단
```

재시도 후 DLQ에 저장되었는지 확인:

```powershell
# 이벤트 상태 확인 (failed 또는 partially_completed)
curl.exe "http://localhost:7071/api/events/cb-test-0001-0000-0000-000000000001?clinic_id=CLINIC_A"

# DLQ 확인
curl.exe "http://localhost:7071/api/dlq?clinic_id=CLINIC_A"
```

### 7-4. 정리

테스트 후 Azure Portal에서 `circuit-breaker` 컨테이너의 문서를 삭제하거나 `state`를 `"closed"`로 변경한다.

---

## 테스트 8: DLQ Replay (재처리)

테스트 7에서 DLQ에 쌓인 항목을 재처리한다.

### 8-1. DLQ 목록 확인

```powershell
curl.exe "http://localhost:7071/api/dlq?clinic_id=CLINIC_A"
```

응답에서 `dlq_id`를 확인한다.

### 8-2. 단건 Replay

```powershell
curl.exe -X POST "http://localhost:7071/api/dlq/{dlq_id}/replay"
```

`{dlq_id}`를 실제 값으로 교체한다.

**기대 응답 (200 OK):**
```json
{
  "dlq_id": "...",
  "replay_status": "replayed",
  "new_correlation_id": "새로-생성된-uuid"
}
```

### 8-3. 이미 Replay된 항목 재시도

같은 `dlq_id`로 다시 호출한다:

```powershell
curl.exe -X POST "http://localhost:7071/api/dlq/{dlq_id}/replay"
```

**기대 응답 (409 Conflict):**
```json
{
  "error": "CONFLICT",
  "message": "DLQ entry already replayed",
  "details": []
}
```

### 8-4. 일괄 Replay

`test-replay-batch.json`:
```json
{"clinic_id":"CLINIC_A","max_count":10}
```

```powershell
curl.exe -X POST http://localhost:7071/api/dlq/replay-batch -H "Content-Type: application/json" -d @test-replay-batch.json
```

**기대 응답 (200 OK):**
```json
{
  "replayed_count": 2,
  "failed_count": 0,
  "skipped_count": 0
}
```

---

## 테스트 체크리스트

| # | 테스트 항목 | 기대 결과 | 확인 |
|---|-----------|----------|------|
| 1 | POST /events (정상) | 201 + `status: queued` | [ ] |
| 2 | POST /events (중복) | 200 + `Event already exists` | [ ] |
| 3 | POST /events (유효성 실패) | 400 + `VALIDATION_ERROR` | [ ] |
| 4 | GET /events/{id}?clinic_id= | 200 + 이벤트 상세 | [ ] |
| 5 | GET /events/{id} (clinic_id 없이) | 200 + Cross-Partition 조회 | [ ] |
| 6 | GET /events/{id} (없는 이벤트) | 404 + `NOT_FOUND` | [ ] |
| 7 | GET /events?clinic_id= | 200 + items 배열 | [ ] |
| 8 | GET /events (clinic_id 누락) | 400 + `VALIDATION_ERROR` | [ ] |
| 9 | GET /dlq?clinic_id= | 200 + items 배열 | [ ] |
| 10 | 서버 로그에서 Outbox 흐름 확인 | pending → published → consumer | [ ] |
| 11 | CB 강제 OPEN → 이벤트 생성 | 알림 실패 → DLQ 저장 | [ ] |
| 12 | POST /dlq/{id}/replay | 200 + `replayed` | [ ] |
| 13 | POST /dlq/{id}/replay (중복) | 409 + `CONFLICT` | [ ] |
| 14 | POST /dlq/replay-batch | 200 + 재처리 카운트 | [ ] |

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `curl`로 POST 시 400 "Invalid JSON body" | PowerShell의 `curl`은 `Invoke-WebRequest` 별칭 | `curl.exe`를 사용하고, JSON은 `-d @파일.json`으로 전달 |
| 127.0.0.1:10000 연결 거부 | Azurite가 실행되지 않음 | 별도 터미널에서 `azurite --silent` 실행 |
| outbox-publisher가 동작하지 않음 | `CosmosDBConnection` 미설정 | `local.settings.json`에 연결 문자열 추가 |
| Timer 트리거(outbox-retry) 실패 | Azurite 미실행 상태에서 Timer 체크포인트 저장 불가 | Azurite 실행 |
| Change Feed가 발화하지 않음 | DB에 문서가 변경되지 않았거나 leases 컨테이너 미생성 | `node scripts/init-db.js`로 초기화 |
| `func` 명령어를 찾을 수 없음 | Azure Functions Core Tools 미설치 | `npm install -g azure-functions-core-tools@4` |
