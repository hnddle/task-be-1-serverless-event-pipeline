"""DLQ Replay 흐름 통합 테스트.

DLQ Replay → Outbox 재발행 → 재처리 흐름을 Cosmos DB Emulator로 검증한다.
Emulator 미실행 시 자동 스킵.

SPEC.md §13.2 참조.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.functions.dlq_api import post_dlq_replay
from src.functions.event_api import post_events
from src.functions.event_consumer import event_consumer
from src.services.cosmos_client import get_dlq_container, get_events_container
from src.services.retry_service import MaxRetryExceededError


def _make_http_request(
    method: str = "POST",
    body: dict | None = None,
    params: dict | None = None,
    route_params: dict | None = None,
) -> MagicMock:
    req = MagicMock()
    req.method = method
    req.params = params or {}
    req.route_params = route_params or {}
    if body is not None:
        req.get_json.return_value = body
    else:
        req.get_json.side_effect = ValueError("No JSON")
    return req


def _make_event_body(clinic_id: str) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "event_type": "insurance_approved",
        "clinic_id": clinic_id,
        "patient_id": "P-003",
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


async def _create_event_and_fail_to_dlq(
    test_settings: Any,
    clinic_id: str,
) -> tuple[str, str]:
    """이벤트 생성 후 Consumer 실패 → DLQ 이동. (event_id, correlation_id) 반환."""
    body = _make_event_body(clinic_id)
    event_id = body["id"]

    with patch("src.functions.event_api._get_settings", return_value=test_settings):
        req = _make_http_request(body=body)
        resp = await post_events(req)
        correlation_id = json.loads(resp.get_body())["correlation_id"]

    # Consumer 실행 — 전체 실패
    mock_retry = MagicMock()
    mock_retry.execute_with_retry = AsyncMock(
        side_effect=MaxRetryExceededError(retry_count=2, last_error="Service down")
    )

    eg_event = _make_event_grid_event(event_id, clinic_id, correlation_id)

    with (
        patch("src.functions.event_consumer._get_settings", return_value=test_settings),
        patch("src.functions.event_consumer.CircuitBreaker", return_value=AsyncMock()),
        patch("src.functions.event_consumer.RateLimiter", return_value=AsyncMock()),
        patch("src.functions.event_consumer.RetryService", return_value=mock_retry),
        patch("src.functions.event_consumer.NotificationFactory") as mock_factory_cls,
    ):
        mock_factory_cls.return_value = MagicMock()
        await event_consumer(eg_event)

    return event_id, correlation_id


@pytest.mark.usefixtures("setup_database")
class TestReplayFlowIntegration:
    """DLQ Replay 통합 테스트 — Cosmos DB Emulator 사용."""

    @pytest.mark.asyncio()
    async def test_replay_creates_new_event_via_outbox(
        self,
        test_settings: Any,
        unique_clinic_id: str,
    ) -> None:
        """DLQ replay → 새 이벤트가 Outbox 패턴으로 재발행된다."""
        # 1. 이벤트 생성 + Consumer 실패 → DLQ 이동
        event_id, original_corr = await _create_event_and_fail_to_dlq(test_settings, unique_clinic_id)

        # 2. DLQ에서 문서 조회
        dlq_container = get_dlq_container(test_settings)
        query = "SELECT * FROM c WHERE c.original_event_id = @event_id"
        dlq_docs = []
        async for item in dlq_container.query_items(
            query=query,
            parameters=[{"name": "@event_id", "value": event_id}],
            partition_key=unique_clinic_id,
        ):
            dlq_docs.append(item)

        assert len(dlq_docs) == 1
        dlq_id = dlq_docs[0]["id"]

        # 3. POST /dlq/{dlq_id}/replay
        with patch("src.functions.dlq_api._get_settings", return_value=test_settings):
            req = _make_http_request(
                method="POST",
                params={"clinic_id": unique_clinic_id},
                route_params={"dlq_id": dlq_id},
            )
            resp = await post_dlq_replay(req)

        assert resp.status_code == 200
        result = json.loads(resp.get_body())
        assert result["replay_status"] == "replayed"
        new_corr = result["new_correlation_id"]
        assert new_corr != original_corr

        # 4. DLQ 문서가 replayed로 갱신
        updated_dlq = await dlq_container.read_item(item=dlq_id, partition_key=unique_clinic_id)
        assert updated_dlq["replay_status"] == "replayed"
        assert updated_dlq["replayed_at"] is not None

        # 5. events 컨테이너에 새 이벤트가 pending 상태로 생성
        events_container = get_events_container(test_settings)
        query = "SELECT * FROM c WHERE c.correlation_id = @corr_id"
        new_events = []
        async for item in events_container.query_items(
            query=query,
            parameters=[{"name": "@corr_id", "value": new_corr}],
            partition_key=unique_clinic_id,
        ):
            new_events.append(item)

        assert len(new_events) == 1
        assert new_events[0]["status"] == "queued"
        assert new_events[0]["_outbox_status"] == "pending"

    @pytest.mark.asyncio()
    async def test_duplicate_replay_returns_409(
        self,
        test_settings: Any,
        unique_clinic_id: str,
    ) -> None:
        """이미 replayed된 DLQ → 409."""
        event_id, _ = await _create_event_and_fail_to_dlq(test_settings, unique_clinic_id)

        dlq_container = get_dlq_container(test_settings)
        query = "SELECT * FROM c WHERE c.original_event_id = @event_id"
        dlq_docs = []
        async for item in dlq_container.query_items(
            query=query,
            parameters=[{"name": "@event_id", "value": event_id}],
            partition_key=unique_clinic_id,
        ):
            dlq_docs.append(item)

        dlq_id = dlq_docs[0]["id"]

        with patch("src.functions.dlq_api._get_settings", return_value=test_settings):
            # 첫 번째 replay → 200
            req1 = _make_http_request(
                method="POST",
                params={"clinic_id": unique_clinic_id},
                route_params={"dlq_id": dlq_id},
            )
            resp1 = await post_dlq_replay(req1)
            assert resp1.status_code == 200

            # 두 번째 replay → 409
            req2 = _make_http_request(
                method="POST",
                params={"clinic_id": unique_clinic_id},
                route_params={"dlq_id": dlq_id},
            )
            resp2 = await post_dlq_replay(req2)
            assert resp2.status_code == 409
