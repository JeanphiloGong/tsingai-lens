from __future__ import annotations

from application.pipeline.collection_build.context import CollectionBuildContext


def run(context: CollectionBuildContext) -> dict:
    progress_callback = context.services.get("objective_progress_callback")
    objectives = context.services["research_objective_service"].build_research_objectives(
        context.collection_id,
        progress_callback=progress_callback,
    )
    return {"objective_count": len(objectives)}
