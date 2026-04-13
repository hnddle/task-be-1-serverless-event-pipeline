"""환경 변수 로드/검증 테스트."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src.shared.config import Settings, load_settings

# 필수 환경 변수 최소 세트
REQUIRED_ENV = {
    "QUEUE_SERVICE_TYPE": "EVENT_GRID",
    "NOTIFICATION_EMAIL_PROVIDER": "sendgrid",
    "NOTIFICATION_SMS_PROVIDER": "twilio",
    "WEBHOOK_URL": "https://example.com/webhook",
    "COSMOS_DB_ENDPOINT": "https://localhost:8081",
    "COSMOS_DB_KEY": "test-key",
    "COSMOS_DB_DATABASE": "test-db",
}


class TestSettingsRequiredVars:
    """필수 환경 변수 검증 테스트."""

    def test_load_settings_with_all_required_vars(self) -> None:
        """모든 필수 변수가 있으면 정상 로드."""
        with patch.dict(os.environ, REQUIRED_ENV, clear=False):
            settings = load_settings()
            assert settings.QUEUE_SERVICE_TYPE == "EVENT_GRID"
            assert settings.COSMOS_DB_ENDPOINT == "https://localhost:8081"
            assert settings.COSMOS_DB_DATABASE == "test-db"

    def test_load_settings_missing_required_var_exits(self) -> None:
        """필수 변수 누락 시 sys.exit(1)."""
        incomplete = {k: v for k, v in REQUIRED_ENV.items() if k != "COSMOS_DB_KEY"}
        with patch.dict(os.environ, incomplete, clear=True), pytest.raises(SystemExit) as exc_info:
            load_settings()
        assert exc_info.value.code == 1

    def test_load_settings_missing_multiple_required_vars_exits(self) -> None:
        """여러 필수 변수 누락 시에도 sys.exit(1)."""
        with patch.dict(os.environ, {}, clear=True), pytest.raises(SystemExit) as exc_info:
            load_settings()
        assert exc_info.value.code == 1


class TestSettingsDefaultValues:
    """선택 환경 변수 기본값 테스트."""

    def test_default_circuit_breaker_values(self) -> None:
        """Circuit Breaker 기본값 확인."""
        with patch.dict(os.environ, REQUIRED_ENV, clear=False):
            settings = load_settings()
            assert settings.CB_FAILURE_THRESHOLD == 5
            assert settings.CB_COOLDOWN_MS == 30000
            assert settings.CB_SUCCESS_THRESHOLD == 2

    def test_default_retry_values(self) -> None:
        """Retry 기본값 확인."""
        with patch.dict(os.environ, REQUIRED_ENV, clear=False):
            settings = load_settings()
            assert settings.MAX_RETRY_COUNT == 3
            assert settings.RETRY_BASE_DELAY_MS == 1000
            assert settings.RETRY_BACKOFF_MULTIPLIER == 2

    def test_default_rate_limiter_values(self) -> None:
        """Rate Limiter 기본값 확인."""
        with patch.dict(os.environ, REQUIRED_ENV, clear=False):
            settings = load_settings()
            assert settings.RATE_LIMIT_EMAIL_PER_SEC == 10
            assert settings.RATE_LIMIT_SMS_PER_SEC == 5
            assert settings.RATE_LIMIT_WEBHOOK_PER_SEC == 20
            assert settings.RATE_LIMIT_MAX_WAIT_MS == 10000

    def test_default_mock_delay_values(self) -> None:
        """Mock Delay 기본값 확인."""
        with patch.dict(os.environ, REQUIRED_ENV, clear=False):
            settings = load_settings()
            assert settings.MOCK_DELAY_MIN_MS == 100
            assert settings.MOCK_DELAY_MAX_MS == 500

    def test_override_optional_values(self) -> None:
        """선택 변수를 환경 변수로 덮어쓸 수 있다."""
        env = {**REQUIRED_ENV, "CB_FAILURE_THRESHOLD": "10", "MAX_RETRY_COUNT": "5"}
        with patch.dict(os.environ, env, clear=False):
            settings = load_settings()
            assert settings.CB_FAILURE_THRESHOLD == 10
            assert settings.MAX_RETRY_COUNT == 5


class TestSettingsDirectConstruction:
    """Settings 직접 생성 테스트."""

    def test_construct_settings_directly(self) -> None:
        """Settings를 직접 생성할 수 있다."""
        settings = Settings(**REQUIRED_ENV)  # type: ignore[arg-type]
        assert settings.QUEUE_SERVICE_TYPE == "EVENT_GRID"
        assert settings.CB_FAILURE_THRESHOLD == 5
