"""재시도 서비스 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.retry_service import (
    MaxRetryExceededError,
    RetryService,
    calculate_delay_ms,
)


def _make_settings(
    max_retry_count: int = 3,
    base_delay_ms: int = 1000,
    backoff_multiplier: int = 2,
) -> MagicMock:
    """테스트용 Settings를 생성한다."""
    settings = MagicMock()
    settings.MAX_RETRY_COUNT = max_retry_count
    settings.RETRY_BASE_DELAY_MS = base_delay_ms
    settings.RETRY_BACKOFF_MULTIPLIER = backoff_multiplier
    return settings


class TestCalculateDelayMs:
    """calculate_delay_ms 함수 테스트."""

    def test_first_retry_uses_base_delay(self) -> None:
        """첫 번째 재시도는 base_delay 그대로."""
        assert calculate_delay_ms(0, 1000, 2) == 1000

    def test_second_retry_doubles(self) -> None:
        """두 번째 재시도는 base * 2."""
        assert calculate_delay_ms(1, 1000, 2) == 2000

    def test_third_retry_quadruples(self) -> None:
        """세 번째 재시도는 base * 4."""
        assert calculate_delay_ms(2, 1000, 2) == 4000

    def test_custom_multiplier(self) -> None:
        """커스텀 배수 적용."""
        assert calculate_delay_ms(2, 500, 3) == 4500  # 500 * 3^2

    def test_zero_retry_count(self) -> None:
        """retry_count=0이면 base_delay 반환."""
        assert calculate_delay_ms(0, 100, 5) == 100


class TestRetryService:
    """RetryService 테스트."""

    @pytest.mark.asyncio()
    async def test_success_on_first_attempt(self) -> None:
        """첫 번째 시도에서 성공하면 재시도 없음."""
        service = RetryService(_make_settings())
        fn = AsyncMock(return_value="ok")

        result = await service.execute_with_retry(fn)

        assert result == "ok"
        fn.assert_awaited_once()

    @pytest.mark.asyncio()
    @patch("src.services.retry_service.asyncio.sleep", new_callable=AsyncMock)
    async def test_success_after_retry(self, mock_sleep: AsyncMock) -> None:
        """실패 후 재시도에서 성공."""
        service = RetryService(_make_settings(max_retry_count=3, base_delay_ms=100))
        fn = AsyncMock(side_effect=[RuntimeError("fail"), RuntimeError("fail"), "ok"])

        result = await service.execute_with_retry(fn)

        assert result == "ok"
        assert fn.await_count == 3
        assert mock_sleep.await_count == 2

        # 백오프 딜레이 확인: 100ms, 200ms
        mock_sleep.assert_any_await(0.1)  # 100ms
        mock_sleep.assert_any_await(0.2)  # 200ms

    @pytest.mark.asyncio()
    @patch("src.services.retry_service.asyncio.sleep", new_callable=AsyncMock)
    async def test_max_retries_exceeded(self, mock_sleep: AsyncMock) -> None:
        """최대 재시도 초과 시 MaxRetryExceededError 발생."""
        service = RetryService(_make_settings(max_retry_count=2, base_delay_ms=100))
        fn = AsyncMock(side_effect=RuntimeError("persistent error"))

        with pytest.raises(MaxRetryExceededError) as exc_info:
            await service.execute_with_retry(fn)

        assert exc_info.value.retry_count == 2
        assert "persistent error" in exc_info.value.last_error
        # 초기 시도(1) + 재시도(2) = 3번 호출
        assert fn.await_count == 3

    @pytest.mark.asyncio()
    @patch("src.services.retry_service.asyncio.sleep", new_callable=AsyncMock)
    async def test_exponential_backoff_delays(self, mock_sleep: AsyncMock) -> None:
        """지수 백오프 딜레이가 정확히 계산된다."""
        service = RetryService(_make_settings(max_retry_count=3, base_delay_ms=1000, backoff_multiplier=2))
        fn = AsyncMock(side_effect=[RuntimeError("e"), RuntimeError("e"), RuntimeError("e"), "ok"])

        await service.execute_with_retry(fn)

        # 딜레이: 1s, 2s, 4s
        assert mock_sleep.await_count == 3
        mock_sleep.assert_any_await(1.0)
        mock_sleep.assert_any_await(2.0)
        mock_sleep.assert_any_await(4.0)

    @pytest.mark.asyncio()
    async def test_zero_max_retries_no_retry(self) -> None:
        """MAX_RETRY_COUNT=0이면 재시도 없이 즉시 실패."""
        service = RetryService(_make_settings(max_retry_count=0))
        fn = AsyncMock(side_effect=RuntimeError("fail"))

        with pytest.raises(MaxRetryExceededError) as exc_info:
            await service.execute_with_retry(fn)

        assert exc_info.value.retry_count == 0
        fn.assert_awaited_once()

    @pytest.mark.asyncio()
    @patch("src.services.retry_service.asyncio.sleep", new_callable=AsyncMock)
    async def test_context_passed_to_log(self, mock_sleep: AsyncMock) -> None:
        """context가 로그에 전달된다."""
        service = RetryService(_make_settings(max_retry_count=1, base_delay_ms=100))
        fn = AsyncMock(side_effect=[RuntimeError("err"), "ok"])

        result = await service.execute_with_retry(fn, context={"event_id": "evt-1", "channel": "email"})

        assert result == "ok"

    @pytest.mark.asyncio()
    @patch("src.services.retry_service.asyncio.sleep", new_callable=AsyncMock)
    async def test_different_settings_change_behavior(self, mock_sleep: AsyncMock) -> None:
        """환경 변수 변경 시 재시도 동작이 변경된다."""
        # max_retry=1, base=500, multiplier=3
        service = RetryService(_make_settings(max_retry_count=1, base_delay_ms=500, backoff_multiplier=3))
        fn = AsyncMock(side_effect=[RuntimeError("e"), "ok"])

        await service.execute_with_retry(fn)

        mock_sleep.assert_awaited_once_with(0.5)  # 500ms
