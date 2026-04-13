"""Rate Limiter — Token Bucket 알고리즘.

{channel}:{provider} 조합별 독립 Rate Limiter를 운용한다.
Cosmos DB `rate-limiter` 컨테이너에 상태를 저장하고 (TTL 60초),
ETag 기반 낙관적 동시성 제어를 적용한다.

SPEC.md §5 참조.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from azure.cosmos.exceptions import CosmosAccessConditionFailedError, CosmosResourceNotFoundError

from src.services.cosmos_client import get_rate_limiter_container
from src.shared.logger import log_with_context

if TYPE_CHECKING:
    from src.shared.config import Settings

logger = logging.getLogger(__name__)

# ETag 충돌 시 최대 재시도 횟수
MAX_ETAG_RETRIES = 3


class RateLimitExceededError(Exception):
    """Rate Limit 대기 시간 초과."""

    def __init__(self, limiter_id: str) -> None:
        super().__init__(f"Rate limit exceeded: {limiter_id}")
        self.limiter_id = limiter_id


class RateLimiter:
    """Token Bucket 기반 Rate Limiter.

    각 {channel}:{provider} 조합별로 독립적으로 운용된다.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._container = get_rate_limiter_container(settings)

    def _make_limiter_id(self, channel: str, provider: str) -> str:
        return f"{channel}:{provider}"

    def _get_max_tokens(self, channel: str) -> float:
        """채널별 초당 최대 토큰 수를 반환한다."""
        if channel == "email":
            return float(self._settings.RATE_LIMIT_EMAIL_PER_SEC)
        if channel == "sms":
            return float(self._settings.RATE_LIMIT_SMS_PER_SEC)
        if channel == "webhook":
            return float(self._settings.RATE_LIMIT_WEBHOOK_PER_SEC)
        return float(self._settings.RATE_LIMIT_EMAIL_PER_SEC)

    async def _read_bucket(self, limiter_id: str, max_tokens: float) -> dict[str, Any]:
        """Cosmos DB에서 버킷 상태를 읽는다. 없으면 기본 버킷 반환."""
        try:
            return await self._container.read_item(
                item=limiter_id,
                partition_key=limiter_id,
            )
        except CosmosResourceNotFoundError:
            return {
                "id": limiter_id,
                "tokens": max_tokens,
                "max_tokens": max_tokens,
                "last_refill_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
            }

    def _refill_tokens(self, bucket: dict[str, Any], max_tokens: float) -> dict[str, Any]:
        """경과 시간에 비례하여 토큰을 리필한다."""
        last_refill = bucket.get("last_refill_at", "")
        if isinstance(last_refill, str) and last_refill:
            last_refill_dt = datetime.fromisoformat(last_refill)
        else:
            last_refill_dt = datetime.now(UTC)

        now = datetime.now(UTC)
        elapsed_sec = (now - last_refill_dt).total_seconds()

        if elapsed_sec > 0:
            current_tokens = float(bucket.get("tokens", 0))
            new_tokens = min(current_tokens + elapsed_sec * max_tokens, max_tokens)
            bucket["tokens"] = new_tokens
            bucket["last_refill_at"] = now.isoformat()

        return bucket

    async def _save_bucket(self, bucket: dict[str, Any]) -> dict[str, Any]:
        """Cosmos DB에 버킷 상태를 저장한다."""
        bucket["updated_at"] = datetime.now(UTC).isoformat()

        kwargs: dict[str, Any] = {
            "body": bucket,
            "partition_key": bucket["id"],
        }
        etag = bucket.get("_etag")
        if etag:
            kwargs["etag"] = etag
            kwargs["match_condition"] = "IfMatch"

        return await self._container.upsert_item(**kwargs)

    async def acquire(self, channel: str, provider: str) -> None:
        """토큰 1개를 소비한다.

        토큰 부족 시 지수 백오프로 대기하며, RATE_LIMIT_MAX_WAIT_MS 초과 시
        RateLimitExceededError를 발생시킨다.

        Raises:
            RateLimitExceededError: 대기 시간 초과.
        """
        limiter_id = self._make_limiter_id(channel, provider)
        max_tokens = self._get_max_tokens(channel)
        max_wait_sec = self._settings.RATE_LIMIT_MAX_WAIT_MS / 1000.0

        start_time = time.monotonic()
        backoff_ms = 100  # 초기 백오프 100ms

        while True:
            for attempt in range(MAX_ETAG_RETRIES):
                bucket = await self._read_bucket(limiter_id, max_tokens)
                bucket = self._refill_tokens(bucket, max_tokens)

                if bucket["tokens"] >= 1.0:
                    bucket["tokens"] -= 1.0
                    try:
                        await self._save_bucket(bucket)
                        return  # 토큰 소비 성공
                    except CosmosAccessConditionFailedError:
                        if attempt < MAX_ETAG_RETRIES - 1:
                            continue
                        raise
                else:
                    # 토큰 부족 — 저장하지 않고 대기로 진입
                    break
            else:
                # ETag 충돌 루프 완료 (토큰은 있었지만 계속 충돌) — 다시 시도
                continue

            # 토큰 부족 — 대기 시간 확인
            elapsed = time.monotonic() - start_time
            if elapsed >= max_wait_sec:
                log_with_context(
                    logger,
                    logging.WARNING,
                    "Rate limit 대기 초과",
                    limiter_id=limiter_id,
                    waited_ms=round(elapsed * 1000),
                )
                raise RateLimitExceededError(limiter_id)

            log_with_context(
                logger,
                logging.INFO,
                "Rate limit 대기",
                limiter_id=limiter_id,
                backoff_ms=backoff_ms,
            )
            await asyncio.sleep(backoff_ms / 1000.0)
            backoff_ms = min(backoff_ms * 2, 2000)  # 최대 2초
