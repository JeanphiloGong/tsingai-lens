from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from utils.logger import (
    bind_request_id,
    bind_user_id,
    clear_request_id,
    clear_user_id,
    get_user_id,
    setup_logger,
)


def test_log_formatter_prioritizes_request_context_and_short_component() -> None:
    logger = setup_logger("application.core.objectives.llm.structured_response")
    handler = next(
        handler
        for handler in logging.getLogger().handlers
        if handler.formatter is not None
        and "%(request_id)s" in handler.formatter._fmt
    )
    request_token = bind_request_id("req-test")
    user_token = bind_user_id("user-123")
    try:
        record = logger.makeRecord(
            logger.name,
            logging.INFO,
            "/app/application/core/objectives/llm/structured_response.py",
            1,
            "user-scoped event",
            (),
            None,
        )
        assert handler.filter(record)
        rendered = handler.format(record)
    finally:
        clear_user_id(user_token)
        clear_request_id(request_token)

    assert [field.strip() for field in rendered.split("|", maxsplit=5)][1:] == [
        "req-test",
        "user-123",
        "INFO",
        "structured_response",
        "user-scoped event",
    ]
    assert "application.core.objectives.llm.structured_response" not in rendered
    assert get_user_id() is None


def test_log_formatter_renders_china_standard_time_with_offset(monkeypatch) -> None:
    monkeypatch.setattr(logging.Formatter, "converter", time.gmtime)
    logger = setup_logger("application.source.collection_service")
    handler = next(
        handler
        for handler in logging.getLogger().handlers
        if handler.formatter is not None
        and "%(request_id)s" in handler.formatter._fmt
    )
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        "/app/application/source/collection_service.py",
        1,
        "collection event",
        (),
        None,
    )
    record.created = datetime(
        2026,
        8,
        26,
        3,
        17,
        8,
        tzinfo=timezone.utc,
    ).timestamp()
    assert handler.filter(record)

    rendered = handler.format(record)

    assert rendered.startswith("2026-08-26 11:17:08 +0800 |")


def test_invalid_user_id_is_not_written_to_log_context() -> None:
    token = bind_user_id("user-1\nforged-log-entry")
    try:
        assert get_user_id() is None
    finally:
        clear_user_id(token)


def test_setup_logger_suppresses_docling_page_profiling() -> None:
    docling_logger = logging.getLogger("docling.pipeline.standard_pdf_pipeline")
    original_level = docling_logger.level
    docling_logger.setLevel(logging.DEBUG)

    try:
        lens_logger = setup_logger("application.source.document_parsing")

        assert docling_logger.getEffectiveLevel() == logging.WARNING
        assert lens_logger.getEffectiveLevel() == logging.DEBUG
    finally:
        docling_logger.setLevel(original_level)
