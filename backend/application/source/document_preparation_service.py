"""Prepare one document for later collection-level research work."""

from __future__ import annotations

from asyncio import CancelledError, Semaphore, Task, create_task, to_thread
from dataclasses import replace
from hashlib import sha256 as hash_sha256
import json
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, cast

import pandas as pd

from application.core.document_profiles.prompts import DOCUMENT_PROFILE_PROMPT_VERSION
from application.core.document_profiles.service import DocumentProfileService
from application.core.objectives.discovery.signal_reconciliation import (
    PAPER_SIGNAL_RECONCILIATION_PROMPT_VERSION,
    PaperSignalReconciler,
)
from application.core.objectives.discovery.study_window import (
    PAPER_RESEARCH_MAP_PROMPT_VERSION,
    PAPER_SOURCE_SIGNAL_PROMPT_VERSION,
    PaperResearchMapExtractor,
)
from application.core.objectives.llm.structured_response import (
    StructuredResponseClient,
    build_default_structured_response_client,
)
from application.core.objectives.paper_research_map_service import PaperResearchMapService
from application.source.collection_service import CollectionService
from application.source.reference_extraction_service import (
    SourceReferenceExtractionService,
)
from application.source.task_service import TaskService
from domain.ports import PaperMapRepository, SourceArtifactRepository
from domain.source import Document, SourceDocument
from infra.source.config.pipeline_mode import IndexingMethod
from infra.source.config.source_runtime_config import (
    CacheConfig,
    InputConfig,
    InputStorageConfig,
    SourceRuntimeConfig,
    StorageConfig,
)
from infra.source.runtime.artifact_bundle import SourceArtifactBundle


logger = logging.getLogger(__name__)

SOURCE_PARSER_VERSION = "source-runtime.v1"
DOCUMENT_ANALYSIS_VERSION = (
    f"{DOCUMENT_PROFILE_PROMPT_VERSION}+{PAPER_RESEARCH_MAP_PROMPT_VERSION}+"
    f"{PAPER_SOURCE_SIGNAL_PROMPT_VERSION}+"
    f"{PAPER_SIGNAL_RECONCILIATION_PROMPT_VERSION}"
)
PAPER_MAP_VERSION = (
    f"{PAPER_RESEARCH_MAP_PROMPT_VERSION}+{PAPER_SOURCE_SIGNAL_PROMPT_VERSION}+"
    f"{PAPER_SIGNAL_RECONCILIATION_PROMPT_VERSION}"
)
_DEFAULT_PREPARATION_CONCURRENCY = 10

SourceArtifactBuilder = Callable[..., Awaitable[list[Any]]]


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


def paper_map_fingerprint(
    *,
    profile_fingerprint: str,
    paper_map_version: str,
) -> str:
    return _stage_fingerprint(
        "paper_map",
        profile_fingerprint=str(profile_fingerprint),
        paper_map_version=str(paper_map_version),
    )


class DocumentPreparationService:
    """Own parsing, triage, and bounded Paper Map creation for one document."""

    def __init__(
        self,
        *,
        collection_service: CollectionService,
        task_service: TaskService,
        source_artifact_repository: SourceArtifactRepository,
        document_profile_service: DocumentProfileService,
        paper_map_repository: PaperMapRepository,
        paper_map_service: PaperResearchMapService,
        response_client: StructuredResponseClient | None = None,
        source_artifact_builder: SourceArtifactBuilder | None = None,
        max_concurrency: int | None = None,
    ) -> None:
        self.collection_service = collection_service
        self.task_service = task_service
        self.source_artifact_repository = source_artifact_repository
        self.document_profile_service = document_profile_service
        self.paper_map_repository = paper_map_repository
        self.paper_map_service = paper_map_service
        self._response_client = response_client
        self._source_artifact_builder = source_artifact_builder
        resolved_concurrency = max_concurrency or int(
            os.getenv(
                "DOCUMENT_PREPARATION_MAX_CONCURRENCY",
                str(_DEFAULT_PREPARATION_CONCURRENCY),
            )
        )
        if resolved_concurrency < 1:
            raise ValueError("document preparation concurrency must be positive")
        self._semaphore = Semaphore(resolved_concurrency)
        self._active_tasks: set[Task[dict[str, Any]]] = set()

    async def recover_interrupted_tasks(self) -> int:
        """Make persisted work without a live worker retryable after restart."""

        active_tasks = [
            *await self.task_service.list_tasks(status="queued"),
            *await self.task_service.list_tasks(status="running"),
        ]
        interrupted_count = 0
        for task in active_tasks:
            if task.get("task_type") != "document_preparation":
                continue
            document_id = task.get("document_id")
            if not document_id:
                continue
            await self.task_service.finish_task(
                task["task_id"],
                status="interrupted",
                current_stage="interrupted",
                progress_percent=task.get("progress_percent", 0),
                errors=[
                    *task.get("errors", ()),
                    "Document preparation was interrupted by a backend restart.",
                ],
            )
            try:
                document = await self.collection_service.get_document(
                    task["collection_id"],
                    document_id,
                )
            except FileNotFoundError:
                interrupted_count += 1
                continue
            if document.status == "processing":
                await self.collection_service.update_document_preparation(
                    task["collection_id"],
                    document_id,
                    status="stored",
                )
            interrupted_count += 1
        if interrupted_count:
            logger.warning(
                "Recovered interrupted document preparation tasks count=%s",
                interrupted_count,
            )
        return interrupted_count

    async def queue_document(
        self,
        collection_id: str,
        document_id: str,
        *,
        mode: IndexingMethod | str = IndexingMethod.Standard,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        document = await self.collection_service.get_document(
            collection_id,
            document_id,
        )
        fingerprint = self.fingerprint_for(document)
        task, created = await self.task_service.get_or_create_document_task(
            collection_id=collection_id,
            document_id=document_id,
            task_type="document_preparation",
            input_fingerprint=fingerprint,
            mode=str(mode),
        )
        if created:
            background = create_task(
                self.run_task(
                    task["task_id"],
                    collection_id,
                    document_id,
                    mode=mode,
                    request_id=request_id,
                )
            )
            self._active_tasks.add(background)
            background.add_done_callback(self._active_tasks.discard)
            background.add_done_callback(self._log_unexpected_failure)
        return task

    async def run_task(
        self,
        task_id: str,
        collection_id: str,
        document_id: str,
        *,
        mode: IndexingMethod | str = IndexingMethod.Standard,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        del request_id
        async with self._semaphore:
            document = await self.collection_service.get_document(
                collection_id,
                document_id,
            )
            source_identity, profile_identity, fingerprint = self.fingerprints_for(
                document
            )
            await self.task_service.update_task(
                task_id,
                status="running",
                current_stage="source_parsing",
                progress_percent=5,
                progress_detail={
                    "phase": "source_parsing",
                    "unit": "document",
                    "message": "Parsing the document into traceable Sources.",
                },
            )
            await self.collection_service.update_document_preparation(
                collection_id,
                document_id,
                status="processing",
            )
            try:
                source_document = await self.source_artifact_repository.read_document(
                    collection_id,
                    document_id,
                )
                if (
                    source_document is None
                    or document.source_fingerprint != source_identity
                ):
                    source_document = await self._parse_document(
                        collection_id,
                        document,
                        mode=mode,
                    )
                    await self.source_artifact_repository.replace_document(
                        collection_id,
                        source_document,
                    )
                    references = SourceReferenceExtractionService().extract(
                        (source_document,)
                    )
                    await self.source_artifact_repository.replace_document_references(
                        document_id,
                        references,
                    )
                    document = await self.collection_service.update_document_preparation(
                        collection_id,
                        document_id,
                        status="processing",
                        source_fingerprint=source_identity,
                        parser_version=SOURCE_PARSER_VERSION,
                    )
                await self.task_service.update_task(
                    task_id,
                    current_stage="document_profile",
                    progress_percent=45,
                    progress_detail={
                        "phase": "document_profile",
                        "unit": "document",
                        "message": "Classifying the paper for research triage.",
                    },
                )
                profile = await self.document_profile_service.read_document_profile(
                    collection_id, document_id
                )
                if profile is None or document.profile_fingerprint != profile_identity:
                    profile = await self.document_profile_service.build_document_profile(
                        collection_id,
                        document_id,
                    )
                    document = await self.collection_service.update_document_preparation(
                        collection_id,
                        document_id,
                        status="processing",
                        profile_fingerprint=profile_identity,
                    )
                await self.task_service.update_task(
                    task_id,
                    current_stage="paper_map",
                    progress_percent=65,
                    progress_detail={
                        "phase": "paper_map",
                        "unit": "document",
                        "message": "Mapping the paper's research scope.",
                    },
                )
                paper_map = await self.paper_map_repository.read(
                    collection_id, document_id
                )
                if paper_map is None or document.preparation_fingerprint != fingerprint:
                    response_client = self._get_response_client()
                    paper_map = await to_thread(
                        self.paper_map_service.build_document_paper_map,
                        collection_id,
                        document=source_document,
                        profile=profile,
                        document_tree=(
                            await self.source_artifact_repository.read_document_tree(
                                collection_id,
                                document_id,
                            )
                        ),
                        paper_map_extractor=PaperResearchMapExtractor(response_client),
                        signal_reconciler=PaperSignalReconciler(response_client),
                    )
                    await self.paper_map_repository.replace(collection_id, paper_map)
                await self.collection_service.update_document_preparation(
                    collection_id,
                    document_id,
                    status="ready",
                    preparation_fingerprint=fingerprint,
                    source_fingerprint=source_identity,
                    profile_fingerprint=profile_identity,
                    parser_version=SOURCE_PARSER_VERSION,
                    document_analysis_version=DOCUMENT_ANALYSIS_VERSION,
                )
                return await self.task_service.finish_task(
                    task_id,
                    status="completed",
                    current_stage="ready",
                    progress_percent=100,
                    progress_detail={
                        "phase": "ready",
                        "unit": "document",
                        "message": "The document is ready for research scope selection.",
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Document preparation failed collection_id=%s document_id=%s task_id=%s",
                    collection_id,
                    document_id,
                    task_id,
                )
                await self.collection_service.update_document_preparation(
                    collection_id,
                    document_id,
                    status="failed",
                )
                await self.task_service.finish_task(
                    task_id,
                    status="failed",
                    current_stage="failed",
                    progress_percent=100,
                    errors=[str(exc)],
                    progress_detail={
                        "phase": "failed",
                        "unit": "document",
                        "message": "Document preparation failed.",
                    },
                )
                raise

    @staticmethod
    def fingerprint_for(document: Document) -> str:
        return DocumentPreparationService.fingerprints_for(document)[2]

    @staticmethod
    def fingerprints_for(document: Document) -> tuple[str, str, str]:
        source_identity = source_fingerprint(
            sha256=document.sha256,
            parser_version=SOURCE_PARSER_VERSION,
        )
        profile_identity = profile_fingerprint(
            source_fingerprint=source_identity,
            profile_version=DOCUMENT_PROFILE_PROMPT_VERSION,
        )
        return (
            source_identity,
            profile_identity,
            paper_map_fingerprint(
                profile_fingerprint=profile_identity,
                paper_map_version=PAPER_MAP_VERSION,
            ),
        )

    async def _parse_document(
        self,
        collection_id: str,
        document: Document,
        *,
        mode: IndexingMethod | str,
    ) -> SourceDocument:
        outputs = await self._get_source_artifact_builder()(
            config=self._source_config(collection_id, document.document_id),
            method=mode,
            input_documents=pd.DataFrame(
                [
                    {
                        "id": document.document_id,
                        "source_path": document.stored_filename,
                        "source_type": Path(document.stored_filename).suffix.lstrip("."),
                        "title": document.original_filename,
                        "creation_date": document.created_at,
                        "text": None,
                    }
                ]
            ),
        )
        errors = [str(error) for output in outputs for error in output.errors or ()]
        if errors:
            raise RuntimeError("; ".join(errors))
        bundle_output = next(
            (
                output
                for output in reversed(outputs)
                if isinstance(output.result, SourceArtifactBundle)
            ),
            None,
        )
        if bundle_output is None:
            raise RuntimeError("Source pipeline did not return an artifact bundle")
        bundle = cast(SourceArtifactBundle, bundle_output.result)
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
                raise RuntimeError(
                    f"Source figure asset is incomplete: {figure.figure_id}"
                )
            referenced_assets.add(image_path)
            storage_key = self.collection_service.write_figure_asset(
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
        self,
        collection_id: str,
        document_id: str,
    ) -> SourceRuntimeConfig:
        paths = self.collection_service.get_paths(collection_id)
        working_dir = paths.output_dir / "documents" / document_id
        return SourceRuntimeConfig(
            root_dir=str(paths.collection_dir),
            input=InputConfig(
                storage=InputStorageConfig(base_dir=str(paths.input_dir)),
                file_type="document",
                encoding="utf-8",
                file_pattern=r".*\.(txt|pdf)$",
            ),
            output=StorageConfig(base_dir=str(working_dir)),
            cache=CacheConfig(base_dir=str(working_dir / "cache")),
        )

    def _get_source_artifact_builder(self) -> SourceArtifactBuilder:
        if self._source_artifact_builder is None:
            from infra.source.runtime.build_source_artifacts import build_source_artifacts

            self._source_artifact_builder = build_source_artifacts
        return self._source_artifact_builder

    def _get_response_client(self) -> StructuredResponseClient:
        if self._response_client is None:
            self._response_client = build_default_structured_response_client()
        return self._response_client

    @staticmethod
    def _log_unexpected_failure(task: Task[dict[str, Any]]) -> None:
        try:
            task.result()
        except CancelledError:
            logger.info("Document preparation task cancelled during backend shutdown")
        except Exception:  # noqa: BLE001
            logger.exception("Document preparation task crashed after scheduling")


__all__ = [
    "DOCUMENT_ANALYSIS_VERSION",
    "DocumentPreparationService",
    "PAPER_MAP_VERSION",
    "SOURCE_PARSER_VERSION",
    "paper_map_fingerprint",
    "profile_fingerprint",
    "source_fingerprint",
]
