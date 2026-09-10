"""Collect internal diagnostics for one Objective analysis execution."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import logging
from threading import Lock
from traceback import walk_tb
from typing import Any


logger = logging.getLogger(__name__)


class AnalysisDiagnosticCollector:
    """Keep concurrent Objective analysis diagnostics isolated by context."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._records: list[dict[str, Any]] = []

    def record(self, payload: Mapping[str, Any]) -> None:
        record = deepcopy(dict(payload))
        with self._lock:
            self._records.append(record)

    @property
    def records(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(deepcopy(self._records))


_ACTIVE_DIAGNOSTIC_COLLECTOR: ContextVar[AnalysisDiagnosticCollector | None] = (
    ContextVar("active_objective_analysis_diagnostic_collector", default=None)
)


@contextmanager
def capture_analysis_diagnostics() -> Iterator[AnalysisDiagnosticCollector]:
    collector = AnalysisDiagnosticCollector()
    token = _ACTIVE_DIAGNOSTIC_COLLECTOR.set(collector)
    try:
        yield collector
    finally:
        _ACTIVE_DIAGNOSTIC_COLLECTOR.reset(token)


def record_analysis_diagnostic(payload: Mapping[str, Any]) -> None:
    record = deepcopy(dict(payload))
    logger.info(
        "Objective analysis internal diagnostic trace=%s",
        json.dumps(record, ensure_ascii=True, separators=(",", ":")),
    )
    collector = _ACTIVE_DIAGNOSTIC_COLLECTOR.get()
    if collector is not None:
        collector.record(record)


def record_analysis_failure(error: Exception, **context: str | int) -> None:
    """Keep failure locations without provider response text, source code or locals."""
    record_analysis_diagnostic(
        {
            **context,
            "trace_type": "objective_analysis_failure",
            "error_type": type(error).__name__,
            "frames": [
                {
                    "file": frame.f_code.co_filename,
                    "line": line,
                    "function": frame.f_code.co_name,
                }
                for frame, line in walk_tb(error.__traceback__)
            ],
        }
    )


__all__ = [
    "AnalysisDiagnosticCollector",
    "capture_analysis_diagnostics",
    "record_analysis_diagnostic",
    "record_analysis_failure",
]
