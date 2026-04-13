"""통합 테스트 공통 fixture.

Cosmos DB Emulator 연결 및 컨테이너 초기화.
Emulator가 실행 중이지 않으면 통합 테스트를 스킵한다.

SPEC.md §13.2, rules/testing.md 참조.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

# Cosmos DB Emulator 기본 설정
EMULATOR_ENDPOINT = "https://localhost:8081"
EMULATOR_KEY = "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
TEST_DATABASE = "test-notification-pipeline"


def _make_test_settings(**overrides: Any) -> Any:
    """통합 테스트용 Settings를 생성한다."""
    from src.shared.config import Settings

    defaults = {
        "COSMOS_DB_ENDPOINT": EMULATOR_ENDPOINT,
        "COSMOS_DB_KEY": EMULATOR_KEY,
        "COSMOS_DB_DATABASE": TEST_DATABASE,
        "QUEUE_SERVICE_TYPE": "EVENT_GRID",
        "NOTIFICATION_EMAIL_PROVIDER": "sendgrid",
        "NOTIFICATION_SMS_PROVIDER": "twilio",
        "WEBHOOK_URL": "https://example.com/webhook",
        "MOCK_DELAY_MIN_MS": "10",
        "MOCK_DELAY_MAX_MS": "20",
        "MAX_RETRY_COUNT": "2",
        "RETRY_BASE_DELAY_MS": "100",
        "RETRY_BACKOFF_MULTIPLIER": "2",
        "CB_FAILURE_THRESHOLD": "3",
        "CB_COOLDOWN_MS": "1000",
        "CB_SUCCESS_THRESHOLD": "2",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def emulator_available() -> bool:
    """Cosmos DB Emulator 연결 가능 여부를 확인한다."""
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        import requests

        resp = requests.get(f"{EMULATOR_ENDPOINT}/_explorer/emulator.pem", timeout=3, verify=False)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def integration_settings(emulator_available: bool) -> Any:
    """통합 테스트용 Settings. Emulator 미사용 시 스킵."""
    if not emulator_available:
        pytest.skip("Cosmos DB Emulator가 실행 중이지 않습니다")
    return _make_test_settings()


@pytest.fixture(scope="session")
async def setup_database(integration_settings: Any) -> None:
    """테스트 데이터베이스 및 컨테이너를 초기화한다."""
    from src.services.cosmos_client import init_containers, reset_client

    reset_client()
    await init_containers(integration_settings)


@pytest.fixture()
def unique_clinic_id() -> str:
    """테스트 간 데이터 격리를 위한 고유 clinic_id."""
    return f"test-clinic-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def test_settings(integration_settings: Any) -> Any:
    """개별 테스트에서 사용할 Settings."""
    return integration_settings
