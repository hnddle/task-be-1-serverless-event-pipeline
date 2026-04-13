"""구조화 JSON 로거.

모든 로그를 JSON 형식으로 stdout에 출력한다.
correlation_id는 contextvars에서 자동으로 가져와 포함한다.
파일 로깅 금지 — 12-Factor XI: Logs.

SPEC.md §10.2 참조.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from src.shared.correlation import get_correlation_id, get_log_context


class JsonFormatter(logging.Formatter):
    """JSON 구조화 로그 포매터.

    출력 형식:
    {
      "timestamp": "ISO 8601",
      "level": "INFO | WARNING | ERROR",
      "correlation_id": "uuid or null",
      "message": "...",
      ...contextFields
    }

    correlation_id, timestamp, level, message는 필수.
    나머지 필드는 해당 컨텍스트에서 관련 있는 경우에만 포함.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "correlation_id": get_correlation_id(),
            "message": record.getMessage(),
        }

        # contextvars에서 추가 로그 필드 병합
        log_context = get_log_context()
        if log_context:
            log_entry.update(log_context)

        # 로그 호출 시 extra로 전달된 필드 병합
        extra = getattr(record, "extra_fields", None)
        if extra and isinstance(extra, dict):
            log_entry.update(extra)

        # 예외 정보 포함
        if record.exc_info and record.exc_info[1] is not None:
            log_entry["error"] = str(record.exc_info[1])
            log_entry["error_type"] = type(record.exc_info[1]).__name__

        # None 값 필드 제거
        log_entry = {k: v for k, v in log_entry.items() if v is not None}

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class ExtraFieldsFilter(logging.Filter):
    """extra_fields 속성을 LogRecord에 안전하게 추가하는 필터."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "extra_fields"):
            record.extra_fields = {}
        return True


def setup_logger(name: str = "notification-pipeline", level: int = logging.INFO) -> logging.Logger:
    """구조화 JSON 로거를 설정하여 반환한다.

    stdout에만 출력하며, 파일 핸들러는 사용하지 않는다.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ExtraFieldsFilter())
    logger.addHandler(handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """구조화 JSON 로거 인스턴스를 반환한다.

    name을 지정하면 해당 이름의 하위 로거를 반환한다.
    """
    base = "notification-pipeline"
    logger_name = f"{base}.{name}" if name else base
    logger = logging.getLogger(logger_name)

    # 부모 로거가 설정되지 않았으면 설정
    parent = logging.getLogger(base)
    if not parent.handlers:
        setup_logger(base)

    return logger


def log_with_context(
    logger: logging.Logger,
    level: int,
    message: str,
    **extra: Any,
) -> None:
    """추가 컨텍스트 필드와 함께 로그를 출력한다.

    예: log_with_context(logger, logging.INFO, "발송 완료", channel="email", duration_ms=150)
    """
    logger.log(level, message, extra={"extra_fields": extra})


def setup_application_insights(connection_string: str | None = None) -> None:
    """Azure Application Insights 연동을 설정한다.

    correlation_id를 operation_id에 매핑하여
    End-to-End Transaction 뷰에서 전체 흐름을 조회할 수 있게 한다.

    SPEC.md §10.1 참조.
    """
    if not connection_string:
        return

    try:
        from opencensus.ext.azure.log_exporter import AzureLogHandler
        from opencensus.trace import config_integration

        config_integration.trace_integrations(["logging"])

        azure_handler = AzureLogHandler(connection_string=connection_string)
        azure_handler.setFormatter(JsonFormatter())
        azure_handler.addFilter(ExtraFieldsFilter())

        base_logger = logging.getLogger("notification-pipeline")
        base_logger.addHandler(azure_handler)
    except ImportError:
        base_logger = logging.getLogger("notification-pipeline")
        base_logger.warning("opencensus-ext-azure 패키지가 설치되지 않아 Application Insights 연동을 건너뜁니다")
