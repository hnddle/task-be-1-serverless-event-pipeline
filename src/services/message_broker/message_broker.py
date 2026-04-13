"""Message Broker 추상 인터페이스.

메시지 큐를 교체 가능한 Backing Service로 취급한다.
환경 변수 변경만으로 큐 서비스를 교체할 수 있다.

SPEC.md §4.1 참조.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MessageBroker(ABC):
    """Message Broker 인터페이스.

    모든 메시지 브로커 어댑터는 이 ABC를 구현해야 한다.
    """

    @abstractmethod
    async def publish(self, event: dict[str, Any]) -> None:
        """이벤트를 메시지 큐에 발행한다.

        Args:
            event: 발행할 이벤트 데이터.

        Raises:
            Exception: 발행 실패 시.
        """

    @abstractmethod
    def get_broker_name(self) -> str:
        """현재 활성 브로커의 이름을 반환한다.

        Returns:
            브로커 이름 (예: "EventGrid", "PubSub").
        """
