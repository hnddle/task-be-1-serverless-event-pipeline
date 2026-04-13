"""Event Consumer — Event Grid 기반 알림 발송.

Event Grid 트리거로 이벤트를 수신하여 채널별 알림을 발송하고
결과를 Cosmos DB에 기록한다.
복원력 패턴: Circuit Breaker → Rate Limiter → Strategy.send() → 재시도.

SPEC.md §9 (Event Consumer) 참조.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import azure.functions as func

from src.services.circuit_breaker import CircuitBreaker, CircuitOpenError
from src.services.cosmos_client import get_events_container
from src.services.dlq_service import DlqService
from src.services.notification.notification_factory import NotificationFactory
from src.services.rate_limiter import RateLimiter, RateLimitExceededError
from src.services.retry_service import MaxRetryExceededError, RetryService
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


async def _send_with_resilience(
    channel: str,
    provider: str,
    notification_data: dict[str, Any],
    *,
    circuit_breaker: CircuitBreaker,
    rate_limiter: RateLimiter,
    retry_service: RetryService,
    factory: NotificationFactory,
) -> dict[str, Any]:
    """복원력 패턴을 적용하여 알림을 발송한다.

    흐름: Circuit Breaker 확인 → Rate Limiter → Strategy.send() → 재시도.

    Returns:
        {"success": bool, "provider": str, "message": str, "duration_ms": float}
    """
    # 1. Circuit Breaker 확인
    try:
        await circuit_breaker.check_state(channel, provider)
    except CircuitOpenError:
        log_with_context(
            logger,
            logging.WARNING,
            "Circuit Breaker Open — 즉시 실패",
            channel=channel,
            provider=provider,
        )
        return {
            "success": False,
            "provider": provider,
            "message": f"Circuit open: {channel}:{provider}",
            "duration_ms": 0.0,
            "circuit_open": True,
        }

    # 2. Rate Limiter + Strategy.send() + 재시도
    async def _attempt_send() -> dict[str, Any]:
        # Rate Limiter
        try:
            await rate_limiter.acquire(channel, provider)
        except RateLimitExceededError:
            log_with_context(
                logger,
                logging.WARNING,
                "Rate limit 대기 초과",
                channel=channel,
                provider=provider,
            )
            raise

        # Strategy 호출
        log_with_context(
            logger,
            logging.INFO,
            "채널 발송 시작",
            channel=channel,
            provider=provider,
        )

        result = await factory.send_notification(channel, notification_data)

        if not result.success:
            raise RuntimeError(result.message)

        return {
            "success": True,
            "provider": result.provider,
            "message": "",
            "duration_ms": result.duration_ms,
        }

    try:
        send_result = await retry_service.execute_with_retry(
            _attempt_send,
            context={"channel": channel, "provider": provider},
        )
        # 성공 → Circuit Breaker 성공 기록
        await circuit_breaker.record_success(channel, provider)
        result: dict[str, Any] = send_result
        return result
    except MaxRetryExceededError as e:
        # 재시도 초과 → Circuit Breaker 실패 기록
        await circuit_breaker.record_failure(channel, provider)
        return {
            "success": False,
            "provider": provider,
            "message": e.last_error,
            "duration_ms": 0.0,
            "retry_count": e.retry_count,
        }
    except RateLimitExceededError:
        # Rate limit 초과 → Circuit Breaker에 미포함
        return {
            "success": False,
            "provider": provider,
            "message": f"Rate limit exceeded: {channel}:{provider}",
            "duration_ms": 0.0,
        }


@bp.event_grid_trigger(arg_name="event")
async def event_consumer(event: func.EventGridEvent) -> None:
    """Event Grid Trigger — 이벤트를 수신하여 채널별 알림을 발송한다.

    처리 흐름:
    1. correlation_id 컨텍스트 바인딩
    2. Cosmos DB에서 이벤트 조회 (Idempotency)
    3. status → processing 갱신
    4. channels 순회: Circuit Breaker → Rate Limiter → send → 재시도
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
    circuit_breaker = CircuitBreaker(settings)
    rate_limiter = RateLimiter(settings)
    retry_service = RetryService(settings)
    dlq_service = DlqService(settings)

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
        provider: str = notification.get("provider", "")

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

        send_result = await _send_with_resilience(
            channel,
            provider,
            {
                "event_id": event_id,
                "clinic_id": clinic_id,
                "channel": channel,
                "provider": provider,
            },
            circuit_breaker=circuit_breaker,
            rate_limiter=rate_limiter,
            retry_service=retry_service,
            factory=factory,
        )

        now = datetime.now(UTC).isoformat()

        if send_result["success"]:
            notification["status"] = "success"
            notification["sent_at"] = now
            log_with_context(
                logger,
                logging.INFO,
                "알림 발송 성공",
                channel=channel,
                provider=send_result["provider"],
                duration_ms=send_result["duration_ms"],
            )
        else:
            notification["status"] = "failed"
            notification["last_error"] = send_result["message"]
            notification["retry_count"] = send_result.get("retry_count", 0)
            log_with_context(
                logger,
                logging.WARNING,
                "알림 발송 실패",
                channel=channel,
                provider=send_result["provider"],
                error=send_result["message"],
            )

            # 최대 재시도 초과 시 DLQ로 이동
            if send_result.get("retry_count", 0) > 0 or send_result.get("circuit_open"):
                await dlq_service.send_to_dlq(
                    original_event_id=event_id,
                    clinic_id=clinic_id,
                    channel=channel,
                    provider=provider,
                    event_type=doc.get("event_type", ""),
                    patient_id=doc.get("patient_id", ""),
                    payload=doc,
                    failure_reason=send_result["message"],
                    retry_count=send_result.get("retry_count", 0),
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
