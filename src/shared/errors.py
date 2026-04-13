"""공통 예외 클래스.

API 경계에서 사용되는 표준 에러 타입.
SPEC.md §8.4 공통 에러 응답 형식 참조.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FieldError:
    """개별 필드 검증 에러."""

    field: str
    message: str


class AppError(Exception):
    """애플리케이션 기본 에러."""

    def __init__(self, error_code: str, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code

    def to_dict(self) -> dict[str, object]:
        return {
            "error": self.error_code,
            "message": self.message,
            "details": [],
        }


@dataclass
class ValidationError(AppError):
    """입력 검증 실패 (400)."""

    details: list[FieldError] = field(default_factory=list)

    def __init__(self, message: str = "Invalid request body", details: list[FieldError] | None = None) -> None:
        super().__init__(
            error_code="VALIDATION_ERROR",
            message=message,
            status_code=400,
        )
        self.details = details or []

    def to_dict(self) -> dict[str, object]:
        return {
            "error": self.error_code,
            "message": self.message,
            "details": [{"field": d.field, "message": d.message} for d in self.details],
        }


class NotFoundError(AppError):
    """리소스 없음 (404)."""

    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(
            error_code="NOT_FOUND",
            message=message,
            status_code=404,
        )


class ConflictError(AppError):
    """충돌 (409)."""

    def __init__(self, message: str = "Resource conflict") -> None:
        super().__init__(
            error_code="CONFLICT",
            message=message,
            status_code=409,
        )
