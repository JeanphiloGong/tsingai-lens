"""Real competing workers, expiry, fencing and published-result continuity."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from application.pipeline import pipeline_run_service
from application.source import collection_service
from domain.core import PreparedDocumentInput
from domain.core.document_profile import DocumentProfile
from infra.persistence.postgres.models.pipeline_run import PipelineRunORM
from infra.persistence.postgres.models.objective import ObjectiveAnalysisORM
from repositories.document_profile_repository import DocumentProfileRepo
from repositories.objective_repository import ObjectiveRepo, AnalysisLeaseLostError
from repositories.pipeline_run_repository import PipelineRunRepo, PipelineLeaseLostError
from tests.support.postgres import seed_collection, seed_objective

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _queue_pipeline(factory, kind="document_preparation"):
    await seed_collection(factory, "worker-papers", document_ids=("paper-a",))
    return await pipeline_run_service.create_run(
        "worker-papers",
        kind,
        scope_type="document" if kind == "document_preparation" else "collection",
        scope_id="paper-a" if kind == "document_preparation" else "worker-papers",
        input_fingerprint="fixed-input",
    )


@pytest.mark.parametrize("kind", ["document_preparation", "objective_discovery"])
async def test_two_pipeline_workers_claim_once_and_expired_worker_cannot_write(
    postgres_session_factory, kind
):
    factory = postgres_session_factory
    run = await _queue_pipeline(factory, kind)
    claim = (
        PipelineRunRepo.claim_next_document_preparation_job
        if kind == "document_preparation"
        else PipelineRunRepo.claim_next_objective_discovery_job
    )
    results = await asyncio.gather(
        claim(worker_id="worker-a", lease_duration=timedelta(seconds=60)),
        claim(worker_id="worker-b", lease_duration=timedelta(seconds=60)),
    )
    (first,) = [job for job in results if job is not None]
    await PipelineRunRepo.renew_lease(first, lease_duration=timedelta(seconds=60))
    async with factory() as db, db.begin():
        await db.execute(
            update(PipelineRunORM)
            .where(PipelineRunORM.run_id == run.run_id)
            .values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
    second = await claim(
        worker_id="worker-replacement", lease_duration=timedelta(seconds=60)
    )
    assert second.lease_version == first.lease_version + 1
    with pytest.raises(PipelineLeaseLostError):
        await pipeline_run_service.finish_run(run.run_id, job=first, status="failed")
    with pytest.raises(PipelineLeaseLostError):
        await PipelineRunRepo.renew_lease(first, lease_duration=timedelta(seconds=60))
    completed = await pipeline_run_service.finish_run(
        run.run_id, job=second, status="completed"
    )
    assert completed.status == "completed"
    with pytest.raises(PipelineLeaseLostError):
        await pipeline_run_service.update_run(
            run.run_id, job=second, current_node="late-progress"
        )


async def _queue_analysis(factory):
    await seed_collection(factory, "worker-papers", document_ids=("paper-a",))
    await seed_objective(factory, "worker-papers", "power-porosity")
    await DocumentProfileRepo.replace(
        "worker-papers",
        DocumentProfile(
            document_id="paper-a",
            title="Ti-6Al-4V LPBF",
            doc_type="experimental",
            profile_warnings=(),
            confidence=0.9,
            source_fingerprint="source-a",
            profile_fingerprint="prepared-a",
        ),
    )
    await collection_service.update_document_preparation(
        "worker-papers", "paper-a", status="ready"
    )
    return await ObjectiveRepo.queue_analysis(
        "worker-papers",
        "power-porosity",
        document_inputs=(PreparedDocumentInput("paper-a", "prepared-a"),),
        pipeline_version="worker-test",
        model_name=None,
        prompt_versions={},
    )


async def test_analysis_takeover_fences_all_worker_writes(postgres_session_factory):
    factory = postgres_session_factory
    await _queue_analysis(factory)
    results = await asyncio.gather(
        *[
            ObjectiveRepo.claim_next_objective_analysis_job(
                worker_id=name, lease_duration=timedelta(seconds=60)
            )
            for name in ("worker-a", "worker-b")
        ]
    )
    (first,) = [job for job in results if job is not None]
    async with factory() as db, db.begin():
        await db.execute(
            update(ObjectiveAnalysisORM).values(
                lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
            )
        )
    second = await ObjectiveRepo.claim_next_objective_analysis_job(
        worker_id="replacement", lease_duration=timedelta(seconds=60)
    )
    assert second.lease_version == first.lease_version + 1
    with pytest.raises(AnalysisLeaseLostError):
        await ObjectiveRepo.fail_analysis(
            *first.analysis.key,
            job=first,
            error_code="late_failure",
            error_message="late",
        )
    with pytest.raises(AnalysisLeaseLostError):
        async with factory() as db, db.begin():
            await ObjectiveRepo.publish_experiment_analysis(
                db, *first.analysis.key, job=first
            )
    failed = await ObjectiveRepo.fail_analysis(
        *second.analysis.key,
        job=second,
        error_code="provider_timeout",
        error_message="Retry later",
    )
    assert failed.status == "failed"


async def test_failed_second_analysis_keeps_successful_published_version(
    postgres_session_factory,
):
    factory = postgres_session_factory
    await _queue_analysis(factory)
    first = await ObjectiveRepo.claim_next_objective_analysis_job(
        worker_id="worker-a", lease_duration=timedelta(seconds=60)
    )
    async with factory() as db, db.begin():
        await ObjectiveRepo.publish_experiment_analysis(
            db, *first.analysis.key, job=first
        )
    await ObjectiveRepo.queue_analysis(
        "worker-papers",
        "power-porosity",
        document_inputs=first.analysis.document_inputs,
        pipeline_version="worker-test",
        model_name=None,
        prompt_versions={},
    )
    second = await ObjectiveRepo.claim_next_objective_analysis_job(
        worker_id="worker-b", lease_duration=timedelta(seconds=60)
    )
    await ObjectiveRepo.fail_analysis(
        *second.analysis.key,
        job=second,
        error_code="provider_timeout",
        error_message="Retry later",
    )
    objective = await ObjectiveRepo.read_objective("worker-papers", "power-porosity")
    assert objective.published_analysis_version == first.analysis.analysis_version
    assert (
        await ObjectiveRepo.read_published_analysis("worker-papers", "power-porosity")
    ).status == "succeeded"


async def test_changed_prepared_input_cannot_publish_analysis(postgres_session_factory):
    factory = postgres_session_factory
    await _queue_analysis(factory)
    job = await ObjectiveRepo.claim_next_objective_analysis_job(
        worker_id="worker-a", lease_duration=timedelta(seconds=60)
    )
    await DocumentProfileRepo.replace(
        "worker-papers",
        DocumentProfile(
            document_id="paper-a",
            title="Changed",
            doc_type="experimental",
            profile_warnings=(),
            confidence=0.9,
            profile_fingerprint="prepared-new",
        ),
    )
    with pytest.raises(ValueError, match="input changed"):
        async with factory() as db, db.begin():
            await ObjectiveRepo.publish_experiment_analysis(
                db, *job.analysis.key, job=job
            )
    assert (
        await ObjectiveRepo.read_objective("worker-papers", "power-porosity")
    ).published_analysis_version is None
