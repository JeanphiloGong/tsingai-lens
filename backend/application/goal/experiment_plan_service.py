from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Mapping

from domain.goal import ExperimentPlanRecord
from domain.ports import ExperimentPlanRepository
from infra.persistence.factory import build_experiment_plan_repository


class ExperimentPlanNotFoundError(FileNotFoundError):
    def __init__(self, collection_id: str, goal_id: str, plan_id: str) -> None:
        self.collection_id = collection_id
        self.goal_id = goal_id
        self.plan_id = plan_id
        super().__init__(f"experiment plan not found: {plan_id}")


class ExperimentPlanService:
    """Manage human-editable experiment plan drafts produced from goal chat."""

    def __init__(self, repository: ExperimentPlanRepository | None = None) -> None:
        self.repository = repository or build_experiment_plan_repository()

    def create_plan(
        self,
        *,
        collection_id: str,
        goal_id: str,
        title: str,
        content: str,
        source_message_id: str | None = None,
        source_links: list[Mapping[str, Any]] | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_by: str | None = None,
    ) -> ExperimentPlanRecord:
        now = _now_iso()
        plan = ExperimentPlanRecord.from_mapping(
            {
                "plan_id": _plan_id(
                    collection_id,
                    goal_id,
                    title,
                    content,
                    source_message_id,
                    now,
                ),
                "collection_id": collection_id,
                "goal_id": goal_id,
                "title": title,
                "content": content,
                "status": "draft",
                "source_message_id": source_message_id,
                "source_links": list(source_links or []),
                "metadata": dict(metadata or {}),
                "created_by": created_by,
                "created_at": now,
                "updated_at": now,
            }
        )
        return self.repository.upsert_plan(plan)

    def list_plans(
        self,
        collection_id: str,
        goal_id: str,
    ) -> tuple[ExperimentPlanRecord, ...]:
        return self.repository.list_plans(collection_id, goal_id)

    def update_plan(
        self,
        *,
        collection_id: str,
        goal_id: str,
        plan_id: str,
        title: str,
        content: str,
        status: str,
    ) -> ExperimentPlanRecord:
        plan = self.repository.read_plan(collection_id, goal_id, plan_id)
        if plan is None:
            raise ExperimentPlanNotFoundError(collection_id, goal_id, plan_id)
        updated = plan.with_updates(
            title=title,
            content=content,
            status=status,
            updated_at=_now_iso(),
        )
        return self.repository.upsert_plan(updated)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_id(*parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return "exp_" + sha1(payload.encode("utf-8")).hexdigest()[:16]
