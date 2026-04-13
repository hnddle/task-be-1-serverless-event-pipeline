"""재시도 서비스 — 지수 백오프.

알림 발송 실패 시 in-process 지수 백오프 재시도를 수행한다.
재시도 간격: RETRY_BASE_DELAY_MS * (RETRY_BACKOFF_MULTIPLIER ** retry_count)

SPEC.md §6.1 참조.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from src.shared.logger import log_with_context

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from src.shared.config import Settings

logger = logging.getLogger(__name__)


class MaxRetryExceededError(Exception):
    """최대 재시도 횟수 초과."""

    def __init__(self, retry_count: int, last_error: str) -> None:
        super().__init__(f"Max retries ({retry_count}) exceeded: {last_error}")
        self.retry_count = retry_count
        self.last_error = last_error


def calculate_delay_ms(
    retry_count: int,
    base_delay_ms: int,
    backoff_multiplier: int,
) -> int:
    """지수 백오프 딜레이를 계산한다.

    delay = base_delay_ms * (backoff_multiplier ** retry_count)
    """
    return int(base_delay_ms * (backoff_multiplier**retry_count))


class RetryService:
    """지수 백오프 재시도 서비스.

    Settings에서 MAX_RETRY_COUNT, RETRY_BASE_DELAY_MS,
    RETRY_BACKOFF_MULTIPLIER를 읽어 재시도 정책을 결정한다.
    """

    def __init__(self, settings: Settings) -> None:
        self._max_retries = settings.MAX_RETRY_COUNT
        self._base_delay_ms = settings.RETRY_BASE_DELAY_MS
        self._backoff_multiplier = settings.RETRY_BACKOFF_MULTIPLIER

    async def execute_with_retry(
        self,
        fn: Callable[[], Awaitable[Any]],
        *,
        context: dict[str, str] | None = None,
    ) -> Any:
        """fn을 실행하고 실패 시 지수 백오프로 재시도한다.

        Args:
            fn: 실행할 비동기 함수.
            context: 로그에 포함할 컨텍스트 (event_id, channel 등).

        Returns:
            fn의 반환값.

        Raises:
            MaxRetryExceededError: 최대 재시도 초과 시.
        """
        ctx = context or {}
        last_error = ""

        for attempt in range(self._max_retries + 1):
            try:
                return await fn()
            except Exception as e:
                last_error = str(e)

                if attempt >= self._max_retries:
                    break

                delay_ms = calculate_delay_ms(
                    attempt,
                    self._base_delay_ms,
                    self._backoff_multiplier,
                )

                log_with_context(
                    logger,
                    logging.WARNING,
                    "재시도 수행",
                    retry_count=attempt + 1,
                    next_delay_ms=delay_ms,
                    error=last_error,
                    **ctx,
                )

                await asyncio.sleep(delay_ms / 1000.0)

        raise MaxRetryExceededError(
            retry_count=self._max_retries,
            last_error=last_error,
        )
