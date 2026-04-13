"""Event API — 이벤트 수신, 저장, 조회.

POST /events: 이벤트 생성 (Cosmos DB 저장 + Idempotency)
GET /events/{event_id}: 이벤트 상세 조회
GET /events: 이벤트 목록 조회 (페이지네이션)

SPEC.md §7, §8.1, §8.2 참조.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import azure.functions as func
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError

from src.models.events import (
    EventStatus,
    NotificationChannel,
    NotificationChannelType,
    NotificationEvent,
    NotificationStatus,
)
from src.services.cosmos_client import get_events_container
from src.shared.config import load_settings
from src.shared.correlation import clear_context, generate_correlation_id, set_correlation_id, set_log_context
from src.shared.errors import ValidationError as AppValidationError
from src.shared.logger import log_with_context
from src.shared.validator import validate_create_event

logger = logging.getLogger(__name__)

bp = func.Blueprint()  # type: ignore[no-untyped-call]

_settings = None


def _get_settings() -> Any:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def _build_notifications(
    channels: list[NotificationChannelType],
    settings: Any,
) -> list[NotificationChannel]:
    """channels 목록에서 notifications 초기 배열을 생성한다."""
    notifications = []
    for ch in channels:
        if ch == NotificationChannelType.EMAIL:
            provider = settings.NOTIFICATION_EMAIL_PROVIDER
        elif ch == NotificationChannelType.SMS:
            provider = settings.NOTIFICATION_SMS_PROVIDER
        else:
            provider = "webhook"
        notifications.append(
            NotificationChannel(
                channel=ch,
                provider=provider,
                status=NotificationStatus.PENDING,
            )
        )
    return notifications


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


@bp.route(route="events", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def post_events(req: func.HttpRequest) -> func.HttpResponse:
    """POST /events — 이벤트 생성.

    Pydantic 입력 검증 → correlation_id 생성 → Cosmos DB 저장.
    409 Conflict 시 기존 문서 조회 후 200 반환.
    """
    clear_context()
    correlation_id = generate_correlation_id()
    set_correlation_id(correlation_id)

    try:
        body = req.get_json()
    except ValueError:
        return _error_response("VALIDATION_ERROR", "Invalid JSON body", 400)

    # 입력 검증
    try:
        validated = validate_create_event(body)
    except AppValidationError as e:
        return _json_response(e.to_dict(), status_code=400)

    set_log_context(event_id=validated.id, clinic_id=validated.clinic_id)

    settings = _get_settings()
    now = datetime.now(tz=UTC)

    # NotificationEvent 문서 생성
    event_doc = NotificationEvent(
        id=validated.id,
        clinic_id=validated.clinic_id,
        status=EventStatus.QUEUED,
        event_type=validated.event_type,
        patient_id=validated.patient_id,
        channels=validated.channels,
        correlation_id=correlation_id,
        notifications=_build_notifications(validated.channels, settings),
        created_at=now,
        updated_at=now,
    )

    container = get_events_container(settings)

    try:
        doc_dict = event_doc.model_dump(by_alias=True)
        await container.create_item(body=doc_dict)

        log_with_context(logger, logging.INFO, "이벤트 생성 완료", status="queued")

        return _json_response(
            {"event_id": validated.id, "status": "queued", "correlation_id": correlation_id},
            status_code=201,
        )

    except CosmosResourceExistsError:
        # Idempotency: 기존 문서 조회 후 200 반환
        log_with_context(logger, logging.INFO, "중복 이벤트 요청", event_id=validated.id)

        try:
            existing = await container.read_item(item=validated.id, partition_key=validated.clinic_id)
            return _json_response(
                {
                    "event_id": existing["id"],
                    "status": existing.get("status", "queued"),
                    "correlation_id": existing.get("correlation_id", correlation_id),
                    "message": "Event already exists",
                },
                status_code=200,
            )
        except CosmosResourceNotFoundError:
            return _error_response("NOT_FOUND", "Event not found", 404)

    except Exception:
        logger.exception("이벤트 생성 실패")
        return _error_response("INTERNAL_ERROR", "Internal server error", 500)


@bp.route(route="events/{event_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def get_event_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """GET /events/{event_id} — 이벤트 상세 조회.

    clinic_id 쿼리 파라미터 필수.
    """
    clear_context()
    event_id = req.route_params.get("event_id", "")
    clinic_id = req.params.get("clinic_id")

    if not clinic_id:
        return _error_response("VALIDATION_ERROR", "clinic_id query parameter is required", 400)

    set_log_context(event_id=event_id, clinic_id=clinic_id)

    settings = _get_settings()
    container = get_events_container(settings)

    try:
        doc = await container.read_item(item=event_id, partition_key=clinic_id)
        # _outbox_status 내부 필드 제거
        doc.pop("_outbox_status", None)
        # Cosmos DB 메타 필드 제거
        for key in ("_rid", "_self", "_etag", "_attachments", "_ts"):
            doc.pop(key, None)
        return _json_response(doc)

    except CosmosResourceNotFoundError:
        return _error_response("NOT_FOUND", f"Event {event_id} not found", 404)

    except Exception:
        logger.exception("이벤트 조회 실패")
        return _error_response("INTERNAL_ERROR", "Internal server error", 500)


@bp.route(route="events", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def get_events(req: func.HttpRequest) -> func.HttpResponse:
    """GET /events — 이벤트 목록 조회.

    clinic_id 필수, status/event_type 필터, continuation_token 페이지네이션.
    """
    clear_context()
    clinic_id = req.params.get("clinic_id")

    if not clinic_id:
        return _error_response("VALIDATION_ERROR", "clinic_id query parameter is required", 400)

    set_log_context(clinic_id=clinic_id)

    status_filter = req.params.get("status")
    event_type_filter = req.params.get("event_type")
    continuation_token = req.params.get("continuation_token")
    page_size = min(int(req.params.get("page_size", "20")), 100)

    settings = _get_settings()
    container = get_events_container(settings)

    # 쿼리 빌드
    conditions = ["c.clinic_id = @clinic_id"]
    parameters: list[dict[str, object]] = [{"name": "@clinic_id", "value": clinic_id}]

    if status_filter:
        conditions.append("c.status = @status")
        parameters.append({"name": "@status", "value": status_filter})

    if event_type_filter:
        conditions.append("c.event_type = @event_type")
        parameters.append({"name": "@event_type", "value": event_type_filter})

    select_fields = (
        "c.id, c.clinic_id, c.status, c.event_type, c.patient_id, "
        "c.channels, c.correlation_id, c.created_at, c.updated_at"
    )
    where_clause = " AND ".join(conditions)
    query = f"SELECT {select_fields} FROM c WHERE {where_clause} ORDER BY c.created_at DESC"

    try:
        items: list[dict[str, Any]] = []
        new_continuation_token = None

        query_iterable = container.query_items(
            query=query,
            parameters=parameters,
            partition_key=clinic_id,
            max_item_count=page_size,
        )

        # 페이지네이션 처리
        pager = query_iterable.by_page(continuation_token)
        async for page in pager:
            async for item in page:
                items.append(item)
            new_continuation_token = pager.continuation_token  # type: ignore[attr-defined]
            break  # 첫 페이지만

        return _json_response(
            {
                "items": items,
                "continuation_token": new_continuation_token,
            }
        )

    except Exception:
        logger.exception("이벤트 목록 조회 실패")
        return _error_response("INTERNAL_ERROR", "Internal server error", 500)
