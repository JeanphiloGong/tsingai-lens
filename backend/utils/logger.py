import contextvars
import logging
import re
import secrets
import sys
from logging.handlers import TimedRotatingFileHandler

from config import LOG_DIR


LOG_DIR.mkdir(parents=True, exist_ok=True)

_QUIET_LIBRARY_LOGGERS = (
    "LiteLLM",
    "litellm",
    "openai",
    "httpx",
    "httpcore",
)
REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_CONTEXT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id",
    default=None,
)
_REQUEST_ID_FORMAT_PLACEHOLDER = "-"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or _REQUEST_ID_FORMAT_PLACEHOLDER
        return True


_REQUEST_ID_FILTER = _RequestIdFilter()


def _configure_library_loggers() -> None:
    for logger_name in _QUIET_LIBRARY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def generate_request_id() -> str:
    return f"req_{secrets.token_hex(8)}"


def get_request_id() -> str | None:
    return _REQUEST_ID_CONTEXT.get()


def bind_request_id(request_id: str) -> contextvars.Token[str | None]:
    return _REQUEST_ID_CONTEXT.set(request_id)


def clear_request_id(token: contextvars.Token[str | None] | None = None) -> None:
    if token is None:
        _REQUEST_ID_CONTEXT.set(None)
        return
    _REQUEST_ID_CONTEXT.reset(token)


def is_valid_request_id(value: str | None) -> bool:
    if value is None:
        return False
    candidate = value.strip()
    return bool(candidate) and bool(_REQUEST_ID_PATTERN.fullmatch(candidate))


def resolve_request_id(value: str | None) -> tuple[str, bool]:
    if is_valid_request_id(value):
        return value.strip(), True
    return generate_request_id(), False


def setup_logger(name: str = __name__) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s | %(name)-24s | %(levelname)-8s | %(request_id)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    debug_file_handler = TimedRotatingFileHandler(
        filename=LOG_DIR / "app_debug.log",
        when="midnight",
        interval=1,
        encoding="utf-8",
    )
    debug_file_handler.setLevel(logging.DEBUG)
    debug_file_handler.setFormatter(formatter)
    debug_file_handler.suffix = "%Y-%m-%d"

    info_file_handler = TimedRotatingFileHandler(
        filename=LOG_DIR / "app_info.log",
        when="midnight",
        interval=1,
        encoding="utf-8",
    )
    info_file_handler.setLevel(logging.INFO)
    info_file_handler.setFormatter(formatter)
    info_file_handler.suffix = "%Y-%m-%d"

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    handlers = [debug_file_handler, info_file_handler, console_handler]

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    def _handler_exists(candidate: logging.Handler) -> bool:
        for existing in root_logger.handlers:
            if type(existing) is not type(candidate):
                continue
            if isinstance(candidate, TimedRotatingFileHandler):
                if getattr(existing, "baseFilename", None) == getattr(
                    candidate,
                    "baseFilename",
                    None,
                ):
                    return True
            elif isinstance(candidate, logging.StreamHandler):
                if getattr(existing, "stream", None) is getattr(candidate, "stream", None):
                    return True
        return False

    for handler in handlers:
        if _REQUEST_ID_FILTER not in handler.filters:
            handler.addFilter(_REQUEST_ID_FILTER)
        if not _handler_exists(handler):
            root_logger.addHandler(handler)
            continue
        handler.close()

    _configure_library_loggers()
    logging.captureWarnings(True)

    return logger


logger = setup_logger("main")
