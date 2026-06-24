from __future__ import annotations

from application.pipeline.goal_analysis.context import GoalAnalysisContext


def run(context: GoalAnalysisContext) -> dict:
    goal = context.services["confirmed_goal_service"].get_goal(
        context.collection_id,
        context.goal_id,
    )
    context.state["goal"] = goal
    return {"goal_id": goal.goal_id}
