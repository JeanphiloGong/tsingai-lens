from __future__ import annotations

from application.core.confirmed_goal_service import ConfirmedGoalService
from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveService,
)
from application.pipeline.goal_analysis.context import GoalAnalysisContext
from application.pipeline.goal_analysis.definitions import (
    ANALYZE_GOAL,
    FINALIZE_GOAL,
    PREPARE_GOAL,
)
from application.pipeline.goal_analysis.nodes import (
    analyze_goal,
    finalize_goal,
    prepare_goal,
)
from application.pipeline.goal_analysis.runner import GoalAnalysisPipelineRunner


class GoalAnalysisPipelineService:
    """Application service for confirmed-goal deep analysis."""

    def __init__(
        self,
        confirmed_goal_service: ConfirmedGoalService | None = None,
        research_objective_service: ResearchObjectiveService | None = None,
    ) -> None:
        self.confirmed_goal_service = confirmed_goal_service or ConfirmedGoalService()
        self.research_objective_service = (
            research_objective_service or ResearchObjectiveService()
        )

    async def run_goal_analysis(self, collection_id: str, goal_id: str) -> dict:
        self.confirmed_goal_service.update_goal_status(
            collection_id=collection_id,
            goal_id=goal_id,
            status="running",
            analysis_error=None,
        )
        context = GoalAnalysisContext(
            collection_id=collection_id,
            goal_id=goal_id,
            services={
                "confirmed_goal_service": self.confirmed_goal_service,
                "research_objective_service": self.research_objective_service,
            },
        )
        result = await self._build_runner().run(context)
        if result["errors"]:
            goal = self.confirmed_goal_service.update_goal_status(
                collection_id=collection_id,
                goal_id=goal_id,
                status="failed",
                analysis_error="; ".join(result["errors"]),
            )
        else:
            goal = self.confirmed_goal_service.update_goal_status(
                collection_id=collection_id,
                goal_id=goal_id,
                status="ready",
                analysis_error=None,
            )
        return {
            "goal": goal,
            "understanding": context.state.get("understanding"),
            "pipeline_nodes": result["pipeline_nodes"],
            "errors": result["errors"],
            "warnings": result["warnings"],
        }

    def get_goal_analysis(self, collection_id: str, goal_id: str) -> dict:
        goal = self.confirmed_goal_service.get_goal(collection_id, goal_id)
        understanding = self.confirmed_goal_service.get_goal_understanding(
            collection_id,
            goal_id,
        )
        return {
            "goal": goal,
            "understanding": understanding,
            "pipeline_nodes": {},
            "errors": [goal.analysis_error] if goal.analysis_error else [],
            "warnings": [],
        }

    def _build_runner(self) -> GoalAnalysisPipelineRunner:
        return GoalAnalysisPipelineRunner(
            {
                PREPARE_GOAL: prepare_goal.run,
                ANALYZE_GOAL: analyze_goal.run,
                FINALIZE_GOAL: finalize_goal.run,
            }
        )
