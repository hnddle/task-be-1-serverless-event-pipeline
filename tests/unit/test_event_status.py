"""이벤트 status 결정 로직 및 Event API 유틸 테스트."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import azure.functions as func
import pytest
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError

from src.functions.event_api import (
    _build_notifications,
    get_event_by_id,
    get_events,
    post_events,
)
from src.models.events import NotificationChannelType, NotificationStatus
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

VALID_EVENT_BODY = {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "event_type": "appointment_confirmed",
    "clinic_id": "CLINIC_123",
    "patient_id": "PATIENT_456",
    "channels": ["email", "sms"],
}


@pytest.fixture()
def settings() -> Settings:
    return Settings(**REQUIRED_ENV)  # type: ignore[arg-type]


def _make_request(
    method: str = "POST",
    body: dict | None = None,
    route_params: dict | None = None,
    params: dict | None = None,
) -> func.HttpRequest:
    """테스트용 HttpRequest를 생성한다."""
    return func.HttpRequest(
        method=method,
        url="http://localhost/api/events",
        headers={"Content-Type": "application/json"},
        body=json.dumps(body).encode() if body else b"",
        route_params=route_params or {},
        params=params or {},
    )


class _MockPager:
    """Cosmos DB by_page() 반환값을 모킹한다."""

    def __init__(self, items: list[dict]) -> None:
        self._items = items
        self.continuation_token = None

    def __aiter__(self):
        return self._pages()

    async def _pages(self):
        async def _page():
            for item in self._items:
                yield item

        yield _page()


def _make_mock_query_iterable(items: list[dict]) -> MagicMock:
    """Cosmos DB query_items 반환값을 모킹한다."""
    mock = MagicMock()
    mock.by_page = lambda continuation_token=None: _MockPager(items)
    mock.continuation_token = None
    return mock


class TestBuildNotifications:
    """_build_notifications 함수 테스트."""

    def test_email_uses_provider_from_settings(self, settings: Settings) -> None:
        """email 채널의 provider가 환경 변수에서 결정된다."""
        notifications = _build_notifications([NotificationChannelType.EMAIL], settings)
        assert len(notifications) == 1
        assert notifications[0].provider == "sendgrid"
        assert notifications[0].status == NotificationStatus.PENDING

    def test_sms_uses_provider_from_settings(self, settings: Settings) -> None:
        """sms 채널의 provider가 환경 변수에서 결정된다."""
        notifications = _build_notifications([NotificationChannelType.SMS], settings)
        assert notifications[0].provider == "twilio"

    def test_webhook_provider_is_fixed(self, settings: Settings) -> None:
        """webhook 채널의 provider는 고정 'webhook'이다."""
        notifications = _build_notifications([NotificationChannelType.WEBHOOK], settings)
        assert notifications[0].provider == "webhook"

    def test_all_channels(self, settings: Settings) -> None:
        """3개 채널 모두에 대해 notifications를 생성한다."""
        channels = [NotificationChannelType.EMAIL, NotificationChannelType.SMS, NotificationChannelType.WEBHOOK]
        notifications = _build_notifications(channels, settings)
        assert len(notifications) == 3
        assert all(n.status == NotificationStatus.PENDING for n in notifications)


class TestPostEvents:
    """POST /events 테스트."""

    @pytest.mark.asyncio()
    @patch("src.functions.event_api._get_settings")
    @patch("src.functions.event_api.get_events_container")
    async def test_valid_post_returns_201(self, mock_container_fn: MagicMock, mock_settings: MagicMock) -> None:
        """유효한 POST 요청 시 201을 반환한다."""
        mock_settings.return_value = Settings(**REQUIRED_ENV)  # type: ignore[arg-type]
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        req = _make_request(method="POST", body=VALID_EVENT_BODY)
        resp = await post_events(req)

        assert resp.status_code == 201
        body = json.loads(resp.get_body())
        assert body["event_id"] == VALID_EVENT_BODY["id"]
        assert body["status"] == "queued"
        assert "correlation_id" in body

    @pytest.mark.asyncio()
    @patch("src.functions.event_api._get_settings")
    @patch("src.functions.event_api.get_events_container")
    async def test_cosmos_saves_with_pending_outbox(
        self, mock_container_fn: MagicMock, mock_settings: MagicMock
    ) -> None:
        """DB에 _outbox_status: 'pending'으로 저장된다."""
        mock_settings.return_value = Settings(**REQUIRED_ENV)  # type: ignore[arg-type]
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        req = _make_request(method="POST", body=VALID_EVENT_BODY)
        await post_events(req)

        mock_container.create_item.assert_awaited_once()
        saved_doc = mock_container.create_item.call_args.kwargs["body"]
        assert saved_doc["_outbox_status"] == "pending"
        assert saved_doc["status"] == "queued"

    @pytest.mark.asyncio()
    @patch("src.functions.event_api._get_settings")
    @patch("src.functions.event_api.get_events_container")
    async def test_duplicate_post_returns_200(self, mock_container_fn: MagicMock, mock_settings: MagicMock) -> None:
        """동일 id 재요청 시 200을 반환한다."""
        mock_settings.return_value = Settings(**REQUIRED_ENV)  # type: ignore[arg-type]
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container

        mock_container.create_item.side_effect = CosmosResourceExistsError()
        mock_container.read_item = AsyncMock(
            return_value={
                "id": VALID_EVENT_BODY["id"],
                "status": "processing",
                "correlation_id": "existing-cid",
            }
        )

        req = _make_request(method="POST", body=VALID_EVENT_BODY)
        resp = await post_events(req)

        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["message"] == "Event already exists"
        assert body["status"] == "processing"

    @pytest.mark.asyncio()
    async def test_invalid_json_returns_400(self) -> None:
        """유효하지 않은 JSON 바디는 400을 반환한다."""
        req = func.HttpRequest(
            method="POST",
            url="http://localhost/api/events",
            headers={"Content-Type": "application/json"},
            body=b"not json",
            route_params={},
            params={},
        )
        resp = await post_events(req)
        assert resp.status_code == 400

    @pytest.mark.asyncio()
    async def test_validation_error_returns_400(self) -> None:
        """검증 실패 시 400 + 에러 상세를 반환한다."""
        req = _make_request(method="POST", body={"channels": []})
        resp = await post_events(req)
        assert resp.status_code == 400
        body = json.loads(resp.get_body())
        assert body["error"] == "VALIDATION_ERROR"
        assert len(body["details"]) > 0


class TestGetEventById:
    """GET /events/{event_id} 테스트."""

    @pytest.mark.asyncio()
    async def test_missing_clinic_id_returns_400(self) -> None:
        """clinic_id가 없으면 400을 반환한다."""
        req = _make_request(method="GET", route_params={"event_id": "some-id"})
        resp = await get_event_by_id(req)
        assert resp.status_code == 400

    @pytest.mark.asyncio()
    @patch("src.functions.event_api._get_settings")
    @patch("src.functions.event_api.get_events_container")
    async def test_existing_event_returns_200(self, mock_container_fn: MagicMock, mock_settings: MagicMock) -> None:
        """존재하는 이벤트 조회 시 200을 반환한다."""
        mock_settings.return_value = Settings(**REQUIRED_ENV)  # type: ignore[arg-type]
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item = AsyncMock(
            return_value={
                "id": "evt-1",
                "clinic_id": "CLINIC_123",
                "status": "completed",
                "_outbox_status": "published",
                "_rid": "xxx",
                "_self": "xxx",
                "_etag": "xxx",
                "_attachments": "xxx",
                "_ts": 123,
            }
        )

        req = _make_request(
            method="GET",
            route_params={"event_id": "evt-1"},
            params={"clinic_id": "CLINIC_123"},
        )
        resp = await get_event_by_id(req)

        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert body["id"] == "evt-1"
        # 내부 필드가 제거됨
        assert "_outbox_status" not in body
        assert "_rid" not in body

    @pytest.mark.asyncio()
    @patch("src.functions.event_api._get_settings")
    @patch("src.functions.event_api.get_events_container")
    async def test_not_found_returns_404(self, mock_container_fn: MagicMock, mock_settings: MagicMock) -> None:
        """존재하지 않는 이벤트 조회 시 404를 반환한다."""
        mock_settings.return_value = Settings(**REQUIRED_ENV)  # type: ignore[arg-type]
        mock_container = AsyncMock()
        mock_container_fn.return_value = mock_container
        mock_container.read_item = AsyncMock(side_effect=CosmosResourceNotFoundError())

        req = _make_request(
            method="GET",
            route_params={"event_id": "nonexistent"},
            params={"clinic_id": "CLINIC_123"},
        )
        resp = await get_event_by_id(req)
        assert resp.status_code == 404


class TestGetEvents:
    """GET /events 테스트."""

    @pytest.mark.asyncio()
    async def test_missing_clinic_id_returns_400(self) -> None:
        """clinic_id가 없으면 400을 반환한다."""
        req = _make_request(method="GET")
        resp = await get_events(req)
        assert resp.status_code == 400

    @pytest.mark.asyncio()
    @patch("src.functions.event_api._get_settings")
    @patch("src.functions.event_api.get_events_container")
    async def test_returns_items_list(self, mock_container_fn: MagicMock, mock_settings: MagicMock) -> None:
        """이벤트 목록을 items 배열로 반환한다."""
        mock_settings.return_value = Settings(**REQUIRED_ENV)  # type: ignore[arg-type]
        mock_container = MagicMock()
        mock_container_fn.return_value = mock_container

        mock_item = {"id": "evt-1", "status": "queued"}
        mock_query_iterable = _make_mock_query_iterable([mock_item])
        mock_container.query_items.return_value = mock_query_iterable

        req = _make_request(method="GET", params={"clinic_id": "CLINIC_123"})
        resp = await get_events(req)

        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert "items" in body
        assert "continuation_token" in body

    @pytest.mark.asyncio()
    @patch("src.functions.event_api._get_settings")
    @patch("src.functions.event_api.get_events_container")
    async def test_page_size_clamped_to_100(self, mock_container_fn: MagicMock, mock_settings: MagicMock) -> None:
        """page_size > 100이면 100으로 클램핑된다."""
        mock_settings.return_value = Settings(**REQUIRED_ENV)  # type: ignore[arg-type]
        mock_container = MagicMock()
        mock_container_fn.return_value = mock_container

        mock_query_iterable = _make_mock_query_iterable([])
        mock_container.query_items.return_value = mock_query_iterable

        req = _make_request(method="GET", params={"clinic_id": "CLINIC_123", "page_size": "200"})
        await get_events(req)

        call_kwargs = mock_container.query_items.call_args.kwargs
        assert call_kwargs["max_item_count"] == 100
