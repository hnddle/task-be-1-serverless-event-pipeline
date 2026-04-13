# Testing Rules

- 프레임워크: pytest + pytest-asyncio
- 테스트 파일 ���치: `tests/unit/`, `tests/integration/`
- 테스트 파일명: `test_{대상 모듈명}.py` (예: `test_circuit_breaker.py`)
- 소스 구조 미러링: `src/services/circuit_breaker.py` → `tests/unit/test_circuit_breaker.py`
- 공유 setup: pytest fixture (`tests/conftest.py`, `beforeEach` 대신 `@pytest.fixture`)
- 테스트 데이터 생성: factory 함수 또는 fixture
- DB 테스트는 실제 Cosmos DB Emulator 사용 (mock 금지)
- 최소 요건: ���든 public ��수에 최소 1개 테스트
- 테스트 이름: `test_{함수명}_{시나리오}_{기대결과}`
  ```python
  def test_circuit_breaker_transitions_to_open_after_threshold_failures():
      ...

  class TestCircuitBreaker:
      def test_transitions_to_open_after_threshold_failures(self):
          ...
  ```

## 단위 테스트 (`tests/unit/`)
- 외부 의존성 없이 실행 가능해야 함
- Cosmos DB, Event Grid 등 외부 서비스는 `unittest.mock` / `pytest-mock` 사용 가능
- 순수 로직 검증: 상태 머신 전이, 딜레이 계산, 입력 검증 등

## 통합 테스트 (`tests/integration/`)
- Cosmos DB Emulator 필수 (mock 금지)
- Azure Functions 런타임 없이 핸들러 함수를 직접 호출하여 테스트
- 테스트 간 데이터 격리: 각 테스트에서 고유 clinic_id 사용
- 비동기 테스트: `pytest-asyncio` 사용 (`asyncio_mode = "auto"`)
