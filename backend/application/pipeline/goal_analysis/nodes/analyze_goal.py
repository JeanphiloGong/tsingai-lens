from __future__ import annotations

from application.pipeline.goal_analysis.context import GoalAnalysisContext


def run(context: GoalAnalysisContext) -> dict:
    goal = context.state["goal"]
    understanding = context.services[
        "research_objective_service"
    ].analyze_confirmed_goal(goal)
    context.state["understanding"] = understanding
    return {
        "goal_id": goal.goal_id,
        "claim_count": len(understanding.claims),
        "relation_count": len(understanding.relations),
        "evidence_ref_count": len(understanding.evidence_refs),
    }
