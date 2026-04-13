"""Event Consumer 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.functions.event_consumer import _determine_final_status, event_consumer
from src.services.notification.notification_strategy import NotificationResult


def _make_event_grid_event(overrides: dict | None = None) -> MagicMock:
    """테스트용 EventGridEvent를 생성한다."""
    data = {
        "id": "evt-001",
        "clinic_id": "CLINIC_123",
        "correlation_id": "cid-001",
        "status": "queued",
        "notifications": [
            {"channel": "email", "provider": "sendgrid", "status": "pending"},
            {"channel": "sms", "provider": "twilio", "status": "pending"},
        ],
    }
    if overrides:
        data.update(overrides)

    event = MagicMock()
    event.get_json.return_value = data
    return event


class TestDetermineFinalStatus:
    """_determine_final_status 헬퍼 테스트."""

    def test_all_success_returns_completed(self) -> None:
        notifications = [
            {"status": "success"},
            {"status": "success"},
        ]
        assert _determine_final_status(notifications) == "completed"

    def test_partial_success_returns_partially_completed(self) -> None:
        notifications = [
            {"status": "success"},
            {"status": "failed"},
        ]
        assert _determine_final_status(notifications) == "partially_completed"

    def test_all_failed_returns_failed(self) -> None:
        notifications = [
            {"status": "failed"},
            {"status": "failed"},
        ]
        assert _determine_final_status(notifications) == "failed"

    def test_single_success_returns_completed(self) -> None:
        notifications = [{"status": "success"}]
        assert _determine_final_status(notifications) == "completed"

    def test_single_failed_returns_failed(self) -> None:
        notifications = [{"status": "failed"}]
        assert _determine_final_status(notifications) == "failed"


class TestEventConsumer:
    """Event Consumer Function 테스트."""

    @pytest.mark.asyncio()
    @patch("src.functions.event_consumer._get_settings")
    @patch("src.functions.event_consumer.get_events_container")
    @patch("src.functions.event_consumer.NotificationFactory")
    async def test_all_channels_success_sets_completed(
        self,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """전체 채널 성공 시 completed로 갱신된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "queued",
            "notifications": [
                {"channel": "email", "provider": "sendgrid", "status": "pending"},
                {"channel": "sms", "provider": "twilio", "status": "pending"},
            ],
        }

        mock_factory = MagicMock()
        mock_factory_cls.return_value = mock_factory
        mock_factory.send_notification = AsyncMock(
            return_value=NotificationResult(success=True, channel="email", provider="sendgrid", duration_ms=50.0)
        )

        event = _make_event_grid_event()
        await event_consumer(event)

        # processing 갱신 + 최종 갱신 = 2번 patch_item
        assert mock_container.patch_item.await_count == 2

        # 최종 상태 확인
        final_call = mock_container.patch_item.call_args_list[-1]
        ops = final_call.kwargs["patch_operations"]
        status_op = next(op for op in ops if op["path"] == "/status")
        assert status_op["value"] == "completed"

    @pytest.mark.asyncio()
    @patch("src.functions.event_consumer._get_settings")
    @patch("src.functions.event_consumer.get_events_container")
    @patch("src.functions.event_consumer.NotificationFactory")
    async def test_partial_success_sets_partially_completed(
        self,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """일부 채널만 성공 시 partially_completed로 갱신된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "queued",
            "notifications": [
                {"channel": "email", "provider": "sendgrid", "status": "pending"},
                {"channel": "sms", "provider": "twilio", "status": "pending"},
            ],
        }

        mock_factory = MagicMock()
        mock_factory_cls.return_value = mock_factory

        # email 성공, sms 실패
        mock_factory.send_notification = AsyncMock(
            side_effect=[
                NotificationResult(success=True, channel="email", provider="sendgrid"),
                NotificationResult(success=False, channel="sms", provider="twilio", message="Timeout"),
            ]
        )

        event = _make_event_grid_event()
        await event_consumer(event)

        final_call = mock_container.patch_item.call_args_list[-1]
        ops = final_call.kwargs["patch_operations"]
        status_op = next(op for op in ops if op["path"] == "/status")
        assert status_op["value"] == "partially_completed"

    @pytest.mark.asyncio()
    @patch("src.functions.event_consumer._get_settings")
    @patch("src.functions.event_consumer.get_events_container")
    @patch("src.functions.event_consumer.NotificationFactory")
    async def test_all_failed_sets_failed(
        self,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """전체 채널 실패 시 failed로 갱신된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "queued",
            "notifications": [
                {"channel": "email", "provider": "sendgrid", "status": "pending"},
            ],
        }

        mock_factory = MagicMock()
        mock_factory_cls.return_value = mock_factory
        mock_factory.send_notification = AsyncMock(
            return_value=NotificationResult(success=False, channel="email", provider="sendgrid", message="Error")
        )

        event = _make_event_grid_event()
        await event_consumer(event)

        final_call = mock_container.patch_item.call_args_list[-1]
        ops = final_call.kwargs["patch_operations"]
        status_op = next(op for op in ops if op["path"] == "/status")
        assert status_op["value"] == "failed"

    @pytest.mark.asyncio()
    @patch("src.functions.event_consumer._get_settings")
    @patch("src.functions.event_consumer.get_events_container")
    @patch("src.functions.event_consumer.NotificationFactory")
    async def test_already_success_channel_is_skipped(
        self,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """이미 success인 채널은 재발송하지 않는다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "queued",
            "notifications": [
                {"channel": "email", "provider": "sendgrid", "status": "success"},
                {"channel": "sms", "provider": "twilio", "status": "pending"},
            ],
        }

        mock_factory = MagicMock()
        mock_factory_cls.return_value = mock_factory
        mock_factory.send_notification = AsyncMock(
            return_value=NotificationResult(success=True, channel="sms", provider="twilio")
        )

        event = _make_event_grid_event()
        await event_consumer(event)

        # sms만 발송됨 (email은 스킵)
        mock_factory.send_notification.assert_awaited_once()
        call_args = mock_factory.send_notification.call_args
        assert call_args[0][0] == "sms"

    @pytest.mark.asyncio()
    @patch("src.functions.event_consumer._get_settings")
    @patch("src.functions.event_consumer.get_events_container")
    @patch("src.functions.event_consumer.NotificationFactory")
    async def test_already_completed_event_is_skipped(
        self,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """이미 완료된 이벤트는 재처리하지 않는다 (Idempotency)."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "completed",
            "notifications": [
                {"channel": "email", "provider": "sendgrid", "status": "success"},
            ],
        }

        mock_factory = MagicMock()
        mock_factory_cls.return_value = mock_factory

        event = _make_event_grid_event()
        await event_consumer(event)

        # 이미 완료 → patch_item 호출 없음
        mock_container.patch_item.assert_not_awaited()
        mock_factory.send_notification.assert_not_called()

    @pytest.mark.asyncio()
    @patch("src.functions.event_consumer._get_settings")
    @patch("src.functions.event_consumer.get_events_container")
    @patch("src.functions.event_consumer.NotificationFactory")
    async def test_event_read_failure_returns_early(
        self,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """이벤트 조회 실패 시 조기 리턴한다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.side_effect = RuntimeError("DB unavailable")

        mock_factory = MagicMock()
        mock_factory_cls.return_value = mock_factory

        event = _make_event_grid_event()
        await event_consumer(event)

        mock_container.patch_item.assert_not_awaited()

    @pytest.mark.asyncio()
    @patch("src.functions.event_consumer._get_settings")
    @patch("src.functions.event_consumer.get_events_container")
    @patch("src.functions.event_consumer.NotificationFactory")
    async def test_processing_status_is_set_before_sending(
        self,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """발송 전 status가 processing으로 갱신된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "queued",
            "notifications": [
                {"channel": "email", "provider": "sendgrid", "status": "pending"},
            ],
        }

        mock_factory = MagicMock()
        mock_factory_cls.return_value = mock_factory
        mock_factory.send_notification = AsyncMock(
            return_value=NotificationResult(success=True, channel="email", provider="sendgrid")
        )

        event = _make_event_grid_event()
        await event_consumer(event)

        # 첫 번째 patch_item = processing 갱신
        first_call = mock_container.patch_item.call_args_list[0]
        ops = first_call.kwargs["patch_operations"]
        status_op = next(op for op in ops if op["path"] == "/status")
        assert status_op["value"] == "processing"

    @pytest.mark.asyncio()
    @patch("src.functions.event_consumer._get_settings")
    @patch("src.functions.event_consumer.get_events_container")
    @patch("src.functions.event_consumer.NotificationFactory")
    async def test_notifications_result_saved_to_cosmos(
        self,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """채널별 발송 결과가 Cosmos DB에 기록된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "queued",
            "notifications": [
                {"channel": "email", "provider": "sendgrid", "status": "pending"},
            ],
        }

        mock_factory = MagicMock()
        mock_factory_cls.return_value = mock_factory
        mock_factory.send_notification = AsyncMock(
            return_value=NotificationResult(success=True, channel="email", provider="sendgrid", duration_ms=42.0)
        )

        event = _make_event_grid_event()
        await event_consumer(event)

        # 최종 patch_item에서 notifications 확인
        final_call = mock_container.patch_item.call_args_list[-1]
        ops = final_call.kwargs["patch_operations"]
        notif_op = next(op for op in ops if op["path"] == "/notifications")
        assert notif_op["value"][0]["status"] == "success"
        assert notif_op["value"][0]["sent_at"] is not None
