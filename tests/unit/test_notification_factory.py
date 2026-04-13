"""Notification Strategy 팩토리 및 Strategy 테스트."""

from __future__ import annotations

import pytest

from src.services.notification.email_strategy import EmailStrategy
from src.services.notification.notification_factory import (
    SUPPORTED_CHANNELS,
    NotificationFactory,
)
from src.services.notification.notification_strategy import (
    NotificationResult,
    NotificationStrategy,
)
from src.services.notification.sms_strategy import SmsStrategy
from src.services.notification.webhook_strategy import WebhookStrategy
from src.shared.config import Settings

REQUIRED_ENV = {
    "QUEUE_SERVICE_TYPE": "EVENT_GRID",
    "NOTIFICATION_EMAIL_PROVIDER": "sendgrid",
    "NOTIFICATION_SMS_PROVIDER": "twilio",
    "WEBHOOK_URL": "https://example.com/webhook",
    "COSMOS_DB_ENDPOINT": "https://localhost:8081",
    "COSMOS_DB_KEY": "test-key",
    "COSMOS_DB_DATABASE": "test-db",
    "MOCK_DELAY_MIN_MS": "10",
    "MOCK_DELAY_MAX_MS": "20",
}

SAMPLE_NOTIFICATION = {"event_id": "test-evt-1", "patient_id": "P-001"}


@pytest.fixture()
def settings() -> Settings:
    return Settings(**REQUIRED_ENV)  # type: ignore[arg-type]


@pytest.fixture()
def factory(settings: Settings) -> NotificationFactory:
    return NotificationFactory(settings)


class TestNotificationStrategyABC:
    """NotificationStrategy ABC 테스트."""

    def test_cannot_instantiate_abc(self) -> None:
        """NotificationStrategy ABC를 직접 인스턴스화할 수 없다."""
        with pytest.raises(TypeError):
            NotificationStrategy()  # type: ignore[abstract]

    def test_email_is_notification_strategy(self) -> None:
        assert issubclass(EmailStrategy, NotificationStrategy)

    def test_sms_is_notification_strategy(self) -> None:
        assert issubclass(SmsStrategy, NotificationStrategy)

    def test_webhook_is_notification_strategy(self) -> None:
        assert issubclass(WebhookStrategy, NotificationStrategy)


class TestNotificationFactory:
    """NotificationFactory 테스트."""

    def test_create_email_strategy(self, factory: NotificationFactory) -> None:
        """email 채널로 EmailStrategy를 생성한다."""
        strategy = factory.create("email")
        assert isinstance(strategy, EmailStrategy)

    def test_create_sms_strategy(self, factory: NotificationFactory) -> None:
        """sms 채널로 SmsStrategy를 생성한다."""
        strategy = factory.create("sms")
        assert isinstance(strategy, SmsStrategy)

    def test_create_webhook_strategy(self, factory: NotificationFactory) -> None:
        """webhook 채널로 WebhookStrategy를 생성한다."""
        strategy = factory.create("webhook")
        assert isinstance(strategy, WebhookStrategy)

    def test_unsupported_channel_raises(self, factory: NotificationFactory) -> None:
        """지원하지 않는 채널이면 ValueError가 발생한다."""
        with pytest.raises(ValueError, match="지원하지 않는 채널"):
            factory.create("push")

    def test_supported_channels(self) -> None:
        """SUPPORTED_CHANNELS에 3개 채널이 포함되어 있다."""
        assert {"email", "sms", "webhook"} == SUPPORTED_CHANNELS

    @pytest.mark.asyncio()
    async def test_send_notification_all_channels(self, factory: NotificationFactory) -> None:
        """3개 채널 전달 시 3개 Strategy 각각 실행된다."""
        results = []
        for channel in ["email", "sms", "webhook"]:
            result = await factory.send_notification(channel, SAMPLE_NOTIFICATION)
            results.append(result)

        assert len(results) == 3
        assert all(r.success for r in results)
        channels = {r.channel for r in results}
        assert channels == {"email", "sms", "webhook"}

    @pytest.mark.asyncio()
    async def test_send_unsupported_channel_returns_failed(self, factory: NotificationFactory) -> None:
        """지원하지 않는 채널은 failed 결과를 반환한다."""
        result = await factory.send_notification("push", SAMPLE_NOTIFICATION)
        assert not result.success
        assert result.channel == "push"
        assert "Unsupported" in result.message


class TestEmailStrategy:
    """EmailStrategy 테스트."""

    @pytest.mark.asyncio()
    async def test_send_returns_success(self, settings: Settings) -> None:
        """Email 발송이 성공 결과를 반환한다."""
        strategy = EmailStrategy(settings)
        result = await strategy.send(SAMPLE_NOTIFICATION)
        assert result.success
        assert result.channel == "email"
        assert result.provider == "sendgrid"
        assert isinstance(result, NotificationResult)

    @pytest.mark.asyncio()
    async def test_delay_within_range(self, settings: Settings) -> None:
        """Mock 딜레이가 환경 변수 범위(10~20ms) 내이다."""
        strategy = EmailStrategy(settings)
        result = await strategy.send(SAMPLE_NOTIFICATION)
        assert result.duration_ms >= 10
        assert result.duration_ms < 100  # 충분한 여유

    def test_get_channel_name(self, settings: Settings) -> None:
        strategy = EmailStrategy(settings)
        assert strategy.get_channel_name() == "email"

    def test_get_provider_name(self, settings: Settings) -> None:
        strategy = EmailStrategy(settings)
        assert strategy.get_provider_name() == "sendgrid"


class TestSmsStrategy:
    """SmsStrategy 테스트."""

    @pytest.mark.asyncio()
    async def test_send_returns_success(self, settings: Settings) -> None:
        """SMS 발송이 성공 결과를 반환한다."""
        strategy = SmsStrategy(settings)
        result = await strategy.send(SAMPLE_NOTIFICATION)
        assert result.success
        assert result.channel == "sms"
        assert result.provider == "twilio"

    @pytest.mark.asyncio()
    async def test_delay_within_range(self, settings: Settings) -> None:
        """Mock 딜레이가 환경 변수 범위 내이다."""
        strategy = SmsStrategy(settings)
        result = await strategy.send(SAMPLE_NOTIFICATION)
        assert result.duration_ms >= 10

    def test_get_channel_name(self, settings: Settings) -> None:
        strategy = SmsStrategy(settings)
        assert strategy.get_channel_name() == "sms"

    def test_get_provider_name(self, settings: Settings) -> None:
        strategy = SmsStrategy(settings)
        assert strategy.get_provider_name() == "twilio"


class TestWebhookStrategy:
    """WebhookStrategy 테스트."""

    @pytest.mark.asyncio()
    async def test_send_returns_success(self, settings: Settings) -> None:
        """Webhook 발송이 성공 결과를 반환한다."""
        strategy = WebhookStrategy(settings)
        result = await strategy.send(SAMPLE_NOTIFICATION)
        assert result.success
        assert result.channel == "webhook"
        assert result.provider == "webhook"

    @pytest.mark.asyncio()
    async def test_delay_within_range(self, settings: Settings) -> None:
        """Mock 딜레이가 환경 변수 범위 내이다."""
        strategy = WebhookStrategy(settings)
        result = await strategy.send(SAMPLE_NOTIFICATION)
        assert result.duration_ms >= 10

    def test_get_channel_name(self, settings: Settings) -> None:
        strategy = WebhookStrategy(settings)
        assert strategy.get_channel_name() == "webhook"

    def test_get_provider_name(self, settings: Settings) -> None:
        strategy = WebhookStrategy(settings)
        assert strategy.get_provider_name() == "webhook"
