"""Events and safe summaries emitted from one direct Task execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from agent.domain.models import Operation


ExecutionEvent = dict[str, object]
EventSink = Callable[[ExecutionEvent], Awaitable[None]]


def operation_activity(operation: Operation) -> dict[str, object]:
    result = operation.result if isinstance(operation.result, Mapping) else {}
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    excerpt = next(
        (
            str(data[key]).strip()
            for key in ("content", "table_markdown", "source_excerpt", "excerpt")
            if isinstance(data.get(key), str) and str(data[key]).strip()
        ),
        None,
    )
    error_code = result.get("error_code") or operation.error_code
    if operation.status == "failed":
        summary = str(error_code or "operation_failed")
    elif operation.name == "read_source":
        summary = _source_summary(data)
    elif operation.name == "inspect_table":
        summary = _table_summary(data)
    elif operation.name == "search_sources":
        matches = data.get("matches")
        summary = f"Found {len(matches)} candidate Sources" if isinstance(matches, list) else "Search completed"
    else:
        summary = "Operation completed"
    return {
        "summary": summary,
        "context": _operation_context(data, operation.name),
        "excerpt": excerpt[:520] if excerpt else None,
        "result_truncated": bool(
            data.get("content_truncated")
            or data.get("output_truncated")
            or (excerpt is not None and len(excerpt) > 520)
        ),
    }


def _source_summary(data: Mapping[str, Any]) -> str:
    title = str(data.get("document_title") or data.get("title") or "Source").strip()
    heading = str(data.get("heading_path") or "").strip()
    page = data.get("page")
    location = " · ".join(
        part for part in (title, heading, f"p. {page}" if page is not None else "") if part
    )
    return f"Read {location or 'Source'}"


def _table_summary(data: Mapping[str, Any]) -> str:
    label = str(data.get("caption") or data.get("table_ref") or "table").strip()
    page = data.get("page")
    return f"Inspected {label}" + (f" · p. {page}" if page is not None else "")


def _operation_context(data: Mapping[str, Any], name: str) -> str:
    document = data.get("document") if isinstance(data.get("document"), Mapping) else {}
    title = str(
        data.get("document_title")
        or data.get("title")
        or document.get("title")
        or ""
    ).strip()
    location = str(
        data.get("heading_path")
        or data.get("source_kind")
        or data.get("source_ref")
        or data.get("table_ref")
        or ""
    ).strip()
    page = data.get("page")
    page_text = f"p. {page}" if page is not None else ""
    return " · ".join(part for part in (title, location, page_text) if part) or name


__all__ = ["EventSink", "ExecutionEvent", "operation_activity"]
