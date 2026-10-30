import asyncio
from dataclasses import replace

import pytest
from application.core.document_profiles.extraction import (
    DOCUMENT_PROFILE_PROMPT_VERSION,
)
from application.pipeline import pipeline_run_service
from application.source import document_preparation_service
from application.source import (
    reference_extraction_service as source_reference_extraction_service,
)
from application.source.document_preparation_service import (
    DOCUMENT_ANALYSIS_VERSION,
    profile_fingerprint,
    source_fingerprint,
)
from domain.core import DocumentProfile
from domain.source import Document, SourceDocument
from infra.persistence import database
from repositories.collection_repository import StoredDocument
from repositories.pipeline_run_repository import PipelineRunRepository
from repositories.source_artifact_repository import SourceArtifactRepository
from tests.support.postgres import seed_collection
from utils.logger import bind_request_id, clear_request_id, get_request_id

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


async def test_queued_preparation_inherits_request_trace_without_argument_forwarding(
    document_preparation_runtime,
    monkeypatch, *, postgres_session_factory
) -> None:
    await seed_collection(
        postgres_session_factory, "col_trace", document_ids=("doc_trace",)
    )
    document = StoredDocument(
        document=Document(
            document_id="doc_trace",
            original_filename="paper.pdf",
            sha256="a" * 64,
            media_type="application/pdf",
            status="stored",
            size_bytes=100,
        ),
        stored_filename="paper.pdf",
        storage_key="col_trace/input/paper.pdf",
        created_at="2026-09-09T00:00:00+00:00",
    )

    class CollectionService:
        async def get_collection_for_user(self, collection_id, user_id):
            assert (collection_id, user_id) == ("col_trace", "user-1")
            return {"collection_id": collection_id}

        async def get_document(self, collection_id, document_id):
            assert (collection_id, document_id) == ("col_trace", "doc_trace")
            return document

    document_preparation_service.collection_service = CollectionService()
    document_preparation_service.pipeline_run_service = pipeline_run_service
    document_preparation_service.SourceArtifactRepo = SourceArtifactRepository()
    document_preparation_service.document_profile_service = object()
    document_preparation_runtime._semaphore = asyncio.Semaphore(1)
    pipeline_run_service.PipelineRunRepo = PipelineRunRepository()
    service = document_preparation_runtime
    service._document_profile_extractor = object()
    request_finished = asyncio.Event()
    observed_request_ids = []

    async def run_preparation(run_id, collection_id, document_id):
        await request_finished.wait()
        observed_request_ids.append(get_request_id())
        observed_request_ids.append(await asyncio.to_thread(get_request_id))
        return await pipeline_run_service.finish_run(run_id, status="completed")

    monkeypatch.setattr(service, "run_document_preparation", run_preparation)
    token = bind_request_id("req_preparation_trace")
    try:
        run = await service.queue_document_preparation(
            "col_trace", "doc_trace", user_id="user-1"
        )
        workers = tuple(service._active_workers)
    finally:
        clear_request_id(token)
        request_finished.set()

    await asyncio.gather(*workers)
    assert run.status == "queued"
    assert observed_request_ids == ["req_preparation_trace", "req_preparation_trace"]


async def test_restart_interrupts_orphaned_preparation_without_discarding_artifacts(
    document_preparation_runtime,
    *, postgres_session_factory
) -> None:
    collection_id = "col_restart"
    document_id = "doc_restart"
    await seed_collection(
        postgres_session_factory, collection_id, document_ids=(document_id,)
    )
    original = StoredDocument(
        document=Document(
            document_id=document_id,
            original_filename="paper.pdf",
            sha256="b" * 64,
            media_type="application/pdf",
            status="processing",
            size_bytes=100,
            source_fingerprint="source-current",
            profile_fingerprint="profile-current",
            preparation_fingerprint="paper-map-current",
            parser_version="source-runtime.v1",
        ),
        stored_filename="paper.pdf",
        storage_key="col_restart/inputs/paper.pdf",
        created_at="2026-08-28T01:00:00+00:00",
    )

    class CollectionService:
        def __init__(self) -> None:
            self.document = original

        async def get_document(self, owner: str, selected: str) -> StoredDocument:
            assert (owner, selected) == (collection_id, document_id)
            return self.document

        async def update_document_preparation(
            self,
            owner: str,
            selected: str,
            **fields,
        ) -> StoredDocument:
            assert (owner, selected) == (collection_id, document_id)
            self.document = replace(
                self.document, document=replace(self.document.document, **fields)
            )
            return self.document

    pipeline_run_service.PipelineRunRepo = PipelineRunRepository()
    task, created = await pipeline_run_service.get_or_create_document_run(
        collection_id=collection_id,
        document_id=document_id,
        pipeline_name="document_preparation",
        input_fingerprint="old-preparation-input",
    )
    assert created is True
    await pipeline_run_service.update_run(task.run_id, status="running")
    collection_service = CollectionService()
    document_preparation_service.collection_service = collection_service
    document_preparation_service.pipeline_run_service = pipeline_run_service
    document_preparation_service.SourceArtifactRepo = SourceArtifactRepository()
    document_preparation_service.document_profile_service = object()
    document_preparation_runtime._semaphore = asyncio.Semaphore(1)
    service = document_preparation_runtime
    service._document_profile_extractor = object()

    recovered = await service.recover_interrupted_runs()

    interrupted = await pipeline_run_service.get_run(task.run_id, user_id="user-1")
    assert recovered == 1
    assert interrupted.status == "failed"
    assert interrupted.current_node == "interrupted"
    assert interrupted.timestamps.finished_at is not None
    assert collection_service.document == replace(
        original, document=replace(original.document, status="stored")
    )

    replacement, replacement_created = (
        await pipeline_run_service.get_or_create_document_run(
            collection_id=collection_id,
            document_id=document_id,
            pipeline_name="document_preparation",
            input_fingerprint="old-preparation-input",
        )
    )
    assert replacement_created is True
    assert replacement.run_id != task.run_id


async def test_restart_keeps_preparation_active_when_document_reset_fails(
    document_preparation_runtime,
    *, postgres_session_factory
) -> None:
    collection_id = "col_restart_retry"
    document_id = "doc_restart_retry"
    await seed_collection(
        postgres_session_factory, collection_id, document_ids=(document_id,)
    )
    document = StoredDocument(
        document=Document(
            document_id=document_id,
            original_filename="paper.pdf",
            sha256="c" * 64,
            media_type="application/pdf",
            status="processing",
            size_bytes=100,
        ),
        stored_filename="paper.pdf",
        storage_key="col_restart_retry/inputs/paper.pdf",
        created_at="2026-08-28T01:00:00+00:00",
    )

    class CollectionService:

        async def get_document(self, owner: str, selected: str) -> StoredDocument:
            assert (owner, selected) == (collection_id, document_id)
            return document

        async def update_document_preparation(
            self, *_args, **_fields
        ) -> StoredDocument:
            raise OSError("database temporarily unavailable")

    pipeline_run_service.PipelineRunRepo = PipelineRunRepository()
    task, _created = await pipeline_run_service.get_or_create_document_run(
        collection_id=collection_id,
        document_id=document_id,
        pipeline_name="document_preparation",
        input_fingerprint="preparation-input",
    )
    await pipeline_run_service.update_run(task.run_id, status="running")
    collection_service = CollectionService()
    document_preparation_service.collection_service = collection_service
    document_preparation_service.pipeline_run_service = pipeline_run_service
    document_preparation_service.SourceArtifactRepo = SourceArtifactRepository()
    document_preparation_service.document_profile_service = object()
    document_preparation_runtime._semaphore = asyncio.Semaphore(1)
    service = document_preparation_runtime
    service._document_profile_extractor = object()

    with pytest.raises(OSError, match="temporarily unavailable"):
        await service.recover_interrupted_runs()

    still_active = await pipeline_run_service.get_run(task.run_id, user_id="user-1")
    assert still_active.status == "running"
    assert still_active.timestamps.finished_at is None


async def test_profile_preparation_reuses_current_source_and_profile(
    document_preparation_runtime,
    *, postgres_session_factory
) -> None:
    collection_id = "col_test"
    document_id = "doc_test"
    base_document = StoredDocument(
        document=Document(
            document_id=document_id,
            original_filename="paper.pdf",
            sha256="a" * 64,
            media_type="application/pdf",
            status="failed",
            size_bytes=100,
        ),
        stored_filename="paper.pdf",
        storage_key="col_test/inputs/paper.pdf",
        created_at="2026-08-27T10:00:00+00:00",
    )
    source_identity, profile_identity = document_preparation_service.fingerprints_for(
        base_document.document
    )

    class CollectionService:
        def __init__(self) -> None:
            self.document = replace(
                base_document,
                document=replace(
                    base_document.document,
                    source_fingerprint=source_identity,
                    profile_fingerprint=profile_identity,
                    preparation_fingerprint="outdated-paper-map",
                ),
            )

        async def get_document(self, owner: str, selected: str) -> StoredDocument:
            assert (owner, selected) == (collection_id, document_id)
            return self.document

        async def update_document_preparation(
            self,
            owner: str,
            selected: str,
            **fields,
        ) -> StoredDocument:
            assert (owner, selected) == (collection_id, document_id)
            self.document = replace(
                self.document, document=replace(self.document.document, **fields)
            )
            return self.document


    profile = DocumentProfile(
        document_id=document_id,
        title="Paper",
        doc_type="experimental",
        profile_warnings=(),
        confidence=0.9,
    )

    class ProfileService:
        async def read(self, owner: str, selected: str):
            assert (owner, selected) == (collection_id, document_id)
            return profile

        async def build_document_profile(self, owner: str, selected: str, **_lineage):
            raise AssertionError("the current profile should be reused")

    async def fail_if_parsed(**kwargs):
        raise AssertionError("the current SourceDocument should be reused")

    sources = SourceArtifactRepository()
    await seed_collection(
        database.AsyncSessionLocal, collection_id, document_ids=(document_id,)
    )
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
    document_preparation_service.collection_service = collection_service
    document_preparation_service.pipeline_run_service = pipeline_run_service
    document_preparation_service.SourceArtifactRepo = sources
    profile_service = ProfileService()
    document_preparation_service.document_profile_service = profile_service
    document_preparation_service.DocumentProfileRepo = profile_service
    document_preparation_runtime._source_artifact_builder = fail_if_parsed
    document_preparation_runtime._semaphore = asyncio.Semaphore(1)
    service = document_preparation_runtime
    service._document_profile_extractor = object()

    run = await pipeline_run_service.create_run(
        collection_id, "document_preparation", scope_type="document", scope_id=document_id,
    )
    result = await service.run_document_preparation(
        run.run_id,
        collection_id,
        document_id,
    )

    assert result.status == "completed"
    assert collection_service.document.document.status == "ready"


async def test_reference_failure_keeps_source_preparation_ready_with_warning(
    document_preparation_runtime,
    monkeypatch, *, postgres_session_factory
) -> None:
    collection_id = "col_reference_warning"
    document_id = "doc_reference_warning"
    await seed_collection(
        postgres_session_factory, collection_id, document_ids=(document_id,)
    )
    document = StoredDocument(
        document=Document(
            document_id=document_id,
            original_filename="paper.pdf",
            sha256="e" * 64,
            media_type="application/pdf",
            status="stored",
            size_bytes=100,
        ),
        stored_filename="paper.pdf",
        storage_key=f"{collection_id}/input/paper.pdf",
        created_at="2026-08-28T10:00:00+00:00",
    )

    class CollectionService:
        def __init__(self) -> None:
            self.document = document

        async def get_document(self, owner: str, selected: str) -> StoredDocument:
            assert (owner, selected) == (collection_id, document_id)
            return self.document

        async def update_document_preparation(
            self, owner: str, selected: str, **fields
        ) -> StoredDocument:
            assert (owner, selected) == (collection_id, document_id)
            self.document = replace(
                self.document, document=replace(self.document.document, **fields)
            )
            return self.document


    class ProfileService:
        async def read(self, *_args):
            return None

        async def build_document_profile(self, *_args, **_lineage):
            return DocumentProfile(
                document_id=document_id,
                title="Paper",
                doc_type="experimental",
                profile_warnings=(),
                confidence=0.9,
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

    monkeypatch.setattr(
        source_reference_extraction_service, "extract_source_references", fail_reference_extraction
    )
    document_preparation_service.collection_service = CollectionService()
    document_preparation_service.pipeline_run_service = pipeline_run_service
    document_preparation_service.SourceArtifactRepo = SourceArtifactRepository()
    profile_service = ProfileService()
    document_preparation_service.document_profile_service = profile_service
    document_preparation_service.DocumentProfileRepo = profile_service
    document_preparation_runtime._source_artifact_builder = None
    document_preparation_runtime._semaphore = asyncio.Semaphore(1)
    service = document_preparation_runtime
    service._document_profile_extractor = object()
    monkeypatch.setattr(service, "_parse_document", parse_document)

    run = await pipeline_run_service.create_run(
        collection_id, "document_preparation", scope_type="document", scope_id=document_id,
    )
    result = await service.run_document_preparation(
        run.run_id,
        collection_id,
        document_id,
    )

    assert result.status == "completed"
    assert result.warnings == (
        "Source reference extraction failed; Source remains available.",
    )


async def test_document_preparation_does_not_build_paper_map_before_objective_selection(
    document_preparation_runtime,
    *, postgres_session_factory
) -> None:
    collection_id = "col_lazy_map"
    document_id = "doc_lazy_map"
    base_document = StoredDocument(
        document=Document(
            document_id=document_id,
            original_filename="paper.pdf",
            sha256="d" * 64,
            media_type="application/pdf",
            status="stored",
            size_bytes=100,
        ),
        stored_filename="paper.pdf",
        storage_key="col_lazy_map/inputs/paper.pdf",
        created_at="2026-08-28T10:00:00+00:00",
    )
    source_identity, _profile_identity = document_preparation_service.fingerprints_for(
        base_document.document
    )
    base_document = replace(
        base_document,
        document=replace(base_document.document, source_fingerprint=source_identity),
    )

    class CollectionService:
        def __init__(self) -> None:
            self.document = base_document

        async def get_document(self, owner: str, selected: str) -> StoredDocument:
            assert (owner, selected) == (collection_id, document_id)
            return self.document

        async def update_document_preparation(
            self,
            owner: str,
            selected: str,
            **fields,
        ) -> StoredDocument:
            assert (owner, selected) == (collection_id, document_id)
            self.document = replace(
                self.document, document=replace(self.document.document, **fields)
            )
            return self.document


    class ProfileService:
        async def read(self, owner: str, selected: str):
            return None

        async def build_document_profile(self, owner: str, selected: str, **_lineage):
            return DocumentProfile(
                document_id=document_id,
                title="Paper",
                doc_type="experimental",
                profile_warnings=(),
                confidence=0.9,
            )

    collection_service = CollectionService()
    source_repository = SourceArtifactRepository()
    await seed_collection(
        database.AsyncSessionLocal, collection_id, document_ids=(document_id,)
    )
    await source_repository.replace_document(
        collection_id,
        SourceDocument(
            document_id=document_id,
            document_order=0,
            title="Paper",
            text="Abstract",
        ),
    )
    document_preparation_service.collection_service = collection_service
    document_preparation_service.pipeline_run_service = pipeline_run_service
    document_preparation_service.SourceArtifactRepo = source_repository
    profile_service = ProfileService()
    document_preparation_service.document_profile_service = profile_service
    document_preparation_service.DocumentProfileRepo = profile_service
    document_preparation_runtime._semaphore = asyncio.Semaphore(1)
    service = document_preparation_runtime
    service._document_profile_extractor = object()

    run = await pipeline_run_service.create_run(
        collection_id, "document_preparation", scope_type="document", scope_id=document_id,
    )
    result = await service.run_document_preparation(
        run.run_id,
        collection_id,
        document_id,
    )

    assert result.status == "completed"
    assert collection_service.document.document.status == "ready"
