"""Correlation ID 컨텍스트 관리.

contextvars 기반으로 함수 실행 컨텍스트에 correlation_id를 바인딩한다.
모든 함수 진입점에서 set_correlation_id()를 호출하면,
해당 컨텍스트 내 모든 로그에 correlation_id가 자동 포함된다.

SPEC.md §10.1 참조.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any

_correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_log_context_var: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)


def generate_correlation_id() -> str:
    """새로운 correlation_id (UUID v4)를 생성한다."""
    return str(uuid.uuid4())


def set_correlation_id(correlation_id: str) -> None:
    """현재 컨텍스트에 correlation_id를 바인딩한다."""
    _correlation_id_var.set(correlation_id)


def get_correlation_id() -> str | None:
    """현재 컨텍스트의 correlation_id를 반환한다."""
    return _correlation_id_var.get()


def set_log_context(**kwargs: Any) -> None:
    """현재 컨텍스트에 추가 로그 필드를 바인딩한다.

    기존 컨텍스트 필드를 유지하면서 새 필드를 추가/덮어쓴다.
    예: set_log_context(event_id="...", channel="email")
    """
    current = _log_context_var.get() or {}
    _log_context_var.set({**current, **kwargs})


def get_log_context() -> dict[str, Any]:
    """현재 컨텍스트의 추가 로그 필드를 반환한다."""
    return _log_context_var.get() or {}


def clear_context() -> None:
    """현재 컨텍스트를 초기화한다."""
    _correlation_id_var.set(None)
    _log_context_var.set(None)
