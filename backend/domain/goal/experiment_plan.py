from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping


ExperimentPlanStatus = Literal["draft", "ready_for_review", "archived"]
EXPERIMENT_PLAN_STATUSES = {"draft", "ready_for_review", "archived"}


@dataclass(frozen=True)
class ExperimentPlanRecord:
    plan_id: str
    collection_id: str
    goal_id: str
    title: str
    content: str
    status: ExperimentPlanStatus
    source_message_id: str | None
    source_links: tuple[Mapping[str, str], ...]
    metadata: Mapping[str, Any]
    created_by: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExperimentPlanRecord":
        source_links = payload.get("source_links")
        return cls(
            plan_id=_required_text(payload.get("plan_id"), "plan_id"),
            collection_id=_required_text(payload.get("collection_id"), "collection_id"),
            goal_id=_required_text(payload.get("goal_id"), "goal_id"),
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

    def to_record(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "collection_id": self.collection_id,
            "goal_id": self.goal_id,
            "title": self.title,
            "content": self.content,
            "status": self.status,
            "source_message_id": self.source_message_id,
            "source_links": [dict(link) for link in self.source_links],
            "metadata": dict(self.metadata),
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
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


def _string_mapping(value: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(key): str(item)
        for key, item in value.items()
        if _optional_text(key) and _optional_text(item)
    }


__all__ = [
    "EXPERIMENT_PLAN_STATUSES",
    "ExperimentPlanRecord",
    "ExperimentPlanStatus",
    "normalize_experiment_plan_status",
]
