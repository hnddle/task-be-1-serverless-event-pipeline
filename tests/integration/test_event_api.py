"""Event API 통합 테스트.

POST /events → Cosmos DB 저장 → 중복 처리 → 조회 흐름을 검증한다.
Cosmos DB Emulator 필수 — Emulator 미실행 시 자동 스킵.

SPEC.md §13.2 참조.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.functions.event_api import get_event_by_id, get_events, post_events


def _make_http_request(
    method: str = "POST",
    body: dict | None = None,
    params: dict | None = None,
    route_params: dict | None = None,
) -> MagicMock:
    """테스트용 HttpRequest를 생성한다."""
    req = MagicMock()
    req.method = method
    req.params = params or {}
    req.route_params = route_params or {}
    if body is not None:
        req.get_json.return_value = body
    else:
        req.get_json.side_effect = ValueError("No JSON")
    return req


def _make_event_body(
    *,
    event_id: str | None = None,
    clinic_id: str = "test-clinic",
    channels: list[str] | None = None,
) -> dict[str, Any]:
    """유효한 이벤트 생성 요청 바디."""
    return {
        "id": event_id or str(uuid.uuid4()),
        "event_type": "appointment_confirmed",
        "clinic_id": clinic_id,
        "patient_id": "P-001",
        "channels": channels or ["email", "sms"],
    }


@pytest.mark.usefixtures("setup_database")
class TestEventApiIntegration:
    """Event API 통합 테스트 — Cosmos DB Emulator 사용."""

    @pytest.mark.asyncio()
    async def test_post_events_creates_and_returns_201(
        self,
        test_settings: Any,
        unique_clinic_id: str,
    ) -> None:
        """POST /events → 201 + DB에 이벤트 저장."""
        body = _make_event_body(clinic_id=unique_clinic_id)

        with patch("src.functions.event_api._get_settings", return_value=test_settings):
            req = _make_http_request(body=body)
            resp = await post_events(req)

        assert resp.status_code == 201
        result = json.loads(resp.get_body())
        assert result["event_id"] == body["id"]
        assert result["status"] == "queued"
        assert "correlation_id" in result

    @pytest.mark.asyncio()
    async def test_duplicate_post_returns_200(
        self,
        test_settings: Any,
        unique_clinic_id: str,
    ) -> None:
        """중복 POST → 200 + 기존 상태 반환."""
        body = _make_event_body(clinic_id=unique_clinic_id)

        with patch("src.functions.event_api._get_settings", return_value=test_settings):
            # 첫 번째 요청 → 201
            req1 = _make_http_request(body=body)
            resp1 = await post_events(req1)
            assert resp1.status_code == 201

            # 동일 요청 → 200 (Idempotency)
            req2 = _make_http_request(body=body)
            resp2 = await post_events(req2)
            assert resp2.status_code == 200

            result = json.loads(resp2.get_body())
            assert result["event_id"] == body["id"]
            assert "message" in result

    @pytest.mark.asyncio()
    async def test_get_event_by_id_returns_detail(
        self,
        test_settings: Any,
        unique_clinic_id: str,
    ) -> None:
        """GET /events/{event_id} → 상세 조회 확인."""
        body = _make_event_body(clinic_id=unique_clinic_id)

        with patch("src.functions.event_api._get_settings", return_value=test_settings):
            # 이벤트 생성
            req = _make_http_request(body=body)
            await post_events(req)

            # 상세 조회
            get_req = _make_http_request(
                method="GET",
                params={"clinic_id": unique_clinic_id},
                route_params={"event_id": body["id"]},
            )
            resp = await get_event_by_id(get_req)

        assert resp.status_code == 200
        result = json.loads(resp.get_body())
        assert result["id"] == body["id"]
        assert result["clinic_id"] == unique_clinic_id
        assert result["event_type"] == "appointment_confirmed"
        assert result["status"] == "queued"
        assert len(result["notifications"]) == 2

    @pytest.mark.asyncio()
    async def test_get_event_not_found_returns_404(
        self,
        test_settings: Any,
        unique_clinic_id: str,
    ) -> None:
        """존재하지 않는 event_id → 404."""
        with patch("src.functions.event_api._get_settings", return_value=test_settings):
            req = _make_http_request(
                method="GET",
                params={"clinic_id": unique_clinic_id},
                route_params={"event_id": str(uuid.uuid4())},
            )
            resp = await get_event_by_id(req)

        assert resp.status_code == 404

    @pytest.mark.asyncio()
    async def test_get_events_list_with_pagination(
        self,
        test_settings: Any,
        unique_clinic_id: str,
    ) -> None:
        """GET /events → 목록 조회 + 페이지네이션 확인."""
        # 3개 이벤트 생성
        event_ids = []
        with patch("src.functions.event_api._get_settings", return_value=test_settings):
            for _ in range(3):
                body = _make_event_body(clinic_id=unique_clinic_id)
                event_ids.append(body["id"])
                req = _make_http_request(body=body)
                resp = await post_events(req)
                assert resp.status_code == 201

            # 목록 조회 (page_size=2)
            list_req = _make_http_request(
                method="GET",
                params={"clinic_id": unique_clinic_id, "page_size": "2"},
            )
            resp = await get_events(list_req)

        assert resp.status_code == 200
        result = json.loads(resp.get_body())
        assert len(result["items"]) == 2
        # continuation_token이 존재해야 다음 페이지가 있음
        assert result["continuation_token"] is not None

    @pytest.mark.asyncio()
    async def test_get_events_missing_clinic_id_returns_400(
        self,
        test_settings: Any,
    ) -> None:
        """clinic_id 없이 목록 조회 → 400."""
        with patch("src.functions.event_api._get_settings", return_value=test_settings):
            req = _make_http_request(method="GET", params={})
            resp = await get_events(req)

        assert resp.status_code == 400
