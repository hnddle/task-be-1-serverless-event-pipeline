"""Notification Event 관련 Pydantic 모델.

Cosmos DB `events` 컨테이너 문서 구조와 1:1 대응.
SPEC.md §3.1 참조.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class EventStatus(StrEnum):
    """이벤트 처리 상태."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"


class NotificationChannelType(StrEnum):
    """지원하는 알림 채널 타입."""

    EMAIL = "email"
    SMS = "sms"
    WEBHOOK = "webhook"


class NotificationStatus(StrEnum):
    """개별 알림 발송 상태."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class OutboxStatus(StrEnum):
    """Transactional Outbox 상태."""

    PENDING = "pending"
    PUBLISHED = "published"
    FAILED_PUBLISH = "failed_publish"


class EventType(StrEnum):
    """지원하는 이벤트 타입."""

    APPOINTMENT_CONFIRMED = "appointment_confirmed"
    INSURANCE_APPROVED = "insurance_approved"
    CLAIM_COMPLETED = "claim_completed"


class NotificationChannel(BaseModel):
    """개별 채널 알림 상태.

    notifications[] 배열의 각 항목.
    provider 필드는 NOTIFICATION_EMAIL_PROVIDER, NOTIFICATION_SMS_PROVIDER
    환경 변수에서 결정됨 (webhook은 고정 "webhook").
    """

    channel: NotificationChannelType
    provider: str
    status: NotificationStatus = NotificationStatus.PENDING
    sent_at: datetime | None = None
    retry_count: int = 0
    last_error: str | None = None


class NotificationEvent(BaseModel):
    """Notification Event 문서 (Cosmos DB `events` 컨테이너).

    id가 곧 Idempotency Key이다.
    clinic_id가 Partition Key이다.
    """

    id: str
    clinic_id: str
    status: EventStatus = EventStatus.QUEUED
    event_type: EventType
    patient_id: str
    channels: list[NotificationChannelType]
    correlation_id: str
    notifications: list[NotificationChannel] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    outbox_status: OutboxStatus = Field(default=OutboxStatus.PENDING, alias="_outbox_status")

    model_config = {"populate_by_name": True}


EventStatusLiteral = Literal[
    "queued", "processing", "completed", "partially_completed", "failed"
]
