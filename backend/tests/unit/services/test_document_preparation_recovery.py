from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from application.core.document_profiles.service import DocumentProfileService
from application.core.document_profiles.extraction import DocumentProfileExtractionError
from application.core.document_profiles.extraction import DocumentProfileModelOutput
from application.pipeline import PipelineRunService
from application.source.document_preparation_service import DocumentPreparationService
from domain.source import Document, SourceDocument
from infra.persistence.memory import (
    MemoryDocumentProfileRepository,
    MemoryPipelineRunRepository,
    MemorySourceArtifactRepository,
)
from tests.support.collection_service import build_test_collection_service


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def preparation(tmp_path):
    collections = build_test_collection_service(tmp_path / "collections")
    collection = await collections.create_collection("LPBF porosity research")
    collection_id = collection["collection_id"]
    document = Document(
        document_id="doc_a",
        original_filename="paper.pdf",
        stored_filename="paper.pdf",
        storage_key=f"{collection_id}/input/paper.pdf",
        sha256="a" * 64,
        media_type="application/pdf",
        status="stored",
        size_bytes=100,
        created_at="2026-09-09T00:00:00+00:00",
    )
    await collections.repository.add_documents(
        collection_id,
        (document,),
        updated_at=document.created_at,
    )
    sources = MemorySourceArtifactRepository()
    profiles = DocumentProfileService(
        collections, sources, MemoryDocumentProfileRepository()
    )
    runs = PipelineRunService(MemoryPipelineRunRepository())
    service = DocumentPreparationService(
        collection_service=collections,
        pipeline_run_service=runs,
        source_artifact_repository=sources,
        document_profile_service=profiles,
        max_concurrency=1,
    )
    return SimpleNamespace(
        service=service,
        collections=collections,
        sources=sources,
        profiles=profiles,
        runs=runs,
        collection_id=collection_id,
        document=document,
    )


@pytest.mark.parametrize("failure_stage", ["read", "running", "processing", "parse"])
async def test_worker_failure_is_terminal_and_retryable(
    preparation, monkeypatch, caplog, failure_stage
):
    ctx = preparation
    run = await ctx.runs.create_run(
        ctx.collection_id,
        "document_preparation",
        scope_type="document",
        scope_id="doc_a",
    )
    failure = OSError("internal path /private/provider/config is unavailable")

    async def fail(*args, **kwargs):
        raise failure

    with monkeypatch.context() as patch:
        if failure_stage == "read":
            patch.setattr(ctx.collections, "get_document", fail)
        elif failure_stage == "running":
            original = ctx.runs.update_run

            async def fail_start(*args, **kwargs):
                if kwargs.get("status") == "running":
                    raise failure
                return await original(*args, **kwargs)

            patch.setattr(ctx.runs, "update_run", fail_start)
        elif failure_stage == "processing":
            patch.setattr(ctx.collections, "update_document_preparation", fail)
        else:
            patch.setattr(ctx.service, "_parse_document", fail)
        with pytest.raises(OSError) as raised:
            await ctx.service.run_document_preparation(
                run["run_id"], ctx.collection_id, "doc_a"
            )
        assert raised.value is failure

    failed = await ctx.runs.get_run(run["run_id"])
    assert failed["status"] == "failed"
    assert failed["finished_at"] is not None
    assert "/private/provider" not in str(failed)
    assert "/private/provider" in caplog.text
    _, created = await ctx.runs.get_or_create_document_run(
        collection_id=ctx.collection_id,
        document_id="doc_a",
        pipeline_name="document_preparation",
        input_fingerprint="retry",
    )
    assert created


async def test_dispatch_failure_does_not_leave_queued_work(preparation, monkeypatch):
    ctx = preparation

    def fail_dispatch(coroutine):
        raise RuntimeError("internal scheduler failure")

    monkeypatch.setattr(
        "application.source.document_preparation_service.create_task", fail_dispatch
    )
    with pytest.raises(RuntimeError, match="could not be scheduled"):
        await ctx.service.queue_document_preparation(ctx.collection_id, "doc_a")
    runs = await ctx.runs.list_runs(collection_id=ctx.collection_id)
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["current_node"] == "dispatch_failed"
    assert not ctx.service._active_workers


@pytest.mark.parametrize("historical_status", [None, "completed", "partial_success"])
async def test_classification_retry_reuses_source_not_failed_profile(
    preparation, monkeypatch, historical_status
):
    ctx = preparation
    parse_calls = 0

    async def parse_document(*args):
        nonlocal parse_calls
        parse_calls += 1
        return SourceDocument(
            document_id="doc_a",
            document_order=0,
            title="Laser power and Ti-6Al-4V porosity",
            text="We varied laser power and measured porosity of Ti-6Al-4V.",
        )

    class Extractor:
        calls = 0

        def extract_document_profile(self, payload):
            self.calls += 1
            if self.calls == 1:
                raise DocumentProfileExtractionError("temporary provider failure")
            return DocumentProfileModelOutput(
                doc_type="experimental", confidence=0.9, profile_warnings=[]
            )

        def consume_last_trace(self):
            return None

    extractor = Extractor()
    ctx.profiles._document_profile_extractor = extractor
    monkeypatch.setattr(ctx.service, "_parse_document", parse_document)
    first = await ctx.service.queue_document_preparation(ctx.collection_id, "doc_a")
    await asyncio.gather(*tuple(ctx.service._active_workers))
    partial = await ctx.runs.get_run(first["run_id"])
    assert partial["status"] == "partial_success"
    assert partial["warnings"]
    assert partial["nodes"]["document_profile"]["status"] == "failed"
    assert (
        await ctx.collections.get_document(ctx.collection_id, "doc_a")
    ).status == "stored"
    source = await ctx.sources.read_document(ctx.collection_id, "doc_a")
    assert source is not None
    if historical_status:
        await ctx.runs.finish_run(first["run_id"], status=historical_status)
        source_id, profile_id = ctx.service.fingerprints_for(ctx.document)
        await ctx.collections.update_document_preparation(
            ctx.collection_id,
            "doc_a",
            status="ready",
            source_fingerprint=source_id,
            profile_fingerprint=profile_id,
            preparation_fingerprint=profile_id,
        )

    retry = await ctx.service.queue_document_preparation(ctx.collection_id, "doc_a")
    assert retry["run_id"] != first["run_id"]
    await asyncio.gather(*tuple(ctx.service._active_workers))
    completed = await ctx.runs.get_run(retry["run_id"])
    assert completed["status"] == "completed"
    assert completed["warnings"] == []
    assert completed["nodes"]["document_profile"]["status"] == "succeeded"
    assert (
        await ctx.collections.get_document(ctx.collection_id, "doc_a")
    ).status == "ready"
    assert await ctx.sources.read_document(ctx.collection_id, "doc_a") == source
    assert parse_calls == 1
    assert extractor.calls == 2
    reused = await ctx.service.queue_document_preparation(ctx.collection_id, "doc_a")
    assert reused["run_id"] == retry["run_id"]
    assert not ctx.service._active_workers


async def test_completed_uncertain_classification_is_reusable(preparation, monkeypatch):
    ctx = preparation

    async def parse_document(*args):
        return SourceDocument(
            document_id="doc_a", document_order=0, title="Paper", text=""
        )

    monkeypatch.setattr(ctx.service, "_parse_document", parse_document)
    first = await ctx.service.queue_document_preparation(ctx.collection_id, "doc_a")
    await asyncio.gather(*tuple(ctx.service._active_workers))
    profile = await ctx.profiles.read_document_profile(ctx.collection_id, "doc_a")
    assert profile.profile_status == "completed"
    assert profile.doc_type == "uncertain"
    assert (await ctx.service.queue_document_preparation(ctx.collection_id, "doc_a"))[
        "run_id"
    ] == first["run_id"]
    assert not ctx.service._active_workers
