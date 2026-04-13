"""Circuit Breaker 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from azure.cosmos.exceptions import CosmosAccessConditionFailedError, CosmosResourceNotFoundError

from src.models.circuit_breaker import CircuitState
from src.services.circuit_breaker import CircuitBreaker, CircuitOpenError


def _make_settings(
    failure_threshold: int = 5,
    cooldown_ms: int = 30000,
    success_threshold: int = 2,
) -> MagicMock:
    """테스트용 Settings를 생성한다."""
    settings = MagicMock()
    settings.CB_FAILURE_THRESHOLD = failure_threshold
    settings.CB_COOLDOWN_MS = cooldown_ms
    settings.CB_SUCCESS_THRESHOLD = success_threshold
    return settings


def _make_doc(
    circuit_id: str = "email:sendgrid",
    state: str = "closed",
    failure_count: int = 0,
    success_count: int = 0,
    opened_at: datetime | None = None,
    etag: str | None = "etag-1",
) -> dict:
    """테스트용 Cosmos DB 문서 dict를 생성한다."""
    doc = {
        "id": circuit_id,
        "state": state,
        "failure_count": failure_count,
        "success_count": success_count,
        "last_failure_at": None,
        "opened_at": opened_at.isoformat() if opened_at else None,
        "updated_at": datetime.now(UTC).isoformat(),
        "_etag": etag,
    }
    return doc


class TestCheckState:
    """check_state 메서드 테스트."""

    @pytest.mark.asyncio()
    @patch("src.services.circuit_breaker.get_circuit_breaker_container")
    async def test_closed_returns_closed(self, mock_container_fn: MagicMock) -> None:
        """Closed 상태 → Closed 반환."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = _make_doc(state="closed")

        cb = CircuitBreaker(_make_settings())
        state = await cb.check_state("email", "sendgrid")
        assert state == CircuitState.CLOSED

    @pytest.mark.asyncio()
    @patch("src.services.circuit_breaker.get_circuit_breaker_container")
    async def test_half_open_returns_half_open(self, mock_container_fn: MagicMock) -> None:
        """Half-Open 상태 → Half-Open 반환."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = _make_doc(state="half-open")

        cb = CircuitBreaker(_make_settings())
        state = await cb.check_state("email", "sendgrid")
        assert state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio()
    @patch("src.services.circuit_breaker.get_circuit_breaker_container")
    async def test_open_not_expired_raises_circuit_open(self, mock_container_fn: MagicMock) -> None:
        """Open + cooldown 미만료 → CircuitOpenError 발생."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = _make_doc(
            state="open",
            opened_at=datetime.now(UTC),  # 방금 열림
        )

        cb = CircuitBreaker(_make_settings(cooldown_ms=30000))
        with pytest.raises(CircuitOpenError):
            await cb.check_state("email", "sendgrid")

    @pytest.mark.asyncio()
    @patch("src.services.circuit_breaker.get_circuit_breaker_container")
    async def test_open_expired_transitions_to_half_open(self, mock_container_fn: MagicMock) -> None:
        """Open + cooldown 만료 → Half-Open 전환."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = _make_doc(
            state="open",
            opened_at=datetime.now(UTC) - timedelta(seconds=60),  # 60초 전
        )
        mock_container.upsert_item.return_value = _make_doc(state="half-open")

        cb = CircuitBreaker(_make_settings(cooldown_ms=30000))
        state = await cb.check_state("email", "sendgrid")
        assert state == CircuitState.HALF_OPEN
        mock_container.upsert_item.assert_awaited_once()

    @pytest.mark.asyncio()
    @patch("src.services.circuit_breaker.get_circuit_breaker_container")
    async def test_not_found_returns_closed(self, mock_container_fn: MagicMock) -> None:
        """문서가 없으면 Closed 반환."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.side_effect = CosmosResourceNotFoundError()

        cb = CircuitBreaker(_make_settings())
        state = await cb.check_state("email", "sendgrid")
        assert state == CircuitState.CLOSED


class TestRecordFailure:
    """record_failure 메서드 테스트."""

    @pytest.mark.asyncio()
    @patch("src.services.circuit_breaker.get_circuit_breaker_container")
    async def test_failures_below_threshold_stay_closed(self, mock_container_fn: MagicMock) -> None:
        """실패 횟수가 threshold 미만이면 Closed 유지."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = _make_doc(failure_count=2)
        mock_container.upsert_item.return_value = _make_doc(failure_count=3)

        cb = CircuitBreaker(_make_settings(failure_threshold=5))
        await cb.record_failure("email", "sendgrid")

        call_body = mock_container.upsert_item.call_args.kwargs["body"]
        assert call_body["state"] == "closed"
        assert call_body["failure_count"] == 3

    @pytest.mark.asyncio()
    @patch("src.services.circuit_breaker.get_circuit_breaker_container")
    async def test_failures_at_threshold_opens_circuit(self, mock_container_fn: MagicMock) -> None:
        """실패 횟수가 threshold에 도달하면 Open 전환."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = _make_doc(failure_count=4)
        mock_container.upsert_item.return_value = _make_doc(state="open", failure_count=5)

        cb = CircuitBreaker(_make_settings(failure_threshold=5))
        await cb.record_failure("email", "sendgrid")

        call_body = mock_container.upsert_item.call_args.kwargs["body"]
        assert call_body["state"] == "open"
        assert call_body["failure_count"] == 5

    @pytest.mark.asyncio()
    @patch("src.services.circuit_breaker.get_circuit_breaker_container")
    async def test_half_open_failure_reopens_circuit(self, mock_container_fn: MagicMock) -> None:
        """Half-Open에서 1회 실패 → Open 재전환."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = _make_doc(state="half-open", success_count=1)
        mock_container.upsert_item.return_value = _make_doc(state="open")

        cb = CircuitBreaker(_make_settings())
        await cb.record_failure("email", "sendgrid")

        call_body = mock_container.upsert_item.call_args.kwargs["body"]
        assert call_body["state"] == "open"

    @pytest.mark.asyncio()
    @patch("src.services.circuit_breaker.get_circuit_breaker_container")
    async def test_new_circuit_failure_creates_document(self, mock_container_fn: MagicMock) -> None:
        """문서가 없는 상태에서 실패 기록 시 새 문서 생성."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.side_effect = CosmosResourceNotFoundError()
        mock_container.upsert_item.return_value = _make_doc(failure_count=1)

        cb = CircuitBreaker(_make_settings(failure_threshold=5))
        await cb.record_failure("email", "sendgrid")

        call_body = mock_container.upsert_item.call_args.kwargs["body"]
        assert call_body["failure_count"] == 1
        assert call_body["state"] == "closed"


class TestRecordSuccess:
    """record_success 메서드 테스트."""

    @pytest.mark.asyncio()
    @patch("src.services.circuit_breaker.get_circuit_breaker_container")
    async def test_closed_success_resets_failure_count(self, mock_container_fn: MagicMock) -> None:
        """Closed 상태에서 성공 시 failure_count 리셋."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = _make_doc(failure_count=3)
        mock_container.upsert_item.return_value = _make_doc(failure_count=0)

        cb = CircuitBreaker(_make_settings())
        await cb.record_success("email", "sendgrid")

        call_body = mock_container.upsert_item.call_args.kwargs["body"]
        assert call_body["failure_count"] == 0

    @pytest.mark.asyncio()
    @patch("src.services.circuit_breaker.get_circuit_breaker_container")
    async def test_half_open_success_below_threshold(self, mock_container_fn: MagicMock) -> None:
        """Half-Open에서 성공이 threshold 미만이면 Half-Open 유지."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = _make_doc(state="half-open", success_count=0)
        mock_container.upsert_item.return_value = _make_doc(state="half-open", success_count=1)

        cb = CircuitBreaker(_make_settings(success_threshold=2))
        await cb.record_success("email", "sendgrid")

        call_body = mock_container.upsert_item.call_args.kwargs["body"]
        assert call_body["state"] == "half-open"
        assert call_body["success_count"] == 1

    @pytest.mark.asyncio()
    @patch("src.services.circuit_breaker.get_circuit_breaker_container")
    async def test_half_open_success_at_threshold_closes_circuit(self, mock_container_fn: MagicMock) -> None:
        """Half-Open에서 연속 성공이 threshold에 도달하면 Closed 복귀."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = _make_doc(state="half-open", success_count=1)
        mock_container.upsert_item.return_value = _make_doc(state="closed", success_count=0, failure_count=0)

        cb = CircuitBreaker(_make_settings(success_threshold=2))
        await cb.record_success("email", "sendgrid")

        call_body = mock_container.upsert_item.call_args.kwargs["body"]
        assert call_body["state"] == "closed"
        assert call_body["failure_count"] == 0
        assert call_body["success_count"] == 0

    @pytest.mark.asyncio()
    @patch("src.services.circuit_breaker.get_circuit_breaker_container")
    async def test_closed_with_zero_failures_no_write(self, mock_container_fn: MagicMock) -> None:
        """Closed + failure_count=0이면 DB 쓰기 안 함."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = _make_doc(failure_count=0)

        cb = CircuitBreaker(_make_settings())
        await cb.record_success("email", "sendgrid")

        mock_container.upsert_item.assert_not_awaited()


class TestETagConflict:
    """ETag 충돌 재시도 테스트."""

    @pytest.mark.asyncio()
    @patch("src.services.circuit_breaker.get_circuit_breaker_container")
    async def test_etag_conflict_retries_on_failure(self, mock_container_fn: MagicMock) -> None:
        """ETag 충돌 시 재읽기 후 재시도한다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        # 첫 번째 read → 충돌 → 두 번째 read → 성공
        mock_container.read_item.side_effect = [
            _make_doc(failure_count=4, etag="etag-old"),
            _make_doc(failure_count=4, etag="etag-new"),
        ]
        mock_container.upsert_item.side_effect = [
            CosmosAccessConditionFailedError(),
            _make_doc(state="open", failure_count=5),
        ]

        cb = CircuitBreaker(_make_settings(failure_threshold=5))
        await cb.record_failure("email", "sendgrid")

        assert mock_container.upsert_item.await_count == 2

    @pytest.mark.asyncio()
    @patch("src.services.circuit_breaker.get_circuit_breaker_container")
    async def test_etag_conflict_exceeds_max_retries(self, mock_container_fn: MagicMock) -> None:
        """최대 재시도 초과 시 예외가 전파된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        mock_container.read_item.return_value = _make_doc(failure_count=4)
        mock_container.upsert_item.side_effect = CosmosAccessConditionFailedError()

        cb = CircuitBreaker(_make_settings(failure_threshold=5))
        with pytest.raises(CosmosAccessConditionFailedError):
            await cb.record_failure("email", "sendgrid")
