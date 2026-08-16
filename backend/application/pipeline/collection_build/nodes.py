from __future__ import annotations

from dataclasses import replace
from typing import Any

from application.pipeline.collection_build.config import CollectionBuildPipelineConfig
from application.pipeline.collection_build.context import CollectionBuildContext
from application.source.reference_extraction_service import (
    SourceReferenceExtractionService,
)
from domain.core import PaperSourceUnitCoverageStatus
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
        method=config.mode,
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
    documents = bundle.to_documents()
    persisted_documents = []
    referenced_assets: set[str] = set()
    for document in documents:
        figures = []
        for figure in document.figures:
            image_path = str(figure.image_path or "").strip()
            if not image_path:
                figures.append(figure)
                continue
            payload = bundle.figure_assets.get(image_path)
            if payload is None or not figure.asset_sha256:
                raise RuntimeError(
                    f"Source figure asset is incomplete: {figure.figure_id}"
                )
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
        persisted_documents.append(
            replace(document, figures=tuple(figures))
        )
    unreferenced_assets = set(bundle.figure_assets) - referenced_assets
    if unreferenced_assets:
        raise RuntimeError(
            "Source figure assets have no metadata rows: "
            + ", ".join(sorted(unreferenced_assets))
        )
    documents = tuple(persisted_documents)
    context.source_artifact_repository.replace_collection_documents(
        context.collection_id,
        context.build_id,
        documents,
    )
    references = SourceReferenceExtractionService().extract(documents)
    context.source_artifact_repository.replace_collection_references(
        context.collection_id,
        context.build_id,
        references,
    )
    return {
        "document_count": len(documents),
        "table_count": sum(len(document.tables) for document in documents),
        "figure_count": sum(len(document.figures) for document in documents),
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
) -> dict[str, Any]:
    facts = context.research_objective_service.discover_and_replace_objective_candidates(
        context.collection_id,
        progress_callback=context.objective_progress_callback,
        build_id=context.build_id,
    )
    coverage = tuple(
        item
        for paper_skim in facts.paper_skims
        for item in paper_skim.source_unit_coverage
    )
    failed_count = sum(
        item.status == PaperSourceUnitCoverageStatus.EXTRACTION_FAILED
        for item in coverage
    )
    warnings = []
    if failed_count:
        unit = "unit" if failed_count == 1 else "units"
        warnings.append(
            f"{failed_count} PaperSkim Source {unit} failed extraction permanently; "
            "candidate objectives were built from the remaining coverage."
        )
    return {
        "objective_candidate_count": len(facts.research_objectives),
        "paper_skim_count": len(facts.paper_skims),
        "source_unit_count": len(coverage),
        "extraction_failed_source_unit_count": failed_count,
        "warnings": warnings,
    }
