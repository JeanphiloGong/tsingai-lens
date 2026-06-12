from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_initial_node_states(node_ids: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    return {
        node_id: {
            "status": "queued",
            "started_at": None,
            "finished_at": None,
            "errors": [],
            "warnings": [],
            "skip_reason": None,
        }
        for node_id in node_ids
    }
