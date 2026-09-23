"""User-controlled authority for Research Agent capabilities."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


class ToolPermissionMode(StrEnum):
    """Controls which capability risks a single chat turn may use."""

    CONFIRM = "confirm"
    READ_ONLY = "read_only"
    NONE = "none"


AUTO_ACTIONS = frozenset({
    "start_research_process",
    "create_objective_candidate",
    "confirm_objective",
    "start_objective_analysis",
    "create_evidence_version",
    "create_finding_version",
    "record_finding_feedback",
    "curate_finding",
    "publish_agent_objective_analysis",
    "create_research_plan",
    "revise_research_plan",
})


def permission_record(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value) if value else {
        "mode": "confirm",
        "actions": [],
        "expires_at": None,
        "revision": 0,
    }


def change_permission(
    current: Mapping[str, Any] | None,
    *,
    mode: str,
    actions: list[str],
    expires_at: str | None,
    expected_revision: int,
) -> dict[str, Any]:
    current_record = permission_record(current)
    if current_record["revision"] != expected_revision:
        raise ValueError("permission_revision_conflict")
    if mode not in {"read_only", "confirm", "auto"}:
        raise ValueError("invalid_permission_mode")
    if not set(actions) <= AUTO_ACTIONS:
        raise ValueError("unknown_permission_action")
    if mode == "auto":
        if not actions or not expires_at:
            raise ValueError("automatic_permission_requires_actions_and_expiry")
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError("permission_expiry_must_be_in_the_future")
    elif actions or expires_at:
        raise ValueError("only_automatic_permission_accepts_actions_and_expiry")
    return {
        "mode": mode,
        "actions": sorted(set(actions)),
        "expires_at": expires_at,
        "revision": current_record["revision"] + 1,
    }


def permits_automatic(
    permission: Mapping[str, Any] | None,
    name: str,
    *,
    now: str,
) -> bool:
    record = permission_record(permission)
    return bool(
        record["mode"] == "auto"
        and name in AUTO_ACTIONS
        and name in record["actions"]
        and datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
        > datetime.fromisoformat(now.replace("Z", "+00:00"))
    )


__all__ = [
    "AUTO_ACTIONS",
    "ToolPermissionMode",
    "change_permission",
    "permission_record",
    "permits_automatic",
]
