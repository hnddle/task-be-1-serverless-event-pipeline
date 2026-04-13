"""Outbox Retry — 발행 실패 문서 재시도.

failed_publish 상태의 문서를 주기적으로 조회하여
pending으로 재갱신함으로써 Change Feed를 재발화시킨다.

SPEC.md §4.4 (Transactional Outbox 패턴) 참조.
"""

from __future__ import annotations

import logging
from typing import Any

import azure.functions as func

from src.services.cosmos_client import get_events_container
from src.shared.config import load_settings
from src.shared.logger import log_with_context

logger = logging.getLogger(__name__)

bp = func.Blueprint()  # type: ignore[no-untyped-call]

_settings = None

QUERY_FAILED_PUBLISH = "SELECT c.id, c.clinic_id FROM c WHERE c._outbox_status = 'failed_publish'"


def _get_settings() -> Any:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


@bp.timer_trigger(
    arg_name="timer",
    schedule="0 */1 * * * *",
)
async def outbox_retry(timer: func.TimerRequest) -> None:
    """Timer Trigger — failed_publish 문서를 pending으로 재갱신한다.

    1분 간격으로 실행되며, Change Feed가 재발화되어
    outbox-publisher가 다시 발행을 시도한다.
    """
    settings = _get_settings()
    container = get_events_container(settings)

    updated = 0
    errors = 0

    async for item in container.query_items(
        query=QUERY_FAILED_PUBLISH,
        enable_cross_partition_query=True,
    ):
        event_id: str = item["id"]
        clinic_id: str = item["clinic_id"]

        try:
            await container.patch_item(
                item=event_id,
                partition_key=clinic_id,
                patch_operations=[
                    {"op": "set", "path": "/_outbox_status", "value": "pending"},
                ],
            )
            updated += 1
        except Exception:
            logger.exception("Outbox Retry 갱신 실패: %s", event_id)
            errors += 1

    log_with_context(
        logger,
        logging.INFO,
        "Outbox Retry 배치 완료",
        updated=updated,
        errors=errors,
        past_due=timer.past_due,
    )
