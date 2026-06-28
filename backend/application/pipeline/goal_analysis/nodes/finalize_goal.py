from __future__ import annotations

from application.pipeline.goal_analysis.context import GoalAnalysisContext


def run(context: GoalAnalysisContext) -> dict:
    understanding = context.state.get("understanding")
    return {
        "goal_id": context.goal_id,
        "status": "ready" if understanding is not None else "failed",
    }
