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

    def __post_init__(self) -> None:
        if self.plan_version < 1:
            raise ValueError("plan_version must be a positive integer")
        if self.plan_version == 1 and self.parent_plan_id is not None:
            raise ValueError("the first revision cannot have a parent_plan_id")
        if self.plan_version > 1 and self.parent_plan_id is None:
            raise ValueError("parent_plan_id is required after the first revision")
        if self.parent_plan_id == self.plan_id:
            raise ValueError("parent_plan_id cannot equal plan_id")
        if self.plan_version > 1 and self.updated_by is None:
            raise ValueError("updated_by is required after the first revision")

    def with_updates(
        self,
        *,
        title: str,
        content: str,
        status: ExperimentPlanStatus,
        updated_at: str,
    ) -> "ExperimentPlanRecord":
        return replace(
            self,
            title=title,
            content=content,
            status=status,
            updated_at=updated_at,
        )

    def next_revision(
        self,
        *,
        plan_id: str,
        title: str,
        content: str,
        status: ExperimentPlanStatus,
        structured_plan: Mapping[str, Any] | None,
        updated_by: str,
        updated_at: str,
        source_links: tuple[Mapping[str, str], ...] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ExperimentPlanRecord":
        return replace(
            self,
            plan_id=plan_id,
            title=title,
            content=content,
            status=status,
            plan_version=self.plan_version + 1,
            parent_plan_id=self.plan_id,
            structured_plan=(
                deepcopy(structured_plan)
                if structured_plan is not None
                else None
            ),
            updated_by=updated_by,
            updated_at=updated_at,
            source_links=deepcopy(self.source_links if source_links is None else source_links),
            metadata=deepcopy(self.metadata if metadata is None else metadata),
        )

__all__ = [
    "EXPERIMENT_PLAN_STATUSES",
    "ExperimentPlanRecord",
    "ExperimentPlanRevisionConflictError",
    "ExperimentPlanStatus",
]
