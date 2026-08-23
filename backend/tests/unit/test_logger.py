from __future__ import annotations

import logging

from utils.logger import (
    bind_request_id,
    bind_user_id,
    clear_request_id,
    clear_user_id,
    get_user_id,
    setup_logger,
)


def test_log_formatter_includes_bounded_user_context() -> None:
    logger = setup_logger("test.user-context")
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
            __file__,
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

    assert "| req-test | user-123 | user-scoped event" in rendered
    assert get_user_id() is None


def test_invalid_user_id_is_not_written_to_log_context() -> None:
    token = bind_user_id("user-1\nforged-log-entry")
    try:
        assert get_user_id() is None
    finally:
        clear_user_id(token)
