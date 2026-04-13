"""Circuit Breaker — Cosmos DB 기반 상태 머신.

{channel}:{provider} 조합별 독립 Circuit Breaker를 운용한다.
상태 머신: Closed → Open → Half-Open → Closed/Open.
ETag 기반 낙관적 동시성 제어를 적용한다.

SPEC.md §4.3 참조.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from azure.cosmos.exceptions import CosmosAccessConditionFailedError, CosmosResourceNotFoundError

from src.models.circuit_breaker import CircuitBreakerDocument, CircuitState
from src.services.cosmos_client import get_circuit_breaker_container
from src.shared.logger import log_with_context

if TYPE_CHECKING:
    from src.shared.config import Settings

logger = logging.getLogger(__name__)

# ETag 충돌 시 최대 재시도 횟수
MAX_ETAG_RETRIES = 3


class CircuitOpenError(Exception):
    """Circuit이 Open 상태여서 요청을 차단한다."""

    def __init__(self, circuit_id: str) -> None:
        super().__init__(f"Circuit open: {circuit_id}")
        self.circuit_id = circuit_id


class CircuitBreaker:
    """Cosmos DB 기반 Circuit Breaker.

    각 {channel}:{provider} 조합별로 독립적으로 운용된다.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._container = get_circuit_breaker_container(settings)

    def _make_circuit_id(self, channel: str, provider: str) -> str:
        """Circuit Breaker ID를 생성한다."""
        return f"{channel}:{provider}"

    async def _read_state(self, circuit_id: str) -> CircuitBreakerDocument:
        """Cosmos DB에서 Circuit Breaker 상태를 읽는다.

        문서가 없으면 Closed 상태의 기본 문서를 반환한다.
        """
        try:
            doc = await self._container.read_item(
                item=circuit_id,
                partition_key=circuit_id,
            )
            return CircuitBreakerDocument(**doc)
        except CosmosResourceNotFoundError:
            return CircuitBreakerDocument(
                id=circuit_id,
                state=CircuitState.CLOSED,
                failure_count=0,
                success_count=0,
                updated_at=_now_ms(),
            )

    async def _save_state(self, doc: CircuitBreakerDocument) -> CircuitBreakerDocument:
        """Cosmos DB에 Circuit Breaker 상태를 저장한다.

        ETag가 있으면 조건부 업데이트, 없으면 upsert.
        """
        body = doc.model_dump(by_alias=True)
        for field in ("updated_at", "last_failure_at", "opened_at"):
            val = body.get(field)
            if val and hasattr(val, "isoformat"):
                body[field] = val.isoformat()

        kwargs: dict[str, Any] = {"body": body, "partition_key": doc.id}
        if doc.etag:
            kwargs["etag"] = doc.etag
            kwargs["match_condition"] = "IfMatch"

        result = await self._container.upsert_item(**kwargs)
        return CircuitBreakerDocument(**result)

    def _is_cooldown_expired(self, doc: CircuitBreakerDocument) -> bool:
        """Open 상태에서 cooldown이 만료되었는지 확인한다."""
        if doc.opened_at is None:
            return True
        elapsed_ms = (time.time() - doc.opened_at.timestamp()) * 1000
        return elapsed_ms >= self._settings.CB_COOLDOWN_MS

    async def check_state(self, channel: str, provider: str) -> CircuitState:
        """현재 Circuit 상태를 확인하고 필요 시 Half-Open으로 전이한다.

        Open이고 cooldown이 만료되면 Half-Open으로 전환한다.
        Open이고 cooldown이 남았으면 CircuitOpenError를 발생시킨다.

        Returns:
            현재 Circuit 상태 (Closed, Half-Open).

        Raises:
            CircuitOpenError: Circuit이 Open 상태이고 cooldown 미만료.
        """
        circuit_id = self._make_circuit_id(channel, provider)

        for attempt in range(MAX_ETAG_RETRIES):
            doc = await self._read_state(circuit_id)

            if doc.state == CircuitState.CLOSED:
                return CircuitState.CLOSED

            if doc.state == CircuitState.HALF_OPEN:
                return CircuitState.HALF_OPEN

            # Open 상태
            if not self._is_cooldown_expired(doc):
                raise CircuitOpenError(circuit_id)

            # cooldown 만료 → Half-Open 전환
            old_state = doc.state
            doc.state = CircuitState.HALF_OPEN
            doc.success_count = 0
            doc.updated_at = _now_ms()

            try:
                await self._save_state(doc)
                _log_state_change(circuit_id, old_state, CircuitState.HALF_OPEN)
                return CircuitState.HALF_OPEN
            except CosmosAccessConditionFailedError:
                if attempt < MAX_ETAG_RETRIES - 1:
                    continue
                raise

        return CircuitState.HALF_OPEN  # pragma: no cover

    async def record_success(self, channel: str, provider: str) -> None:
        """성공을 기록한다.

        Half-Open에서 연속 성공이 CB_SUCCESS_THRESHOLD에 도달하면 Closed로 복귀.
        Closed에서는 failure_count를 0으로 리셋.
        """
        circuit_id = self._make_circuit_id(channel, provider)

        for attempt in range(MAX_ETAG_RETRIES):
            doc = await self._read_state(circuit_id)

            if doc.state == CircuitState.CLOSED:
                if doc.failure_count > 0:
                    doc.failure_count = 0
                    doc.updated_at = _now_ms()
                    try:
                        await self._save_state(doc)
                    except CosmosAccessConditionFailedError:
                        if attempt < MAX_ETAG_RETRIES - 1:
                            continue
                        raise
                return

            if doc.state == CircuitState.HALF_OPEN:
                doc.success_count += 1
                doc.updated_at = _now_ms()

                if doc.success_count >= self._settings.CB_SUCCESS_THRESHOLD:
                    old_state = doc.state
                    doc.state = CircuitState.CLOSED
                    doc.failure_count = 0
                    doc.success_count = 0
                    doc.opened_at = None

                    try:
                        await self._save_state(doc)
                        _log_state_change(circuit_id, old_state, CircuitState.CLOSED)
                    except CosmosAccessConditionFailedError:
                        if attempt < MAX_ETAG_RETRIES - 1:
                            continue
                        raise
                else:
                    try:
                        await self._save_state(doc)
                    except CosmosAccessConditionFailedError:
                        if attempt < MAX_ETAG_RETRIES - 1:
                            continue
                        raise
                return

            # Open 상태에서 success는 무시 (비정상 경로)
            return

    async def record_failure(self, channel: str, provider: str) -> None:
        """실패를 기록한다.

        Closed에서 연속 실패가 CB_FAILURE_THRESHOLD에 도달하면 Open으로 전환.
        Half-Open에서 1회 실패 시 즉시 Open으로 재전환.
        """
        circuit_id = self._make_circuit_id(channel, provider)

        for attempt in range(MAX_ETAG_RETRIES):
            doc = await self._read_state(circuit_id)

            now = _now_ms()
            doc.failure_count += 1
            doc.last_failure_at = now
            doc.updated_at = now

            old_state: CircuitState

            if doc.state == CircuitState.CLOSED:
                if doc.failure_count >= self._settings.CB_FAILURE_THRESHOLD:
                    old_state = doc.state
                    doc.state = CircuitState.OPEN
                    doc.opened_at = now
                    doc.success_count = 0

                    try:
                        await self._save_state(doc)
                        _log_state_change(circuit_id, old_state, CircuitState.OPEN)
                    except CosmosAccessConditionFailedError:
                        if attempt < MAX_ETAG_RETRIES - 1:
                            continue
                        raise
                else:
                    try:
                        await self._save_state(doc)
                    except CosmosAccessConditionFailedError:
                        if attempt < MAX_ETAG_RETRIES - 1:
                            continue
                        raise
                return

            if doc.state == CircuitState.HALF_OPEN:
                old_state = doc.state
                doc.state = CircuitState.OPEN
                doc.opened_at = now
                doc.success_count = 0

                try:
                    await self._save_state(doc)
                    _log_state_change(circuit_id, old_state, CircuitState.OPEN)
                except CosmosAccessConditionFailedError:
                    if attempt < MAX_ETAG_RETRIES - 1:
                        continue
                    raise
                return

            # Open 상태에서 failure는 카운트만 갱신
            try:
                await self._save_state(doc)
            except CosmosAccessConditionFailedError:
                if attempt < MAX_ETAG_RETRIES - 1:
                    continue
                raise
            return


def _now_ms() -> Any:
    """현재 시각을 datetime으로 반환한다."""
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _log_state_change(circuit_id: str, from_state: CircuitState, to_state: CircuitState) -> None:
    """Circuit Breaker 상태 변경 로그를 출력한다."""
    log_with_context(
        logger,
        logging.WARNING,
        "Circuit Breaker 상태 변경",
        circuit_id=circuit_id,
        from_state=str(from_state),
        to_state=str(to_state),
    )
