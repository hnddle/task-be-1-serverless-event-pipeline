"""Circuit Breaker 상태 Pydantic 모델.

Cosmos DB `circuit-breaker` 컨테이너 문서 구조와 1:1 대응.
SPEC.md §3.3 참조.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CircuitState(StrEnum):
    """Circuit Breaker 상태."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


class CircuitBreakerDocument(BaseModel):
    """Circuit Breaker 상태 문서 (Cosmos DB `circuit-breaker` 컨테이너).

    id는 `{channel}:{provider}` 형식이며 Partition Key를 겸한다.
    _etag는 낙관적 동시성 제어에 사용된다.
    """

    id: str
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_at: datetime | None = None
    opened_at: datetime | None = None
    updated_at: datetime
    etag: str | None = Field(default=None, alias="_etag")

    model_config = {"populate_by_name": True}
