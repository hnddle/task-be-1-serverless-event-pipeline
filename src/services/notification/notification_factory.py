"""Notification Strategy 팩토리.

채널 이름에 따라 적절한 NotificationStrategy 구현체를 생성한다.

SPEC.md §4.2 참조.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.services.notification.email_strategy import EmailStrategy
from src.services.notification.notification_strategy import (
    NotificationResult,
    NotificationStrategy,
)
from src.services.notification.sms_strategy import SmsStrategy
from src.services.notification.webhook_strategy import WebhookStrategy

if TYPE_CHECKING:
    from src.shared.config import Settings

logger = logging.getLogger(__name__)

# 지원하는 채널 목록
SUPPORTED_CHANNELS = {"email", "sms", "webhook"}


class NotificationFactory:
    """채널별 NotificationStrategy 인스턴스를 생성하는 팩토리."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create(self, channel: str) -> NotificationStrategy:
        """채널에 해당하는 Strategy를 생성한다.

        Args:
            channel: 알림 채널 (email, sms, webhook).

        Returns:
            NotificationStrategy 구현체.

        Raises:
            ValueError: 지원하지 않는 채널인 경우.
        """
        if channel == "email":
            return EmailStrategy(self._settings)
        if channel == "sms":
            return SmsStrategy(self._settings)
        if channel == "webhook":
            return WebhookStrategy(self._settings)

        supported = ", ".join(sorted(SUPPORTED_CHANNELS))
        msg = f"지원하지 않는 채널: '{channel}'. 지원: {supported}"
        raise ValueError(msg)

    async def send_notification(self, channel: str, notification: dict[str, object]) -> NotificationResult:
        """채널에 맞는 Strategy로 알림을 발송한다.

        지원하지 않는 채널이면 failed 결과를 반환하고 에러 로그를 남긴다.
        """
        try:
            strategy = self.create(channel)
            return await strategy.send(notification)
        except ValueError:
            logger.error("지원하지 않는 채널: %s", channel)
            return NotificationResult(
                success=False,
                channel=channel,
                provider="unknown",
                message=f"Unsupported channel: {channel}",
            )
