"""Message Broker 팩토리 및 어댑터 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.message_broker.event_grid_adapter import EventGridAdapter
from src.services.message_broker.message_broker import MessageBroker
from src.services.message_broker.message_broker_factory import (
    SUPPORTED_BROKER_TYPES,
    MessageBrokerFactory,
)
from src.shared.config import Settings

REQUIRED_ENV = {
    "QUEUE_SERVICE_TYPE": "EVENT_GRID",
    "NOTIFICATION_EMAIL_PROVIDER": "sendgrid",
    "NOTIFICATION_SMS_PROVIDER": "twilio",
    "WEBHOOK_URL": "https://example.com/webhook",
    "COSMOS_DB_ENDPOINT": "https://localhost:8081",
    "COSMOS_DB_KEY": "test-key",
    "COSMOS_DB_DATABASE": "test-db",
}


@pytest.fixture()
def settings() -> Settings:
    return Settings(**REQUIRED_ENV)  # type: ignore[arg-type]


class TestMessageBrokerABC:
    """MessageBroker ABC 테스트."""

    def test_cannot_instantiate_abc(self) -> None:
        """MessageBroker ABC를 직접 인스턴스화할 수 없다."""
        with pytest.raises(TypeError):
            MessageBroker()  # type: ignore[abstract]

    def test_event_grid_adapter_is_message_broker(self) -> None:
        """EventGridAdapter가 MessageBroker의 하위 클래스이다."""
        assert issubclass(EventGridAdapter, MessageBroker)


class TestMessageBrokerFactory:
    """MessageBrokerFactory 테스트."""

    @patch("src.services.message_broker.event_grid_adapter.EventGridPublisherClient")
    @patch("src.services.message_broker.message_broker_factory.AzureKeyCredential")
    def test_create_event_grid(self, mock_cred: MagicMock, mock_client: MagicMock, settings: Settings) -> None:
        """EVENT_GRID 타입으로 EventGridAdapter를 생성한다."""
        broker = MessageBrokerFactory.create(settings)
        assert isinstance(broker, EventGridAdapter)

    @patch("src.services.message_broker.event_grid_adapter.EventGridPublisherClient")
    @patch("src.services.message_broker.message_broker_factory.AzureKeyCredential")
    def test_create_event_grid_case_insensitive(self, mock_cred: MagicMock, mock_client: MagicMock) -> None:
        """QUEUE_SERVICE_TYPE 비교가 대소문자를 구분하지 않는다."""
        env = {**REQUIRED_ENV, "QUEUE_SERVICE_TYPE": "event_grid"}
        s = Settings(**env)  # type: ignore[arg-type]
        broker = MessageBrokerFactory.create(s)
        assert isinstance(broker, EventGridAdapter)

    def test_unsupported_type_raises_value_error(self) -> None:
        """지원하지 않는 QUEUE_SERVICE_TYPE이면 ValueError가 발생한다."""
        env = {**REQUIRED_ENV, "QUEUE_SERVICE_TYPE": "KAFKA"}
        s = Settings(**env)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="지원하지 않는 QUEUE_SERVICE_TYPE"):
            MessageBrokerFactory.create(s)

    def test_unsupported_type_error_includes_supported(self) -> None:
        """에러 메시지에 지원하는 타입 목록이 포함된다."""
        env = {**REQUIRED_ENV, "QUEUE_SERVICE_TYPE": "SNS"}
        s = Settings(**env)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="EVENT_GRID"):
            MessageBrokerFactory.create(s)

    def test_supported_broker_types_contains_event_grid(self) -> None:
        """SUPPORTED_BROKER_TYPES에 EVENT_GRID가 포함되어 있다."""
        assert "EVENT_GRID" in SUPPORTED_BROKER_TYPES


class TestEventGridAdapter:
    """EventGridAdapter 테스트."""

    @patch("src.services.message_broker.event_grid_adapter.EventGridPublisherClient")
    def test_get_broker_name(self, mock_client_cls: MagicMock) -> None:
        """get_broker_name이 'EventGrid'를 반환한다."""
        mock_cred = MagicMock()
        adapter = EventGridAdapter(endpoint="https://example.com", credential=mock_cred)
        assert adapter.get_broker_name() == "EventGrid"

    @pytest.mark.asyncio()
    @patch("src.services.message_broker.event_grid_adapter.EventGridPublisherClient")
    async def test_publish_sends_event(self, mock_client_cls: MagicMock) -> None:
        """publish가 Event Grid 클라이언트에 이벤트를 전달한다."""
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        mock_cred = MagicMock()
        adapter = EventGridAdapter(endpoint="https://example.com", credential=mock_cred)

        event = {"id": "test-id-123", "event_type": "appointment_confirmed"}
        await adapter.publish(event)

        mock_client.send.assert_awaited_once()
        sent_events = mock_client.send.call_args[0][0]
        assert len(sent_events) == 1

    @pytest.mark.asyncio()
    @patch("src.services.message_broker.event_grid_adapter.EventGridPublisherClient")
    async def test_publish_event_has_correct_type(self, mock_client_cls: MagicMock) -> None:
        """발행된 이벤트의 event_type이 올바르다."""
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        mock_cred = MagicMock()
        adapter = EventGridAdapter(endpoint="https://example.com", credential=mock_cred)

        event = {"id": "test-id-456", "event_type": "claim_completed"}
        await adapter.publish(event)

        sent_events = mock_client.send.call_args[0][0]
        eg_event = sent_events[0]
        assert eg_event.event_type == "NotificationPipeline.EventCreated"
        assert eg_event.subject == "/events/test-id-456"
        assert eg_event.data == event

    @pytest.mark.asyncio()
    @patch("src.services.message_broker.event_grid_adapter.EventGridPublisherClient")
    async def test_close_closes_client(self, mock_client_cls: MagicMock) -> None:
        """close가 클라이언트를 닫는다."""
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        mock_cred = MagicMock()
        adapter = EventGridAdapter(endpoint="https://example.com", credential=mock_cred)
        await adapter.close()

        mock_client.close.assert_awaited_once()

    def test_adapter_implements_message_broker(self) -> None:
        """EventGridAdapter가 MessageBroker 인터페이스의 모든 메서드를 구현한다."""
        assert hasattr(EventGridAdapter, "publish")
        assert hasattr(EventGridAdapter, "get_broker_name")
