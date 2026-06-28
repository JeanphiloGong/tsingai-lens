from __future__ import annotations

import logging
from typing import Any

from application.core.confirmed_goal_service import (
    ConfirmedGoalNotFoundError,
    ConfirmedGoalService,
)
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

logger = logging.getLogger(__name__)

_GOAL_PROGRESS_UPDATE_INTERVAL = 3


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
        context = GoalAnalysisContext(
            collection_id=collection_id,
            goal_id=goal_id,
            services={},
        )
        try:
            self.confirmed_goal_service.update_goal_status(
                collection_id=collection_id,
                goal_id=goal_id,
                status="running",
                analysis_error=None,
                analysis_progress={
                    "phase": "goal_analysis_started",
                    "unit": "steps",
                    "message": "Goal analysis has started.",
                },
            )
            context.services.update(
                {
                    "confirmed_goal_service": self.confirmed_goal_service,
                    "research_objective_service": self.research_objective_service,
                    "goal_progress_callback": self._build_goal_progress_callback(
                        collection_id,
                        goal_id,
                    ),
                }
            )
            result = await self._build_runner().run(context)
            if result["errors"]:
                goal = self.confirmed_goal_service.update_goal_status(
                    collection_id=collection_id,
                    goal_id=goal_id,
                    status="failed",
                    analysis_error="; ".join(result["errors"]),
                    analysis_progress={
                        "phase": "failed",
                        "unit": "steps",
                        "message": "Goal analysis failed.",
                    },
                )
            else:
                goal = self.confirmed_goal_service.update_goal_status(
                    collection_id=collection_id,
                    goal_id=goal_id,
                    status="ready",
                    analysis_error=None,
                    analysis_progress={
                        "phase": "completed",
                        "unit": "steps",
                        "message": "Goal analysis is ready.",
                    },
                )
            return {
                "goal": goal,
                "understanding": context.state.get("understanding"),
                "pipeline_nodes": result["pipeline_nodes"],
                "errors": result["errors"],
                "warnings": result["warnings"],
            }
        except (ConfirmedGoalNotFoundError, FileNotFoundError):
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Goal analysis failed collection_id=%s goal_id=%s",
                collection_id,
                goal_id,
            )
            goal = self.confirmed_goal_service.update_goal_status(
                collection_id=collection_id,
                goal_id=goal_id,
                status="failed",
                analysis_error=str(exc),
                analysis_progress={
                    "phase": "failed",
                    "unit": "steps",
                    "message": "Goal analysis failed.",
                },
            )
            return {
                "goal": goal,
                "understanding": context.state.get("understanding"),
                "pipeline_nodes": {},
                "errors": [str(exc)],
                "warnings": [],
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

    def start_goal_analysis(self, collection_id: str, goal_id: str) -> dict:
        goal = self.confirmed_goal_service.get_goal(collection_id, goal_id)
        if goal.status == "running":
            return self.get_goal_analysis(collection_id, goal_id)
        self.confirmed_goal_service.update_goal_status(
            collection_id=collection_id,
            goal_id=goal_id,
            status="running",
            analysis_error=None,
            analysis_progress={
                "phase": "queued",
                "unit": "steps",
                "message": "Goal analysis is queued.",
            },
        )
        return self.get_goal_analysis(collection_id, goal_id)

    def _build_runner(self) -> GoalAnalysisPipelineRunner:
        return GoalAnalysisPipelineRunner(
            {
                PREPARE_GOAL: prepare_goal.run,
                ANALYZE_GOAL: analyze_goal.run,
                FINALIZE_GOAL: finalize_goal.run,
            }
        )

    def _build_goal_progress_callback(self, collection_id: str, goal_id: str):
        last_update: dict[str, tuple[str, int | None, int | None]] = {
            "value": ("", None, None),
        }

        def callback(progress_detail: dict[str, Any]) -> None:
            phase = str(progress_detail.get("phase") or "").strip()
            if not phase:
                return
            current = self._safe_int(progress_detail.get("current"))
            total = self._safe_int(progress_detail.get("total"))
            previous_phase, previous_current, previous_total = last_update["value"]
            should_update = (
                phase != previous_phase
                or total != previous_total
                or current is None
                or total is None
                or current == 1
                or current >= total
                or previous_current is None
                or current - previous_current >= _GOAL_PROGRESS_UPDATE_INTERVAL
            )
            if not should_update:
                return
            last_update["value"] = (phase, current, total)
            goal = self.confirmed_goal_service.update_goal_progress(
                collection_id=collection_id,
                goal_id=goal_id,
                analysis_progress=progress_detail,
            )
            logger.info(
                "Goal analysis progress collection_id=%s goal_id=%s phase=%s status=%s",
                collection_id,
                goal_id,
                phase,
                goal.status,
            )

        return callback

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
