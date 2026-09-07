from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping


ExperimentPlanStatus = Literal["draft", "ready_for_review", "archived"]
EXPERIMENT_PLAN_STATUSES = {"draft", "ready_for_review", "archived"}


class ExperimentPlanRevisionConflictError(ValueError):
    """The requested parent already has a successor or was otherwise superseded."""


@dataclass(frozen=True)
class ExperimentPlanRecord:
    plan_id: str
    collection_id: str
    objective_id: str
    title: str
    content: str
    status: ExperimentPlanStatus
    source_message_id: str | None
    source_links: tuple[Mapping[str, str], ...]
    metadata: Mapping[str, Any]
    created_by: str | None
    created_at: str
    updated_at: str
    plan_version: int = 1
    parent_plan_id: str | None = None
    structured_plan: Mapping[str, Any] | None = None
    updated_by: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExperimentPlanRecord":
        source_links = payload.get("source_links")
        plan_id = _required_text(payload.get("plan_id"), "plan_id")
        plan_version = _positive_int(payload.get("plan_version", 1), "plan_version")
        parent_plan_id = _optional_text(payload.get("parent_plan_id"))
        updated_by = _optional_text(payload.get("updated_by"))
        if plan_version == 1 and parent_plan_id is not None:
            raise ValueError("the first revision cannot have a parent_plan_id")
        if plan_version > 1 and parent_plan_id is None:
            raise ValueError("parent_plan_id is required after the first revision")
        if parent_plan_id == plan_id:
            raise ValueError("parent_plan_id cannot equal plan_id")
        if plan_version > 1 and updated_by is None:
            raise ValueError("updated_by is required after the first revision")
        structured_plan = payload.get("structured_plan")
        if structured_plan is not None and not isinstance(
            structured_plan,
            Mapping,
        ):
            raise ValueError("structured_plan must be an object")
        return cls(
            plan_id=plan_id,
            collection_id=_required_text(payload.get("collection_id"), "collection_id"),
            objective_id=_required_text(payload.get("objective_id"), "objective_id"),
            title=_required_text(payload.get("title"), "title"),
            content=_required_text(payload.get("content"), "content"),
            status=normalize_experiment_plan_status(payload.get("status")),
            source_message_id=_optional_text(payload.get("source_message_id")),
            source_links=tuple(
                _string_mapping(item)
                for item in source_links
                if isinstance(item, Mapping)
            )
            if isinstance(source_links, list | tuple)
            else (),
            metadata=dict(payload.get("metadata"))
            if isinstance(payload.get("metadata"), Mapping)
            else {},
            created_by=_optional_text(payload.get("created_by")),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            plan_version=plan_version,
            parent_plan_id=parent_plan_id,
            structured_plan=(
                deepcopy(dict(structured_plan))
                if isinstance(structured_plan, Mapping)
                else None
            ),
            updated_by=updated_by,
        )

    def with_updates(
        self,
        *,
        title: Any,
        content: Any,
        status: Any,
        updated_at: str,
    ) -> "ExperimentPlanRecord":
        return replace(
            self,
            title=_required_text(title, "title"),
            content=_required_text(content, "content"),
            status=normalize_experiment_plan_status(status),
            updated_at=str(updated_at),
        )

    def next_revision(
        self,
        *,
        plan_id: Any,
        title: Any,
        content: Any,
        status: Any,
        structured_plan: Mapping[str, Any] | None,
        updated_by: Any,
        updated_at: str,
        source_links: tuple[Mapping[str, str], ...] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ExperimentPlanRecord":
        payload = self.to_record()
        payload.update(
            {
                "plan_id": _required_text(plan_id, "plan_id"),
                "title": title,
                "content": content,
                "status": status,
                "plan_version": self.plan_version + 1,
                "parent_plan_id": self.plan_id,
                "structured_plan": structured_plan,
                "updated_by": updated_by,
                "updated_at": str(updated_at),
            }
        )
        if source_links is not None:
            payload["source_links"] = [dict(item) for item in source_links]
        if metadata is not None:
            payload["metadata"] = dict(metadata)
        return ExperimentPlanRecord.from_mapping(payload)

    def to_record(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "collection_id": self.collection_id,
            "objective_id": self.objective_id,
            "title": self.title,
            "content": self.content,
            "status": self.status,
            "source_message_id": self.source_message_id,
            "source_links": [dict(link) for link in self.source_links],
            "metadata": dict(self.metadata),
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "plan_version": self.plan_version,
            "parent_plan_id": self.parent_plan_id,
            "structured_plan": (
                deepcopy(dict(self.structured_plan))
                if self.structured_plan is not None
                else None
            ),
            "updated_by": self.updated_by,
        }


def normalize_experiment_plan_status(value: Any) -> ExperimentPlanStatus:
    status = str(value or "draft").strip().lower()
    if status not in EXPERIMENT_PLAN_STATUSES:
        raise ValueError(
            "experiment plan status must be one of: draft, ready_for_review, archived"
        )
    return status  # type: ignore[return-value]


def _required_text(value: Any, field_name: str) -> str:
    text = _optional_text(value)
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a positive integer")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        raise ValueError(f"{field_name} must be a positive integer")
    if number < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return number


def _string_mapping(value: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(key): str(item)
        for key, item in value.items()
        if _optional_text(key) and _optional_text(item)
    }


__all__ = [
    "EXPERIMENT_PLAN_STATUSES",
    "ExperimentPlanRecord",
    "ExperimentPlanRevisionConflictError",
    "ExperimentPlanStatus",
    "normalize_experiment_plan_status",
]
