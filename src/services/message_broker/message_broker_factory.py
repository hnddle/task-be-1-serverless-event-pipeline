"""Message Broker 팩토리.

환경 변수 QUEUE_SERVICE_TYPE에 따라 적절한 MessageBroker 어댑터를 생성한다.

SPEC.md §4.1 참조.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from azure.core.credentials import AzureKeyCredential

from src.services.message_broker.event_grid_adapter import EventGridAdapter

if TYPE_CHECKING:
    from src.services.message_broker.message_broker import MessageBroker
    from src.shared.config import Settings

# 지원하는 브로커 타입
SUPPORTED_BROKER_TYPES = {"EVENT_GRID"}


class MessageBrokerFactory:
    """QUEUE_SERVICE_TYPE에 따라 MessageBroker 인스턴스를 생성하는 팩토리."""

    @staticmethod
    def create(settings: Settings) -> MessageBroker:
        """환경 변수 기반으로 MessageBroker 인스턴스를 생성한다.

        Args:
            settings: 애플리케이션 설정.

        Returns:
            MessageBroker 구현체 인스턴스.

        Raises:
            ValueError: 지원하지 않는 QUEUE_SERVICE_TYPE인 경우.
        """
        broker_type = settings.QUEUE_SERVICE_TYPE.upper()

        if broker_type == "EVENT_GRID":
            endpoint = getattr(settings, "EVENT_GRID_ENDPOINT", "")
            key = getattr(settings, "EVENT_GRID_KEY", "")
            credential = AzureKeyCredential(key)
            return EventGridAdapter(endpoint=endpoint, credential=credential)

        supported = ", ".join(sorted(SUPPORTED_BROKER_TYPES))
        msg = f"지원하지 않는 QUEUE_SERVICE_TYPE: '{settings.QUEUE_SERVICE_TYPE}'. 지원: {supported}"
        raise ValueError(msg)
