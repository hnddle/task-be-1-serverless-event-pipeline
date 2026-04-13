"""DLQ API — Dead Letter Queue 조회 및 Replay.

GET /dlq: DLQ 메시지 목록 조회 (필터/페이지네이션)
POST /dlq/{dlq_id}/replay: 단건 DLQ Replay
POST /dlq/replay-batch: 배치 DLQ Replay

SPEC.md §6.3, §8.3 참조.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import azure.functions as func
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from src.services.cosmos_client import get_dlq_container, get_events_container
from src.shared.config import load_settings
from src.shared.correlation import clear_context, generate_correlation_id, set_correlation_id, set_log_context
from src.shared.logger import log_with_context

logger = logging.getLogger(__name__)

bp = func.Blueprint()  # type: ignore[no-untyped-call]

_settings = None


def _get_settings() -> Any:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def _json_response(body: dict[str, Any], status_code: int = 200) -> func.HttpResponse:
    """JSON HttpResponse를 생성한다."""
    return func.HttpResponse(
        body=json.dumps(body, ensure_ascii=False, default=str),
        status_code=status_code,
        mimetype="application/json",
    )


def _error_response(
    error_code: str,
    message: str,
    status_code: int,
    details: list[Any] | None = None,
) -> func.HttpResponse:
    """에러 JSON 응답을 생성한다."""
    return _json_response(
        {"error": error_code, "message": message, "details": details or []},
        status_code=status_code,
    )


async def _replay_single(
    dlq_container: Any,
    events_container: Any,
    dlq_doc: dict[str, Any],
) -> dict[str, Any]:
    """단건 DLQ 문서를 Replay한다.

    1. replay_status → replayed, replayed_at 기록
    2. 새 correlation_id 발급
    3. 원본 payload 기반으로 events 컨테이너에 새 이벤트 생성 (Outbox 패턴)

    Returns:
        {"dlq_id": str, "replay_status": "replayed", "new_correlation_id": str}
    """
    new_correlation_id = generate_correlation_id()
    now = datetime.now(UTC).isoformat()

    original_correlation_id = dlq_doc.get("correlation_id", "")

    log_with_context(
        logger,
        logging.INFO,
        "DLQ Replay",
        dlq_id=dlq_doc["id"],
        original_event_id=dlq_doc.get("original_event_id", ""),
        original_correlation_id=original_correlation_id,
        new_correlation_id=new_correlation_id,
    )

    # 1. DLQ 문서 갱신
    dlq_doc["replay_status"] = "replayed"
    dlq_doc["replayed_at"] = now
    await dlq_container.upsert_item(body=dlq_doc)

    # 2. 원본 payload 기반 새 이벤트 생성 (Outbox 패턴)
    payload = dlq_doc.get("payload", {})
    new_event_id = str(uuid.uuid4())

    new_event: dict[str, Any] = {
        "id": new_event_id,
        "clinic_id": dlq_doc.get("clinic_id", payload.get("clinic_id", "")),
        "status": "queued",
        "event_type": dlq_doc.get("event_type", payload.get("event_type", "")),
        "patient_id": dlq_doc.get("patient_id", payload.get("patient_id", "")),
        "channels": [dlq_doc.get("channel", "")],
        "correlation_id": new_correlation_id,
        "notifications": [
            {
                "channel": dlq_doc.get("channel", ""),
                "provider": dlq_doc.get("provider", ""),
                "status": "pending",
                "sent_at": None,
                "retry_count": 0,
                "last_error": None,
            }
        ],
        "created_at": now,
        "updated_at": now,
        "_outbox_status": "pending",
    }

    await events_container.create_item(body=new_event)

    return {
        "dlq_id": dlq_doc["id"],
        "replay_status": "replayed",
        "new_correlation_id": new_correlation_id,
    }


@bp.route(route="dlq", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def get_dlq(req: func.HttpRequest) -> func.HttpResponse:
    """GET /dlq — DLQ 메시지 목록 조회.

    clinic_id 필수, replay_status/event_type/date_from/date_to 필터,
    continuation_token/page_size 페이지네이션.
    """
    clear_context()
    clinic_id = req.params.get("clinic_id")

    if not clinic_id:
        return _error_response("VALIDATION_ERROR", "clinic_id query parameter is required", 400)

    set_log_context(clinic_id=clinic_id)

    replay_status = req.params.get("replay_status")
    event_type = req.params.get("event_type")
    date_from = req.params.get("date_from")
    date_to = req.params.get("date_to")
    continuation_token = req.params.get("continuation_token")
    page_size = min(int(req.params.get("page_size", "20")), 100)

    settings = _get_settings()
    container = get_dlq_container(settings)

    # 쿼리 빌드
    conditions = ["c.clinic_id = @clinic_id"]
    parameters: list[dict[str, object]] = [{"name": "@clinic_id", "value": clinic_id}]

    if replay_status:
        conditions.append("c.replay_status = @replay_status")
        parameters.append({"name": "@replay_status", "value": replay_status})

    if event_type:
        conditions.append("c.event_type = @event_type")
        parameters.append({"name": "@event_type", "value": event_type})

    if date_from:
        conditions.append("c.created_at >= @date_from")
        parameters.append({"name": "@date_from", "value": date_from})

    if date_to:
        conditions.append("c.created_at <= @date_to")
        parameters.append({"name": "@date_to", "value": date_to})

    where_clause = " AND ".join(conditions)
    query = f"SELECT * FROM c WHERE {where_clause} ORDER BY c.created_at DESC"

    try:
        items: list[dict[str, Any]] = []
        new_continuation_token = None

        query_iterable = container.query_items(
            query=query,
            parameters=parameters,
            partition_key=clinic_id,
            max_item_count=page_size,
        )

        pager = query_iterable.by_page(continuation_token)
        async for page in pager:
            async for item in page:
                # Cosmos DB 메타 필드 제거
                for key in ("_rid", "_self", "_etag", "_attachments", "_ts"):
                    item.pop(key, None)
                items.append(item)
            new_continuation_token = pager.continuation_token  # type: ignore[attr-defined]
            break  # 첫 페이지만

        return _json_response(
            {
                "items": items,
                "continuation_token": new_continuation_token,
                "total_count": len(items),
            }
        )

    except Exception:
        logger.exception("DLQ 목록 조회 실패")
        return _error_response("INTERNAL_ERROR", "Internal server error", 500)


@bp.route(route="dlq/{dlq_id}/replay", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def post_dlq_replay(req: func.HttpRequest) -> func.HttpResponse:
    """POST /dlq/{dlq_id}/replay — 단건 DLQ Replay.

    replay_status → replayed, 새 correlation_id 발급, Outbox 패턴으로 재발행.
    이미 replayed → 409.
    """
    clear_context()
    dlq_id = req.route_params.get("dlq_id", "")
    clinic_id = req.params.get("clinic_id")

    if not clinic_id:
        return _error_response("VALIDATION_ERROR", "clinic_id query parameter is required", 400)

    set_log_context(dlq_id=dlq_id, clinic_id=clinic_id)

    settings = _get_settings()
    dlq_container = get_dlq_container(settings)
    events_container = get_events_container(settings)

    try:
        dlq_doc = await dlq_container.read_item(item=dlq_id, partition_key=clinic_id)
    except CosmosResourceNotFoundError:
        return _error_response("NOT_FOUND", f"DLQ item {dlq_id} not found", 404)
    except Exception:
        logger.exception("DLQ 조회 실패")
        return _error_response("INTERNAL_ERROR", "Internal server error", 500)

    # 이미 replayed → 409
    if dlq_doc.get("replay_status") == "replayed":
        return _error_response("CONFLICT", f"DLQ item {dlq_id} already replayed", 409)

    try:
        result = await _replay_single(dlq_container, events_container, dlq_doc)
        return _json_response(result)
    except Exception:
        logger.exception("DLQ Replay 실패")
        return _error_response("INTERNAL_ERROR", "Internal server error", 500)


@bp.route(route="dlq/replay-batch", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def post_dlq_replay_batch(req: func.HttpRequest) -> func.HttpResponse:
    """POST /dlq/replay-batch — 배치 DLQ Replay.

    clinic_id 필수, event_type/date_from/date_to 선택, max_count (기본 100, 최대 500).
    """
    clear_context()

    try:
        body: dict[str, Any] = req.get_json()
    except ValueError:
        return _error_response("VALIDATION_ERROR", "Invalid JSON body", 400)

    clinic_id = body.get("clinic_id")
    if not clinic_id:
        return _error_response("VALIDATION_ERROR", "clinic_id is required", 400)

    correlation_id = generate_correlation_id()
    set_correlation_id(correlation_id)
    set_log_context(clinic_id=clinic_id)

    event_type = body.get("event_type")
    date_from = body.get("date_from")
    date_to = body.get("date_to")
    max_count = min(int(body.get("max_count", 100)), 500)

    settings = _get_settings()
    dlq_container = get_dlq_container(settings)
    events_container = get_events_container(settings)

    # pending 상태만 조회
    conditions = ["c.clinic_id = @clinic_id", "c.replay_status = 'pending'"]
    parameters: list[dict[str, object]] = [{"name": "@clinic_id", "value": clinic_id}]

    if event_type:
        conditions.append("c.event_type = @event_type")
        parameters.append({"name": "@event_type", "value": event_type})

    if date_from:
        conditions.append("c.created_at >= @date_from")
        parameters.append({"name": "@date_from", "value": date_from})

    if date_to:
        conditions.append("c.created_at <= @date_to")
        parameters.append({"name": "@date_to", "value": date_to})

    where_clause = " AND ".join(conditions)
    query = f"SELECT * FROM c WHERE {where_clause}"

    replayed_count = 0
    failed_count = 0
    skipped_count = 0

    try:
        query_iterable = dlq_container.query_items(
            query=query,
            parameters=parameters,
            partition_key=clinic_id,
        )

        processed = 0
        async for doc in query_iterable:
            if processed >= max_count:
                break

            # 이미 replayed → skip
            if doc.get("replay_status") != "pending":
                skipped_count += 1
                processed += 1
                continue

            try:
                await _replay_single(dlq_container, events_container, doc)
                replayed_count += 1
            except Exception:
                logger.exception("배치 Replay 개별 실패: %s", doc.get("id", "unknown"))
                failed_count += 1

            processed += 1

        return _json_response(
            {
                "replayed_count": replayed_count,
                "failed_count": failed_count,
                "skipped_count": skipped_count,
            }
        )

    except Exception:
        logger.exception("DLQ 배치 Replay 실패")
        return _error_response("INTERNAL_ERROR", "Internal server error", 500)
