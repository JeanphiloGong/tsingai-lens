from __future__ import annotations

from domain.goal import (
    ExperimentPlanRecord,
    ExperimentPlanRevisionConflictError,
)


class InMemoryExperimentPlanRepository:
    def __init__(self) -> None:
        self.plans: dict[str, ExperimentPlanRecord] = {}

    async def upsert_plan(self, plan: ExperimentPlanRecord) -> ExperimentPlanRecord:
        existing = self.plans.get(plan.plan_id)
        if existing is not None:
            if existing == plan:
                return existing
            raise ExperimentPlanRevisionConflictError(
                "experiment plan revisions are immutable"
            )
        if plan.parent_plan_id is not None:
            raise ValueError("use append_plan_revision for a successor revision")
        self.plans[plan.plan_id] = plan
        return plan

    async def append_plan_revision(
        self, plan: ExperimentPlanRecord
    ) -> ExperimentPlanRecord:
        parent = self.plans.get(plan.parent_plan_id or "")
        if parent is None:
            raise ValueError("experiment plan parent revision was not found")
        _validate_successor(parent, plan)
        if plan.plan_id in self.plans:
            raise ExperimentPlanRevisionConflictError(
                "experiment plan revision identity already exists"
            )
        if any(
            item.parent_plan_id == parent.plan_id for item in self.plans.values()
        ):
            raise ExperimentPlanRevisionConflictError(
                "experiment plan revision has already been superseded"
            )
        self.plans[plan.plan_id] = plan
        return plan

    async def read_plan(
        self,
        collection_id: str,
        objective_id: str,
        plan_id: str,
    ) -> ExperimentPlanRecord | None:
        plan = self.plans.get(plan_id)
        if plan is None:
            return None
        if plan.collection_id != collection_id or plan.objective_id != objective_id:
            return None
        return plan

    async def list_plans(
        self,
        collection_id: str,
        objective_id: str,
    ) -> tuple[ExperimentPlanRecord, ...]:
        parent_ids = {
            plan.parent_plan_id
            for plan in self.plans.values()
            if plan.parent_plan_id is not None
        }
        return tuple(
            plan
            for plan in self.plans.values()
            if plan.collection_id == collection_id
            and plan.objective_id == objective_id
            and plan.plan_id not in parent_ids
        )


def _validate_successor(
    parent: ExperimentPlanRecord,
    successor: ExperimentPlanRecord,
) -> None:
    if (
        successor.parent_plan_id != parent.plan_id
        or successor.collection_id != parent.collection_id
        or successor.objective_id != parent.objective_id
        or successor.plan_version != parent.plan_version + 1
        or successor.created_by != parent.created_by
        or successor.created_at != parent.created_at
    ):
        raise ValueError("experiment plan revision does not continue its parent")


__all__ = ["InMemoryExperimentPlanRepository"]
