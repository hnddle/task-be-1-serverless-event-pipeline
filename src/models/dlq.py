"""Dead Letter Queue 관련 Pydantic 모델.

Cosmos DB `dead-letter-queue` 컨테이너 문서 구조와 1:1 대응.
SPEC.md §3.2 참조.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class ReplayStatus(StrEnum):
    """DLQ 재처리 상태."""

    PENDING = "pending"
    REPLAYED = "replayed"
    PERMANENTLY_FAILED = "permanently_failed"


class DeadLetterDocument(BaseModel):
    """Dead Letter Queue 문서 (Cosmos DB `dead-letter-queue` 컨테이너).

    clinic_id가 Partition Key이다.
    payload는 원본 이벤트 전체 문서의 스냅샷.
    """

    id: str
    original_event_id: str
    clinic_id: str
    channel: str
    provider: str
    event_type: str
    patient_id: str
    payload: dict[str, Any]
    failure_reason: str
    retry_count: int = 0
    correlation_id: str
    created_at: datetime
    replay_status: ReplayStatus = ReplayStatus.PENDING
    replayed_at: datetime | None = None
