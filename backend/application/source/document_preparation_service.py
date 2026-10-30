"""Prepare one document for later collection-level research work."""

from __future__ import annotations

import json
import logging
import os
from asyncio import CancelledError, Semaphore
from asyncio import Task as AsyncTask
from asyncio import create_task
from dataclasses import replace
from hashlib import sha256 as hash_sha256
from pathlib import Path
from typing import Any, Awaitable, Callable

import pandas as pd
from application.core.document_profiles import service as document_profile_service
from application.core.document_profiles.extraction import (
    DOCUMENT_PROFILE_PROMPT_VERSION,
)
from application.pipeline import pipeline_run_service
from application.pipeline.pipeline_run_service import document_preparation_error_message
from application.source import collection_service
from application.source import (
    reference_extraction_service as source_reference_extraction_service,
)
from domain.core.document_profile import PROFILE_STATUS_COMPLETED
from domain.source import Document, SourceDocument
from exceptions import ResourceNotFoundException, ServiceUnavailableException
from infra.source.artifact_bundle import SourceArtifactBundle
from infra.source.config.source_parser_config import (
    InputConfig,
    InputStorageConfig,
    SourceParserConfig,
    StorageConfig,
)
from repositories.collection_repository import StoredDocument
from repositories.document_profile_repository import DocumentProfileRepo

logger = logging.getLogger(__name__)

SOURCE_PARSER_VERSION = "source-runtime.v1"
DOCUMENT_ANALYSIS_VERSION = DOCUMENT_PROFILE_PROMPT_VERSION
# Keep database-backed preparation below the default PostgreSQL pool capacity.
# Status polling and run finalization need connections while workers parse papers.
_DEFAULT_PREPARATION_CONCURRENCY = 3

SourceArtifactBuilder = Callable[..., Awaitable[SourceArtifactBundle]]


def _stage_fingerprint(stage: str, **values: str) -> str:
    payload = json.dumps(
        {"stage": stage, **values},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hash_sha256(payload.encode("utf-8")).hexdigest()


def source_fingerprint(
    *,
    sha256: str,
    parser_version: str,
) -> str:
    return _stage_fingerprint(
        "source",
        document_sha256=str(sha256),
        parser_version=str(parser_version),
    )


def profile_fingerprint(
    *,
    source_fingerprint: str,
    profile_version: str,
) -> str:
    return _stage_fingerprint(
        "profile",
        source_fingerprint=str(source_fingerprint),
        profile_version=str(profile_version),
    )


from repositories.source_artifact_repository import SourceArtifactRepo

_source_artifact_builder = None
_semaphore = Semaphore(
    int(
        os.getenv(
            "DOCUMENT_PREPARATION_MAX_CONCURRENCY",
            str(_DEFAULT_PREPARATION_CONCURRENCY),
        )
    )
)
_active_workers: set[AsyncTask[dict[str, Any]]] = set()


async def recover_interrupted_runs() -> int:
    """Make persisted work without a live worker retryable after restart."""

    active_runs = await pipeline_run_service.list_interrupted_runs()
    interrupted_count = 0
    for run in active_runs:
        if run.get("pipeline_name") != "document_preparation":
            continue
        if run.get("scope_type") != "document":
            continue
        document_id = str(run["scope_id"])
        try:
            document = await collection_service.get_document(
                run["collection_id"],
                document_id,
            )
        except ResourceNotFoundException:
            document = None
        if document is not None and document.document.status == "processing":
            await collection_service.update_document_preparation(
                run["collection_id"],
                document_id,
                status="stored",
            )
        await pipeline_run_service.finish_run(
            run["run_id"],
            status="failed",
            current_node="interrupted",
            progress_percent=run.get("progress_percent", 0),
            errors=[
                *run.get("errors", ()),
                "Document preparation was interrupted by a backend restart.",
            ],
        )
        interrupted_count += 1
    if interrupted_count:
        logger.warning(
            "Recovered interrupted document preparation runs count=%s",
            interrupted_count,
        )
    return interrupted_count


async def queue_document_preparation(
    collection_id: str,
    document_id: str,
    *,
    user_id: str,
) -> dict[str, Any]:
    """Queue or reuse preparation of one collection document."""

    await collection_service.get_collection_for_user(collection_id, user_id)

    document = await collection_service.get_document(
        collection_id,
        document_id,
    )
    fingerprint = preparation_fingerprint_for(document.document)
    run, created = await pipeline_run_service.get_or_create_document_run(
        collection_id=collection_id,
        document_id=document_id,
        pipeline_name="document_preparation",
        input_fingerprint=fingerprint,
        reuse_completed=await _can_reuse_preparation(collection_id, document),
    )
    if created:
        coroutine = run_document_preparation(
            run["run_id"],
            collection_id,
            document_id,
        )
        try:
            background = create_task(coroutine)
        except Exception as exc:
            coroutine.close()
            logger.exception(
                "Document preparation dispatch failed run_id=%s", run["run_id"]
            )
            await _fail_preparation(
                run["run_id"], collection_id, document_id, "dispatch_failed"
            )
            raise ServiceUnavailableException(
                document_preparation_error_message("dispatch_failed"),
                data={
                    "code": "document_preparation_dispatch_failed",
                    "run_id": run["run_id"],
                    "collection_id": collection_id,
                    "document_id": document_id,
                },
            ) from exc
        _active_workers.add(background)
        background.add_done_callback(_active_workers.discard)
        background.add_done_callback(_log_unexpected_failure)
    return run


async def _can_reuse_preparation(collection_id: str, record: StoredDocument) -> bool:
    document = record.document
    source_identity, profile_identity = fingerprints_for(document)
    if (
        document.status != "ready"
        or document.preparation_fingerprint != profile_identity
        or document.profile_fingerprint != profile_identity
        or document.source_fingerprint != source_identity
    ):
        return False
    profile = await DocumentProfileRepo.read(
        collection_id,
        document.document_id,
    )
    if profile is None or profile.profile_status != PROFILE_STATUS_COMPLETED:
        return False
    return (
        await SourceArtifactRepo.read_document(
            collection_id,
            document.document_id,
        )
        is not None
    )


async def run_document_preparation(
    run_id: str,
    collection_id: str,
    document_id: str,
) -> dict[str, Any]:
    async with _semaphore:
        stage = "source_parsing"
        preparation_warnings: list[str] = []
        try:
            record = await collection_service.get_document(collection_id, document_id)
            document = record.document
            source_identity, profile_identity = fingerprints_for(document)
            fingerprint = profile_identity
            await pipeline_run_service.update_run(
                run_id,
                status="running",
                current_node=stage,
                progress_percent=5,
                progress_detail={
                    "phase": stage,
                    "unit": "document",
                    "message": "Parsing the document into traceable Sources.",
                },
            )
            await collection_service.update_document_preparation(
                collection_id,
                document_id,
                status="processing",
            )
            source_document = await SourceArtifactRepo.read_document(
                collection_id,
                document_id,
            )
            if (
                source_document is None
                or document.source_fingerprint != source_identity
            ):
                source_document = await _parse_document(
                    collection_id,
                    record,
                )
                source_document = replace(
                    source_document,
                    metadata={
                        **source_document.metadata,
                        "parser_version": SOURCE_PARSER_VERSION,
                        "source_fingerprint": source_identity,
                    },
                )
                await SourceArtifactRepo.replace_document(
                    collection_id,
                    source_document,
                )
                try:
                    references = source_reference_extraction_service.extract(
                        (source_document,)
                    )
                    await SourceArtifactRepo.replace_document_references(
                        document_id,
                        references,
                    )
                except Exception:  # noqa: BLE001
                    warning = (
                        "Source reference extraction failed; Source remains available."
                    )
                    preparation_warnings.append(warning)
                    logger.warning(
                        "Source reference extraction failed collection_id=%s document_id=%s",
                        collection_id,
                        document_id,
                        exc_info=True,
                    )
                record = await collection_service.update_document_preparation(
                    collection_id,
                    document_id,
                    status="processing",
                    source_fingerprint=source_identity,
                    parser_version=SOURCE_PARSER_VERSION,
                )
                document = record.document
            stage = "document_profile"
            await pipeline_run_service.update_run(
                run_id,
                current_node="document_profile",
                progress_percent=45,
                progress_detail={
                    "phase": "document_profile",
                    "unit": "document",
                    "message": "Classifying the paper for research triage.",
                },
            )
            profile = await DocumentProfileRepo.read(collection_id, document_id)
            if (
                profile is None
                or document.profile_fingerprint != profile_identity
                or profile.profile_status != PROFILE_STATUS_COMPLETED
            ):
                profile = await document_profile_service.build_document_profile(
                    collection_id,
                    document_id,
                    source_fingerprint=source_identity,
                    profile_fingerprint=profile_identity,
                )
            if profile.profile_status != PROFILE_STATUS_COMPLETED:
                await collection_service.update_document_preparation(
                    collection_id,
                    document_id,
                    status="stored",
                )
                message = document_preparation_error_message("document_profile")
                return await pipeline_run_service.finish_run(
                    run_id,
                    status="partial_success",
                    current_node="document_profile",
                    warnings=[*preparation_warnings, message],
                    errors=[message],
                    progress_detail={
                        "phase": "document_profile",
                        "unit": "document",
                        "message": message,
                    },
                )
            await collection_service.update_document_preparation(
                collection_id,
                document_id,
                status="ready",
                preparation_fingerprint=fingerprint,
                source_fingerprint=source_identity,
                profile_fingerprint=profile_identity,
                parser_version=SOURCE_PARSER_VERSION,
                document_analysis_version=DOCUMENT_ANALYSIS_VERSION,
            )
            return await pipeline_run_service.finish_run(
                run_id,
                status="completed",
                current_node="ready",
                progress_percent=100,
                progress_detail={
                    "phase": "ready",
                    "unit": "document",
                    "message": "The document is ready for research scope selection.",
                },
                warnings=preparation_warnings,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Document preparation failed collection_id=%s document_id=%s run_id=%s",
                collection_id,
                document_id,
                run_id,
            )
            await _fail_preparation(run_id, collection_id, document_id, stage)
            raise


async def _fail_preparation(
    run_id: str,
    collection_id: str,
    document_id: str,
    stage: str,
) -> None:
    # A failed document write must not prevent terminalizing its run.
    try:
        await collection_service.update_document_preparation(
            collection_id,
            document_id,
            status="failed",
        )
    except Exception:
        logger.exception(
            "Could not record document preparation failure run_id=%s", run_id
        )
    try:
        await pipeline_run_service.finish_run(
            run_id,
            status="failed",
            current_node=stage,
            errors=[document_preparation_error_message(stage)],
            progress_detail={
                "phase": "failed",
                "unit": "document",
                "message": document_preparation_error_message(stage),
            },
        )
    except Exception:
        logger.exception(
            "Could not terminalize failed document preparation run_id=%s", run_id
        )


def preparation_fingerprint_for(document: Document) -> str:
    return fingerprints_for(document)[1]


def fingerprints_for(document: Document) -> tuple[str, str]:
    source_identity = source_fingerprint(
        sha256=document.sha256,
        parser_version=SOURCE_PARSER_VERSION,
    )
    profile_identity = profile_fingerprint(
        source_fingerprint=source_identity,
        profile_version=DOCUMENT_PROFILE_PROMPT_VERSION,
    )
    return source_identity, profile_identity


async def _parse_document(
    collection_id: str,
    record: StoredDocument,
) -> SourceDocument:
    document = record.document
    bundle = await _get_source_artifact_builder()(
        config=_source_config(collection_id, document.document_id),
        input_documents=pd.DataFrame(
            [
                {
                    "id": document.document_id,
                    "source_path": record.stored_filename,
                    "source_type": Path(record.stored_filename).suffix.lstrip("."),
                    "title": document.original_filename,
                    "creation_date": record.created_at,
                    "text": None,
                }
            ]
        ),
    )
    parsed = bundle.to_documents()
    if len(parsed) != 1 or parsed[0].document_id != document.document_id:
        raise RuntimeError("Source pipeline returned the wrong document identity")
    source_document = parsed[0]
    figures = []
    referenced_assets: set[str] = set()
    for figure in source_document.figures:
        image_path = str(figure.image_path or "").strip()
        if not image_path:
            figures.append(figure)
            continue
        payload = bundle.figure_assets.get(image_path)
        if payload is None or not figure.asset_sha256:
            raise RuntimeError(f"Source figure asset is incomplete: {figure.figure_id}")
        referenced_assets.add(image_path)
        storage_key = collection_service.write_figure_asset(
            collection_id,
            document.document_id,
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
    return replace(source_document, figures=tuple(figures))


def _source_config(
    collection_id: str,
    document_id: str,
) -> SourceParserConfig:
    paths = collection_service.workspace.get_paths(collection_id)
    working_dir = paths.output_dir / "documents" / document_id
    return SourceParserConfig(
        root_dir=str(paths.collection_dir),
        input=InputConfig(
            storage=InputStorageConfig(base_dir=str(paths.input_dir)),
            file_type="document",
            encoding="utf-8",
            file_pattern=r".*\.(txt|pdf)$",
        ),
        output=StorageConfig(base_dir=str(working_dir)),
    )


def _get_source_artifact_builder() -> SourceArtifactBuilder:
    global _source_artifact_builder
    if _source_artifact_builder is None:
        from infra.source.build_source_artifacts import (
            build_source_artifacts,
        )

        _source_artifact_builder = build_source_artifacts
    return _source_artifact_builder


def _log_unexpected_failure(worker: AsyncTask[dict[str, Any]]) -> None:
    try:
        worker.result()
    except CancelledError:
        logger.info("Document preparation run cancelled during backend shutdown")
    except Exception:  # noqa: BLE001
        logger.exception("Document preparation run crashed after scheduling")


__all__ = [
    "DOCUMENT_ANALYSIS_VERSION",
    "SOURCE_PARSER_VERSION",
    "profile_fingerprint",
    "source_fingerprint",
    "recover_interrupted_runs",
    "queue_document_preparation",
    "run_document_preparation",
    "preparation_fingerprint_for",
    "fingerprints_for",
]
