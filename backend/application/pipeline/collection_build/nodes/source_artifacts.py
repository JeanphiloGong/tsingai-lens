from __future__ import annotations

from dataclasses import replace
from typing import Any

from application.pipeline.collection_build.context import CollectionBuildContext
from application.source.reference_extraction_service import (
    SourceReferenceExtractionService,
)
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
    figures = []
    referenced_assets: set[str] = set()
    for figure in artifacts.figures:
        image_path = str(figure.image_path or "").strip()
        if not image_path:
            figures.append(figure)
            continue
        payload = bundle.figure_assets.get(image_path)
        if payload is None or not figure.asset_sha256:
            raise RuntimeError(f"Source figure asset is incomplete: {figure.figure_id}")
        referenced_assets.add(image_path)
        storage_key = context.collection_service.write_figure_asset(
            context.collection_id,
            context.build_id,
            image_path,
            payload,
            figure.asset_sha256,
        )
        figures.append(
            replace(
                figure,
                image_path=storage_key,
                image_size_bytes=len(payload),
            )
        )
    unreferenced_assets = set(bundle.figure_assets) - referenced_assets
    if unreferenced_assets:
        raise RuntimeError(
            "Source figure assets have no metadata rows: "
            + ", ".join(sorted(unreferenced_assets))
        )
    artifacts = replace(artifacts, figures=tuple(figures))
    context.source_artifact_repository.replace_collection_artifacts(
        context.collection_id,
        context.build_id,
        artifacts,
    )
    references = SourceReferenceExtractionService().extract(artifacts)
    context.source_artifact_repository.replace_collection_references(
        context.collection_id,
        context.build_id,
        references,
    )
    return {
        "document_count": len(artifacts.documents),
        "table_count": len(artifacts.tables),
        "figure_count": len(artifacts.figures),
    }
