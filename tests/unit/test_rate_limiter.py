"""Rate Limiter 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from azure.cosmos.exceptions import CosmosAccessConditionFailedError, CosmosResourceNotFoundError

from src.services.rate_limiter import RateLimiter, RateLimitExceededError


def _make_settings(
    email_per_sec: int = 10,
    sms_per_sec: int = 5,
    webhook_per_sec: int = 20,
    max_wait_ms: int = 10000,
) -> MagicMock:
    """테스트용 Settings를 생성한다."""
    settings = MagicMock()
    settings.RATE_LIMIT_EMAIL_PER_SEC = email_per_sec
    settings.RATE_LIMIT_SMS_PER_SEC = sms_per_sec
    settings.RATE_LIMIT_WEBHOOK_PER_SEC = webhook_per_sec
    settings.RATE_LIMIT_MAX_WAIT_MS = max_wait_ms
    return settings


def _make_bucket(
    limiter_id: str = "email:sendgrid",
    tokens: float = 10.0,
    max_tokens: float = 10.0,
    etag: str | None = "etag-1",
    last_refill_at: datetime | None = None,
) -> dict:
    """테스트용 버킷 dict를 생성한다."""
    now = datetime.now(UTC)
    return {
        "id": limiter_id,
        "tokens": tokens,
        "max_tokens": max_tokens,
        "last_refill_at": (last_refill_at or now).isoformat(),
        "updated_at": now.isoformat(),
        "_etag": etag,
    }


class TestAcquireToken:
    """acquire 메서드 테스트."""

    @pytest.mark.asyncio()
    @patch("src.services.rate_limiter.get_rate_limiter_container")
    async def test_acquire_with_available_tokens(self, mock_container_fn: MagicMock) -> None:
        """토큰이 있으면 즉시 소비된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = _make_bucket(tokens=5.0)
        mock_container.upsert_item.return_value = _make_bucket(tokens=4.0)

        rl = RateLimiter(_make_settings())
        await rl.acquire("email", "sendgrid")

        mock_container.upsert_item.assert_awaited_once()
        saved = mock_container.upsert_item.call_args.kwargs["body"]
        assert saved["tokens"] < 5.0  # 토큰이 감소했어야 함

    @pytest.mark.asyncio()
    @patch("src.services.rate_limiter.get_rate_limiter_container")
    async def test_acquire_new_bucket_on_not_found(self, mock_container_fn: MagicMock) -> None:
        """버킷이 없으면 기본 버킷으로 시작한다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.side_effect = CosmosResourceNotFoundError()
        mock_container.upsert_item.return_value = _make_bucket(tokens=9.0)

        rl = RateLimiter(_make_settings(email_per_sec=10))
        await rl.acquire("email", "sendgrid")

        mock_container.upsert_item.assert_awaited_once()

    @pytest.mark.asyncio()
    @patch("src.services.rate_limiter.get_rate_limiter_container")
    async def test_acquire_no_tokens_exceeds_wait_raises(self, mock_container_fn: MagicMock) -> None:
        """토큰이 없고 대기 시간 초과 시 RateLimitExceededError 발생."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        # 매번 현재 시각 기준 토큰 0 버킷 반환 (리필 불가)
        def _fresh_empty_bucket(**kwargs: object) -> dict:
            return _make_bucket(tokens=0.0, max_tokens=0.0, last_refill_at=datetime.now(UTC))

        mock_container.read_item.side_effect = _fresh_empty_bucket

        rl = RateLimiter(_make_settings(max_wait_ms=200))  # 200ms 대기 제한

        with pytest.raises(RateLimitExceededError):
            await rl.acquire("email", "sendgrid")

    @pytest.mark.asyncio()
    @patch("src.services.rate_limiter.get_rate_limiter_container")
    async def test_token_refill_based_on_elapsed_time(self, mock_container_fn: MagicMock) -> None:
        """경과 시간에 따라 토큰이 리필된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        # 1초 전에 마지막 리필, 토큰 0 -> 10 토큰/초 * 1초 = ~10 토큰 리필
        mock_container.read_item.return_value = _make_bucket(
            tokens=0.0,
            max_tokens=10.0,
            last_refill_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        mock_container.upsert_item.return_value = _make_bucket(tokens=9.0)

        rl = RateLimiter(_make_settings(email_per_sec=10))
        await rl.acquire("email", "sendgrid")

        saved = mock_container.upsert_item.call_args.kwargs["body"]
        # 리필 후 1개 소비했으므로 ~9.0 이상
        assert saved["tokens"] >= 8.0

    @pytest.mark.asyncio()
    @patch("src.services.rate_limiter.get_rate_limiter_container")
    async def test_channel_specific_rates(self, mock_container_fn: MagicMock) -> None:
        """채널별 다른 rate가 적용된다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.side_effect = CosmosResourceNotFoundError()
        mock_container.upsert_item.return_value = _make_bucket()

        settings = _make_settings(email_per_sec=10, sms_per_sec=5)
        rl = RateLimiter(settings)

        # email
        await rl.acquire("email", "sendgrid")
        email_bucket = mock_container.upsert_item.call_args.kwargs["body"]
        email_max = email_bucket["max_tokens"]

        # sms
        mock_container.read_item.side_effect = CosmosResourceNotFoundError()
        await rl.acquire("sms", "twilio")
        sms_bucket = mock_container.upsert_item.call_args.kwargs["body"]
        sms_max = sms_bucket["max_tokens"]

        assert email_max == 10.0
        assert sms_max == 5.0


class TestETagConflict:
    """ETag 충돌 재시도 테스트."""

    @pytest.mark.asyncio()
    @patch("src.services.rate_limiter.get_rate_limiter_container")
    async def test_etag_conflict_retries(self, mock_container_fn: MagicMock) -> None:
        """ETag 충돌 시 재읽기 후 재시도한다."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.side_effect = [
            _make_bucket(tokens=5.0, etag="old"),
            _make_bucket(tokens=5.0, etag="new"),
        ]
        mock_container.upsert_item.side_effect = [
            CosmosAccessConditionFailedError(),
            _make_bucket(tokens=4.0),
        ]

        rl = RateLimiter(_make_settings())
        await rl.acquire("email", "sendgrid")

        assert mock_container.upsert_item.await_count == 2

    @pytest.mark.asyncio()
    @patch("src.services.rate_limiter.get_rate_limiter_container")
    async def test_etag_conflict_exceeds_max_retries(self, mock_container_fn: MagicMock) -> None:
        """최대 재시도 초과 시 예외 전파."""
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item.return_value = _make_bucket(tokens=5.0)
        mock_container.upsert_item.side_effect = CosmosAccessConditionFailedError()

        rl = RateLimiter(_make_settings())
        with pytest.raises(CosmosAccessConditionFailedError):
            await rl.acquire("email", "sendgrid")
