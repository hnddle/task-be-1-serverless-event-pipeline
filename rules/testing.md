# Testing Rules

- 테스트 파일은 소스 구조를 미러링: `app/services/foo.py` → `tests/services/test_foo.py`
- 공유 setup은 fixture 사용 (pytest fixture, beforeEach 등)
- DB 테스트는 실제 테스트 DB 사용 (mock 금지)
- 최소 요건: 모든 public 함수에 최소 1개 테스트
- 테스트 이름: `test_{함수명}_{시나리오}_{기대결과}`

## Python (pytest)
- 프레임워크: pytest
- 비동기 테스트: `pytest-asyncio`
- 테스트 데이터 생성: `factory_boy`

## TypeScript (Vitest)
- 프레임워크: Vitest + React Testing Library (컴포넌트)
- E2E: Playwright

## 스택에 맞게 위 섹션을 선택하여 사용
