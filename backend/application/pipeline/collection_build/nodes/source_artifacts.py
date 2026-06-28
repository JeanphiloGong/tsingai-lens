from __future__ import annotations

from typing import Any

from application.pipeline.collection_build.context import CollectionBuildContext


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
    return {"outputs": outputs}
