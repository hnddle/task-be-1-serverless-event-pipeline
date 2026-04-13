"""Outbox 흐름 통합 테스트.

POST → Change Feed → outbox_publisher → Event Grid 발행 흐름,
발행 실패 → failed_publish → outbox_retry → pending 복원 흐름을 검증한다.
Cosmos DB Emulator 필수 — Emulator 미실행 시 자동 스킵.

SPEC.md §13.2 참조.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.functions.event_api import post_events
from src.functions.outbox_publisher import outbox_publisher
from src.functions.outbox_retry import outbox_retry
from src.services.cosmos_client import get_events_container


def _make_http_request(body: dict[str, Any]) -> MagicMock:
    """테스트용 POST HttpRequest."""
    req = MagicMock()
    req.method = "POST"
    req.params = {}
    req.route_params = {}
    req.get_json.return_value = body
    return req


def _make_event_body(clinic_id: str) -> dict[str, Any]:
    """유효한 이벤트 생성 요청 바디."""
    return {
        "id": str(uuid.uuid4()),
        "event_type": "appointment_confirmed",
        "clinic_id": clinic_id,
        "patient_id": "P-001",
        "channels": ["email"],
    }


def _make_document_list(docs: list[dict[str, Any]]) -> MagicMock:
    """테스트용 DocumentList를 생성한다."""
    doc_list = MagicMock()
    mock_docs = []
    for d in docs:
        mock_doc = MagicMock()
        mock_doc.to_dict.return_value = d
        mock_docs.append(mock_doc)
    doc_list.__iter__ = lambda self: iter(mock_docs)
    doc_list.__len__ = lambda self: len(mock_docs)
    return doc_list


@pytest.mark.usefixtures("setup_database")
class TestOutboxPublisherIntegration:
    """Outbox Publisher 통합 테스트 — Cosmos DB Emulator 사용."""

    @pytest.mark.asyncio()
    async def test_pending_document_published_to_event_grid(
        self,
        test_settings: Any,
        unique_clinic_id: str,
    ) -> None:
        """pending 문서가 Event Grid로 발행되고 published로 갱신된다."""
        # 1. POST /events로 이벤트 생성 (pending 상태)
        body = _make_event_body(unique_clinic_id)
        event_id = body["id"]

        with patch("src.functions.event_api._get_settings", return_value=test_settings):
            req = _make_http_request(body)
            resp = await post_events(req)
            assert resp.status_code == 201

        # 2. Cosmos DB에서 문서 조회하여 pending 확인
        container = get_events_container(test_settings)
        doc = await container.read_item(item=event_id, partition_key=unique_clinic_id)
        assert doc["_outbox_status"] == "pending"

        # 3. outbox_publisher 실행 (broker는 mock)
        mock_broker = MagicMock()
        mock_broker.publish = AsyncMock()
        mock_broker.get_broker_name = MagicMock(return_value="EventGrid")

        doc_list = _make_document_list([doc])

        with (
            patch("src.functions.outbox_publisher._get_settings", return_value=test_settings),
            patch("src.functions.outbox_publisher._get_broker", return_value=mock_broker),
        ):
            await outbox_publisher(doc_list)

        # 4. broker.publish가 호출됨
        mock_broker.publish.assert_awaited_once()

        # 5. Cosmos DB에서 published로 갱신 확인
        updated = await container.read_item(item=event_id, partition_key=unique_clinic_id)
        assert updated["_outbox_status"] == "published"

    @pytest.mark.asyncio()
    async def test_publish_failure_sets_failed_publish(
        self,
        test_settings: Any,
        unique_clinic_id: str,
    ) -> None:
        """발행 실패 시 failed_publish로 갱신된다."""
        body = _make_event_body(unique_clinic_id)
        event_id = body["id"]

        with patch("src.functions.event_api._get_settings", return_value=test_settings):
            req = _make_http_request(body)
            await post_events(req)

        container = get_events_container(test_settings)
        doc = await container.read_item(item=event_id, partition_key=unique_clinic_id)

        # broker 발행 실패
        mock_broker = MagicMock()
        mock_broker.publish = AsyncMock(side_effect=RuntimeError("Event Grid unavailable"))
        mock_broker.get_broker_name = MagicMock(return_value="EventGrid")

        doc_list = _make_document_list([doc])

        with (
            patch("src.functions.outbox_publisher._get_settings", return_value=test_settings),
            patch("src.functions.outbox_publisher._get_broker", return_value=mock_broker),
        ):
            await outbox_publisher(doc_list)

        # failed_publish로 갱신
        updated = await container.read_item(item=event_id, partition_key=unique_clinic_id)
        assert updated["_outbox_status"] == "failed_publish"


@pytest.mark.usefixtures("setup_database")
class TestOutboxRetryIntegration:
    """Outbox Retry 통합 테스트 — Cosmos DB Emulator 사용."""

    @pytest.mark.asyncio()
    async def test_failed_publish_retried_to_pending(
        self,
        test_settings: Any,
        unique_clinic_id: str,
    ) -> None:
        """failed_publish → outbox_retry → pending 복원."""
        # 1. 이벤트 생성 후 강제로 failed_publish 설정
        body = _make_event_body(unique_clinic_id)
        event_id = body["id"]

        with patch("src.functions.event_api._get_settings", return_value=test_settings):
            req = _make_http_request(body)
            await post_events(req)

        container = get_events_container(test_settings)
        await container.patch_item(
            item=event_id,
            partition_key=unique_clinic_id,
            patch_operations=[
                {"op": "set", "path": "/_outbox_status", "value": "failed_publish"},
            ],
        )

        # 2. outbox_retry 실행
        timer = MagicMock()
        timer.past_due = False

        with patch("src.functions.outbox_retry._get_settings", return_value=test_settings):
            await outbox_retry(timer)

        # 3. pending으로 복원 확인
        updated = await container.read_item(item=event_id, partition_key=unique_clinic_id)
        assert updated["_outbox_status"] == "pending"
