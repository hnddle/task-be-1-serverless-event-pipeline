"""알림 발송 Strategy 인터페이스.

채널(email, sms, webhook)별 발송 전략을 추상화한다.

SPEC.md §4.2 참조.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class NotificationResult:
    """알림 발송 결과."""

    success: bool
    channel: str
    provider: str
    message: str = ""
    duration_ms: float = 0.0


class NotificationStrategy(ABC):
    """알림 발송 Strategy 인터페이스.

    각 채널(email, sms, webhook)별 구현체가 이 ABC를 상속한다.
    """

    @abstractmethod
    async def send(self, notification: dict[str, object]) -> NotificationResult:
        """알림을 발송한다.

        Args:
            notification: 발송할 알림 데이터.

        Returns:
            발송 결과.
        """

    @abstractmethod
    def get_channel_name(self) -> str:
        """채널 이름을 반환한다."""

    @abstractmethod
    def get_provider_name(self) -> str:
        """프로바이더 이름을 반환한다."""
