"""Event Consumer — Event Grid 기반 알림 발송.

Event Grid 트리거로 이벤트를 수신하여 채널별 알림을 발송하고
결과를 Cosmos DB에 기록한다.

SPEC.md §9 (Event Consumer) 참조.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import azure.functions as func

from src.services.cosmos_client import get_events_container
from src.services.notification.notification_factory import NotificationFactory
from src.shared.config import load_settings
from src.shared.correlation import clear_context, set_correlation_id, set_log_context
from src.shared.logger import log_with_context

logger = logging.getLogger(__name__)

bp = func.Blueprint()  # type: ignore[no-untyped-call]

_settings = None


def _get_settings() -> Any:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def _determine_final_status(notifications: list[dict[str, Any]]) -> str:
    """채널별 결과를 집계하여 최종 이벤트 상태를 결정한다.

    - 전체 성공 → completed
    - 일부 성공 → partially_completed
    - 전체 실패 → failed
    """
    statuses = [n["status"] for n in notifications]
    success_count = statuses.count("success")

    if success_count == len(statuses):
        return "completed"
    if success_count > 0:
        return "partially_completed"
    return "failed"


@bp.event_grid_trigger(arg_name="event")
async def event_consumer(event: func.EventGridEvent) -> None:
    """Event Grid Trigger — 이벤트를 수신하여 채널별 알림을 발송한다.

    처리 흐름:
    1. correlation_id 컨텍스트 바인딩
    2. Cosmos DB에서 이벤트 조회 (Idempotency)
    3. status → processing 갱신
    4. channels 순회: success 스킵 → Strategy.send()
    5. 결과 집계 → Cosmos DB 기록
    """
    event_data: dict[str, Any] = event.get_json()

    event_id: str = event_data.get("id", "unknown")
    clinic_id: str = event_data.get("clinic_id", "unknown")
    correlation_id: str = event_data.get("correlation_id", "")

    # 1. 컨텍스트 바인딩
    clear_context()
    if correlation_id:
        set_correlation_id(correlation_id)
    set_log_context(event_id=event_id, clinic_id=clinic_id)

    log_with_context(logger, logging.INFO, "Event Consumer 시작")

    settings = _get_settings()
    container = get_events_container(settings)
    factory = NotificationFactory(settings)

    # 2. Cosmos DB에서 이벤트 조회
    try:
        doc = await container.read_item(item=event_id, partition_key=clinic_id)
    except Exception:
        logger.exception("이벤트 조회 실패: %s", event_id)
        return

    notifications: list[dict[str, Any]] = doc.get("notifications", [])

    # 이미 최종 상태인 경우 스킵 (Idempotency)
    current_status = doc.get("status", "")
    if current_status in ("completed", "partially_completed", "failed"):
        log_with_context(
            logger,
            logging.INFO,
            "이미 처리된 이벤트 스킵",
            current_status=current_status,
        )
        return

    # 3. status → processing 갱신
    await container.patch_item(
        item=event_id,
        partition_key=clinic_id,
        patch_operations=[
            {"op": "set", "path": "/status", "value": "processing"},
            {"op": "set", "path": "/updated_at", "value": datetime.now(UTC).isoformat()},
        ],
    )

    # 4. channels 순회
    for notification in notifications:
        channel: str = notification.get("channel", "")

        # 이미 success인 채널 스킵 (멱등성)
        if notification.get("status") == "success":
            log_with_context(
                logger,
                logging.INFO,
                "이미 성공한 채널 스킵",
                channel=channel,
            )
            continue

        set_log_context(event_id=event_id, clinic_id=clinic_id, channel=channel)

        # Strategy 호출
        result = await factory.send_notification(
            channel,
            {
                "event_id": event_id,
                "clinic_id": clinic_id,
                "channel": channel,
                "provider": notification.get("provider", ""),
            },
        )

        now = datetime.now(UTC).isoformat()

        if result.success:
            notification["status"] = "success"
            notification["sent_at"] = now
            log_with_context(
                logger,
                logging.INFO,
                "알림 발송 성공",
                channel=channel,
                provider=result.provider,
                duration_ms=result.duration_ms,
            )
        else:
            notification["status"] = "failed"
            notification["last_error"] = result.message
            log_with_context(
                logger,
                logging.WARNING,
                "알림 발송 실패",
                channel=channel,
                provider=result.provider,
                error=result.message,
            )

    # 5. 결과 집계 및 Cosmos DB 기록
    final_status = _determine_final_status(notifications)

    await container.patch_item(
        item=event_id,
        partition_key=clinic_id,
        patch_operations=[
            {"op": "set", "path": "/status", "value": final_status},
            {"op": "set", "path": "/notifications", "value": notifications},
            {"op": "set", "path": "/updated_at", "value": datetime.now(UTC).isoformat()},
        ],
    )

    log_with_context(
        logger,
        logging.INFO,
        "Event Consumer 완료",
        final_status=final_status,
        total_channels=len(notifications),
    )
