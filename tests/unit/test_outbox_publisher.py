"""Outbox Publisher 테스트."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.functions.outbox_publisher import outbox_publisher


def _make_document(overrides: dict | None = None) -> MagicMock:
    """테스트용 Cosmos DB Document를 생성한다."""
    doc_dict = {
        "id": "evt-001",
        "clinic_id": "CLINIC_123",
        "correlation_id": "cid-001",
        "_outbox_status": "pending",
        "status": "queued",
    }
    if overrides:
        doc_dict.update(overrides)

    mock_doc = MagicMock()
    mock_doc.to_dict.return_value = doc_dict
    mock_doc.to_json.return_value = json.dumps(doc_dict)
    return mock_doc


def _make_document_list(docs: list[MagicMock]) -> MagicMock:
    """테스트용 DocumentList를 생성한다."""
    doc_list = MagicMock()
    doc_list.__iter__ = lambda self: iter(docs)
    doc_list.__len__ = lambda self: len(docs)
    doc_list.__bool__ = lambda self: bool(docs)
    return doc_list


class TestOutboxPublisher:
    """Outbox Publisher Function 테스트."""

    @pytest.mark.asyncio()
    @patch("src.functions.outbox_publisher._get_broker")
    @patch("src.functions.outbox_publisher._get_settings")
    @patch("src.functions.outbox_publisher.get_events_container")
    async def test_pending_document_is_published(
        self, mock_container_fn: MagicMock, mock_settings: MagicMock, mock_broker_fn: MagicMock
    ) -> None:
        """pending 문서가 발행되고 published로 갱신된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_broker = AsyncMock()
        mock_broker.get_broker_name = MagicMock(return_value="EventGrid")
        mock_broker_fn.return_value = mock_broker

        doc = _make_document()
        doc_list = _make_document_list([doc])

        await outbox_publisher(doc_list)

        mock_broker.publish.assert_awaited_once()
        mock_container.patch_item.assert_awaited_once()
        patch_ops = mock_container.patch_item.call_args.kwargs["patch_operations"]
        assert patch_ops[0]["value"] == "published"

    @pytest.mark.asyncio()
    @patch("src.functions.outbox_publisher._get_broker")
    @patch("src.functions.outbox_publisher._get_settings")
    @patch("src.functions.outbox_publisher.get_events_container")
    async def test_published_document_is_skipped(
        self, mock_container_fn: MagicMock, mock_settings: MagicMock, mock_broker_fn: MagicMock
    ) -> None:
        """published 문서는 무시된다 (무한 루프 방지)."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_broker = AsyncMock()
        mock_broker_fn.return_value = mock_broker

        doc = _make_document({"_outbox_status": "published"})
        doc_list = _make_document_list([doc])

        await outbox_publisher(doc_list)

        mock_broker.publish.assert_not_awaited()
        mock_container.patch_item.assert_not_awaited()

    @pytest.mark.asyncio()
    @patch("src.functions.outbox_publisher._get_broker")
    @patch("src.functions.outbox_publisher._get_settings")
    @patch("src.functions.outbox_publisher.get_events_container")
    async def test_failed_publish_document_is_skipped(
        self, mock_container_fn: MagicMock, mock_settings: MagicMock, mock_broker_fn: MagicMock
    ) -> None:
        """failed_publish 문서도 무시된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_broker = AsyncMock()
        mock_broker_fn.return_value = mock_broker

        doc = _make_document({"_outbox_status": "failed_publish"})
        doc_list = _make_document_list([doc])

        await outbox_publisher(doc_list)

        mock_broker.publish.assert_not_awaited()

    @pytest.mark.asyncio()
    @patch("src.functions.outbox_publisher._get_broker")
    @patch("src.functions.outbox_publisher._get_settings")
    @patch("src.functions.outbox_publisher.get_events_container")
    async def test_publish_failure_sets_failed_publish(
        self, mock_container_fn: MagicMock, mock_settings: MagicMock, mock_broker_fn: MagicMock
    ) -> None:
        """발행 실패 시 failed_publish로 갱신된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_broker = AsyncMock()
        mock_broker.publish.side_effect = RuntimeError("Network error")
        mock_broker_fn.return_value = mock_broker

        doc = _make_document()
        doc_list = _make_document_list([doc])

        await outbox_publisher(doc_list)

        mock_container.patch_item.assert_awaited_once()
        patch_ops = mock_container.patch_item.call_args.kwargs["patch_operations"]
        assert patch_ops[0]["value"] == "failed_publish"

    @pytest.mark.asyncio()
    @patch("src.functions.outbox_publisher._get_broker")
    @patch("src.functions.outbox_publisher._get_settings")
    @patch("src.functions.outbox_publisher.get_events_container")
    async def test_mixed_documents_only_pending_processed(
        self, mock_container_fn: MagicMock, mock_settings: MagicMock, mock_broker_fn: MagicMock
    ) -> None:
        """pending과 published가 혼재된 배치에서 pending만 처리한다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_broker = AsyncMock()
        mock_broker.get_broker_name = MagicMock(return_value="EventGrid")
        mock_broker_fn.return_value = mock_broker

        docs = [
            _make_document({"id": "evt-1", "_outbox_status": "pending"}),
            _make_document({"id": "evt-2", "_outbox_status": "published"}),
            _make_document({"id": "evt-3", "_outbox_status": "pending"}),
        ]
        doc_list = _make_document_list(docs)

        await outbox_publisher(doc_list)

        assert mock_broker.publish.await_count == 2
        assert mock_container.patch_item.await_count == 2

    @pytest.mark.asyncio()
    async def test_empty_document_list(self) -> None:
        """빈 문서 목록은 에러 없이 종료된다."""
        doc_list = _make_document_list([])
        await outbox_publisher(doc_list)  # 예외 없이 통과
