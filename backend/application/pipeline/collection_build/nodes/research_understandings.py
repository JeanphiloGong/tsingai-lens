from __future__ import annotations

from application.pipeline.collection_build.context import CollectionBuildContext


def run(context: CollectionBuildContext) -> dict:
    objective_understandings = context.services[
        "research_objective_service"
    ].persist_objective_understandings(context.collection_id)
    material_understandings = context.services[
        "research_view_aggregation_service"
    ].persist_material_understandings(context.collection_id)
    return {
        "objective_understanding_count": len(objective_understandings),
        "material_understanding_count": len(material_understandings),
    }
