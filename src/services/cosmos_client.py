"""Cosmos DB 클라이언트 싱글턴 및 컨테이너 초기화.

azure-cosmos 비동기 SDK를 사용하여 Cosmos DB에 접근한다.
5개 컨테이너: events, dead-letter-queue, circuit-breaker, rate-limiter, leases.

SPEC.md §3.5 참조.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from azure.cosmos import PartitionKey
from azure.cosmos.aio import CosmosClient, DatabaseProxy

if TYPE_CHECKING:
    from azure.cosmos.aio._container import ContainerProxy

    from src.shared.config import Settings

logger = logging.getLogger(__name__)

# 컨테이너 정의: (이름, partition_key_path, ttl 또는 None)
CONTAINER_DEFINITIONS: list[dict[str, Any]] = [
    {
        "id": "events",
        "partition_key": "/clinic_id",
        "ttl": None,
        "indexing_policy": {
            "automatic": True,
            "indexingMode": "consistent",
            "includedPaths": [{"path": "/*"}],
            "excludedPaths": [{"path": '/"_etag"/?'}],
            "compositeIndexes": [
                [
                    {"path": "/status", "order": "ascending"},
                    {"path": "/event_type", "order": "ascending"},
                    {"path": "/created_at", "order": "descending"},
                ]
            ],
        },
    },
    {
        "id": "dead-letter-queue",
        "partition_key": "/clinic_id",
        "ttl": None,
        "indexing_policy": None,
    },
    {
        "id": "circuit-breaker",
        "partition_key": "/id",
        "ttl": None,
        "indexing_policy": None,
    },
    {
        "id": "rate-limiter",
        "partition_key": "/id",
        "ttl": 60,
        "indexing_policy": None,
    },
    {
        "id": "leases",
        "partition_key": "/id",
        "ttl": None,
        "indexing_policy": None,
    },
]

# 싱글턴 인스턴스
_client: CosmosClient | None = None
_database: DatabaseProxy | None = None


def get_cosmos_client(settings: Settings) -> CosmosClient:
    """Cosmos DB 클라이언트 싱글턴을 반환한다.

    최초 호출 시 클라이언트를 생성하고, 이후에는 동일 인스턴스를 반환한다.
    """
    global _client
    if _client is None:
        _client = CosmosClient(
            url=settings.COSMOS_DB_ENDPOINT,
            credential=settings.COSMOS_DB_KEY,
        )
        logger.info("Cosmos DB 클라이언트 생성 완료: %s", settings.COSMOS_DB_ENDPOINT)
    return _client


def get_database(settings: Settings) -> DatabaseProxy:
    """Cosmos DB 데이터베이스 프록시를 반환한다."""
    global _database
    if _database is None:
        client = get_cosmos_client(settings)
        _database = client.get_database_client(settings.COSMOS_DB_DATABASE)
        logger.info("Cosmos DB 데이터베이스 참조: %s", settings.COSMOS_DB_DATABASE)
    return _database


def get_container(settings: Settings, container_name: str) -> ContainerProxy:
    """지정된 이름의 컨테이너 프록시를 반환한다.

    유효한 컨테이너 이름: events, dead-letter-queue, circuit-breaker, rate-limiter, leases.
    """
    valid_names = {defn["id"] for defn in CONTAINER_DEFINITIONS}
    if container_name not in valid_names:
        msg = f"알 수 없는 컨테이너: {container_name}. 유효한 이름: {', '.join(sorted(valid_names))}"
        raise ValueError(msg)

    database = get_database(settings)
    return database.get_container_client(container_name)


def get_events_container(settings: Settings) -> ContainerProxy:
    """events 컨테이너 프록시를 반환한다."""
    return get_container(settings, "events")


def get_dlq_container(settings: Settings) -> ContainerProxy:
    """dead-letter-queue 컨테이너 프록시를 반환한다."""
    return get_container(settings, "dead-letter-queue")


def get_circuit_breaker_container(settings: Settings) -> ContainerProxy:
    """circuit-breaker 컨테이너 프록시를 반환한다."""
    return get_container(settings, "circuit-breaker")


def get_rate_limiter_container(settings: Settings) -> ContainerProxy:
    """rate-limiter 컨테이너 프록시를 반환한다."""
    return get_container(settings, "rate-limiter")


def get_leases_container(settings: Settings) -> ContainerProxy:
    """leases 컨테이너 프록시를 반환한다."""
    return get_container(settings, "leases")


async def init_containers(settings: Settings) -> None:
    """누락된 컨테이너를 올바른 Partition Key, TTL, 인덱싱 정책으로 생성한다.

    로컬 개발/Emulator 환경에서 컨테이너가 없으면 자동 생성한다.
    이미 존재하는 컨테이너는 건너뛴다.
    """
    client = get_cosmos_client(settings)

    # 데이터베이스 생성 (없으면)
    database = await client.create_database_if_not_exists(id=settings.COSMOS_DB_DATABASE)
    logger.info("데이터베이스 확인/생성 완료: %s", settings.COSMOS_DB_DATABASE)

    for defn in CONTAINER_DEFINITIONS:
        container_id = defn["id"]
        partition_key = PartitionKey(path=defn["partition_key"])

        kwargs: dict[str, Any] = {
            "id": container_id,
            "partition_key": partition_key,
        }

        if defn["ttl"] is not None:
            kwargs["default_ttl"] = defn["ttl"]

        if defn["indexing_policy"] is not None:
            kwargs["indexing_policy"] = defn["indexing_policy"]

        await database.create_container_if_not_exists(**kwargs)
        logger.info("컨테이너 확인/생성 완료: %s", container_id)


async def close_client() -> None:
    """Cosmos DB 클라이언트 연결을 종료한다."""
    global _client, _database
    if _client is not None:
        await _client.close()
        _client = None
        _database = None
        logger.info("Cosmos DB 클라이언트 연결 종료")


def reset_client() -> None:
    """싱글턴 상태를 초기화한다. 테스트용."""
    global _client, _database
    _client = None
    _database = None
