"""DLQ API 테스트."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from src.functions.dlq_api import get_dlq, post_dlq_replay, post_dlq_replay_batch


def _make_http_request(
    method: str = "GET",
    params: dict | None = None,
    route_params: dict | None = None,
    body: dict | None = None,
) -> MagicMock:
    """테스트용 HttpRequest를 생성한다."""
    req = MagicMock()
    req.method = method
    req.params = params or {}
    req.route_params = route_params or {}
    if body is not None:
        req.get_json.return_value = body
    else:
        req.get_json.side_effect = ValueError("No JSON body")
    return req


def _make_dlq_doc(
    dlq_id: str = "dlq-001",
    clinic_id: str = "CLINIC_123",
    replay_status: str = "pending",
    channel: str = "email",
    provider: str = "sendgrid",
) -> dict:
    """테스트용 DLQ 문서를 생성한다."""
    return {
        "id": dlq_id,
        "original_event_id": "evt-001",
        "clinic_id": clinic_id,
        "channel": channel,
        "provider": provider,
        "event_type": "appointment_confirmed",
        "patient_id": "P-001",
        "payload": {
            "id": "evt-001",
            "clinic_id": clinic_id,
            "event_type": "appointment_confirmed",
            "patient_id": "P-001",
        },
        "failure_reason": "Timeout",
        "retry_count": 3,
        "correlation_id": "old-corr-001",
        "created_at": "2026-04-01T00:00:00+00:00",
        "replay_status": replay_status,
        "replayed_at": None,
    }


class TestGetDlq:
    """GET /dlq 테스트."""

    @pytest.mark.asyncio()
    @patch("src.functions.dlq_api._get_settings")
    @patch("src.functions.dlq_api.get_dlq_container")
    async def test_missing_clinic_id_returns_400(
        self,
        _mock_container_fn: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """clinic_id 누락 시 400 반환."""
        req = _make_http_request(params={})
        resp = await get_dlq(req)
        assert resp.status_code == 400
        body = json.loads(resp.get_body())
        assert body["error"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio()
    @patch("src.functions.dlq_api._get_settings")
    @patch("src.functions.dlq_api.get_dlq_container")
    async def test_returns_items_with_pagination(
        self,
        mock_container_fn: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """정상 조회 시 items, continuation_token, total_count를 반환한다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        # 페이지네이션 mock: query_items는 sync 함수
        doc = _make_dlq_doc()

        mock_pager = AsyncMock()
        mock_pager.__aiter__ = lambda self: _async_iter([_AsyncIterable([doc])])
        mock_pager.continuation_token = "next-token-123"

        mock_query = MagicMock()
        mock_query.by_page.return_value = mock_pager
        mock_container.query_items = MagicMock(return_value=mock_query)

        req = _make_http_request(params={"clinic_id": "CLINIC_123"})
        resp = await get_dlq(req)

        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert len(body["items"]) == 1
        assert body["items"][0]["id"] == "dlq-001"
        assert body["continuation_token"] == "next-token-123"
        assert body["total_count"] == 1

    @pytest.mark.asyncio()
    @patch("src.functions.dlq_api._get_settings")
    @patch("src.functions.dlq_api.get_dlq_container")
    async def test_filters_applied_to_query(
        self,
        mock_container_fn: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """replay_status, event_type 필터가 쿼리에 반���된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        mock_pager = AsyncMock()
        mock_pager.__aiter__ = lambda self: _async_iter([_AsyncIterable([])])
        mock_pager.continuation_token = None
        mock_query = MagicMock()
        mock_query.by_page.return_value = mock_pager
        mock_container.query_items = MagicMock(return_value=mock_query)

        req = _make_http_request(
            params={
                "clinic_id": "CLINIC_123",
                "replay_status": "pending",
                "event_type": "appointment_confirmed",
            }
        )
        await get_dlq(req)

        call_kwargs = mock_container.query_items.call_args
        query_str = call_kwargs.kwargs.get("query", "")
        assert "replay_status" in query_str
        assert "event_type" in query_str


class TestPostDlqReplay:
    """POST /dlq/{dlq_id}/replay 테스트."""

    @pytest.mark.asyncio()
    @patch("src.functions.dlq_api._get_settings")
    @patch("src.functions.dlq_api.get_dlq_container")
    @patch("src.functions.dlq_api.get_events_container")
    async def test_replay_success(
        self,
        mock_events_fn: MagicMock,
        mock_dlq_fn: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """정상 Replay 시 200 반환 + replayed 상태."""
        mock_dlq = AsyncMock()
        mock_dlq_fn.return_value = mock_dlq
        mock_events = AsyncMock()
        mock_events_fn.return_value = mock_events

        mock_dlq.read_item.return_value = _make_dlq_doc(replay_status="pending")

        req = _make_http_request(
            method="POST",
            params={"clinic_id": "CLINIC_123"},
            route_params={"dlq_id": "dlq-001"},
        )
        resp = await post_dlq_replay(req)

        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["dlq_id"] == "dlq-001"
        assert body["replay_status"] == "replayed"
        assert "new_correlation_id" in body
        # events 컨테이너에 새 이벤트 생성
        mock_events.create_item.assert_awaited_once()
        # DLQ 문서 갱신
        mock_dlq.upsert_item.assert_awaited_once()

    @pytest.mark.asyncio()
    @patch("src.functions.dlq_api._get_settings")
    @patch("src.functions.dlq_api.get_dlq_container")
    @patch("src.functions.dlq_api.get_events_container")
    async def test_already_replayed_returns_409(
        self,
        _mock_events_fn: MagicMock,
        mock_dlq_fn: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """이미 replayed된 문서 → 409."""
        mock_dlq = AsyncMock()
        mock_dlq_fn.return_value = mock_dlq
        mock_dlq.read_item.return_value = _make_dlq_doc(replay_status="replayed")

        req = _make_http_request(
            method="POST",
            params={"clinic_id": "CLINIC_123"},
            route_params={"dlq_id": "dlq-001"},
        )
        resp = await post_dlq_replay(req)

        assert resp.status_code == 409
        body = json.loads(resp.get_body())
        assert body["error"] == "CONFLICT"

    @pytest.mark.asyncio()
    @patch("src.functions.dlq_api._get_settings")
    @patch("src.functions.dlq_api.get_dlq_container")
    @patch("src.functions.dlq_api.get_events_container")
    async def test_not_found_returns_404(
        self,
        _mock_events_fn: MagicMock,
        mock_dlq_fn: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """존재하지 않는 DLQ ID → 404."""
        mock_dlq = AsyncMock()
        mock_dlq_fn.return_value = mock_dlq
        mock_dlq.read_item.side_effect = CosmosResourceNotFoundError()

        req = _make_http_request(
            method="POST",
            params={"clinic_id": "CLINIC_123"},
            route_params={"dlq_id": "dlq-999"},
        )
        resp = await post_dlq_replay(req)

        assert resp.status_code == 404

    @pytest.mark.asyncio()
    @patch("src.functions.dlq_api._get_settings")
    @patch("src.functions.dlq_api.get_dlq_container")
    @patch("src.functions.dlq_api.get_events_container")
    async def test_missing_clinic_id_returns_400(
        self,
        _mock_events_fn: MagicMock,
        _mock_dlq_fn: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """clinic_id 누락 시 400."""
        req = _make_http_request(
            method="POST",
            params={},
            route_params={"dlq_id": "dlq-001"},
        )
        resp = await post_dlq_replay(req)

        assert resp.status_code == 400

    @pytest.mark.asyncio()
    @patch("src.functions.dlq_api._get_settings")
    @patch("src.functions.dlq_api.get_dlq_container")
    @patch("src.functions.dlq_api.get_events_container")
    async def test_new_correlation_id_generated(
        self,
        mock_events_fn: MagicMock,
        mock_dlq_fn: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """Replay 시 새 correlation_id가 발급된다."""
        mock_dlq = AsyncMock()
        mock_dlq_fn.return_value = mock_dlq
        mock_events = AsyncMock()
        mock_events_fn.return_value = mock_events

        mock_dlq.read_item.return_value = _make_dlq_doc()

        req = _make_http_request(
            method="POST",
            params={"clinic_id": "CLINIC_123"},
            route_params={"dlq_id": "dlq-001"},
        )
        resp = await post_dlq_replay(req)

        body = json.loads(resp.get_body())
        # 새 correlation_id는 원본과 다름
        assert body["new_correlation_id"] != "old-corr-001"
        # events에 생성된 문서의 correlation_id 확인
        created_event = mock_events.create_item.call_args.kwargs["body"]
        assert created_event["correlation_id"] == body["new_correlation_id"]


class TestPostDlqReplayBatch:
    """POST /dlq/replay-batch 테스트."""

    @pytest.mark.asyncio()
    @patch("src.functions.dlq_api._get_settings")
    @patch("src.functions.dlq_api.get_dlq_container")
    @patch("src.functions.dlq_api.get_events_container")
    async def test_batch_replay_success(
        self,
        mock_events_fn: MagicMock,
        mock_dlq_fn: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """배치 Replay 정상 동작."""
        mock_dlq = AsyncMock()
        mock_dlq_fn.return_value = mock_dlq
        mock_events = AsyncMock()
        mock_events_fn.return_value = mock_events

        docs = [_make_dlq_doc(dlq_id=f"dlq-{i}") for i in range(3)]
        mock_dlq.query_items = MagicMock(return_value=_AsyncIterable(docs))

        req = _make_http_request(
            method="POST",
            body={"clinic_id": "CLINIC_123"},
        )
        resp = await post_dlq_replay_batch(req)

        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["replayed_count"] == 3
        assert body["failed_count"] == 0
        assert body["skipped_count"] == 0

    @pytest.mark.asyncio()
    @patch("src.functions.dlq_api._get_settings")
    @patch("src.functions.dlq_api.get_dlq_container")
    @patch("src.functions.dlq_api.get_events_container")
    async def test_batch_max_count_clamped_to_500(
        self,
        mock_events_fn: MagicMock,
        mock_dlq_fn: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """max_count > 500 → 500으로 클램핑."""
        mock_dlq = AsyncMock()
        mock_dlq_fn.return_value = mock_dlq
        mock_events = AsyncMock()
        mock_events_fn.return_value = mock_events

        # 600개 문서 — 500개만 처리됨
        docs = [_make_dlq_doc(dlq_id=f"dlq-{i}") for i in range(600)]
        mock_dlq.query_items = MagicMock(return_value=_AsyncIterable(docs))

        req = _make_http_request(
            method="POST",
            body={"clinic_id": "CLINIC_123", "max_count": 999},
        )
        resp = await post_dlq_replay_batch(req)

        body = json.loads(resp.get_body())
        assert body["replayed_count"] == 500

    @pytest.mark.asyncio()
    @patch("src.functions.dlq_api._get_settings")
    @patch("src.functions.dlq_api.get_dlq_container")
    @patch("src.functions.dlq_api.get_events_container")
    async def test_batch_missing_clinic_id_returns_400(
        self,
        _mock_events_fn: MagicMock,
        _mock_dlq_fn: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """clinic_id 누락 시 400."""
        req = _make_http_request(method="POST", body={})
        resp = await post_dlq_replay_batch(req)

        assert resp.status_code == 400

    @pytest.mark.asyncio()
    @patch("src.functions.dlq_api._get_settings")
    @patch("src.functions.dlq_api.get_dlq_container")
    @patch("src.functions.dlq_api.get_events_container")
    async def test_batch_counts_accurate(
        self,
        mock_events_fn: MagicMock,
        mock_dlq_fn: MagicMock,
        _mock_settings: MagicMock,
    ) -> None:
        """배치 결과 카운트가 정확하다 (replayed, failed, skipped)."""
        mock_dlq = AsyncMock()
        mock_dlq_fn.return_value = mock_dlq
        mock_events = AsyncMock()
        mock_events_fn.return_value = mock_events

        docs = [
            _make_dlq_doc(dlq_id="dlq-ok"),
            _make_dlq_doc(dlq_id="dlq-fail"),
            _make_dlq_doc(dlq_id="dlq-ok2"),
        ]
        mock_dlq.query_items = MagicMock(return_value=_AsyncIterable(docs))

        # 두 번째 upsert(dlq-fail)만 실패
        call_count = 0

        async def _upsert_side_effect(**kwargs: object) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("DB write error")
            return {}

        mock_dlq.upsert_item.side_effect = _upsert_side_effect

        req = _make_http_request(
            method="POST",
            body={"clinic_id": "CLINIC_123"},
        )
        resp = await post_dlq_replay_batch(req)

        body = json.loads(resp.get_body())
        assert body["replayed_count"] == 2
        assert body["failed_count"] == 1
        assert body["skipped_count"] == 0


# --- Helpers ---


async def _async_iter(items: list) -> Any:
    """비동기 이터레이터 헬퍼."""
    for item in items:
        yield item


class _AsyncIterable:
    """비동기 이터러블 래퍼 — query_items 반환값 mock."""

    def __init__(self, items: list) -> None:
        self._items = items

    def __aiter__(self) -> _AsyncIterable:
        self._index = 0
        return self

    async def __anext__(self) -> Any:
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item
