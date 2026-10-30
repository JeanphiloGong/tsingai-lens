"""User-controlled authority for Research Agent capabilities."""

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Mapping


class ToolPermissionMode(StrEnum):
    """Controls which capability risks a single chat turn may use."""

    CONFIRM = "confirm"
    READ_ONLY = "read_only"
    NONE = "none"


AUTO_ACTIONS = frozenset(
    {
        "start_research_process",
        "create_objective_candidate",
        "confirm_objective",
        "start_objective_analysis",
        "create_finding_version",
        "record_finding_feedback",
        "curate_finding",
        "create_paper_experiment_revision",
        "create_research_plan",
        "revise_research_plan",
    }
)
# A non-null expiry is a temporary grant; persistent grants use ``None``.
MAX_AUTOMATIC_PERMISSION_HOURS = 24


class PermissionChangeError(ValueError):
    """One rejected permission change, with an explicit stable reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def change_permission(
    current: Mapping[str, Any] | None,
    *,
    mode: str,
    actions: list[str],
    all_actions: bool = False,
    expires_at: str | None,
    expected_revision: int,
) -> dict[str, Any]:
    current_record = {
        "mode": "confirm",
        "actions": [],
        "expires_at": None,
        "revision": 0,
    }
    if current:
        current_record.update(current)
    if current_record["revision"] != expected_revision:
        raise PermissionChangeError("permission_revision_conflict")
    if mode not in {"read_only", "confirm", "auto"}:
        raise PermissionChangeError("invalid_permission_mode")
    requested_actions = set(actions)
    if not requested_actions <= AUTO_ACTIONS:
        raise PermissionChangeError("unknown_permission_action")
    if all_actions and mode != "auto":
        raise PermissionChangeError("only_automatic_permission_accepts_all_actions")
    if all_actions:
        actions = sorted(AUTO_ACTIONS)
    if mode == "auto":
        if not actions:
            raise PermissionChangeError("automatic_permission_requires_actions")
        if expires_at is not None:
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except (AttributeError, TypeError, ValueError) as exc:
                raise PermissionChangeError("invalid_permission_expiry") from exc
            if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                raise PermissionChangeError("permission_expiry_must_be_in_the_future")
            maximum = datetime.now(timezone.utc) + timedelta(
                hours=MAX_AUTOMATIC_PERMISSION_HOURS
            )
            if expiry > maximum:
                raise PermissionChangeError("permission_expiry_cannot_exceed_24_hours")
    elif actions or expires_at is not None:
        raise PermissionChangeError(
            "only_automatic_permission_accepts_actions_and_expiry"
        )
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
    record = {
        "mode": "confirm",
        "actions": [],
        "expires_at": None,
        "revision": 0,
    }
    if permission:
        record.update(permission)
    expiry = record.get("expires_at")
    if expiry is not None:
        try:
            expires_at = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            current_time = datetime.fromisoformat(now.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            return False
        if expires_at.tzinfo is None or current_time.tzinfo is None:
            return False
        is_current = expires_at > current_time
    else:
        is_current = True
    return bool(
        record.get("mode") == "auto"
        and name in AUTO_ACTIONS
        and name in (record.get("actions") or ())
        and is_current
    )


__all__ = [
    "AUTO_ACTIONS",
    "MAX_AUTOMATIC_PERMISSION_HOURS",
    "ToolPermissionMode",
    "PermissionChangeError",
    "change_permission",
    "permits_automatic",
]
