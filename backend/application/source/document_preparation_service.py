"""Prepare one document for later workspace-level research work."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import ExitStack
from dataclasses import replace
from hashlib import sha256 as hash_sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Awaitable, Callable

import httpx
import pandas as pd
from openai import OpenAI
from application.core.document_profiles import service as document_profile_service
from application.core.document_profiles.extraction import (
    DOCUMENT_PROFILE_PROMPT_VERSION,
    DocumentProfileExtractor,
)
from application.pipeline import pipeline_run_service
from application.pipeline.pipeline_run_service import document_preparation_error_message
from application.source import workspace_service
from application.source import (
    reference_extraction_service as source_reference_extraction_service,
)
from domain.core.document_profile import PROFILE_STATUS_COMPLETED
from document.domain.source import SourceDocument
from document.domain.document import Document
from exceptions import ServiceUnavailableException
from infra.llm.model_credentials import provider_options
from infra.persistence.database import AsyncSessionLocal
from infra.persistence.file import FileWorkspace
from infra.source.artifact_bundle import SourceArtifactBundle
from infra.source.config.source_parser_config import (
    InputConfig,
    InputStorageConfig,
    SourceParserConfig,
    StorageConfig,
)
from repositories.workspace_repository import StoredDocument
from repositories.document_profile_repository import DocumentProfileRepo
from repositories.model_connection_repository import ModelConnectionRepo
from repositories.object_store import ObjectStore
from repositories.pipeline_run_repository import (
    PipelineLeaseLostError,
    PipelineRun,
    PipelineRunJobSnapshot,
    PipelineRunRepo,
)
from repositories.source_artifact_repository import SourceArtifactRepo
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SOURCE_PARSER_VERSION = "source-runtime.v1"
DOCUMENT_ANALYSIS_VERSION = DOCUMENT_PROFILE_PROMPT_VERSION
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
    connection_id: str | None = None,
) -> str:
    # Keep historical fingerprints readable for already completed runs.
    model = {"model_connection_id": connection_id} if connection_id is not None else {}
    return _stage_fingerprint(
        "profile",
        source_fingerprint=str(source_fingerprint),
        profile_version=str(profile_version),
        **model,
    )


async def queue_document_preparation(
    workspace_id: str,
    document_id: str,
    *,
    user_id: str,
) -> PipelineRun:
    """Queue or reuse preparation of one workspace document."""

    await workspace_service.get_workspace_for_user(workspace_id, user_id)

    document = await workspace_service.get_document(
        workspace_id,
        document_id,
    )
    assignment = await ModelConnectionRepo.read_assignment("document_profile")
    if assignment is None:
        raise ServiceUnavailableException(
            "Ask an administrator to assign a processing model.",
            data={"code": "processing_model_unassigned", "purpose": "document_profile"},
        )
    connection_id = assignment.connection_id
    source_identity, profile_identity = fingerprints_for(document.document, connection_id)
    run, _ = await pipeline_run_service.get_or_create_document_run(
        workspace_id=workspace_id,
        document_id=document_id,
        pipeline_name="document_preparation",
        input_fingerprint=profile_identity,
        context={
            "document_sha256": document.document.sha256,
            "profile_version": DOCUMENT_ANALYSIS_VERSION,
            "parser_version": SOURCE_PARSER_VERSION,
            "model_connection_id": connection_id,
        },
        reuse_completed=await _can_reuse_document_preparation(
            workspace_id, document, source_identity, profile_identity
        ),
    )
    return run


async def _can_reuse_document_preparation(
    workspace_id: str, record: StoredDocument, source_identity: str, profile_identity: str
) -> bool:
    if (
        record.status != "ready"
        or record.preparation_fingerprint != profile_identity
        or record.profile_fingerprint != profile_identity
        or record.source_fingerprint != source_identity
    ):
        return False
    profile = await DocumentProfileRepo.read(
        workspace_id,
        document.document_id,
    )
    if profile is None or profile.profile_status != PROFILE_STATUS_COMPLETED:
        return False
    return (
        await SourceArtifactRepo.read_document(
            workspace_id,
            document.document_id,
        )
        is not None
    )


async def _parse_document_sources(
    workspace_id: str,
    record: StoredDocument,
    *,
    workspace: FileWorkspace,
    object_store: ObjectStore,
    source_artifact_builder: SourceArtifactBuilder,
    work_dir: Path,
) -> SourceDocument:
    document = record.document
    parser_task = asyncio.create_task(
        source_artifact_builder(
            config=_source_parser_config(
                workspace_id, workspace=workspace, work_dir=work_dir
            ),
            input_documents=pd.DataFrame(
                [
                    {
                        "id": document.document_id,
                        "source_path": record.storage_key,
                        "source_type": Path(document.filename).suffix.lstrip("."),
                        "title": document.filename,
                        "creation_date": record.created_at,
                        "text": None,
                    }
                ]
            ),
        )
    )
    try:
        bundle = await asyncio.shield(parser_task)
    except asyncio.CancelledError:
        await asyncio.gather(parser_task, return_exceptions=True)
        raise
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
        storage_key = workspace_service.write_figure_asset(
            workspace_id,
            document.document_id,
            image_path,
            payload,
            figure.asset_sha256,
            object_store=object_store,
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


def _source_parser_config(
    workspace_id: str,
    *,
    workspace: FileWorkspace,
    work_dir: Path,
) -> SourceParserConfig:
    paths = workspace.get_paths(workspace_id)
    return SourceParserConfig(
        root_dir=str(paths.workspace_dir),
        input=InputConfig(
            storage=InputStorageConfig(base_dir=str(paths.input_dir)),
            file_type="document",
            encoding="utf-8",
            file_pattern=r".*\.(txt|pdf)$",
        ),
        output=StorageConfig(base_dir=str(work_dir)),
    )


async def _check_preparation_input(
    db: AsyncSession, job: PipelineRunJobSnapshot
) -> StoredDocument:
    await PipelineRunRepo.lock_job(db, job)
    record = await workspace_service.get_document(
        job.run.workspace_id, job.run.scope_id, db=db
    )
    if (
        preparation_fingerprint_for(
            record.document, job.run.context.get("model_connection_id")
        ) != job.run.input_fingerprint
        or job.run.context["document_sha256"] != record.document.sha256
    ):
        raise ValueError("document preparation input changed")
    return record


async def execute_document_preparation_job(
    job: PipelineRunJobSnapshot,
    *,
    workspace: FileWorkspace,
    object_store: ObjectStore,
    source_artifact_builder: SourceArtifactBuilder,
    profile_extractor: DocumentProfileExtractor | None = None,
) -> PipelineRun:
    run_id = job.run.run_id
    workspace_id = job.run.workspace_id
    document_id = job.run.scope_id
    stage = "source_parsing"
    warnings: list[str] = []
    connection_id = job.run.context.get("model_connection_id")
    try:
        async with AsyncSessionLocal() as db, db.begin():
            record = await _check_preparation_input(db, job)
            source_identity, profile_identity = fingerprints_for(record.document, connection_id)
            await workspace_service.update_document_preparation(
                workspace_id, document_id, status="processing", db=db
            )
            await pipeline_run_service.update_run(
                run_id,
                job=job,
                db=db,
                status="running",
                current_node=stage,
                progress_percent=5,
            )
        source_document = await SourceArtifactRepo.read_document(
            workspace_id, document_id
        )
        if (
            source_document is None
            or record.source_fingerprint != source_identity
        ):
            temporary_root = (
                workspace.get_paths(workspace_id).output_dir / "preparation"
            )
            temporary_root.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(
                prefix=f"{run_id}-{job.lease_version}-", dir=temporary_root
            ) as work_dir:
                source_document = await _parse_document_sources(
                    workspace_id,
                    record,
                    workspace=workspace,
                    object_store=object_store,
                    source_artifact_builder=source_artifact_builder,
                    work_dir=Path(work_dir),
                )
            source_document = replace(
                source_document,
                metadata={
                    **source_document.metadata,
                    "parser_version": SOURCE_PARSER_VERSION,
                    "source_fingerprint": source_identity,
                },
            )
            async with AsyncSessionLocal() as db, db.begin():
                await _check_preparation_input(db, job)
                await SourceArtifactRepo.replace_document(
                    workspace_id, source_document, db=db
                )
                await workspace_service.update_document_preparation(
                    workspace_id,
                    document_id,
                    status="processing",
                    source_fingerprint=source_identity,
                    parser_version=SOURCE_PARSER_VERSION,
                    db=db,
                )
            try:
                references = (
                    source_reference_extraction_service.extract_source_references(
                        (source_document,)
                    )
                )
                async with AsyncSessionLocal() as db, db.begin():
                    await _check_preparation_input(db, job)
                    await SourceArtifactRepo.replace_document_references(
                        document_id, references, db=db
                    )
            except PipelineLeaseLostError:
                raise
            except Exception:
                warnings.append(
                    "Source reference extraction failed; Source remains available."
                )
                logger.warning(
                    "Source reference extraction failed run_id=%s",
                    run_id,
                    exc_info=True,
                )
        stage = "document_profile"
        async with AsyncSessionLocal() as db, db.begin():
            await pipeline_run_service.update_run(
                run_id, job=job, db=db, current_node=stage, progress_percent=45
            )
        profile = await DocumentProfileRepo.read(workspace_id, document_id)
        if (
            profile is None
            or record.profile_fingerprint != profile_identity
            or profile.profile_status != PROFILE_STATUS_COMPLETED
        ):
            with ExitStack() as clients:
                if profile_extractor is None:
                    connection = (
                        await ModelConnectionRepo.read(connection_id) if connection_id else None
                    )
                    if connection is None:
                        raise ServiceUnavailableException(
                            "Queue document preparation with an assigned model.",
                            data={"code": "processing_model_unavailable"},
                        )
                    client = clients.enter_context(OpenAI(
                        **provider_options(connection),
                        http_client=httpx.Client(follow_redirects=False),
                    ))
                    profile_extractor = DocumentProfileExtractor(client=client, model=connection.model)
                profile = await document_profile_service.build_document_profile(
                    workspace_id,
                    document_id,
                    source_fingerprint=source_identity,
                    profile_fingerprint=profile_identity,
                    extractor=profile_extractor,
                )
        async with AsyncSessionLocal() as db, db.begin():
            await _check_preparation_input(db, job)
            await DocumentProfileRepo.replace(workspace_id, profile, db=db)
            if profile.profile_status != PROFILE_STATUS_COMPLETED:
                message = document_preparation_error_message(stage)
                await workspace_service.update_document_preparation(
                    workspace_id, document_id, status="stored", db=db
                )
                return await pipeline_run_service.finish_run(
                    run_id,
                    job=job,
                    db=db,
                    status="partial_success",
                    current_node=stage,
                    warnings=[*warnings, message],
                    errors=[message],
                )
            await workspace_service.update_document_preparation(
                workspace_id,
                document_id,
                status="ready",
                preparation_fingerprint=profile_identity,
                source_fingerprint=source_identity,
                profile_fingerprint=profile_identity,
                parser_version=SOURCE_PARSER_VERSION,
                document_analysis_version=DOCUMENT_ANALYSIS_VERSION,
                db=db,
            )
            return await pipeline_run_service.finish_run(
                run_id,
                job=job,
                db=db,
                status="completed",
                current_node="ready",
                warnings=warnings,
            )
    except PipelineLeaseLostError:
        raise
    except Exception:
        logger.exception(
            "Document preparation failed run_id=%s stage=%s", run_id, stage
        )
        async with AsyncSessionLocal() as db, db.begin():
            await PipelineRunRepo.lock_job(db, job)
            await workspace_service.update_document_preparation(
                workspace_id, document_id, status="failed", db=db
            )
            return await pipeline_run_service.finish_run(
                run_id,
                job=job,
                db=db,
                status="failed",
                current_node=stage,
                errors=[document_preparation_error_message(stage)],
            )


def preparation_fingerprint_for(document: Document, connection_id: str | None = None) -> str:
    return fingerprints_for(document, connection_id)[1]


def fingerprints_for(document: Document, connection_id: str | None = None) -> tuple[str, str]:
    source_identity = source_fingerprint(
        sha256=document.sha256,
        parser_version=SOURCE_PARSER_VERSION,
    )
    profile_identity = profile_fingerprint(
        source_fingerprint=source_identity,
        profile_version=DOCUMENT_PROFILE_PROMPT_VERSION,
        connection_id=connection_id,
    )
    return source_identity, profile_identity
