"""POST /events 입력 검증 테스트."""

from __future__ import annotations

import uuid

import pytest

from src.shared.errors import ValidationError
from src.shared.validator import CreateEventRequest, validate_create_event

VALID_BODY = {
    "id": str(uuid.uuid4()),
    "event_type": "appointment_confirmed",
    "clinic_id": "CLINIC_123",
    "patient_id": "PATIENT_456",
    "channels": ["email", "sms"],
}


def _body(**overrides: object) -> dict[str, object]:
    """VALID_BODY에 오버라이드를 적용한 딕셔너리를 반환한다."""
    return {**VALID_BODY, **overrides}


class TestValidRequest:
    """유효한 요청 검증 테스트."""

    def test_valid_request_passes(self) -> None:
        """모든 필드가 유효하면 검증을 통과한다."""
        result = validate_create_event(VALID_BODY)
        assert isinstance(result, CreateEventRequest)
        assert result.clinic_id == "CLINIC_123"

    def test_valid_all_channels(self) -> None:
        """email, sms, webhook 모든 채널을 포함한 요청이 통과한다."""
        body = _body(channels=["email", "sms", "webhook"])
        result = validate_create_event(body)
        assert len(result.channels) == 3

    def test_valid_single_channel(self) -> None:
        """채널이 1개만 있어도 통과한다."""
        body = _body(channels=["webhook"])
        result = validate_create_event(body)
        assert len(result.channels) == 1

    def test_valid_all_event_types(self) -> None:
        """모든 event_type이 통과한다."""
        for et in ["appointment_confirmed", "insurance_approved", "claim_completed"]:
            body = _body(event_type=et)
            result = validate_create_event(body)
            assert result.event_type == et


class TestIdValidation:
    """id 필드 검증 테스트."""

    def test_invalid_uuid_format(self) -> None:
        """UUID 형식이 아닌 id는 에러가 발생한다."""
        body = _body(id="not-a-uuid")
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        assert any(d["field"] == "id" for d in details)

    def test_missing_id(self) -> None:
        """id가 누락되면 에러가 발생한다."""
        body = {k: v for k, v in VALID_BODY.items() if k != "id"}
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        assert any(d["field"] == "id" for d in details)

    def test_uuid_v1_is_rejected(self) -> None:
        """UUID v1은 거부된다."""
        body = _body(id=str(uuid.uuid1()))
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        assert any(d["field"] == "id" for d in details)


class TestEventTypeValidation:
    """event_type 필드 검증 테스트."""

    def test_unsupported_event_type(self) -> None:
        """지원하지 않는 event_type은 에러가 발생한다."""
        body = _body(event_type="order_placed")
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        field_detail = next(d for d in details if d["field"] == "event_type")
        assert "appointment_confirmed" in field_detail["message"]
        assert "insurance_approved" in field_detail["message"]
        assert "claim_completed" in field_detail["message"]

    def test_missing_event_type(self) -> None:
        """event_type이 누락되면 에러가 발생한다."""
        body = {k: v for k, v in VALID_BODY.items() if k != "event_type"}
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        assert any(d["field"] == "event_type" for d in details)


class TestClinicIdValidation:
    """clinic_id 필드 검증 테스트."""

    def test_empty_clinic_id(self) -> None:
        """빈 문자열 clinic_id는 에러가 발생한다."""
        body = _body(clinic_id="")
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        assert any(d["field"] == "clinic_id" for d in details)

    def test_whitespace_clinic_id(self) -> None:
        """공백만 있는 clinic_id는 에러가 발생한다."""
        body = _body(clinic_id="   ")
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        assert any(d["field"] == "clinic_id" for d in details)

    def test_missing_clinic_id(self) -> None:
        """clinic_id가 누락되면 에러가 발생한다."""
        body = {k: v for k, v in VALID_BODY.items() if k != "clinic_id"}
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        assert any(d["field"] == "clinic_id" for d in details)


class TestPatientIdValidation:
    """patient_id 필드 검증 테스트."""

    def test_empty_patient_id(self) -> None:
        """빈 문자열 patient_id는 에러가 발생한다."""
        body = _body(patient_id="")
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        assert any(d["field"] == "patient_id" for d in details)

    def test_missing_patient_id(self) -> None:
        """patient_id가 누락되면 에러가 발생한다."""
        body = {k: v for k, v in VALID_BODY.items() if k != "patient_id"}
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        assert any(d["field"] == "patient_id" for d in details)


class TestChannelsValidation:
    """channels 필드 검증 테스트."""

    def test_empty_channels_array(self) -> None:
        """빈 channels 배열은 에러가 발생한다."""
        body = _body(channels=[])
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        assert any(d["field"] == "channels" for d in details)

    def test_duplicate_channels(self) -> None:
        """중복 채널은 에러가 발생한다."""
        body = _body(channels=["email", "email"])
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        assert any(d["field"] == "channels" for d in details)
        field_detail = next(d for d in details if d["field"] == "channels")
        assert "Duplicate" in field_detail["message"]

    def test_unsupported_channel(self) -> None:
        """지원하지 않는 채널은 에러가 발생한다."""
        body = _body(channels=["email", "push"])
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        assert len(details) > 0

    def test_missing_channels(self) -> None:
        """channels가 누락되면 에러가 발생한다."""
        body = {k: v for k, v in VALID_BODY.items() if k != "channels"}
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        assert any(d["field"] == "channels" for d in details)

    def test_channels_not_array(self) -> None:
        """channels가 배열이 아니면 에러가 발생한다."""
        body = _body(channels="email")
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        assert any(d["field"] == "channels" for d in details)


class TestErrorResponseFormat:
    """에러 응답 형식 테스트."""

    def test_error_response_has_correct_structure(self) -> None:
        """ValidationError.to_dict()가 SPEC §8.4 형식을 따른다."""
        body = _body(id="invalid", event_type="unknown", channels=[])
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        error_dict = exc_info.value.to_dict()
        assert error_dict["error"] == "VALIDATION_ERROR"
        assert error_dict["message"] == "Invalid request body"
        assert isinstance(error_dict["details"], list)
        assert len(error_dict["details"]) > 0

    def test_multiple_field_errors(self) -> None:
        """여러 필드가 동시에 실패하면 모든 에러가 details에 포함된다."""
        body = {"channels": []}  # id, event_type, clinic_id, patient_id 누락 + channels 비어있음
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        fields = {d["field"] for d in details}
        assert "id" in fields
        assert "event_type" in fields
        assert "clinic_id" in fields
        assert "patient_id" in fields

    def test_each_detail_has_field_and_message(self) -> None:
        """각 detail 항목에 field와 message가 있다."""
        body = _body(id="bad")
        with pytest.raises(ValidationError) as exc_info:
            validate_create_event(body)
        details = exc_info.value.to_dict()["details"]
        for detail in details:
            assert "field" in detail
            assert "message" in detail
