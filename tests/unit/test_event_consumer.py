"""Event Consumer 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.functions.event_consumer import _determine_final_status, event_consumer
from src.services.circuit_breaker import CircuitOpenError
from src.services.notification.notification_strategy import NotificationResult
from src.services.rate_limiter import RateLimitExceededError
from src.services.retry_service import MaxRetryExceededError


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


# 공통 patch 대상
_PATCHES = [
    "src.functions.event_consumer._get_settings",
    "src.functions.event_consumer.get_events_container",
    "src.functions.event_consumer.NotificationFactory",
    "src.functions.event_consumer.CircuitBreaker",
    "src.functions.event_consumer.RateLimiter",
    "src.functions.event_consumer.RetryService",
    "src.functions.event_consumer.DlqService",
]


def _setup_mocks(
    mock_dlq_cls: MagicMock,
    mock_retry_cls: MagicMock,
    mock_rl_cls: MagicMock,
    mock_cb_cls: MagicMock,
    mock_factory_cls: MagicMock,
    mock_container_fn: MagicMock,
) -> tuple[AsyncMock, MagicMock, MagicMock, MagicMock, MagicMock, AsyncMock]:
    """공통 mock 설정을 수행한다."""
    mock_container = AsyncMock()
    mock_container_fn.return_value = mock_container

    mock_factory = MagicMock()
    mock_factory_cls.return_value = mock_factory

    mock_cb = AsyncMock()
    mock_cb_cls.return_value = mock_cb

    mock_rl = AsyncMock()
    mock_rl_cls.return_value = mock_rl

    mock_retry = MagicMock()
    mock_retry_cls.return_value = mock_retry

    mock_dlq = AsyncMock()
    mock_dlq_cls.return_value = mock_dlq

    return mock_container, mock_factory, mock_cb, mock_rl, mock_retry, mock_dlq


class TestDetermineFinalStatus:
    """_determine_final_status 헬퍼 테스트."""

    def test_all_success_returns_completed(self) -> None:
        assert _determine_final_status([{"status": "success"}, {"status": "success"}]) == "completed"

    def test_partial_success_returns_partially_completed(self) -> None:
        assert _determine_final_status([{"status": "success"}, {"status": "failed"}]) == "partially_completed"

    def test_all_failed_returns_failed(self) -> None:
        assert _determine_final_status([{"status": "failed"}, {"status": "failed"}]) == "failed"

    def test_single_success_returns_completed(self) -> None:
        assert _determine_final_status([{"status": "success"}]) == "completed"

    def test_single_failed_returns_failed(self) -> None:
        assert _determine_final_status([{"status": "failed"}]) == "failed"


class TestEventConsumer:
    """Event Consumer Function 테스트."""

    @pytest.mark.asyncio()
    @patch(*_PATCHES[:1])  # _get_settings
    @patch(*_PATCHES[1:2])  # get_events_container
    @patch(*_PATCHES[2:3])  # NotificationFactory
    @patch(*_PATCHES[3:4])  # CircuitBreaker
    @patch(*_PATCHES[4:5])  # RateLimiter
    @patch(*_PATCHES[5:6])  # RetryService
    @patch(*_PATCHES[6:7])  # DlqService
    async def test_all_channels_success_sets_completed(
        self,
        mock_dlq_cls: MagicMock,
        mock_retry_cls: MagicMock,
        mock_rl_cls: MagicMock,
        mock_cb_cls: MagicMock,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """전체 채널 성공 시 completed로 갱신된다."""
        mock_container, mock_factory, _mock_cb, _mock_rl, mock_retry, _mock_dlq = _setup_mocks(
            mock_dlq_cls, mock_retry_cls, mock_rl_cls, mock_cb_cls, mock_factory_cls, mock_container_fn
        )
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "queued",
            "notifications": [
                {"channel": "email", "provider": "sendgrid", "status": "pending"},
                {"channel": "sms", "provider": "twilio", "status": "pending"},
            ],
        }
        mock_factory.send_notification = AsyncMock(
            return_value=NotificationResult(success=True, channel="email", provider="sendgrid", duration_ms=50.0)
        )
        mock_retry.execute_with_retry = AsyncMock(
            return_value={"success": True, "provider": "sendgrid", "message": "", "duration_ms": 50.0}
        )

        await event_consumer(_make_event_grid_event())

        final_call = mock_container.patch_item.call_args_list[-1]
        ops = final_call.kwargs["patch_operations"]
        status_op = next(op for op in ops if op["path"] == "/status")
        assert status_op["value"] == "completed"

    @pytest.mark.asyncio()
    @patch(*_PATCHES[:1])
    @patch(*_PATCHES[1:2])
    @patch(*_PATCHES[2:3])
    @patch(*_PATCHES[3:4])
    @patch(*_PATCHES[4:5])
    @patch(*_PATCHES[5:6])
    @patch(*_PATCHES[6:7])
    async def test_circuit_open_sets_failed_and_sends_to_dlq(
        self,
        mock_dlq_cls: MagicMock,
        mock_retry_cls: MagicMock,
        mock_rl_cls: MagicMock,
        mock_cb_cls: MagicMock,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """Circuit Open → 즉시 실패 + DLQ 이동."""
        mock_container, _mock_factory, mock_cb, _mock_rl, mock_retry, mock_dlq = _setup_mocks(
            mock_dlq_cls, mock_retry_cls, mock_rl_cls, mock_cb_cls, mock_factory_cls, mock_container_fn
        )
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "queued",
            "event_type": "appointment_confirmed",
            "patient_id": "P-001",
            "notifications": [
                {"channel": "email", "provider": "sendgrid", "status": "pending"},
            ],
        }
        mock_cb.check_state.side_effect = CircuitOpenError("email:sendgrid")

        await event_consumer(_make_event_grid_event())

        mock_retry.execute_with_retry.assert_not_called()
        # DLQ에 저장
        mock_dlq.send_to_dlq.assert_awaited_once()
        dlq_call = mock_dlq.send_to_dlq.call_args.kwargs
        assert dlq_call["channel"] == "email"
        assert dlq_call["provider"] == "sendgrid"
        # 최종 상태: failed
        final_call = mock_container.patch_item.call_args_list[-1]
        ops = final_call.kwargs["patch_operations"]
        status_op = next(op for op in ops if op["path"] == "/status")
        assert status_op["value"] == "failed"

    @pytest.mark.asyncio()
    @patch(*_PATCHES[:1])
    @patch(*_PATCHES[1:2])
    @patch(*_PATCHES[2:3])
    @patch(*_PATCHES[3:4])
    @patch(*_PATCHES[4:5])
    @patch(*_PATCHES[5:6])
    @patch(*_PATCHES[6:7])
    async def test_rate_limit_exceeded_sets_failed_no_dlq(
        self,
        mock_dlq_cls: MagicMock,
        mock_retry_cls: MagicMock,
        mock_rl_cls: MagicMock,
        mock_cb_cls: MagicMock,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """Rate Limit 초과 → 실패 (DLQ 미이동, Circuit Breaker 미포함)."""
        mock_container, _mock_factory, mock_cb, _mock_rl, mock_retry, mock_dlq = _setup_mocks(
            mock_dlq_cls, mock_retry_cls, mock_rl_cls, mock_cb_cls, mock_factory_cls, mock_container_fn
        )
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "queued",
            "notifications": [
                {"channel": "email", "provider": "sendgrid", "status": "pending"},
            ],
        }
        mock_retry.execute_with_retry = AsyncMock(side_effect=RateLimitExceededError("email:sendgrid"))

        await event_consumer(_make_event_grid_event())

        mock_cb.record_failure.assert_not_awaited()
        mock_dlq.send_to_dlq.assert_not_awaited()
        final_call = mock_container.patch_item.call_args_list[-1]
        ops = final_call.kwargs["patch_operations"]
        status_op = next(op for op in ops if op["path"] == "/status")
        assert status_op["value"] == "failed"

    @pytest.mark.asyncio()
    @patch(*_PATCHES[:1])
    @patch(*_PATCHES[1:2])
    @patch(*_PATCHES[2:3])
    @patch(*_PATCHES[3:4])
    @patch(*_PATCHES[4:5])
    @patch(*_PATCHES[5:6])
    @patch(*_PATCHES[6:7])
    async def test_max_retry_exceeded_records_cb_failure_and_sends_to_dlq(
        self,
        mock_dlq_cls: MagicMock,
        mock_retry_cls: MagicMock,
        mock_rl_cls: MagicMock,
        mock_cb_cls: MagicMock,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """재시도 초과 → Circuit Breaker 실패 기록 + DLQ 이동."""
        mock_container, _mock_factory, mock_cb, _mock_rl, mock_retry, mock_dlq = _setup_mocks(
            mock_dlq_cls, mock_retry_cls, mock_rl_cls, mock_cb_cls, mock_factory_cls, mock_container_fn
        )
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "queued",
            "event_type": "claim_completed",
            "patient_id": "P-002",
            "notifications": [
                {"channel": "email", "provider": "sendgrid", "status": "pending"},
            ],
        }
        mock_retry.execute_with_retry = AsyncMock(
            side_effect=MaxRetryExceededError(retry_count=3, last_error="Timeout")
        )

        await event_consumer(_make_event_grid_event())

        mock_cb.record_failure.assert_awaited_once_with("email", "sendgrid")
        # DLQ에 저장
        mock_dlq.send_to_dlq.assert_awaited_once()
        dlq_call = mock_dlq.send_to_dlq.call_args.kwargs
        assert dlq_call["original_event_id"] == "evt-001"
        assert dlq_call["clinic_id"] == "CLINIC_123"
        assert dlq_call["channel"] == "email"
        assert dlq_call["failure_reason"] == "Timeout"
        assert dlq_call["retry_count"] == 3

    @pytest.mark.asyncio()
    @patch(*_PATCHES[:1])
    @patch(*_PATCHES[1:2])
    @patch(*_PATCHES[2:3])
    @patch(*_PATCHES[3:4])
    @patch(*_PATCHES[4:5])
    @patch(*_PATCHES[5:6])
    @patch(*_PATCHES[6:7])
    async def test_success_records_cb_success(
        self,
        mock_dlq_cls: MagicMock,
        mock_retry_cls: MagicMock,
        mock_rl_cls: MagicMock,
        mock_cb_cls: MagicMock,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """발송 성공 → Circuit Breaker 성공 기록."""
        mock_container, _mock_factory, mock_cb, _mock_rl, mock_retry, _mock_dlq = _setup_mocks(
            mock_dlq_cls, mock_retry_cls, mock_rl_cls, mock_cb_cls, mock_factory_cls, mock_container_fn
        )
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "queued",
            "notifications": [
                {"channel": "email", "provider": "sendgrid", "status": "pending"},
            ],
        }
        mock_retry.execute_with_retry = AsyncMock(
            return_value={"success": True, "provider": "sendgrid", "message": "", "duration_ms": 50.0}
        )

        await event_consumer(_make_event_grid_event())

        mock_cb.record_success.assert_awaited_once_with("email", "sendgrid")

    @pytest.mark.asyncio()
    @patch(*_PATCHES[:1])
    @patch(*_PATCHES[1:2])
    @patch(*_PATCHES[2:3])
    @patch(*_PATCHES[3:4])
    @patch(*_PATCHES[4:5])
    @patch(*_PATCHES[5:6])
    @patch(*_PATCHES[6:7])
    async def test_already_success_channel_is_skipped(
        self,
        mock_dlq_cls: MagicMock,
        mock_retry_cls: MagicMock,
        mock_rl_cls: MagicMock,
        mock_cb_cls: MagicMock,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """이미 success인 채널은 재발송하지 않는다."""
        mock_container, _mock_factory, mock_cb, _mock_rl, mock_retry, _mock_dlq = _setup_mocks(
            mock_dlq_cls, mock_retry_cls, mock_rl_cls, mock_cb_cls, mock_factory_cls, mock_container_fn
        )
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "queued",
            "notifications": [
                {"channel": "email", "provider": "sendgrid", "status": "success"},
                {"channel": "sms", "provider": "twilio", "status": "pending"},
            ],
        }
        mock_retry.execute_with_retry = AsyncMock(
            return_value={"success": True, "provider": "twilio", "message": "", "duration_ms": 30.0}
        )

        await event_consumer(_make_event_grid_event())

        mock_cb.check_state.assert_awaited_once_with("sms", "twilio")

    @pytest.mark.asyncio()
    @patch(*_PATCHES[:1])
    @patch(*_PATCHES[1:2])
    @patch(*_PATCHES[2:3])
    @patch(*_PATCHES[3:4])
    @patch(*_PATCHES[4:5])
    @patch(*_PATCHES[5:6])
    @patch(*_PATCHES[6:7])
    async def test_already_completed_event_is_skipped(
        self,
        mock_dlq_cls: MagicMock,
        mock_retry_cls: MagicMock,
        mock_rl_cls: MagicMock,
        mock_cb_cls: MagicMock,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """이미 완료된 이벤트는 재처리하지 않는다."""
        mock_container, *_ = _setup_mocks(
            mock_dlq_cls, mock_retry_cls, mock_rl_cls, mock_cb_cls, mock_factory_cls, mock_container_fn
        )
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "completed",
            "notifications": [{"channel": "email", "provider": "sendgrid", "status": "success"}],
        }

        await event_consumer(_make_event_grid_event())

        mock_container.patch_item.assert_not_awaited()

    @pytest.mark.asyncio()
    @patch(*_PATCHES[:1])
    @patch(*_PATCHES[1:2])
    @patch(*_PATCHES[2:3])
    @patch(*_PATCHES[3:4])
    @patch(*_PATCHES[4:5])
    @patch(*_PATCHES[5:6])
    @patch(*_PATCHES[6:7])
    async def test_event_read_failure_returns_early(
        self,
        mock_dlq_cls: MagicMock,
        mock_retry_cls: MagicMock,
        mock_rl_cls: MagicMock,
        mock_cb_cls: MagicMock,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """이벤트 조회 실패 시 조기 리턴."""
        mock_container, *_ = _setup_mocks(
            mock_dlq_cls, mock_retry_cls, mock_rl_cls, mock_cb_cls, mock_factory_cls, mock_container_fn
        )
        mock_container.read_item.side_effect = RuntimeError("DB unavailable")

        await event_consumer(_make_event_grid_event())

        mock_container.patch_item.assert_not_awaited()

    @pytest.mark.asyncio()
    @patch(*_PATCHES[:1])
    @patch(*_PATCHES[1:2])
    @patch(*_PATCHES[2:3])
    @patch(*_PATCHES[3:4])
    @patch(*_PATCHES[4:5])
    @patch(*_PATCHES[5:6])
    @patch(*_PATCHES[6:7])
    async def test_processing_status_set_before_sending(
        self,
        mock_dlq_cls: MagicMock,
        mock_retry_cls: MagicMock,
        mock_rl_cls: MagicMock,
        mock_cb_cls: MagicMock,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """발송 전 status가 processing으로 갱신된다."""
        mock_container, _mock_factory, _mock_cb, _mock_rl, mock_retry, _mock_dlq = _setup_mocks(
            mock_dlq_cls, mock_retry_cls, mock_rl_cls, mock_cb_cls, mock_factory_cls, mock_container_fn
        )
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "queued",
            "notifications": [{"channel": "email", "provider": "sendgrid", "status": "pending"}],
        }
        mock_retry.execute_with_retry = AsyncMock(
            return_value={"success": True, "provider": "sendgrid", "message": "", "duration_ms": 10.0}
        )

        await event_consumer(_make_event_grid_event())

        first_call = mock_container.patch_item.call_args_list[0]
        ops = first_call.kwargs["patch_operations"]
        status_op = next(op for op in ops if op["path"] == "/status")
        assert status_op["value"] == "processing"

    @pytest.mark.asyncio()
    @patch(*_PATCHES[:1])
    @patch(*_PATCHES[1:2])
    @patch(*_PATCHES[2:3])
    @patch(*_PATCHES[3:4])
    @patch(*_PATCHES[4:5])
    @patch(*_PATCHES[5:6])
    @patch(*_PATCHES[6:7])
    async def test_partial_success_sends_failed_to_dlq(
        self,
        mock_dlq_cls: MagicMock,
        mock_retry_cls: MagicMock,
        mock_rl_cls: MagicMock,
        mock_cb_cls: MagicMock,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """2/3 성공, 1/3 실패 → partially_completed + DLQ 1건."""
        mock_container, _mock_factory, _mock_cb, _mock_rl, mock_retry, mock_dlq = _setup_mocks(
            mock_dlq_cls, mock_retry_cls, mock_rl_cls, mock_cb_cls, mock_factory_cls, mock_container_fn
        )
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "queued",
            "event_type": "appointment_confirmed",
            "patient_id": "P-001",
            "notifications": [
                {"channel": "email", "provider": "sendgrid", "status": "pending"},
                {"channel": "sms", "provider": "twilio", "status": "pending"},
                {"channel": "webhook", "provider": "webhook", "status": "pending"},
            ],
        }
        # email 성공, sms 실패(재시도 초과), webhook 성공
        mock_retry.execute_with_retry = AsyncMock(
            side_effect=[
                {"success": True, "provider": "sendgrid", "message": "", "duration_ms": 50.0},
                MaxRetryExceededError(retry_count=3, last_error="SMS gateway down"),
                {"success": True, "provider": "webhook", "message": "", "duration_ms": 30.0},
            ]
        )

        await event_consumer(_make_event_grid_event())

        # DLQ에 sms만 저장
        mock_dlq.send_to_dlq.assert_awaited_once()
        dlq_call = mock_dlq.send_to_dlq.call_args.kwargs
        assert dlq_call["channel"] == "sms"
        assert dlq_call["failure_reason"] == "SMS gateway down"
        # 최종 상태: partially_completed
        final_call = mock_container.patch_item.call_args_list[-1]
        ops = final_call.kwargs["patch_operations"]
        status_op = next(op for op in ops if op["path"] == "/status")
        assert status_op["value"] == "partially_completed"

    @pytest.mark.asyncio()
    @patch(*_PATCHES[:1])
    @patch(*_PATCHES[1:2])
    @patch(*_PATCHES[2:3])
    @patch(*_PATCHES[3:4])
    @patch(*_PATCHES[4:5])
    @patch(*_PATCHES[5:6])
    @patch(*_PATCHES[6:7])
    async def test_all_channels_fail_sends_all_to_dlq(
        self,
        mock_dlq_cls: MagicMock,
        mock_retry_cls: MagicMock,
        mock_rl_cls: MagicMock,
        mock_cb_cls: MagicMock,
        mock_factory_cls: MagicMock,
        mock_container_fn: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """전체 채널 실패 → failed + DLQ 2건."""
        mock_container, _mock_factory, _mock_cb, _mock_rl, mock_retry, mock_dlq = _setup_mocks(
            mock_dlq_cls, mock_retry_cls, mock_rl_cls, mock_cb_cls, mock_factory_cls, mock_container_fn
        )
        mock_container.read_item.return_value = {
            "id": "evt-001",
            "clinic_id": "CLINIC_123",
            "status": "queued",
            "event_type": "claim_completed",
            "patient_id": "P-003",
            "notifications": [
                {"channel": "email", "provider": "sendgrid", "status": "pending"},
                {"channel": "sms", "provider": "twilio", "status": "pending"},
            ],
        }
        mock_retry.execute_with_retry = AsyncMock(
            side_effect=[
                MaxRetryExceededError(retry_count=3, last_error="Email error"),
                MaxRetryExceededError(retry_count=3, last_error="SMS error"),
            ]
        )

        await event_consumer(_make_event_grid_event())

        assert mock_dlq.send_to_dlq.await_count == 2
        # 최종 상태: failed
        final_call = mock_container.patch_item.call_args_list[-1]
        ops = final_call.kwargs["patch_operations"]
        status_op = next(op for op in ops if op["path"] == "/status")
        assert status_op["value"] == "failed"
