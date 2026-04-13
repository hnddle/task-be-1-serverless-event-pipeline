"""Outbox Publisher — Change Feed 기반 이벤트 발행.

Cosmos DB Change Feed에서 _outbox_status: "pending" 문서를 감지하여
Message Broker에 발행한다.

SPEC.md §4.4 (Transactional Outbox 패턴) 참조.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import azure.functions as func

from src.services.cosmos_client import get_events_container
from src.services.message_broker.message_broker_factory import MessageBrokerFactory
from src.shared.config import load_settings
from src.shared.correlation import clear_context, set_correlation_id, set_log_context
from src.shared.logger import log_with_context

logger = logging.getLogger(__name__)

bp = func.Blueprint()  # type: ignore[no-untyped-call]

_settings = None
_broker = None


def _get_settings() -> Any:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def _get_broker() -> Any:
    global _broker
    if _broker is None:
        _broker = MessageBrokerFactory.create(_get_settings())
    return _broker


@bp.cosmos_db_trigger(
    arg_name="documents",
    connection="CosmosDBConnection",
    database_name="%COSMOS_DB_DATABASE%",
    container_name="events",
    lease_container_name="leases",
    create_lease_container_if_not_exists=True,
)
async def outbox_publisher(documents: func.DocumentList) -> None:
    """Change Feed Trigger — pending 문서를 감지하여 Event Grid에 발행한다.

    무한 루프 방지: _outbox_status가 "pending"인 문서만 처리한다.
    """
    if not documents:
        return

    settings = _get_settings()
    broker = _get_broker()
    container = get_events_container(settings)

    processed = 0
    skipped = 0

    for doc in documents:
        doc_dict = doc.to_dict() if hasattr(doc, "to_dict") else json.loads(doc.to_json())

        outbox_status = doc_dict.get("_outbox_status", "")
        event_id = doc_dict.get("id", "unknown")
        clinic_id = doc_dict.get("clinic_id", "unknown")

        # 무한 루프 방지: pending만 처리
        if outbox_status != "pending":
            skipped += 1
            continue

        clear_context()
        correlation_id = doc_dict.get("correlation_id", "")
        if correlation_id:
            set_correlation_id(correlation_id)
        set_log_context(event_id=event_id, clinic_id=clinic_id)

        try:
            # Message Broker에 발행
            await broker.publish(doc_dict)

            # 발행 성공 → published로 갱신
            await container.patch_item(
                item=event_id,
                partition_key=clinic_id,
                patch_operations=[
                    {"op": "set", "path": "/_outbox_status", "value": "published"},
                ],
            )

            log_with_context(
                logger,
                logging.INFO,
                "Outbox 발행 완료",
                broker=broker.get_broker_name(),
            )
            processed += 1

        except Exception:
            # 발행 실패 → failed_publish로 갱신
            logger.exception("Outbox 발행 실패: %s", event_id)

            try:
                await container.patch_item(
                    item=event_id,
                    partition_key=clinic_id,
                    patch_operations=[
                        {"op": "set", "path": "/_outbox_status", "value": "failed_publish"},
                    ],
                )
            except Exception:
                logger.exception("failed_publish 갱신 실패: %s", event_id)

    log_with_context(
        logger,
        logging.INFO,
        "Outbox Publisher 배치 완료",
        processed=processed,
        skipped=skipped,
        total=len(documents),
    )
