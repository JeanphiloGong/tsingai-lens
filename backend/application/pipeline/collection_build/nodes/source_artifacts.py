from __future__ import annotations

from typing import Any

from application.pipeline.collection_build.context import CollectionBuildContext
from infra.source.runtime.artifact_bundle import SourceArtifactBundle


async def run(context: CollectionBuildContext) -> dict[str, Any]:
    build_source_artifacts = context.services["build_source_artifacts"]
    outputs = await build_source_artifacts(
        config=context.config,
        method=context.method,
        additional_context=context.additional_context,
        verbose=context.verbose,
    )
    errors = [str(err) for output in outputs for err in (output.errors or [])]
    if errors:
        raise RuntimeError("; ".join(errors))
    bundle = next(
        (
            output.result
            for output in reversed(outputs)
            if isinstance(output.result, SourceArtifactBundle)
        ),
        None,
    )
    if bundle is None:
        raise RuntimeError("Source pipeline did not return an artifact bundle")
    artifacts = bundle.to_artifact_set()
    context.source_artifact_repository.replace_collection_artifacts(
        context.collection_id,
        context.build_id,
        artifacts,
    )
    context.source_reference_repository.replace_collection_figures(
        context.collection_id,
        artifacts.figures,
    )
    return {
        "document_count": len(artifacts.documents),
        "table_count": len(artifacts.tables),
        "figure_count": len(artifacts.figures),
    }
