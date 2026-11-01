
from infra.persistence import database
"""Preparation keeps traceable Source on Profile failure and reuses it on retry."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.source import (
    collection_service,
    document_preparation_service as preparation,
)
from application.core.document_profiles import service as profiles
from domain.core.document_profile import DocumentProfile
from domain.source import SourceDocument
from repositories.pipeline_run_repository import PipelineRunRepo
from repositories.source_artifact_repository import SourceArtifactRepo
from tests.support.postgres import seed_collection

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def prepared_inputs(postgres_session_factory, monkeypatch, collection_workspace):
    await seed_collection(
        postgres_session_factory, "prepare-papers", document_ids=("paper-a",)
    )
    parse = AsyncMock(
        return_value=SourceDocument(
            document_id="paper-a",
            document_order=0,
            title="LPBF",
            text="Methods and measured porosity",
        )
    )
    monkeypatch.setattr(preparation, "_parse_document_sources", parse)
    monkeypatch.setattr(
        preparation.source_reference_extraction_service,
        "extract_source_references",
        lambda _: (_ for _ in ()).throw(ValueError("no reference boundary")),
    )
    return SimpleNamespace(
        factory=postgres_session_factory, parse=parse, workspace=collection_workspace
    )


async def test_profile_retry_preserves_sources_and_reuses_them(
    prepared_inputs, monkeypatch
):
    ctx = prepared_inputs
    build = AsyncMock(
        side_effect=[
            DocumentProfile(
                "paper-a",
                "LPBF",
                "uncertain",
                ("document_profile_extraction_failed",),
                0,
                profile_status="extraction_failed",
            ),
            DocumentProfile("paper-a", "LPBF", "experimental", (), 0.9),
        ]
    )

    # Real Profile builder binds fingerprints; the boundary stub supplies the same facts.
    async def profile(
        owner, document_id, *, source_fingerprint, profile_fingerprint, extractor
    ):
        from dataclasses import replace

        result = await build()
        return replace(
            result,
            source_fingerprint=source_fingerprint,
            profile_fingerprint=profile_fingerprint,
        )

    monkeypatch.setattr(profiles, "build_document_profile", profile)
    first = await preparation.queue_document_preparation(
        "prepare-papers", "paper-a", user_id="user-1"
    )
    job = await PipelineRunRepo.claim_next_document_preparation_job(
        worker_id="worker-a", lease_duration=timedelta(seconds=60)
    )
    result = await preparation.execute_document_preparation_job(
        job,
        workspace=ctx.workspace,
        object_store=object(),
        source_artifact_builder=object(),
        profile_extractor=object(),
    )
    assert result.status == "partial_success"
    assert (
        await SourceArtifactRepo.read_document("prepare-papers", "paper-a") is not None
    )
    second = await preparation.queue_document_preparation(
        "prepare-papers", "paper-a", user_id="user-1"
    )
    assert second.run_id != first.run_id
    job = await PipelineRunRepo.claim_next_document_preparation_job(
        worker_id="worker-b", lease_duration=timedelta(seconds=60)
    )
    result = await preparation.execute_document_preparation_job(
        job,
        workspace=ctx.workspace,
        object_store=object(),
        source_artifact_builder=object(),
        profile_extractor=object(),
    )
    assert result.status == "completed"
    assert (
        await collection_service.get_document("prepare-papers", "paper-a")
    ).document.status == "ready"
    assert ctx.parse.await_count == 1
    reused = await preparation.queue_document_preparation(
        "prepare-papers", "paper-a", user_id="user-1"
    )
    assert reused.run_id == second.run_id
    assert (
        await PipelineRunRepo.claim_next_document_preparation_job(
            worker_id="worker-c", lease_duration=timedelta(seconds=60)
        )
        is None
    )


async def test_parser_failure_is_terminal_and_safe(prepared_inputs, monkeypatch):
    ctx = prepared_inputs
    ctx.parse.side_effect = OSError("private provider path /private/key")
    run = await preparation.queue_document_preparation(
        "prepare-papers", "paper-a", user_id="user-1"
    )
    job = await PipelineRunRepo.claim_next_document_preparation_job(
        worker_id="worker", lease_duration=timedelta(seconds=60)
    )
    failed = await preparation.execute_document_preparation_job(
        job,
        workspace=ctx.workspace,
        object_store=object(),
        source_artifact_builder=object(),
        profile_extractor=object(),
    )
    assert failed.status == "failed"
    assert "/private" not in str(failed)
    assert (
        await preparation.queue_document_preparation(
            "prepare-papers", "paper-a", user_id="user-1"
        )
    ).run_id != run.run_id


async def test_submission_does_not_execute_in_web(prepared_inputs, monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(preparation, "execute_document_preparation_job", execute)
    first = await preparation.queue_document_preparation(
        "prepare-papers", "paper-a", user_id="user-1"
    )
    again = await preparation.queue_document_preparation(
        "prepare-papers", "paper-a", user_id="user-1"
    )
    assert first.status == "queued" and again.run_id == first.run_id
    execute.assert_not_awaited()


@pytest.mark.parametrize("stage", ["source", "profile"])
async def test_preparation_takeover_rejects_late_stage_publication(
    prepared_inputs, monkeypatch, stage
):
    from datetime import datetime, timezone
    from sqlalchemy import update
    from infra.persistence.postgres.models.pipeline_run import PipelineRunORM
    from repositories.document_profile_repository import DocumentProfileRepo
    from repositories.pipeline_run_repository import PipelineLeaseLostError

    ctx = prepared_inputs
    run = await preparation.queue_document_preparation(
        "prepare-papers", "paper-a", user_id="user-1"
    )
    original = await PipelineRunRepo.claim_next_document_preparation_job(
        worker_id="original", lease_duration=timedelta(seconds=60)
    )
    replacements = []

    async def take_over():
        async with ctx.factory() as db, db.begin():
            await db.execute(
                update(PipelineRunORM)
                .where(PipelineRunORM.run_id == run.run_id)
                .values(
                    lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
                )
            )
        replacements.append(
            await PipelineRunRepo.claim_next_document_preparation_job(
                worker_id="replacement", lease_duration=timedelta(seconds=60)
            )
        )

    async def parse(*args, **kwargs):
        if stage == "source" and not replacements:
            await take_over()
        return SourceDocument("paper-a", 0, "LPBF", "Methods and measured porosity")

    async def profile(
        owner, document_id, *, source_fingerprint, profile_fingerprint, extractor
    ):
        if stage == "profile" and not replacements:
            await take_over()
        return DocumentProfile(
            document_id,
            "LPBF",
            "experimental",
            (),
            0.9,
            source_fingerprint=source_fingerprint,
            profile_fingerprint=profile_fingerprint,
        )

    ctx.parse.side_effect = parse
    monkeypatch.setattr(profiles, "build_document_profile", profile)
    resources = dict(
        workspace=ctx.workspace,
        object_store=object(),
        source_artifact_builder=object(),
        profile_extractor=object(),
    )
    with pytest.raises(PipelineLeaseLostError):
        await preparation.execute_document_preparation_job(original, **resources)
    assert await DocumentProfileRepo.read("prepare-papers", "paper-a") is None
    source = await SourceArtifactRepo.read_document("prepare-papers", "paper-a")
    assert (source is not None) == (stage == "profile")
    async with database.AsyncSessionLocal() as db, db.begin():
        assert (await PipelineRunRepo.read_run(run.run_id, db=db)).status == "running"
    assert replacements[0].lease_version > original.lease_version

    result = await preparation.execute_document_preparation_job(
        replacements[0], **resources
    )
    assert result.status == "completed"
    assert (
        await collection_service.get_document("prepare-papers", "paper-a")
    ).document.status == "ready"
    assert ctx.parse.await_count == (2 if stage == "source" else 1)
