# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

치과 보험 청구 시스템 — 이벤트 기반 알림 파이프라인 (Serverless Event Pipeline).
SPEC.md와 PLAN.md에 따라 구현 완료. Node.js/TypeScript 기반.

- `SPEC.md` — 기술 명세서 (단일 진실 공급원)
- `PLAN.md` — 구현 계획서

## Architecture (핵심 흐름)

```
POST /events → Cosmos DB 저장 (Outbox: pending) → 즉시 201 응답
       ↓
Change Feed Trigger → outbox-publisher (pending만 필터링) → Event Grid 발행
       ↓
event-consumer → channels 순회:
  Circuit Breaker 확인 → Rate Limiter 확인 → NotificationStrategy.send()
       ↓
  성공 → Cosmos DB 기록 (completed/partially_completed)
  실패 → 재시도 (지수 백오프, MAX_RETRY_COUNT) → 초과 시 DLQ 저장
       ↓
DLQ API → GET /dlq 조회 → POST /dlq/:id/replay 재처리
```

### Azure Functions (5개)

| Function | Trigger | 역할 |
|----------|---------|------|
| `event-api` | HTTP | POST /events, GET /events/{event_id}, GET /events |
| `dlq-api` | HTTP | GET /dlq, POST /dlq/{dlq_id}/replay, POST /dlq/replay-batch |
| `outbox-publisher` | Cosmos DB Change Feed | pending 문서 감지 → Event Grid 발행 |
| `outbox-retry` | Timer (1분) | failed_publish → pending 재갱신 |
| `event-consumer` | Event Grid | 채널별 알림 발송 처리 |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Node.js 20+ |
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
| Type Checker | TypeScript (strict mode) |

## Project Structure

```
src/
├── functions/              # Azure Functions 모듈 (5개, app.http/cosmosDB/timer/eventGrid)
│   ├── event-api.ts
│   ├── outbox-publisher.ts
│   ├── outbox-retry.ts
│   ├── event-consumer.ts
│   └── dlq-api.ts
├── services/               # 비즈니스 로직
│   ├── cosmos-client.ts
│   ├── message-broker/     # Adapter+Factory 패턴 (interface)
│   ├── notification/       # Strategy 패턴 (interface)
│   ├── circuit-breaker.ts
│   ├── rate-limiter.ts
│   ├── retry-service.ts
│   └── dlq-service.ts
├── shared/                 # 공통 유틸 (config, logger, validator, correlation, errors)
│   ├── config.ts
│   ├── logger.ts
│   ├── validator.ts
│   ├── correlation.ts
│   └── errors.ts
└── models/                 # TypeScript 인터페이스 (Cosmos DB 문서 구조와 1:1)
    ├── events.ts
    ├── circuit-breaker.ts
    ├── dlq.ts
    └── rate-limiter.ts
tests/
├── unit/                   # 단위 테스트 (15 파일, 181 tests)
└── integration/            # 통합 테스트 (5 파일, Cosmos DB Emulator)
```

## Development Commands

```bash
npm install                           # 의존성 설치
npm run build                         # TypeScript 빌드
npm start                             # Azure Functions 로컬 실행
npx jest                              # 전체 테스트
npx jest tests/unit                   # 단위 테스트만
npx jest tests/integration            # 통합 테스트만 (Emulator 필요)
npx jest -t "test_name"               # 특정 테스트 실행
npx tsc --noEmit                      # 타입 체크
```

## Git Workflow

- **Gitflow**: master(프로덕션) / develop(통합) / feature·release·hotfix 브랜치
- **master 직접 커밋 금지**
- **커밋 메시지**: Conventional Commits, **한글로 작성** (기술 용어는 영어 허용)
  ```
  {type}({scope}): {한글 subject}
  ```
- Feature → develop (squash merge), Release/Hotfix → master AND develop (--no-ff)
- Feature 브랜치 네이밍: `feature/step-{X}-{Y}-{short-desc}`
- 상세 규칙: `rules/git-workflow.md`

## Key Rules

### Code Style (`rules/code-style/typescript.md`)
- TypeScript strict mode
- 모든 함수 파라미터와 반환 타입에 type annotation 필수
- 데이터 검증: Zod 스키마 사용
- 비동기 I/O: `async/await` 사용
- import 순서: node builtins → third-party → local
- 문자열: 템플릿 리터럴 우선
- 최대 줄 길이: 120자
- 프로덕션 코드에서 `console.log()` 금지 — `src/shared/logger.ts` 사용
- 상수: `UPPER_SNAKE_CASE`
- 환경 변수: `src/shared/config.ts`의 `loadSettings()` 경유
- Path alias: `@src/*` → `src/*`, `@tests/*` → `tests/*`

### Testing (`rules/testing.md`)
- 프레임워크: Jest + ts-jest
- 테스트 파일 위치: `tests/unit/`, `tests/integration/`
- 파일명: `{모듈명}.test.ts` (단위), `{흐름}.integration.test.ts` (통합)
- 통합 테스트는 실제 Cosmos DB Emulator 사용 (Emulator 미실행 시 자동 스킵)
- 최소 요건: 모든 public 함수에 최소 1개 테스트
- 테스트용 settings 주입: `_setSettingsForTest()` 패턴

### Security (`rules/security.md`)
- 시크릿 하드코딩 절대 금지 — 모든 시크릿은 환경변수로 로드
- `local.settings.json`은 `.gitignore` 대상 (절대 커밋 금지)
- API 경계에서 모든 외부 입력 검증 (Zod)
- 로그에 민감정보(키, 토큰, 환자 개인정보) 절대 금지

### 12-Factor App (`rules/twelve-factor.md`)
- **III. Config**: 코드 내 하드코딩 금지, 환경변수 전용 (`src/shared/config.ts`)
- **IV. Backing Services**: Cosmos DB, Event Grid를 교체 가능한 리소스로 취급
- **XI. Logs**: stdout/stderr만 사용, 파일 로깅 금지, JSON 구조화 로그

## Design Patterns

구현 시 반드시 SPEC.md의 패턴 요구사항을 준수한다:

- **Adapter + Factory** (`src/services/message-broker/`): `QUEUE_SERVICE_TYPE` 환경변수로 브로커 교체
- **Strategy** (`src/services/notification/`): 채널별 알림 전략, Mock 발송
- **Circuit Breaker** (`src/services/circuit-breaker.ts`): `{channel}:{provider}` 조합별 독립 운용, ETag 동시성 제어
- **Token Bucket Rate Limiter** (`src/services/rate-limiter.ts`): ETag 동시성 제어
- **Transactional Outbox** (`src/functions/outbox-publisher.ts`): Change Feed 기반, 무한루프 방지 필수

## Implementation Tracking

- Current plan: PLAN.md
- Mark completed steps by changing `[ ]` to `[x]`
- 구현 시 `/step X-Y` 스킬로 자동 실행, `/ship`으로 커밋+푸시

## Notes

- 문서 기본 언어: 한국어
- 서비스 언어: 한국어 전용
- Cosmos DB 컨테이너 6개: `events`, `dead-letter-queue`, `circuit-breaker`, `rate-limiter`, `leases`, `logs`
- 환경 변수 전체 목록: SPEC.md §11 참조, 템플릿: `local.settings.sample.json`
- Python에서 Node.js/TypeScript로 마이그레이션 완료 (Azure Functions 무료 구독 Windows 호환)
