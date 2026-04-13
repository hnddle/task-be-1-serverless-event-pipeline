"""Azure Event Grid 어댑터.

azure-eventgrid SDK를 래핑하여 MessageBroker 인터페이스를 구현한다.

SPEC.md §4.1 참조.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from azure.eventgrid import EventGridEvent
from azure.eventgrid.aio import EventGridPublisherClient

from src.services.message_broker.message_broker import MessageBroker

if TYPE_CHECKING:
    from azure.core.credentials import AzureKeyCredential

logger = logging.getLogger(__name__)


class EventGridAdapter(MessageBroker):
    """Azure Event Grid MessageBroker 어댑터.

    Event Grid Topic에 이벤트를 발행한다.
    """

    def __init__(self, endpoint: str, credential: AzureKeyCredential) -> None:
        self._endpoint = endpoint
        self._credential = credential
        self._client = EventGridPublisherClient(endpoint, credential)

    async def publish(self, event: dict[str, Any]) -> None:
        """이벤트를 Event Grid Topic에 발행한다."""
        eg_event = EventGridEvent(
            event_type="NotificationPipeline.EventCreated",
            subject=f"/events/{event.get('id', 'unknown')}",
            data=event,
            data_version="1.0",
        )
        await self._client.send([eg_event])
        logger.info(
            "Event Grid 이벤트 발행 완료: %s",
            event.get("id", "unknown"),
        )

    def get_broker_name(self) -> str:
        """브로커 이름을 반환한다."""
        return "EventGrid"

    async def close(self) -> None:
        """클라이언트 연결을 종료한다."""
        await self._client.close()
