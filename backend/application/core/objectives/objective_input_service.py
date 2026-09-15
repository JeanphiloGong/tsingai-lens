"""Load the exact prepared papers consumed by Objective workflows."""

from __future__ import annotations

from asyncio import Semaphore, gather, to_thread
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, TypedDict

from application.core.document_profiles.service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.core.objectives.discovery.paper_understanding.workflow import (
    PAPER_RESEARCH_MAP_PROMPT_VERSION,
    PaperResearchMapExtractor,
)
from application.core.objectives.llm.structured_response import (
    StructuredResponseClient,
    build_default_structured_response_client,
)
from application.core.objectives.paper_research_map_service import (
    PaperResearchMapService,
)
from application.source.collection_service import CollectionService
from domain.core import PaperResearchMap, PreparedDocumentInput
from domain.core.document_profile import DocumentProfile
from application.repositories.paper_map_repository import PaperMapRepository
from application.repositories.source_artifact_repository import SourceArtifactRepository
from domain.source import (
    SourceBlock,
    SourceDocument,
    SourceDocumentTree,
    SourceFigure,
    SourceReferenceSet,
    SourceTable,
    SourceTableCell,
    build_source_document_tree,
)


class ObjectiveSourceInputs(TypedDict):
    """Prepared paper data shared by discovery and analysis, without model clients."""

    documents: tuple[SourceDocument, ...]
    profiles_by_document_id: dict[str, DocumentProfile]
    blocks_by_document_id: dict[str, list[SourceBlock]]
    tables_by_document_id: dict[str, list[SourceTable]]
    table_cells_by_document_id: dict[str, list[SourceTableCell]]
    figures_by_document_id: dict[str, list[SourceFigure]]
    document_trees_by_document_id: dict[str, SourceDocumentTree | None]


_PAPER_MAP_DOCUMENT_MAX_CONCURRENCY = 10
PAPER_RESEARCH_MAP_POLICY_VERSION = "+".join(
    (
        "paper_research_map_selection.v3",
        PAPER_RESEARCH_MAP_PROMPT_VERSION,
    )
)


def paper_map_input_fingerprint(preparation_fingerprint: str) -> str:
    return sha256(
        json.dumps(
            {
                "preparation_fingerprint": preparation_fingerprint,
                "paper_map_policy_version": PAPER_RESEARCH_MAP_POLICY_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class ResearchObjectivesNotReadyError(RuntimeError):
    """Raised when a collection cannot serve prepared research inputs."""

    def __init__(self, collection_id: str) -> None:
        self.collection_id = collection_id
        super().__init__(f"research objectives not ready: {collection_id}")


class ObjectiveInputService:
    """Freeze prepared Documents and load their Source/Profile/Map inputs."""

    def __init__(
        self,
        *,
        collection_service: CollectionService,
        source_artifact_repository: SourceArtifactRepository,
        paper_map_repository: PaperMapRepository,
        document_profile_service: DocumentProfileService,
        paper_map_service: PaperResearchMapService,
        response_client: StructuredResponseClient | None = None,
    ) -> None:
        self.collection_service = collection_service
        self.source_artifact_repository = source_artifact_repository
        self.paper_map_repository = paper_map_repository
        self.document_profile_service = document_profile_service
        self.paper_map_service = paper_map_service
        self._response_client = response_client

    async def resolve_prepared_document_inputs(
        self,
        collection_id: str,
        document_ids: tuple[str, ...],
    ) -> tuple[PreparedDocumentInput, ...]:
        if not document_ids:
            raise ValueError("Objective discovery requires at least one document")
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("Objective discovery document IDs must be unique")

        inputs: list[PreparedDocumentInput] = []
        for document_id in document_ids:
            document = await self.collection_service.get_document(
                collection_id,
                document_id,
            )
            if document.status != "ready" or not document.preparation_fingerprint:
                raise ResearchObjectivesNotReadyError(collection_id)
            inputs.append(
                PreparedDocumentInput(
                    document_id=document_id,
                    preparation_fingerprint=document.preparation_fingerprint,
                )
            )
        return tuple(inputs)

    async def load_source_inputs(
        self,
        collection_id: str,
        *,
        document_inputs: tuple[PreparedDocumentInput, ...],
    ) -> ObjectiveSourceInputs:
        current_inputs = await self.resolve_prepared_document_inputs(
            collection_id,
            tuple(item.document_id for item in document_inputs),
        )
        if current_inputs != document_inputs:
            raise ValueError(
                "prepared document input is stale; select the current document state"
            )
        try:
            profiles: tuple[DocumentProfile, ...] = (
                await self.document_profile_service.read_document_profiles(
                    collection_id,
                    tuple(item.document_id for item in document_inputs),
                )
            )
        except DocumentProfilesNotReadyError as exc:
            raise ResearchObjectivesNotReadyError(collection_id) from exc
        expected_ids = {item.document_id for item in document_inputs}
        if {profile.document_id for profile in profiles} != expected_ids:
            raise ResearchObjectivesNotReadyError(collection_id)

        try:
            documents = await self._load_source_documents(
                collection_id,
                document_inputs=document_inputs,
            )
        except FileNotFoundError as exc:
            raise ResearchObjectivesNotReadyError(collection_id) from exc

        document_ids = tuple(document.document_id for document in documents)
        references = await self.source_artifact_repository.read_collection_references(
            collection_id,
            document_ids,
        )
        document_trees_by_document_id = {
            document.document_id: build_source_document_tree(
                collection_id=collection_id,
                document=document,
                blocks=document.blocks,
                tables=document.tables,
                figures=document.figures,
                references=self._references_for_document(
                    references,
                    document.document_id,
                ),
            )
            for document in documents
        }
        return {
            "documents": documents,
            "profiles_by_document_id": {
                profile.document_id: profile for profile in profiles
            },
            "blocks_by_document_id": {
                document.document_id: list(document.blocks) for document in documents
            },
            "tables_by_document_id": {
                document.document_id: list(document.tables) for document in documents
            },
            "table_cells_by_document_id": {
                document.document_id: list(document.table_cells)
                for document in documents
            },
            "figures_by_document_id": {
                document.document_id: list(document.figures) for document in documents
            },
            "document_trees_by_document_id": document_trees_by_document_id,
        }

    async def load_or_build_paper_maps(
        self,
        collection_id: str,
        *,
        document_inputs: tuple[PreparedDocumentInput, ...],
        source_inputs: ObjectiveSourceInputs,
        progress_callback: Any | None = None,
    ) -> tuple[PaperResearchMap, ...]:
        document_ids = tuple(item.document_id for item in document_inputs)
        existing_maps = await self.paper_map_repository.list_collection(
            collection_id,
            document_ids,
        )
        maps_by_document_id = {item.document_id: item for item in existing_maps}
        inputs_by_document_id = {item.document_id: item for item in document_inputs}
        map_input_fingerprints = {
            document_id: paper_map_input_fingerprint(item.preparation_fingerprint)
            for document_id, item in inputs_by_document_id.items()
        }
        documents_by_id = {
            document.document_id: document for document in source_inputs["documents"]
        }
        build_limit = Semaphore(_PAPER_MAP_DOCUMENT_MAX_CONCURRENCY)
        stale_document_ids = tuple(
            document_id
            for document_id in document_ids
            if maps_by_document_id.get(document_id) is None
            or maps_by_document_id[document_id].input_fingerprint
            != map_input_fingerprints[document_id]
            or maps_by_document_id[document_id].map_version
            != PAPER_RESEARCH_MAP_POLICY_VERSION
            or not maps_by_document_id[document_id].coverage_complete
        )
        completed_map_count = 0

        async def build_map(document_id: str) -> None:
            nonlocal completed_map_count

            def report_document_progress(detail: dict[str, Any]) -> None:
                if progress_callback is None:
                    return
                progress_callback(
                    {
                        **detail,
                        "current": completed_map_count,
                        "total": len(stale_document_ids),
                        "unit": "documents",
                        "active_document_id": document_id,
                    }
                )

            async with build_limit:
                paper_map = await to_thread(
                    self.paper_map_service.build_document_paper_map,
                    collection_id,
                    document=documents_by_id[document_id],
                    profile=source_inputs["profiles_by_document_id"][document_id],
                    document_tree=source_inputs["document_trees_by_document_id"][
                        document_id
                    ],
                    paper_map_extractor=PaperResearchMapExtractor(self.response_client),
                    progress_callback=report_document_progress,
                )
            paper_map = replace(
                paper_map,
                input_fingerprint=map_input_fingerprints[document_id],
                map_version=PAPER_RESEARCH_MAP_POLICY_VERSION,
                generated_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.paper_map_repository.replace(collection_id, paper_map)
            maps_by_document_id[document_id] = paper_map
            completed_map_count += 1
            if progress_callback is not None:
                progress_callback(
                    {
                        "phase": "paper_research_map_completed",
                        "current": completed_map_count,
                        "total": len(stale_document_ids),
                        "unit": "documents",
                        "message": "Mapped one selected paper for research question formation.",
                        "active_document_id": document_id,
                    }
                )

        await gather(*(build_map(document_id) for document_id in stale_document_ids))
        return tuple(maps_by_document_id[document_id] for document_id in document_ids)

    @property
    def response_client(self) -> StructuredResponseClient:
        if self._response_client is None:
            self._response_client = build_default_structured_response_client()
        return self._response_client

    async def _load_source_documents(
        self,
        collection_id: str,
        *,
        document_inputs: tuple[PreparedDocumentInput, ...],
    ) -> tuple[SourceDocument, ...]:
        document_ids = tuple(item.document_id for item in document_inputs)
        documents = await self.source_artifact_repository.read_documents(
            collection_id,
            document_ids,
        )
        if tuple(document.document_id for document in documents) != document_ids:
            raise FileNotFoundError(f"source artifacts not ready: {collection_id}")
        return documents

    @staticmethod
    def _references_for_document(
        references: SourceReferenceSet,
        document_id: str,
    ) -> SourceReferenceSet:
        entries = tuple(
            item for item in references.entries if item.document_id == document_id
        )
        reference_ids = {item.reference_id for item in entries}
        return SourceReferenceSet(
            entries=entries,
            mentions=tuple(
                item for item in references.mentions if item.document_id == document_id
            ),
            resolutions=tuple(
                item
                for item in references.resolutions
                if item.reference_id in reference_ids
            ),
            candidates=tuple(
                item
                for item in references.candidates
                if item.reference_id in reference_ids
            ),
        )


__all__ = [
    "ObjectiveInputService",
    "ObjectiveSourceInputs",
    "PAPER_RESEARCH_MAP_POLICY_VERSION",
    "ResearchObjectivesNotReadyError",
    "paper_map_input_fingerprint",
]
