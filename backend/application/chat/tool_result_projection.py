"""Explicit projections for durable Chat tool-result records."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any

from domain.chat import ChatToolResult


def tool_result_record(result: ChatToolResult) -> dict[str, Any]:
    """Return the stable record used by Chat storage, context, and digests."""
    return {
        "tool_call_id": result.tool_call_id,
        "status": result.status.value,
        "data": deepcopy(dict(result.data)),
        "resource_refs": [asdict(item) for item in result.resource_refs],
        "warnings": list(result.warnings),
        "error_code": result.error_code,
        "error_message": result.error_message,
    }
