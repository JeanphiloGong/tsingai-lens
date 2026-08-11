from __future__ import annotations

from dataclasses import replace
from typing import Any

from application.pipeline.collection_build.config import CollectionBuildPipelineConfig
from application.pipeline.collection_build.context import CollectionBuildContext
from application.pipeline.collection_build.definitions import SOURCE_ARTIFACTS
from application.source.reference_extraction_service import (
    SourceReferenceExtractionService,
)
from infra.source.runtime.artifact_bundle import SourceArtifactBundle


async def build_source_artifacts(
    context: CollectionBuildContext,
    config: CollectionBuildPipelineConfig,
) -> dict[str, Any]:
    files = context.collection_service.list_files(context.collection_id)
    if not files:
        raise RuntimeError("集合内没有可构建文件")
    context.state["file_count"] = len(files)

    outputs = await context.build_source_artifacts(
        config=config.source,
        method=config.method,
        additional_context=config.source_additional_context,
        verbose=config.verbose,
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


def register_artifacts(
    context: CollectionBuildContext,
    config: CollectionBuildPipelineConfig,
) -> dict:
    artifacts = context.artifact_registry_service.register(
        context.task_id,
        context.collection_id,
        config.source.output.base_dir,
        build_id=context.build_id,
    )
    context.state["artifacts"] = artifacts
    return {"output_path": artifacts["output_path"]}


def build_document_profiles(
    context: CollectionBuildContext,
    _config: CollectionBuildPipelineConfig,
) -> dict:
    profiles = context.document_profile_service.build_document_profiles(
        context.collection_id,
        build_id=context.build_id,
    )
    return {"profile_count": len(profiles)}


def discover_and_replace_objective_candidates(
    context: CollectionBuildContext,
    _config: CollectionBuildPipelineConfig,
) -> None:
    context.research_objective_service.discover_and_replace_objective_candidates(
        context.collection_id,
        progress_callback=context.objective_progress_callback,
        build_id=context.build_id,
    )


def finalize(
    context: CollectionBuildContext,
    _config: CollectionBuildPipelineConfig,
) -> dict:
    task = context.task_service.get_task(context.task_id)
    node_states = task.get("pipeline_nodes", {})
    source_status = node_states.get(SOURCE_ARTIFACTS, {}).get("status")
    if source_status != "succeeded":
        status = "failed"
    elif any(state.get("status") == "failed" for state in node_states.values()):
        status = "partial_success"
    else:
        status = "completed"
    output_path = None
    artifacts = context.state.get("artifacts")
    if isinstance(artifacts, dict):
        output_path = artifacts.get("output_path")
    context.state["final_status"] = status
    return {"status": status, "output_path": output_path}
