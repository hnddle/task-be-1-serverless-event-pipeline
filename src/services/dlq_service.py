"""Dead Letter Queue 서비스.

최대 재시도 초과 메시지를 DLQ 컨테이너에 저장하고
원본 이벤트 문서의 해당 채널 상태를 갱신한다.

SPEC.md §6.2 (Dead Letter Queue) 참조.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.services.cosmos_client import get_dlq_container
from src.shared.correlation import get_correlation_id
from src.shared.logger import log_with_context

if TYPE_CHECKING:
    from src.shared.config import Settings

logger = logging.getLogger(__name__)


class DlqService:
    """DLQ 저장 및 조회 서비스.

    최대 재시도 초과 시 채널별 실패 정보를 DLQ 컨테이너에 저장한다.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send_to_dlq(
        self,
        *,
        original_event_id: str,
        clinic_id: str,
        channel: str,
        provider: str,
        event_type: str,
        patient_id: str,
        payload: dict[str, Any],
        failure_reason: str,
        retry_count: int,
    ) -> dict[str, Any]:
        """실패한 채널 메시지를 DLQ에 저장한다.

        Args:
            original_event_id: 원본 이벤트 ID.
            clinic_id: Partition Key.
            channel: 실패한 채널명.
            provider: 실패한 프로바이더명.
            event_type: 이벤트 타입.
            patient_id: 환자 ID.
            payload: 원본 이벤트 전체 문서 스냅샷.
            failure_reason: 최종 실패 사유.
            retry_count: 총 재시도 횟수.

        Returns:
            저장된 DLQ 문서.
        """
        dlq_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        correlation_id = get_correlation_id() or ""

        dlq_doc: dict[str, Any] = {
            "id": dlq_id,
            "original_event_id": original_event_id,
            "clinic_id": clinic_id,
            "channel": channel,
            "provider": provider,
            "event_type": event_type,
            "patient_id": patient_id,
            "payload": payload,
            "failure_reason": failure_reason,
            "retry_count": retry_count,
            "correlation_id": correlation_id,
            "created_at": now,
            "replay_status": "pending",
            "replayed_at": None,
        }

        container = get_dlq_container(self._settings)
        await container.create_item(body=dlq_doc)

        log_with_context(
            logger,
            logging.ERROR,
            "DLQ 이동",
            event_id=original_event_id,
            dlq_id=dlq_id,
            channel=channel,
            provider=provider,
            failure_reason=failure_reason,
            total_retry_count=retry_count,
        )

        return dlq_doc
