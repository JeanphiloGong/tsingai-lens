from __future__ import annotations

from application.pipeline.goal_analysis.context import GoalAnalysisContext

_REVIEW_ONLY_WARNING = (
    "goal analysis produced review candidates but no primary research findings"
)
_NO_RESEARCH_FINDINGS_ERROR = "goal analysis produced no research findings"


def run(context: GoalAnalysisContext) -> dict:
    understanding = context.state.get("understanding")
    if understanding is None:
        raise RuntimeError("goal analysis did not produce research understanding")
    presentation = getattr(understanding, "presentation", {}) or {}
    if isinstance(understanding, dict):
        presentation = understanding.get("presentation") or {}
    if not _has_research_findings(presentation) and (
        research_understanding_service := context.services.get(
            "research_understanding_service"
        )
    ) is not None:
        understanding = research_understanding_service.with_presentation(understanding)
        context.state["understanding"] = understanding
        presentation = getattr(understanding, "presentation", {}) or {}
        if isinstance(understanding, dict):
            presentation = understanding.get("presentation") or {}
    if not _has_research_findings(presentation):
        raise RuntimeError(_NO_RESEARCH_FINDINGS_ERROR)
    result = {
        "goal_id": context.goal_id,
        "status": "ready",
    }
    if not presentation.get("primary_findings"):
        result["warnings"] = [_REVIEW_ONLY_WARNING]
    return result


def _has_research_findings(presentation: dict) -> bool:
    return bool(
        presentation.get("primary_findings")
        or presentation.get("review_queue_findings")
    )
