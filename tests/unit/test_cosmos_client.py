"""Cosmos DB 클라이언트 싱글턴 및 컨테이너 참조 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.cosmos_client import (
    CONTAINER_DEFINITIONS,
    close_client,
    get_circuit_breaker_container,
    get_container,
    get_cosmos_client,
    get_database,
    get_dlq_container,
    get_events_container,
    get_leases_container,
    get_rate_limiter_container,
    init_containers,
    reset_client,
)
from src.shared.config import Settings

REQUIRED_ENV = {
    "QUEUE_SERVICE_TYPE": "EVENT_GRID",
    "NOTIFICATION_EMAIL_PROVIDER": "sendgrid",
    "NOTIFICATION_SMS_PROVIDER": "twilio",
    "WEBHOOK_URL": "https://example.com/webhook",
    "COSMOS_DB_ENDPOINT": "https://localhost:8081",
    "COSMOS_DB_KEY": "test-key",
    "COSMOS_DB_DATABASE": "test-db",
}


@pytest.fixture()
def settings() -> Settings:
    return Settings(**REQUIRED_ENV)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset() -> None:
    """각 테스트 전후로 싱글턴 상태를 초기화한다."""
    reset_client()
    yield  # type: ignore[misc]
    reset_client()


class TestCosmosClientSingleton:
    """Cosmos DB 클라이언트 싱글턴 테스트."""

    @patch("src.services.cosmos_client.CosmosClient")
    def test_get_cosmos_client_creates_once(self, mock_cls: MagicMock, settings: Settings) -> None:
        """get_cosmos_client를 여러 번 호출해도 클라이언트는 한 번만 생성된다."""
        client1 = get_cosmos_client(settings)
        client2 = get_cosmos_client(settings)
        assert client1 is client2
        mock_cls.assert_called_once_with(
            url=settings.COSMOS_DB_ENDPOINT,
            credential=settings.COSMOS_DB_KEY,
        )

    @patch("src.services.cosmos_client.CosmosClient")
    def test_get_cosmos_client_uses_settings(self, mock_cls: MagicMock, settings: Settings) -> None:
        """클라이언트가 Settings의 endpoint와 key를 사용한다."""
        get_cosmos_client(settings)
        mock_cls.assert_called_once_with(
            url="https://localhost:8081",
            credential="test-key",
        )

    @patch("src.services.cosmos_client.CosmosClient")
    def test_get_database_returns_proxy(self, mock_cls: MagicMock, settings: Settings) -> None:
        """get_database가 데이터베이스 프록시를 반환한다."""
        mock_client = MagicMock()
        mock_cls.return_value = mock_client

        db = get_database(settings)
        mock_client.get_database_client.assert_called_once_with("test-db")
        assert db is mock_client.get_database_client.return_value

    @patch("src.services.cosmos_client.CosmosClient")
    def test_get_database_singleton(self, mock_cls: MagicMock, settings: Settings) -> None:
        """get_database를 여러 번 호출해도 동일 프록시를 반환한다."""
        mock_client = MagicMock()
        mock_cls.return_value = mock_client

        db1 = get_database(settings)
        db2 = get_database(settings)
        assert db1 is db2
        mock_client.get_database_client.assert_called_once()

    @patch("src.services.cosmos_client.CosmosClient")
    def test_reset_client_clears_singleton(self, mock_cls: MagicMock, settings: Settings) -> None:
        """reset_client가 싱글턴 상태를 초기화한다."""
        get_cosmos_client(settings)
        reset_client()
        get_cosmos_client(settings)
        assert mock_cls.call_count == 2


class TestContainerAccess:
    """컨테이너 참조 함수 테스트."""

    @patch("src.services.cosmos_client.CosmosClient")
    def test_get_container_returns_proxy(self, mock_cls: MagicMock, settings: Settings) -> None:
        """get_container가 올바른 컨테이너 프록시를 반환한다."""
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_db = mock_client.get_database_client.return_value

        container = get_container(settings, "events")
        mock_db.get_container_client.assert_called_once_with("events")
        assert container is mock_db.get_container_client.return_value

    def test_get_container_invalid_name_raises(self, settings: Settings) -> None:
        """유효하지 않은 컨테이너 이름이면 ValueError가 발생한다."""
        with pytest.raises(ValueError, match="알 수 없는 컨테이너"):
            get_container(settings, "invalid-container")

    @patch("src.services.cosmos_client.CosmosClient")
    def test_get_events_container(self, mock_cls: MagicMock, settings: Settings) -> None:
        """get_events_container가 events 컨테이너를 반환한다."""
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_db = mock_client.get_database_client.return_value

        get_events_container(settings)
        mock_db.get_container_client.assert_called_once_with("events")

    @patch("src.services.cosmos_client.CosmosClient")
    def test_get_dlq_container(self, mock_cls: MagicMock, settings: Settings) -> None:
        """get_dlq_container가 dead-letter-queue 컨테이너를 반환한다."""
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_db = mock_client.get_database_client.return_value

        get_dlq_container(settings)
        mock_db.get_container_client.assert_called_once_with("dead-letter-queue")

    @patch("src.services.cosmos_client.CosmosClient")
    def test_get_circuit_breaker_container(self, mock_cls: MagicMock, settings: Settings) -> None:
        """get_circuit_breaker_container가 circuit-breaker 컨테이너를 반환한다."""
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_db = mock_client.get_database_client.return_value

        get_circuit_breaker_container(settings)
        mock_db.get_container_client.assert_called_once_with("circuit-breaker")

    @patch("src.services.cosmos_client.CosmosClient")
    def test_get_rate_limiter_container(self, mock_cls: MagicMock, settings: Settings) -> None:
        """get_rate_limiter_container가 rate-limiter 컨테이너를 반환한다."""
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_db = mock_client.get_database_client.return_value

        get_rate_limiter_container(settings)
        mock_db.get_container_client.assert_called_once_with("rate-limiter")

    @patch("src.services.cosmos_client.CosmosClient")
    def test_get_leases_container(self, mock_cls: MagicMock, settings: Settings) -> None:
        """get_leases_container가 leases 컨테이너를 반환한다."""
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_db = mock_client.get_database_client.return_value

        get_leases_container(settings)
        mock_db.get_container_client.assert_called_once_with("leases")


class TestContainerDefinitions:
    """컨테이너 정의 상수 테스트."""

    def test_five_containers_defined(self) -> None:
        """5개 컨테이너가 정의되어 있다."""
        assert len(CONTAINER_DEFINITIONS) == 5

    def test_container_names(self) -> None:
        """올바른 컨테이너 이름들이 정의되어 있다."""
        names = {defn["id"] for defn in CONTAINER_DEFINITIONS}
        assert names == {"events", "dead-letter-queue", "circuit-breaker", "rate-limiter", "leases"}

    def test_events_partition_key(self) -> None:
        """events 컨테이너의 Partition Key가 /clinic_id이다."""
        events = next(d for d in CONTAINER_DEFINITIONS if d["id"] == "events")
        assert events["partition_key"] == "/clinic_id"

    def test_dlq_partition_key(self) -> None:
        """dead-letter-queue 컨테이너의 Partition Key가 /clinic_id이다."""
        dlq = next(d for d in CONTAINER_DEFINITIONS if d["id"] == "dead-letter-queue")
        assert dlq["partition_key"] == "/clinic_id"

    def test_circuit_breaker_partition_key(self) -> None:
        """circuit-breaker 컨테이너의 Partition Key가 /id이다."""
        cb = next(d for d in CONTAINER_DEFINITIONS if d["id"] == "circuit-breaker")
        assert cb["partition_key"] == "/id"

    def test_rate_limiter_partition_key(self) -> None:
        """rate-limiter 컨테이너의 Partition Key가 /id이다."""
        rl = next(d for d in CONTAINER_DEFINITIONS if d["id"] == "rate-limiter")
        assert rl["partition_key"] == "/id"

    def test_rate_limiter_ttl(self) -> None:
        """rate-limiter 컨테이너의 TTL이 60초이다."""
        rl = next(d for d in CONTAINER_DEFINITIONS if d["id"] == "rate-limiter")
        assert rl["ttl"] == 60

    def test_other_containers_no_ttl(self) -> None:
        """rate-limiter 이외 컨테이너는 TTL이 없다."""
        others = [d for d in CONTAINER_DEFINITIONS if d["id"] != "rate-limiter"]
        for defn in others:
            assert defn["ttl"] is None, f"{defn['id']}에 TTL이 설정되어 있음"

    def test_events_has_composite_index(self) -> None:
        """events 컨테이너에 status, event_type, created_at 복합 인덱스가 있다."""
        events = next(d for d in CONTAINER_DEFINITIONS if d["id"] == "events")
        policy = events["indexing_policy"]
        assert policy is not None
        composites = policy["compositeIndexes"]
        assert len(composites) == 1
        paths = [idx["path"] for idx in composites[0]]
        assert paths == ["/status", "/event_type", "/created_at"]


class TestInitContainers:
    """init_containers 함수 테스트."""

    @pytest.mark.asyncio()
    @patch("src.services.cosmos_client.CosmosClient")
    async def test_init_creates_database_and_containers(self, mock_cls: MagicMock, settings: Settings) -> None:
        """init_containers가 데이터베이스와 5개 컨테이너를 생성한다."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_database = AsyncMock()
        mock_client.create_database_if_not_exists = AsyncMock(return_value=mock_database)

        await init_containers(settings)

        mock_client.create_database_if_not_exists.assert_awaited_once_with(id="test-db")
        assert mock_database.create_container_if_not_exists.await_count == 5

    @pytest.mark.asyncio()
    @patch("src.services.cosmos_client.CosmosClient")
    async def test_init_sets_rate_limiter_ttl(self, mock_cls: MagicMock, settings: Settings) -> None:
        """init_containers가 rate-limiter 컨테이너에 TTL 60을 설정한다."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_database = AsyncMock()
        mock_client.create_database_if_not_exists = AsyncMock(return_value=mock_database)

        await init_containers(settings)

        calls = mock_database.create_container_if_not_exists.call_args_list
        rl_call = next(c for c in calls if c.kwargs.get("id") == "rate-limiter")
        assert rl_call.kwargs["default_ttl"] == 60

    @pytest.mark.asyncio()
    @patch("src.services.cosmos_client.CosmosClient")
    async def test_init_sets_events_indexing_policy(self, mock_cls: MagicMock, settings: Settings) -> None:
        """init_containers가 events 컨테이너에 인덱싱 정책을 설정한다."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_database = AsyncMock()
        mock_client.create_database_if_not_exists = AsyncMock(return_value=mock_database)

        await init_containers(settings)

        calls = mock_database.create_container_if_not_exists.call_args_list
        events_call = next(c for c in calls if c.kwargs.get("id") == "events")
        assert "indexing_policy" in events_call.kwargs
        policy = events_call.kwargs["indexing_policy"]
        assert "compositeIndexes" in policy


class TestCloseClient:
    """close_client 함수 테스트."""

    @pytest.mark.asyncio()
    @patch("src.services.cosmos_client.CosmosClient")
    async def test_close_client_clears_state(self, mock_cls: MagicMock, settings: Settings) -> None:
        """close_client가 클라이언트 연결을 종료하고 싱글턴 상태를 초기화한다."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client

        get_cosmos_client(settings)
        await close_client()

        mock_client.close.assert_awaited_once()

        # 싱글턴이 초기화되어 다시 생성됨
        get_cosmos_client(settings)
        assert mock_cls.call_count == 2

    @pytest.mark.asyncio()
    async def test_close_client_noop_when_not_initialized(self) -> None:
        """클라이언트가 초기화되지 않은 상태에서 close_client를 호출해도 에러가 없다."""
        await close_client()  # 예외 없이 통과해야 함
