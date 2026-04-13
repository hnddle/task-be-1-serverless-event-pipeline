# Security Rules

- 소스코드에 비밀키, API 키, 비밀번호, 토큰을 절대 하드코딩 금지
- 모든 시크릿은 환경변수로 로드 (`src/shared/config.py` — pydantic-settings 경유)
- 로컬 개발은 `local.settings.json` 사용 (절대 커밋 금지, `.gitignore` 대상)
- `local.settings.sample.json`은 placeholder 값만 포함하여 커밋
- API 경계에서 모든 외부 입력을 검증 (Pydantic BaseModel)
- Cosmos DB 쿼리: 파라미터화된 쿼리만 사용 — 문자열 직접 조합 금지
- 로그 위생: 시크릿, 토큰, 환자 개인정보(patient_id 제외)는 절대 로깅 금지
- CORS: 허용 오리진 명시적 제한 (`host.json`에서 설정)
- 환경 변수 검증: 필수 변수 누락 시 Fail-fast (프로세스 종료)
