from __future__ import annotations

from typing import Protocol

from domain.goal import ExperimentPlanRecord


class ExperimentPlanRepository(Protocol):
    async def upsert_plan(
        self, plan: ExperimentPlanRecord
    ) -> ExperimentPlanRecord: ...

    async def append_plan_revision(
        self, plan: ExperimentPlanRecord
    ) -> ExperimentPlanRecord: ...

    async def read_plan(
        self,
        collection_id: str,
        objective_id: str,
        plan_id: str,
    ) -> ExperimentPlanRecord | None: ...

    async def list_plans(
        self,
        collection_id: str,
        objective_id: str,
    ) -> tuple[ExperimentPlanRecord, ...]: ...
