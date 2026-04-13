"""Consumer 채널별 발송 + 상태 갱신 통합 테스트.

Event Consumer 정상 발송 → completed, 일부 실패 → partially_completed 흐름을 검증한다.
Cosmos DB Emulator 필수 — Emulator 미실행 시 자동 스킵.

SPEC.md §13.2 참조.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.functions.event_api import post_events
from src.functions.event_consumer import event_consumer
from src.services.cosmos_client import get_events_container
from src.services.retry_service import MaxRetryExceededError


def _make_http_request(body: dict[str, Any]) -> MagicMock:
    req = MagicMock()
    req.method = "POST"
    req.params = {}
    req.route_params = {}
    req.get_json.return_value = body
    return req


def _make_event_body(clinic_id: str, channels: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "event_type": "appointment_confirmed",
        "clinic_id": clinic_id,
        "patient_id": "P-001",
        "channels": channels or ["email", "sms", "webhook"],
    }


def _make_event_grid_event(event_id: str, clinic_id: str, correlation_id: str) -> MagicMock:
    event = MagicMock()
    event.get_json.return_value = {
        "id": event_id,
        "clinic_id": clinic_id,
        "correlation_id": correlation_id,
    }
    return event


@pytest.mark.usefixtures("setup_database")
class TestConsumerFlowIntegration:
    """Consumer 흐름 통합 테스트 — Cosmos DB Emulator 사용."""

    @pytest.mark.asyncio()
    async def test_all_channels_success_sets_completed(
        self,
        test_settings: Any,
        unique_clinic_id: str,
    ) -> None:
        """전체 채널 성공 → completed 상태."""
        body = _make_event_body(unique_clinic_id)
        event_id = body["id"]

        # 1. 이벤트 생성
        with patch("src.functions.event_api._get_settings", return_value=test_settings):
            req = _make_http_request(body)
            resp = await post_events(req)
            correlation_id = resp.get_body()
            import json

            correlation_id = json.loads(correlation_id)["correlation_id"]

        container = get_events_container(test_settings)

        # 2. Consumer 실행 — 복원력 서비스 mock (성공)
        mock_retry = MagicMock()
        mock_retry.execute_with_retry = AsyncMock(
            return_value={"success": True, "provider": "mock", "message": "", "duration_ms": 10.0}
        )
        mock_cb = AsyncMock()
        mock_rl = AsyncMock()
        mock_dlq = AsyncMock()

        eg_event = _make_event_grid_event(event_id, unique_clinic_id, correlation_id)

        with (
            patch("src.functions.event_consumer._get_settings", return_value=test_settings),
            patch("src.functions.event_consumer.CircuitBreaker", return_value=mock_cb),
            patch("src.functions.event_consumer.RateLimiter", return_value=mock_rl),
            patch("src.functions.event_consumer.RetryService", return_value=mock_retry),
            patch("src.functions.event_consumer.DlqService", return_value=mock_dlq),
            patch("src.functions.event_consumer.NotificationFactory") as mock_factory_cls,
        ):
            mock_factory_cls.return_value = MagicMock()
            await event_consumer(eg_event)

        # 3. Cosmos DB에서 completed 확인
        doc = await container.read_item(item=event_id, partition_key=unique_clinic_id)
        assert doc["status"] == "completed"
        for n in doc["notifications"]:
            assert n["status"] == "success"

    @pytest.mark.asyncio()
    async def test_partial_failure_sets_partially_completed(
        self,
        test_settings: Any,
        unique_clinic_id: str,
    ) -> None:
        """일부 채널 실패 → partially_completed 상태."""
        body = _make_event_body(unique_clinic_id, channels=["email", "sms"])
        event_id = body["id"]

        with patch("src.functions.event_api._get_settings", return_value=test_settings):
            req = _make_http_request(body)
            resp = await post_events(req)
            import json

            correlation_id = json.loads(resp.get_body())["correlation_id"]

        container = get_events_container(test_settings)

        # email 성공, sms 실패(재시도 초과)
        mock_retry = MagicMock()
        mock_retry.execute_with_retry = AsyncMock(
            side_effect=[
                {"success": True, "provider": "sendgrid", "message": "", "duration_ms": 10.0},
                MaxRetryExceededError(retry_count=2, last_error="SMS gateway down"),
            ]
        )
        mock_cb = AsyncMock()
        mock_rl = AsyncMock()
        mock_dlq = AsyncMock()

        eg_event = _make_event_grid_event(event_id, unique_clinic_id, correlation_id)

        with (
            patch("src.functions.event_consumer._get_settings", return_value=test_settings),
            patch("src.functions.event_consumer.CircuitBreaker", return_value=mock_cb),
            patch("src.functions.event_consumer.RateLimiter", return_value=mock_rl),
            patch("src.functions.event_consumer.RetryService", return_value=mock_retry),
            patch("src.functions.event_consumer.DlqService", return_value=mock_dlq),
            patch("src.functions.event_consumer.NotificationFactory") as mock_factory_cls,
        ):
            mock_factory_cls.return_value = MagicMock()
            await event_consumer(eg_event)

        doc = await container.read_item(item=event_id, partition_key=unique_clinic_id)
        assert doc["status"] == "partially_completed"
        # DLQ에 sms 저장됨
        mock_dlq.send_to_dlq.assert_awaited_once()
