from dataclasses import replace

import pytest

from application.core.document_profiles.prompts import DOCUMENT_PROFILE_PROMPT_VERSION
from application.source.document_preparation_service import (
    DOCUMENT_ANALYSIS_VERSION,
    DocumentPreparationService,
    profile_fingerprint,
    source_fingerprint,
)
from domain.core import DocumentProfile
from domain.source import Document, SourceDocument
from infra.persistence.memory import (
    MemorySourceArtifactRepository,
    MemoryPipelineRunRepository,
)
from application.pipeline import PipelineRunService
from application.source.reference_extraction_service import SourceReferenceExtractionService


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_document_preparation_fingerprints_invalidate_only_dependent_stages():
    source_v1 = source_fingerprint(
        sha256="a" * 64,
        parser_version="source-runtime.v1",
    )
    profile_v1 = profile_fingerprint(
        source_fingerprint=source_v1,
        profile_version="document-profile.v1",
    )
    assert source_v1 == source_fingerprint(
        sha256="a" * 64,
        parser_version="source-runtime.v1",
    )
    assert profile_v1 == profile_fingerprint(
        source_fingerprint=source_v1,
        profile_version="document-profile.v1",
    )
    profile_v2 = profile_fingerprint(
        source_fingerprint=source_v1,
        profile_version="document-profile.v2",
    )
    assert profile_v2 != profile_v1

    source_v2 = source_fingerprint(
        sha256="a" * 64,
        parser_version="source-runtime.v2",
    )
    assert source_v2 != source_v1
    assert profile_v1 != profile_fingerprint(
        source_fingerprint=source_v2,
        profile_version="document-profile.v1",
    )


def test_document_preparation_version_covers_only_profile_triage() -> None:
    assert DOCUMENT_ANALYSIS_VERSION == DOCUMENT_PROFILE_PROMPT_VERSION


async def test_restart_interrupts_orphaned_preparation_without_discarding_artifacts() -> None:
    collection_id = "col_restart"
    document_id = "doc_restart"
    original = Document(
        document_id=document_id,
        original_filename="paper.pdf",
        stored_filename="paper.pdf",
        storage_key="col_restart/inputs/paper.pdf",
        sha256="b" * 64,
        media_type="application/pdf",
        status="processing",
        size_bytes=100,
        created_at="2026-08-28T01:00:00+00:00",
        source_fingerprint="source-current",
        profile_fingerprint="profile-current",
        preparation_fingerprint="paper-map-current",
        parser_version="source-runtime.v1",
    )

    class CollectionService:
        def __init__(self) -> None:
            self.document = original

        async def get_document(self, owner: str, selected: str) -> Document:
            assert (owner, selected) == (collection_id, document_id)
            return self.document

        async def update_document_preparation(
            self,
            owner: str,
            selected: str,
            **fields,
        ) -> Document:
            assert (owner, selected) == (collection_id, document_id)
            self.document = replace(self.document, **fields)
            return self.document

    pipeline_run_service = PipelineRunService(MemoryPipelineRunRepository())
    task, created = await pipeline_run_service.get_or_create_document_run(
        collection_id=collection_id,
        document_id=document_id,
        pipeline_name="document_preparation",
        input_fingerprint="old-preparation-input",
    )
    assert created is True
    await pipeline_run_service.update_run(task["run_id"], status="running")
    collection_service = CollectionService()
    service = DocumentPreparationService(
        collection_service=collection_service,
        pipeline_run_service=pipeline_run_service,
        source_artifact_repository=MemorySourceArtifactRepository(),
        document_profile_service=object(),
        max_concurrency=1,
    )

    recovered = await service.recover_interrupted_runs()

    interrupted = await pipeline_run_service.get_run(task["run_id"])
    assert recovered == 1
    assert interrupted["status"] == "failed"
    assert interrupted["current_node"] == "interrupted"
    assert interrupted["finished_at"] is not None
    assert collection_service.document == replace(original, status="stored")

    replacement, replacement_created = (
        await pipeline_run_service.get_or_create_document_run(
            collection_id=collection_id,
            document_id=document_id,
            pipeline_name="document_preparation",
            input_fingerprint="old-preparation-input",
        )
    )
    assert replacement_created is True
    assert replacement["run_id"] != task["run_id"]


async def test_restart_keeps_preparation_active_when_document_reset_fails() -> None:
    collection_id = "col_restart_retry"
    document_id = "doc_restart_retry"
    document = Document(
        document_id=document_id,
        original_filename="paper.pdf",
        stored_filename="paper.pdf",
        storage_key="col_restart_retry/inputs/paper.pdf",
        sha256="c" * 64,
        media_type="application/pdf",
        status="processing",
        size_bytes=100,
        created_at="2026-08-28T01:00:00+00:00",
    )

    class CollectionService:
        async def get_document(self, owner: str, selected: str) -> Document:
            assert (owner, selected) == (collection_id, document_id)
            return document

        async def update_document_preparation(self, *_args, **_fields) -> Document:
            raise OSError("database temporarily unavailable")

    pipeline_run_service = PipelineRunService(MemoryPipelineRunRepository())
    task, _created = await pipeline_run_service.get_or_create_document_run(
        collection_id=collection_id,
        document_id=document_id,
        pipeline_name="document_preparation",
        input_fingerprint="preparation-input",
    )
    await pipeline_run_service.update_run(task["run_id"], status="running")
    collection_service = CollectionService()
    service = DocumentPreparationService(
        collection_service=collection_service,
        pipeline_run_service=pipeline_run_service,
        source_artifact_repository=MemorySourceArtifactRepository(),
        document_profile_service=object(),
        max_concurrency=1,
    )

    with pytest.raises(OSError, match="temporarily unavailable"):
        await service.recover_interrupted_runs()

    still_active = await pipeline_run_service.get_run(task["run_id"])
    assert still_active["status"] == "running"
    assert still_active["finished_at"] is None


async def test_profile_preparation_reuses_current_source_and_profile() -> None:
    collection_id = "col_test"
    document_id = "doc_test"
    base_document = Document(
        document_id=document_id,
        original_filename="paper.pdf",
        stored_filename="paper.pdf",
        storage_key="col_test/inputs/paper.pdf",
        sha256="a" * 64,
        media_type="application/pdf",
        status="failed",
        size_bytes=100,
        created_at="2026-08-27T10:00:00+00:00",
    )
    source_identity, profile_identity = DocumentPreparationService.fingerprints_for(
        base_document
    )

    class CollectionService:
        def __init__(self) -> None:
            self.document = replace(
                base_document,
                source_fingerprint=source_identity,
                profile_fingerprint=profile_identity,
                preparation_fingerprint="outdated-paper-map",
            )

        async def get_document(self, owner: str, selected: str) -> Document:
            assert (owner, selected) == (collection_id, document_id)
            return self.document

        async def update_document_preparation(
            self,
            owner: str,
            selected: str,
            **fields,
        ) -> Document:
            assert (owner, selected) == (collection_id, document_id)
            self.document = replace(self.document, **fields)
            return self.document

    class PipelineRunService:
        async def update_run(self, run_id: str, **fields):
            return {"run_id": run_id, **fields}

        async def finish_run(self, run_id: str, **fields):
            return {"run_id": run_id, **fields}

    profile = DocumentProfile.from_mapping(
        {
            "document_id": document_id,
            "title": "Paper",
            "doc_type": "experimental",
            "profile_warnings": [],
            "confidence": 0.9,
        }
    )

    class ProfileService:
        async def read_document_profile(self, owner: str, selected: str):
            assert (owner, selected) == (collection_id, document_id)
            return profile

        async def build_document_profile(self, owner: str, selected: str):
            raise AssertionError("the current profile should be reused")

    async def fail_if_parsed(**kwargs):
        raise AssertionError("the current SourceDocument should be reused")

    sources = MemorySourceArtifactRepository()
    await sources.replace_document(
        collection_id,
        SourceDocument(
            document_id=document_id,
            document_order=0,
            title="Paper",
            text="Methods and results",
        ),
    )
    collection_service = CollectionService()
    service = DocumentPreparationService(
        collection_service=collection_service,
        pipeline_run_service=PipelineRunService(),
        source_artifact_repository=sources,
        document_profile_service=ProfileService(),
        source_artifact_builder=fail_if_parsed,
        max_concurrency=1,
    )

    result = await service.run_document_preparation(
        "task_test",
        collection_id,
        document_id,
    )

    assert result["status"] == "completed"
    assert collection_service.document.status == "ready"


async def test_reference_failure_keeps_source_preparation_ready_with_warning(
    monkeypatch,
) -> None:
    collection_id = "col_reference_warning"
    document_id = "doc_reference_warning"
    document = Document(
        document_id=document_id,
        original_filename="paper.pdf",
        stored_filename="paper.pdf",
        storage_key=f"{collection_id}/input/paper.pdf",
        sha256="e" * 64,
        media_type="application/pdf",
        status="stored",
        size_bytes=100,
        created_at="2026-08-28T10:00:00+00:00",
    )

    class CollectionService:
        def __init__(self) -> None:
            self.document = document

        async def get_document(self, owner: str, selected: str) -> Document:
            assert (owner, selected) == (collection_id, document_id)
            return self.document

        async def update_document_preparation(
            self, owner: str, selected: str, **fields
        ) -> Document:
            assert (owner, selected) == (collection_id, document_id)
            self.document = replace(self.document, **fields)
            return self.document

    class RunService:
        async def update_run(self, run_id: str, **fields):
            return {"run_id": run_id, **fields}

        async def finish_run(self, run_id: str, **fields):
            return {"run_id": run_id, **fields}

    class ProfileService:
        async def read_document_profile(self, *_args):
            return None

        async def build_document_profile(self, *_args):
            return DocumentProfile.from_mapping(
                {
                    "document_id": document_id,
                    "title": "Paper",
                    "doc_type": "experimental",
                    "profile_warnings": [],
                    "confidence": 0.9,
                }
            )

    async def parse_document(_collection_id, _document):
        return SourceDocument(
            document_id=document_id,
            document_order=0,
            title="Paper",
            text="Methods and results",
        )

    def fail_reference_extraction(self, _documents):
        raise RuntimeError("reference parser unavailable")

    monkeypatch.setattr(SourceReferenceExtractionService, "extract", fail_reference_extraction)
    service = DocumentPreparationService(
        collection_service=CollectionService(),
        pipeline_run_service=RunService(),
        source_artifact_repository=MemorySourceArtifactRepository(),
        document_profile_service=ProfileService(),
        source_artifact_builder=None,
        max_concurrency=1,
    )
    service._parse_document = parse_document

    result = await service.run_document_preparation(
        "run_reference_warning",
        collection_id,
        document_id,
    )

    assert result["status"] == "completed"
    assert result["warnings"] == [
        "Source reference extraction failed; Source remains available."
    ]


async def test_document_preparation_does_not_build_paper_map_before_objective_selection() -> None:
    collection_id = "col_lazy_map"
    document_id = "doc_lazy_map"
    base_document = Document(
        document_id=document_id,
        original_filename="paper.pdf",
        stored_filename="paper.pdf",
        storage_key="col_lazy_map/inputs/paper.pdf",
        sha256="d" * 64,
        media_type="application/pdf",
        status="stored",
        size_bytes=100,
        created_at="2026-08-28T10:00:00+00:00",
    )
    source_identity, _profile_identity = (
        DocumentPreparationService.fingerprints_for(base_document)
    )
    base_document = replace(base_document, source_fingerprint=source_identity)

    class CollectionService:
        def __init__(self) -> None:
            self.document = base_document

        async def get_document(self, owner: str, selected: str) -> Document:
            assert (owner, selected) == (collection_id, document_id)
            return self.document

        async def update_document_preparation(
            self,
            owner: str,
            selected: str,
            **fields,
        ) -> Document:
            assert (owner, selected) == (collection_id, document_id)
            self.document = replace(self.document, **fields)
            return self.document

    class PipelineRunService:
        async def update_run(self, run_id: str, **fields):
            return {"run_id": run_id, **fields}

        async def finish_run(self, run_id: str, **fields):
            return {"run_id": run_id, **fields}

    class ProfileService:
        async def read_document_profile(self, owner: str, selected: str):
            return None

        async def build_document_profile(self, owner: str, selected: str):
            return DocumentProfile.from_mapping(
                {
                    "document_id": document_id,
                    "title": "Paper",
                    "doc_type": "experimental",
                    "profile_warnings": [],
                    "confidence": 0.9,
                }
            )

    collection_service = CollectionService()
    source_repository = MemorySourceArtifactRepository()
    await source_repository.replace_document(
        collection_id,
        SourceDocument(
            document_id=document_id,
            document_order=0,
            title="Paper",
            text="Abstract",
        ),
    )
    service = DocumentPreparationService(
        collection_service=collection_service,
        pipeline_run_service=PipelineRunService(),
        source_artifact_repository=source_repository,
        document_profile_service=ProfileService(),
        max_concurrency=1,
    )

    result = await service.run_document_preparation(
        "task_lazy_map",
        collection_id,
        document_id,
    )

    assert result["status"] == "completed"
    assert collection_service.document.status == "ready"
