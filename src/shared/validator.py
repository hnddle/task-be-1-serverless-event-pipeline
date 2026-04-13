"""POST /events 요청 입력 검증.

Pydantic BaseModel 기반으로 요청 바디를 검증한다.
검증 실패 시 ValidationError (errors.py)를 발생시킨다.

SPEC.md §8.1 입력 검증 규칙 참조.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, field_validator

from src.models.events import EventType, NotificationChannelType
from src.shared.errors import FieldError, ValidationError


class CreateEventRequest(BaseModel):
    """POST /events 요청 바디 스키마.

    SPEC.md §8.1 입력 검증 규칙:
    - id: 필수, UUID v4 형식
    - event_type: 필수, appointment_confirmed / insurance_approved / claim_completed
    - clinic_id: 필수, 비어 있지 않은 문자열
    - patient_id: 필수, 비어 있지 않은 문자열
    - channels: 필수, 1개 이상 배열, email/sms/webhook만 허용, 중복 불가
    """

    id: str
    event_type: EventType
    clinic_id: str
    patient_id: str
    channels: list[NotificationChannelType]

    @field_validator("id")
    @classmethod
    def validate_uuid_v4(cls, v: str) -> str:
        """id가 유효한 UUID v4 형식인지 검증한다."""
        try:
            parsed = uuid.UUID(v, version=4)
            if str(parsed) != v:
                msg = "Must be a valid UUID v4 format"
                raise ValueError(msg)
        except ValueError as e:
            msg = "Must be a valid UUID v4 format"
            raise ValueError(msg) from e
        return v

    @field_validator("clinic_id")
    @classmethod
    def validate_clinic_id_not_empty(cls, v: str) -> str:
        """clinic_id가 비어 있지 않은 문자열인지 검증한다."""
        if not v.strip():
            msg = "Must not be empty"
            raise ValueError(msg)
        return v

    @field_validator("patient_id")
    @classmethod
    def validate_patient_id_not_empty(cls, v: str) -> str:
        """patient_id가 비어 있지 않은 문자열인지 검증한다."""
        if not v.strip():
            msg = "Must not be empty"
            raise ValueError(msg)
        return v

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, v: list[NotificationChannelType]) -> list[NotificationChannelType]:
        """channels가 1개 이상이고 중복이 없는지 검증한다."""
        if len(v) == 0:
            msg = "Must contain at least one channel"
            raise ValueError(msg)
        if len(v) != len(set(v)):
            msg = "Duplicate channels are not allowed"
            raise ValueError(msg)
        return v


def validate_create_event(body: dict[str, Any]) -> CreateEventRequest:
    """POST /events 요청 바디를 검증하여 CreateEventRequest를 반환한다.

    검증 실패 시 ValidationError (src.shared.errors)를 발생시킨다.
    에러 응답 형식: { error: "VALIDATION_ERROR", message, details: [{ field, message }] }
    """
    try:
        return CreateEventRequest.model_validate(body)
    except Exception as e:
        if hasattr(e, "errors"):
            # Pydantic ValidationError
            details = [
                FieldError(
                    field=_extract_field_name(err),
                    message=_extract_message(err),
                )
                for err in e.errors()
            ]
            raise ValidationError(details=details) from e
        raise ValidationError(details=[FieldError(field="body", message=str(e))]) from e


def _extract_field_name(err: dict[str, Any]) -> str:
    """Pydantic 에러에서 필드명을 추출한다."""
    loc = err.get("loc", ())
    if loc:
        return str(loc[-1])
    return "unknown"


def _extract_message(err: dict[str, Any]) -> str:
    """Pydantic 에러에서 사용자 친화적 메시지를 추출한다."""
    err_type = err.get("type", "")
    field_name = _extract_field_name(err)

    if err_type == "missing":
        return f"{field_name} is required"

    if err_type == "string_type":
        return "Must be a string"

    if err_type == "list_type":
        return "Must be an array"

    # event_type enum 에러
    if err_type == "enum" and field_name == "event_type":
        valid = ", ".join(e.value for e in EventType)
        return f"Must be one of: {valid}"

    # channels 내부 enum 에러
    if err_type == "enum":
        valid = ", ".join(e.value for e in NotificationChannelType)
        return f"Must be one of: {valid}"

    # field_validator에서 발생한 ValueError
    msg: str = str(err.get("msg", ""))
    if msg.startswith("Value error, "):
        return msg[len("Value error, ") :]

    return msg or "Invalid value"
