from __future__ import annotations

from typing import Any

from domain.core import ConfirmedGoal, ResearchObjective, ResearchUnderstanding
from domain.ports import CoreFactRepository
from infra.persistence.factory import build_core_fact_repository


class ConfirmedGoalNotFoundError(FileNotFoundError):
    def __init__(self, collection_id: str, goal_id: str) -> None:
        self.collection_id = collection_id
        self.goal_id = goal_id
        super().__init__(f"confirmed goal not found: {goal_id}")


class ConfirmedGoalService:
    """Manage user- or benchmark-confirmed research questions."""

    def __init__(self, repository: CoreFactRepository | None = None) -> None:
        self.repository = repository or build_core_fact_repository()

    def create_goal(
        self,
        *,
        collection_id: str,
        question: str,
        source_type: str = "user_input",
        material_hints: list[str] | tuple[str, ...] = (),
        process_hints: list[str] | tuple[str, ...] = (),
        property_hints: list[str] | tuple[str, ...] = (),
        source_objective_id: str | None = None,
    ) -> ConfirmedGoal:
        payload = {
            "collection_id": collection_id,
            "question": question,
            "source_type": source_type,
            "material_hints": material_hints,
            "process_hints": process_hints,
            "property_hints": property_hints,
            "source_objective_id": source_objective_id,
            "status": "pending",
        }
        if source_objective_id:
            objective = self._find_objective(collection_id, source_objective_id)
            if objective is not None:
                payload.update(
                    {
                        "question": question or objective.question,
                        "material_hints": material_hints or objective.material_scope,
                        "process_hints": process_hints or objective.process_axes,
                        "property_hints": property_hints or objective.property_axes,
                    }
                )
        return self.repository.upsert_confirmed_goal(
            ConfirmedGoal.from_mapping(payload)
        )

    def list_goals(self, collection_id: str) -> tuple[ConfirmedGoal, ...]:
        return self.repository.list_confirmed_goals(collection_id)

    def get_goal(self, collection_id: str, goal_id: str) -> ConfirmedGoal:
        goal = self.repository.read_confirmed_goal(collection_id, goal_id)
        if goal is None:
            raise ConfirmedGoalNotFoundError(collection_id, goal_id)
        return goal

    def update_goal_status(
        self,
        *,
        collection_id: str,
        goal_id: str,
        status: str,
        analysis_error: str | None = None,
        analysis_progress: dict[str, Any] | None = None,
    ) -> ConfirmedGoal:
        goal = self.get_goal(collection_id, goal_id)
        payload = {
            **goal.to_record(),
            "status": status,
            "analysis_error": analysis_error,
            "analysis_progress": analysis_progress,
            "updated_at": None,
        }
        return self.repository.upsert_confirmed_goal(
            ConfirmedGoal.from_mapping(payload)
        )

    def update_goal_progress(
        self,
        *,
        collection_id: str,
        goal_id: str,
        analysis_progress: dict[str, Any],
    ) -> ConfirmedGoal:
        goal = self.get_goal(collection_id, goal_id)
        payload = {
            **goal.to_record(),
            "analysis_progress": analysis_progress,
            "updated_at": None,
        }
        return self.repository.upsert_confirmed_goal(
            ConfirmedGoal.from_mapping(payload)
        )

    def get_goal_understanding(
        self,
        collection_id: str,
        goal_id: str,
    ) -> ResearchUnderstanding | None:
        return self.repository.read_research_understanding(
            collection_id,
            "goal",
            goal_id,
        )

    def _find_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective | None:
        facts = self.repository.read_collection_facts(collection_id)
        for objective in facts.research_objectives:
            if objective.objective_id == objective_id:
                return objective
        return None
