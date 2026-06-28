from __future__ import annotations

from application.pipeline.collection_build.context import CollectionBuildContext


def run(context: CollectionBuildContext) -> dict:
    artifacts = context.artifact_registry_service.upsert(
        context.collection_id,
        context.output_dir,
    )
    context.state["artifacts"] = artifacts
    return {"output_path": artifacts["output_path"]}
