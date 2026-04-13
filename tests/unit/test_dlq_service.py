"""DLQ 서비스 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.dlq_service import DlqService


def _make_settings() -> MagicMock:
    """테스트용 Settings를 생성한다."""
    settings = MagicMock()
    settings.COSMOS_DB_ENDPOINT = "https://localhost:8081"
    settings.COSMOS_DB_KEY = "test-key"
    settings.COSMOS_DB_DATABASE = "test-db"
    return settings


SAMPLE_PAYLOAD: dict = {
    "id": "evt-1",
    "clinic_id": "clinic-1",
    "event_type": "appointment_confirmed",
    "patient_id": "P-001",
    "notifications": [],
}


class TestSendToDlq:
    """send_to_dlq 메서드 테스트."""

    @pytest.mark.asyncio()
    @patch("src.services.dlq_service.get_dlq_container")
    @patch("src.services.dlq_service.get_correlation_id", return_value="corr-123")
    async def test_creates_dlq_document(
        self,
        _mock_corr: MagicMock,
        mock_container_fn: MagicMock,
    ) -> None:
        """DLQ 문서가 올바른 필드로 생성된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        service = DlqService(_make_settings())
        result = await service.send_to_dlq(
            original_event_id="evt-1",
            clinic_id="clinic-1",
            channel="email",
            provider="sendgrid",
            event_type="appointment_confirmed",
            patient_id="P-001",
            payload=SAMPLE_PAYLOAD,
            failure_reason="persistent error",
            retry_count=3,
        )

        mock_container.create_item.assert_awaited_once()
        saved = mock_container.create_item.call_args.kwargs["body"]

        assert saved["original_event_id"] == "evt-1"
        assert saved["clinic_id"] == "clinic-1"
        assert saved["channel"] == "email"
        assert saved["provider"] == "sendgrid"
        assert saved["event_type"] == "appointment_confirmed"
        assert saved["patient_id"] == "P-001"
        assert saved["payload"] == SAMPLE_PAYLOAD
        assert saved["failure_reason"] == "persistent error"
        assert saved["retry_count"] == 3
        assert saved["correlation_id"] == "corr-123"
        assert saved["replay_status"] == "pending"
        assert saved["replayed_at"] is None
        assert "id" in saved
        assert "created_at" in saved

        # 반환값도 동일
        assert result == saved

    @pytest.mark.asyncio()
    @patch("src.services.dlq_service.get_dlq_container")
    @patch("src.services.dlq_service.get_correlation_id", return_value=None)
    async def test_empty_correlation_id_when_none(
        self,
        _mock_corr: MagicMock,
        mock_container_fn: MagicMock,
    ) -> None:
        """correlation_id가 None이면 빈 문자열로 저장된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        service = DlqService(_make_settings())
        await service.send_to_dlq(
            original_event_id="evt-2",
            clinic_id="clinic-2",
            channel="sms",
            provider="twilio",
            event_type="claim_completed",
            patient_id="P-002",
            payload={},
            failure_reason="timeout",
            retry_count=2,
        )

        saved = mock_container.create_item.call_args.kwargs["body"]
        assert saved["correlation_id"] == ""

    @pytest.mark.asyncio()
    @patch("src.services.dlq_service.get_dlq_container")
    @patch("src.services.dlq_service.get_correlation_id", return_value="corr-456")
    async def test_dlq_id_is_unique_uuid(
        self,
        _mock_corr: MagicMock,
        mock_container_fn: MagicMock,
    ) -> None:
        """DLQ 문서 ID가 UUID v4 형식이다."""
        import uuid

        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        service = DlqService(_make_settings())
        result = await service.send_to_dlq(
            original_event_id="evt-3",
            clinic_id="clinic-3",
            channel="webhook",
            provider="webhook",
            event_type="insurance_approved",
            patient_id="P-003",
            payload={},
            failure_reason="connection refused",
            retry_count=3,
        )

        # UUID v4 형식 검증
        dlq_id = result["id"]
        parsed = uuid.UUID(dlq_id, version=4)
        assert str(parsed) == dlq_id

    @pytest.mark.asyncio()
    @patch("src.services.dlq_service.get_dlq_container")
    @patch("src.services.dlq_service.get_correlation_id", return_value="corr-789")
    async def test_zero_retry_count(
        self,
        _mock_corr: MagicMock,
        mock_container_fn: MagicMock,
    ) -> None:
        """retry_count=0인 경우도 정상 저장된다 (Circuit Open 즉시 실패)."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        service = DlqService(_make_settings())
        result = await service.send_to_dlq(
            original_event_id="evt-4",
            clinic_id="clinic-4",
            channel="email",
            provider="sendgrid",
            event_type="appointment_confirmed",
            patient_id="P-004",
            payload={},
            failure_reason="Circuit open: email:sendgrid",
            retry_count=0,
        )

        assert result["retry_count"] == 0
        assert result["failure_reason"] == "Circuit open: email:sendgrid"
