"""Outbox Retry 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.functions.outbox_retry import outbox_retry


def _make_timer(past_due: bool = False) -> MagicMock:
    """테스트용 TimerRequest를 생성한다."""
    timer = MagicMock()
    timer.past_due = past_due
    return timer


class TestOutboxRetry:
    """Outbox Retry Function 테스트."""

    @pytest.mark.asyncio()
    @patch("src.functions.outbox_retry._get_settings")
    @patch("src.functions.outbox_retry.get_events_container")
    async def test_failed_publish_documents_are_retried(
        self, mock_container_fn: MagicMock, mock_settings: MagicMock
    ) -> None:
        """failed_publish 문서가 pending으로 재갱신된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        # query_items가 async iterable을 반환
        items = [
            {"id": "evt-1", "clinic_id": "CLINIC_A"},
            {"id": "evt-2", "clinic_id": "CLINIC_B"},
        ]

        async def _mock_query_items(**kwargs: object) -> AsyncMock:
            for item in items:
                yield item

        mock_container.query_items = _mock_query_items

        timer = _make_timer()
        await outbox_retry(timer)

        assert mock_container.patch_item.await_count == 2

        # 첫 번째 호출 확인
        first_call = mock_container.patch_item.call_args_list[0]
        assert first_call.kwargs["item"] == "evt-1"
        assert first_call.kwargs["partition_key"] == "CLINIC_A"
        assert first_call.kwargs["patch_operations"][0]["value"] == "pending"

        # 두 번째 호출 확인
        second_call = mock_container.patch_item.call_args_list[1]
        assert second_call.kwargs["item"] == "evt-2"
        assert second_call.kwargs["partition_key"] == "CLINIC_B"
        assert second_call.kwargs["patch_operations"][0]["value"] == "pending"

    @pytest.mark.asyncio()
    @patch("src.functions.outbox_retry._get_settings")
    @patch("src.functions.outbox_retry.get_events_container")
    async def test_no_failed_documents(self, mock_container_fn: MagicMock, mock_settings: MagicMock) -> None:
        """failed_publish 문서가 없으면 아무 작업도 하지 않는다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        async def _mock_query_items(**kwargs: object) -> AsyncMock:
            return
            yield  # async generator로 만들기 위한 unreachable yield

        mock_container.query_items = _mock_query_items

        timer = _make_timer()
        await outbox_retry(timer)

        mock_container.patch_item.assert_not_awaited()

    @pytest.mark.asyncio()
    @patch("src.functions.outbox_retry._get_settings")
    @patch("src.functions.outbox_retry.get_events_container")
    async def test_patch_failure_does_not_stop_processing(
        self, mock_container_fn: MagicMock, mock_settings: MagicMock
    ) -> None:
        """하나의 문서 갱신 실패가 나머지 문서 처리를 중단하지 않는다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        items = [
            {"id": "evt-1", "clinic_id": "CLINIC_A"},
            {"id": "evt-2", "clinic_id": "CLINIC_B"},
            {"id": "evt-3", "clinic_id": "CLINIC_C"},
        ]

        async def _mock_query_items(**kwargs: object) -> AsyncMock:
            for item in items:
                yield item

        mock_container.query_items = _mock_query_items

        # 두 번째 호출에서 실패
        mock_container.patch_item.side_effect = [None, RuntimeError("DB error"), None]

        timer = _make_timer()
        await outbox_retry(timer)

        # 3건 모두 시도됨
        assert mock_container.patch_item.await_count == 3

    @pytest.mark.asyncio()
    @patch("src.functions.outbox_retry._get_settings")
    @patch("src.functions.outbox_retry.get_events_container")
    async def test_past_due_timer_still_processes(self, mock_container_fn: MagicMock, mock_settings: MagicMock) -> None:
        """past_due 타이머도 정상 처리된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        items = [{"id": "evt-1", "clinic_id": "CLINIC_A"}]

        async def _mock_query_items(**kwargs: object) -> AsyncMock:
            for item in items:
                yield item

        mock_container.query_items = _mock_query_items

        timer = _make_timer(past_due=True)
        await outbox_retry(timer)

        mock_container.patch_item.assert_awaited_once()
