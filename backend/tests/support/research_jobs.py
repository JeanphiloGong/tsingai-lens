"""Real repository claims and short transactions for scientific persistence fixtures."""

from datetime import timedelta
from infra.persistence import database
from repositories.document_profile_repository import DocumentProfileRepo
from application.source import collection_service
from domain.core.document_profile import DocumentProfile


async def claim_analysis_fixture(
    repository, collection_id, objective_id, analysis_version
):
    job = await repository.claim_next_objective_analysis_job(
        worker_id="scientific-fixture", lease_duration=timedelta(seconds=300)
    )
    if job is None:
        return None
    assert job.analysis.key == (collection_id, objective_id, analysis_version)
    for item in job.analysis.document_inputs:
        await DocumentProfileRepo.replace(
            collection_id,
            DocumentProfile(
                document_id=item.document_id,
                title=item.document_id,
                doc_type="experimental",
                profile_warnings=(),
                confidence=0.9,
                source_fingerprint=item.preparation_fingerprint,
                profile_fingerprint=item.preparation_fingerprint,
            ),
        )
        await collection_service.update_document_preparation(
            collection_id, item.document_id, status="ready"
        )
    if not hasattr(repository, "_fixture_jobs"):
        repository._fixture_jobs = {}
    repository._fixture_jobs[job.analysis.key] = job
    return job.analysis


def analysis_job_fixture(repository, collection_id, objective_id, analysis_version):
    return repository._fixture_jobs[(collection_id, objective_id, analysis_version)]


async def update_pipeline_fixture(repository, run):
    job = await pipeline_job_fixture(repository, run.run_id)
    async with database.AsyncSessionLocal() as db, db.begin():
        return await repository.update_run(run, job=job, db=db)


async def pipeline_job_fixture(repository, run_id):
    jobs = getattr(repository, "_fixture_pipeline_jobs", {})
    if run_id in jobs:
        return jobs[run_id]
    async with database.AsyncSessionLocal() as db, db.begin():
        run = await repository.read_run(run_id, db=db)
    claim = (
        repository.claim_next_document_preparation_job
        if run.pipeline_name == "document_preparation"
        else repository.claim_next_objective_discovery_job
    )
    job = await claim(
        worker_id="pipeline-fixture", lease_duration=timedelta(seconds=300)
    )
    assert job.run.run_id == run_id
    jobs[run_id] = job
    repository._fixture_pipeline_jobs = jobs
    return job
