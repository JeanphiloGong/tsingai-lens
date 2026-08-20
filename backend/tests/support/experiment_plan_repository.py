from __future__ import annotations

from domain.goal import ExperimentPlanRecord


class InMemoryExperimentPlanRepository:
    def __init__(self) -> None:
        self.plans: dict[str, ExperimentPlanRecord] = {}

    def upsert_plan(self, plan: ExperimentPlanRecord) -> ExperimentPlanRecord:
        existing = self.plans.get(plan.plan_id)
        if existing is not None and (
            existing.collection_id != plan.collection_id
            or existing.objective_id != plan.objective_id
        ):
            raise ValueError("experiment plan identity cannot be reassigned")
        self.plans[plan.plan_id] = plan
        return plan

    def read_plan(
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

    def list_plans(
        self,
        collection_id: str,
        objective_id: str,
    ) -> tuple[ExperimentPlanRecord, ...]:
        return tuple(
            plan
            for plan in self.plans.values()
            if plan.collection_id == collection_id
            and plan.objective_id == objective_id
        )


__all__ = ["InMemoryExperimentPlanRepository"]
