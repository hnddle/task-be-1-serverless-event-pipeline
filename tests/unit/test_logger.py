"""구조화 로거 및 Correlation ID 컨텍스트 테스트."""

from __future__ import annotations

import io
import json
import logging
from typing import Any

from src.shared.correlation import (
    clear_context,
    generate_correlation_id,
    get_correlation_id,
    get_log_context,
    set_correlation_id,
    set_log_context,
)
from src.shared.logger import JsonFormatter, get_logger, log_with_context, setup_logger


class TestCorrelationId:
    """Correlation ID 컨텍스트 관리 테스트."""

    def setup_method(self) -> None:
        clear_context()

    def test_generate_correlation_id_is_uuid_format(self) -> None:
        """생성된 correlation_id가 UUID 형식이다."""
        cid = generate_correlation_id()
        assert len(cid) == 36
        assert cid.count("-") == 4

    def test_set_and_get_correlation_id(self) -> None:
        """correlation_id를 설정하고 조회할 수 있다."""
        set_correlation_id("test-cid-123")
        assert get_correlation_id() == "test-cid-123"

    def test_default_correlation_id_is_none(self) -> None:
        """기본값은 None이다."""
        assert get_correlation_id() is None

    def test_clear_context_resets_correlation_id(self) -> None:
        """clear_context()로 초기화된다."""
        set_correlation_id("test-cid")
        clear_context()
        assert get_correlation_id() is None

    def test_set_and_get_log_context(self) -> None:
        """추가 로그 컨텍스트를 설정하고 조회할 수 있다."""
        set_log_context(event_id="evt-1", channel="email")
        ctx = get_log_context()
        assert ctx["event_id"] == "evt-1"
        assert ctx["channel"] == "email"

    def test_set_log_context_merges_fields(self) -> None:
        """set_log_context는 기존 필드를 유지하며 새 필드를 추가한다."""
        set_log_context(event_id="evt-1")
        set_log_context(channel="sms")
        ctx = get_log_context()
        assert ctx["event_id"] == "evt-1"
        assert ctx["channel"] == "sms"

    def test_clear_context_resets_log_context(self) -> None:
        """clear_context()로 로그 컨텍스트도 초기화된다."""
        set_log_context(event_id="evt-1")
        clear_context()
        assert get_log_context() == {}


def _make_test_logger(name: str) -> tuple[logging.Logger, io.StringIO]:
    """테스트용 로거와 출력 스트림을 생성한다."""
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    return logger, stream


def _parse_log(stream: io.StringIO) -> dict[str, Any]:
    """스트림에서 마지막 로그 라인을 JSON 파싱한다."""
    output = stream.getvalue()
    lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
    assert lines, "No log output captured"
    return json.loads(lines[-1])  # type: ignore[no-any-return]


class TestJsonLogger:
    """JSON 구조화 로거 출력 형식 테스트."""

    def setup_method(self) -> None:
        clear_context()

    def test_log_output_is_json(self) -> None:
        """로그가 JSON 형식으로 출력된다."""
        logger, stream = _make_test_logger("test-json-output")
        logger.info("테스트 메시지")
        entry = _parse_log(stream)
        assert entry["message"] == "테스트 메시지"
        assert entry["level"] == "INFO"
        assert "timestamp" in entry

    def test_log_includes_correlation_id(self) -> None:
        """correlation_id가 컨텍스트에 설정되면 로그에 포함된다."""
        set_correlation_id("cid-test-456")
        logger, stream = _make_test_logger("test-cid-include")
        logger.info("상관관계 테스트")
        entry = _parse_log(stream)
        assert entry["correlation_id"] == "cid-test-456"

    def test_log_without_correlation_id_omits_field(self) -> None:
        """correlation_id가 설정되지 않으면 필드가 제외된다."""
        logger, stream = _make_test_logger("test-cid-omit")
        logger.info("메시지")
        entry = _parse_log(stream)
        assert "correlation_id" not in entry

    def test_log_includes_context_fields(self) -> None:
        """set_log_context로 설정한 필드가 로그에 포함된다."""
        set_log_context(event_id="evt-789", channel="webhook")
        logger, stream = _make_test_logger("test-ctx-fields")
        logger.info("컨텍스트 테스트")
        entry = _parse_log(stream)
        assert entry["event_id"] == "evt-789"
        assert entry["channel"] == "webhook"

    def test_log_with_context_includes_extra_fields(self) -> None:
        """log_with_context로 전달한 extra 필드가 로그에 포함된다."""
        logger, stream = _make_test_logger("test-extra")
        log_with_context(
            logger,
            logging.INFO,
            "발송 완료",
            duration_ms=150,
            provider="sendgrid",
        )
        entry = _parse_log(stream)
        assert entry["message"] == "발송 완료"
        assert entry["duration_ms"] == 150
        assert entry["provider"] == "sendgrid"

    def test_log_error_includes_exception_info(self) -> None:
        """예외 발생 시 error, error_type 필드가 포함된다."""
        logger, stream = _make_test_logger("test-exc")
        try:
            raise ValueError("테스트 에러")
        except ValueError:
            logger.error("에러 발생", exc_info=True)
        entry = _parse_log(stream)
        assert entry["error"] == "테스트 에러"
        assert entry["error_type"] == "ValueError"

    def test_log_level_warning(self) -> None:
        """WARNING 레벨이 정확히 출력된다."""
        logger, stream = _make_test_logger("test-warn")
        logger.warning("경고 메시지")
        entry = _parse_log(stream)
        assert entry["level"] == "WARNING"


class TestGetLogger:
    """get_logger 유틸리티 테스트."""

    def teardown_method(self) -> None:
        parent = logging.getLogger("notification-pipeline")
        parent.handlers.clear()

    def test_get_logger_returns_child_logger(self) -> None:
        """name을 지정하면 하위 로거를 반환한다."""
        logger = get_logger("event-api")
        assert logger.name == "notification-pipeline.event-api"

    def test_get_logger_without_name_returns_base(self) -> None:
        """name 없이 호출하면 기본 로거를 반환한다."""
        logger = get_logger()
        assert logger.name == "notification-pipeline"

    def test_get_logger_sets_up_parent_handler(self) -> None:
        """부모 로거에 핸들러가 없으면 자동으로 설정한다."""
        parent = logging.getLogger("notification-pipeline")
        parent.handlers.clear()
        get_logger("test-child")
        assert len(parent.handlers) > 0


class TestSetupLogger:
    """setup_logger 테스트."""

    def teardown_method(self) -> None:
        logger = logging.getLogger("test-setup")
        logger.handlers.clear()

    def test_setup_logger_outputs_to_stdout(self) -> None:
        """setup_logger는 stdout StreamHandler를 추가한다."""
        logger = setup_logger("test-setup")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)

    def test_setup_logger_idempotent(self) -> None:
        """setup_logger를 여러 번 호출해도 핸들러가 중복되지 않는다."""
        setup_logger("test-setup")
        setup_logger("test-setup")
        logger = logging.getLogger("test-setup")
        assert len(logger.handlers) == 1
