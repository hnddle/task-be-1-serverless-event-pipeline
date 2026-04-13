"""DLQ 이동 흐름 통합 테스트.

재시도 초과 → DLQ 저장 흐름을 Cosmos DB Emulator로 검증한다.
Emulator 미실행 시 자동 스킵.

SPEC.md §13.2 참조.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.functions.event_api import post_events
from src.functions.event_consumer import event_consumer
from src.services.cosmos_client import get_dlq_container, get_events_container
from src.services.retry_service import MaxRetryExceededError


def _make_http_request(body: dict[str, Any]) -> MagicMock:
    req = MagicMock()
    req.method = "POST"
    req.params = {}
    req.route_params = {}
    req.get_json.return_value = body
    return req


def _make_event_body(clinic_id: str) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "event_type": "claim_completed",
        "clinic_id": clinic_id,
        "patient_id": "P-002",
        "channels": ["email"],
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
class TestDlqFlowIntegration:
    """DLQ 이동 흐름 통합 테스트 — Cosmos DB Emulator 사용."""

    @pytest.mark.asyncio()
    async def test_max_retry_exceeded_saves_to_dlq(
        self,
        test_settings: Any,
        unique_clinic_id: str,
    ) -> None:
        """최대 재시도 초과 → DLQ 컨테이너에 저장."""
        body = _make_event_body(unique_clinic_id)
        event_id = body["id"]

        # 1. 이벤트 생성
        with patch("src.functions.event_api._get_settings", return_value=test_settings):
            req = _make_http_request(body)
            resp = await post_events(req)
            import json

            correlation_id = json.loads(resp.get_body())["correlation_id"]

        # 2. Consumer 실행 — 전체 실패 (DLQ 서비스는 실제 Cosmos DB 사용)
        mock_retry = MagicMock()
        mock_retry.execute_with_retry = AsyncMock(
            side_effect=MaxRetryExceededError(retry_count=2, last_error="Persistent failure")
        )
        mock_cb = AsyncMock()
        mock_rl = AsyncMock()

        eg_event = _make_event_grid_event(event_id, unique_clinic_id, correlation_id)

        with (
            patch("src.functions.event_consumer._get_settings", return_value=test_settings),
            patch("src.functions.event_consumer.CircuitBreaker", return_value=mock_cb),
            patch("src.functions.event_consumer.RateLimiter", return_value=mock_rl),
            patch("src.functions.event_consumer.RetryService", return_value=mock_retry),
            patch("src.functions.event_consumer.NotificationFactory") as mock_factory_cls,
        ):
            mock_factory_cls.return_value = MagicMock()
            await event_consumer(eg_event)

        # 3. events 컨테이너에서 failed 확인
        events_container = get_events_container(test_settings)
        doc = await events_container.read_item(item=event_id, partition_key=unique_clinic_id)
        assert doc["status"] == "failed"

        # 4. DLQ 컨테이너에서 문서 조회
        dlq_container = get_dlq_container(test_settings)
        query = "SELECT * FROM c WHERE c.original_event_id = @event_id"
        items = []
        async for item in dlq_container.query_items(
            query=query,
            parameters=[{"name": "@event_id", "value": event_id}],
            partition_key=unique_clinic_id,
        ):
            items.append(item)

        assert len(items) == 1
        dlq_doc = items[0]
        assert dlq_doc["original_event_id"] == event_id
        assert dlq_doc["clinic_id"] == unique_clinic_id
        assert dlq_doc["channel"] == "email"
        assert dlq_doc["failure_reason"] == "Persistent failure"
        assert dlq_doc["retry_count"] == 2
        assert dlq_doc["replay_status"] == "pending"
        assert dlq_doc["correlation_id"] == correlation_id
