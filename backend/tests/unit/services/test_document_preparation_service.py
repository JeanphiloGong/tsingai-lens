from dataclasses import replace

import pytest

from application.source.document_preparation_service import (
    DocumentPreparationService,
    paper_map_fingerprint,
    profile_fingerprint,
    source_fingerprint,
)
from domain.core import DocumentProfile, PaperSkim
from domain.source import Document, SourceDocument
from infra.persistence.memory import (
    MemoryPaperMapRepository,
    MemorySourceArtifactRepository,
)


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
    paper_map_v1 = paper_map_fingerprint(
        profile_fingerprint=profile_v1,
        paper_map_version="paper-map.v1",
    )

    assert source_v1 == source_fingerprint(
        sha256="a" * 64,
        parser_version="source-runtime.v1",
    )
    assert profile_v1 == profile_fingerprint(
        source_fingerprint=source_v1,
        profile_version="document-profile.v1",
    )
    assert paper_map_v1 != paper_map_fingerprint(
        profile_fingerprint=profile_v1,
        paper_map_version="paper-map.v2",
    )

    profile_v2 = profile_fingerprint(
        source_fingerprint=source_v1,
        profile_version="document-profile.v2",
    )
    assert profile_v2 != profile_v1
    assert paper_map_v1 != paper_map_fingerprint(
        profile_fingerprint=profile_v2,
        paper_map_version="paper-map.v1",
    )

    source_v2 = source_fingerprint(
        sha256="a" * 64,
        parser_version="source-runtime.v2",
    )
    assert source_v2 != source_v1
    assert profile_v1 != profile_fingerprint(
        source_fingerprint=source_v2,
        profile_version="document-profile.v1",
    )


async def test_paper_map_change_reuses_current_source_and_profile() -> None:
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
    source_identity, profile_identity, preparation_identity = (
        DocumentPreparationService.fingerprints_for(base_document)
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

    class TaskService:
        async def update_task(self, task_id: str, **fields):
            return {"task_id": task_id, **fields}

        async def finish_task(self, task_id: str, **fields):
            return {"task_id": task_id, **fields}

    profile = DocumentProfile.from_mapping(
        {
            "document_id": document_id,
            "collection_id": collection_id,
            "title": "Paper",
            "doc_type": "experimental",
            "parsing_warnings": [],
            "confidence": 0.9,
        }
    )

    class ProfileService:
        async def read_document_profile(self, owner: str, selected: str):
            assert (owner, selected) == (collection_id, document_id)
            return profile

        async def build_document_profile(self, owner: str, selected: str):
            raise AssertionError("the current profile should be reused")

    class PaperMapService:
        calls = 0

        def build_document_paper_map(self, owner: str, **kwargs) -> PaperSkim:
            assert owner == collection_id
            self.calls += 1
            return PaperSkim.from_mapping(
                {
                    "document_id": document_id,
                    "doc_role": "primary_experiment",
                    "studies": [],
                    "evidence_density": "low",
                    "confidence": 0.7,
                }
            )

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
    paper_maps = MemoryPaperMapRepository()
    await paper_maps.replace(
        collection_id,
        PaperSkim.from_mapping(
            {
                "document_id": document_id,
                "doc_role": "primary_experiment",
                "studies": [],
                "evidence_density": "low",
                "confidence": 0.6,
            }
        ),
    )
    collection_service = CollectionService()
    paper_map_service = PaperMapService()
    service = DocumentPreparationService(
        collection_service=collection_service,
        task_service=TaskService(),
        source_artifact_repository=sources,
        document_profile_service=ProfileService(),
        paper_map_repository=paper_maps,
        paper_skim_service=paper_map_service,
        response_client=object(),
        source_artifact_builder=fail_if_parsed,
        max_concurrency=1,
    )

    result = await service.run_task(
        "task_test",
        collection_id,
        document_id,
    )

    assert result["status"] == "completed"
    assert paper_map_service.calls == 1
    assert collection_service.document.status == "ready"
    assert (
        collection_service.document.preparation_fingerprint
        == preparation_identity
    )
