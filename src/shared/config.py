"""환경 변수 로드 및 Fail-fast 검증.

pydantic-settings 기반. 필수 환경 변수 누락 시 에러 로그 출력 후 프로세스 종료.
SPEC.md §11 참조.
"""

from __future__ import annotations

import logging
import sys

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """애플리케이션 설정.

    필수 변수(기본값 없음)가 누락되면 pydantic ValidationError 발생.
    선택 변수는 SPEC.md §11의 기본값을 따른다.
    """

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=True,
    )

    # 필수 — Message Broker
    QUEUE_SERVICE_TYPE: str

    # 필수 — Notification Providers
    NOTIFICATION_EMAIL_PROVIDER: str
    NOTIFICATION_SMS_PROVIDER: str
    WEBHOOK_URL: str

    # 필수 — Cosmos DB
    COSMOS_DB_ENDPOINT: str
    COSMOS_DB_KEY: str
    COSMOS_DB_DATABASE: str

    # 선택 — Circuit Breaker
    CB_FAILURE_THRESHOLD: int = 5
    CB_COOLDOWN_MS: int = 30000
    CB_SUCCESS_THRESHOLD: int = 2

    # 선택 — Retry
    MAX_RETRY_COUNT: int = 3
    RETRY_BASE_DELAY_MS: int = 1000
    RETRY_BACKOFF_MULTIPLIER: int = 2

    # 선택 — Rate Limiter
    RATE_LIMIT_EMAIL_PER_SEC: int = 10
    RATE_LIMIT_SMS_PER_SEC: int = 5
    RATE_LIMIT_WEBHOOK_PER_SEC: int = 20
    RATE_LIMIT_MAX_WAIT_MS: int = 10000

    # 선택 — Mock Delay
    MOCK_DELAY_MIN_MS: int = 100
    MOCK_DELAY_MAX_MS: int = 500


def load_settings() -> Settings:
    """환경 변수를 로드하여 Settings 인스턴스를 반환한다.

    필수 변수 누락 시 에러 로그를 출력하고 프로세스를 종료한다 (Fail-fast).
    """
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as e:
        missing = [
            err["loc"][0]
            for err in e.errors()
            if err["type"] == "missing"
        ]
        if missing:
            logger.error("필수 환경 변수 누락: %s", ", ".join(str(m) for m in missing))
        else:
            logger.error("환경 변수 검증 실패: %s", e)
        sys.exit(1)
