"""Email 알림 Mock 발송 Strategy.

실제 발송 대신 랜덤 딜레이 후 성공을 반환한다.

SPEC.md §4.2 참조.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import TYPE_CHECKING

from src.services.notification.notification_strategy import (
    NotificationResult,
    NotificationStrategy,
)
from src.shared.logger import log_with_context

if TYPE_CHECKING:
    from src.shared.config import Settings

logger = logging.getLogger(__name__)


class EmailStrategy(NotificationStrategy):
    """Email Mock 발송 Strategy.

    MOCK_DELAY_MIN_MS ~ MOCK_DELAY_MAX_MS 범위 랜덤 딜레이 후 성공 반환.
    provider는 NOTIFICATION_EMAIL_PROVIDER 환경 변수에서 결정.
    """

    def __init__(self, settings: Settings) -> None:
        self._provider = settings.NOTIFICATION_EMAIL_PROVIDER
        self._delay_min_ms = settings.MOCK_DELAY_MIN_MS
        self._delay_max_ms = settings.MOCK_DELAY_MAX_MS

    async def send(self, notification: dict[str, object]) -> NotificationResult:
        """Email Mock 발송."""
        delay_ms = random.randint(self._delay_min_ms, self._delay_max_ms)
        start = time.monotonic()

        await asyncio.sleep(delay_ms / 1000)

        duration_ms = (time.monotonic() - start) * 1000

        log_with_context(
            logger,
            logging.INFO,
            "Email Mock 발송 완료",
            channel="email",
            provider=self._provider,
            delay_ms=delay_ms,
            duration_ms=round(duration_ms, 2),
            event_id=notification.get("event_id", "unknown"),
        )

        return NotificationResult(
            success=True,
            channel="email",
            provider=self._provider,
            message=f"Mock email sent (delay: {delay_ms}ms)",
            duration_ms=round(duration_ms, 2),
        )

    def get_channel_name(self) -> str:
        return "email"

    def get_provider_name(self) -> str:
        return self._provider
