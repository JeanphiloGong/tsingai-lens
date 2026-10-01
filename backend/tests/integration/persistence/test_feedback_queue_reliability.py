"""Feedback ingestion, source changes, and selected publication against PostgreSQL."""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, select

from application.feedback.analysis_handler import FeedbackAnalysisHandler
from application.feedback.analysis_worker import FeedbackAnalysisWorker
from application.feedback.dataset_export_service import FeedbackDatasetExportService
from application.feedback.dataset_service import FeedbackDatasetService
from application.feedback.dataset_service import FeedbackDatasetConflict
from application.feedback.sample_build_worker import DatasetSampleBuildWorker
from application.feedback.sft_sample_builder import SftSampleBuilder
from domain.feedback.sample_revision import SampleRevision, SftRevisionContent
from infra.persistence.postgres import feedback_dataset_sample_repository as sample_module
from infra.persistence.postgres.feedback_dataset_export_repository import PostgresFeedbackDatasetExportRepository
from infra.persistence.postgres.feedback_dataset_repository import PostgresFeedbackDatasetRepository
from infra.persistence.postgres.feedback_dataset_sample_repository import PostgresFeedbackDatasetSampleRepository
from infra.persistence.postgres.models.feedback import AnalysisJobRow, FeedbackAnalysisResultRow, FeedbackCaseRow
from infra.persistence.postgres.models.feedback_dataset import FeedbackDatasetSampleRow
from infra.persistence.postgres.models.feedback_dataset import FeedbackDatasetRow
from infra.persistence.postgres.models.collection import Collection
from tests.integration.persistence.test_feedback_workbench import COLLECTION_ID, SESSION_ID, USER_ID, feedback_chain

pytestmark = pytest.mark.anyio


def _now():
    return datetime.now(timezone.utc).isoformat()


def _service(chain, factory):
    return FeedbackDatasetService(
        repository=PostgresFeedbackDatasetRepository(factory), collection_service=chain.collection_service,
        sample_repository=PostgresFeedbackDatasetSampleRepository(factory), case_repository=chain.cases,
    )


async def _analyze(chain, answer=None):
    answer = answer or chain.answer
    await chain.chat_service.set_message_feedback_for_user(
        SESSION_ID, answer.message_id, USER_ID, rating="not_helpful", reason="incorrect",
        comment="The figure caption records the missing preheating condition.",
    )
    terminal = await FeedbackAnalysisWorker(
        job_repository=chain.jobs, case_repository=chain.cases,
        handler=FeedbackAnalysisHandler(chat_repository=chain.chat),
    ).run_once()
    assert terminal.status == "succeeded"
    cases = await chain.cases.list_cases(collection_id=COLLECTION_ID)
    return next(case for case in cases if case.anchor_message_id == answer.message_id)


async def _second_case(chain):
    answer = replace(chain.answer, message_id="second-preheat-answer", created_at=_now())
    await chain.chat.save_trajectory(
        session=chain.session.update(user_id=USER_ID, collection_id=COLLECTION_ID, updated_at=_now()),
        messages=(chain.question, chain.answer, answer), tool_calls=(), tool_results=(),
    )
    return await _analyze(chain, answer)


def _content():
    return {
        "schema_version": "literature-sft.v1",
        "messages": [{"role": "user", "content": "Compare the preheating evidence in Paper A and Paper B."}],
        "context": [{"document_title": "Paper B", "text": "Figure 3 caption records preheating at 200 C."}],
        "target": "Paper B records 200 C preheating; this source does not establish Paper A's condition.",
        "evidence": [{"document_title": "Paper B", "text": "Figure 3 caption records preheating at 200 C."}],
    }


async def _confirm_all_sft(chain, service):
    records = await service.list_records_for_user(user_id=USER_ID, collection_id=COLLECTION_ID)
    dataset = next(record.dataset for record in records if record.dataset.task_type == "sft")
    worker = DatasetSampleBuildWorker(
        job_repository=chain.jobs, dataset_repository=service.repository,
        sample_repository=service.sample_repository, case_repository=chain.cases, builder=SftSampleBuilder(),
    )
    while await worker.run_once() is not None:
        pass
    samples = await service.sample_repository.list_samples(dataset_id=dataset.dataset_id)
    confirmed = []
    for sample in samples:
        edited = await service.update_sample(
            user_id=USER_ID, dataset_id=dataset.dataset_id, sample_id=sample.sample_id,
            expected_revision_id=sample.current_revision_id, expected_generation=sample.generation, content=_content(),
        )
        confirmed.append(await service.confirm_sample(
            user_id=USER_ID, dataset_id=dataset.dataset_id, sample_id=sample.sample_id,
            expected_revision_id=edited.current_revision_id,
        ))
    return dataset, tuple(confirmed)


async def test_list_is_read_only_and_withdrawn_case_does_not_hide_normal_case(feedback_chain, postgres_session_factory):
    chain = feedback_chain
    healthy = await _analyze(chain)
    withdrawn = await _second_case(chain)
    async with postgres_session_factory.begin() as session:
        row = await session.get(FeedbackCaseRow, withdrawn.case_id)
        row.status = "withdrawn"
    service = _service(chain, postgres_session_factory)
    before = tuple(job.job_id for job in await chain.jobs.list_jobs())
    for _ in range(2):
        records = await service.list_records_for_user(user_id=USER_ID, collection_id=COLLECTION_ID)
        assert len(records) == 3
        for record in records:
            result = await service.list_samples_for_user(user_id=USER_ID, dataset_id=record.dataset.dataset_id)
            assert result.total == 1
            assert result.items[0].source_case_id == healthy.case_id
    assert tuple(job.job_id for job in await chain.jobs.list_jobs()) == before


@pytest.mark.parametrize("bad_source", ["stale", "withdrawn"])
async def test_selected_publication_ignores_unselected_bad_source(bad_source, feedback_chain, postgres_session_factory):
    chain = feedback_chain
    healthy = await _analyze(chain)
    bad = await _second_case(chain)
    service = _service(chain, postgres_session_factory)
    dataset, samples = await _confirm_all_sft(chain, service)
    chosen = next(sample for sample in samples if sample.source_case_id == healthy.case_id)
    unselected = next(sample for sample in samples if sample.source_case_id == bad.case_id)
    async with postgres_session_factory.begin() as session:
        if bad_source == "stale":
            row = await session.get(FeedbackDatasetSampleRow, unselected.sample_id)
            row.source_digest = "0" * 64
        else:
            row = await session.get(FeedbackCaseRow, bad.case_id)
            row.status = "withdrawn"
    exports = FeedbackDatasetExportService(
        dataset_service=service, sample_repository=service.sample_repository,
        repository=PostgresFeedbackDatasetExportRepository(postgres_session_factory),
    )
    preview = await exports.preview_for_user(user_id=USER_ID, dataset_id=dataset.dataset_id, sample_ids=[chosen.sample_id])
    exported = await exports.publish_for_user(
        user_id=USER_ID, dataset_id=dataset.dataset_id, preview_id=preview.preview_id,
        preview_digest=preview.preview_digest, allow_partial=False, idempotency_key="healthy-only",
    )
    assert len(exported.rows) == 1
    assert exported.members[0].sample_id == chosen.sample_id


async def test_case_and_all_sample_jobs_roll_back_together(feedback_chain, postgres_session_factory, monkeypatch):
    chain = feedback_chain
    original = sample_module._collect_sample
    calls = 0

    async def fail_second_task(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated second queue write failure")
        return await original(*args)

    monkeypatch.setattr(sample_module, "_collect_sample", fail_second_task)
    await chain.chat_service.set_message_feedback_for_user(
        SESSION_ID, chain.answer.message_id, USER_ID, rating="not_helpful", reason="incorrect", comment="Check the caption.",
    )
    failed = await FeedbackAnalysisWorker(
        job_repository=chain.jobs, case_repository=chain.cases,
        handler=FeedbackAnalysisHandler(chat_repository=chain.chat),
    ).run_once()
    assert failed.status == "failed"
    async with postgres_session_factory() as session:
        for model in (FeedbackCaseRow, FeedbackAnalysisResultRow, FeedbackDatasetSampleRow):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        assert await session.scalar(select(func.count()).select_from(AnalysisJobRow).where(
            AnalysisJobRow.job_type == "dataset_sample_build",
        )) == 0


async def test_background_backfill_skips_withdrawn_cases_and_is_idempotent(feedback_chain, postgres_session_factory):
    chain = feedback_chain
    healthy = await _analyze(chain)
    withdrawn = await _second_case(chain)
    async with postgres_session_factory.begin() as session:
        row = await session.get(FeedbackCaseRow, withdrawn.case_id)
        row.status = "withdrawn"
        await session.execute(delete(FeedbackDatasetSampleRow))
        await session.execute(delete(AnalysisJobRow).where(AnalysisJobRow.job_type == "dataset_sample_build"))
    repository = PostgresFeedbackDatasetSampleRepository(postgres_session_factory)
    assert await repository.backfill_existing_cases() == 1
    assert await repository.backfill_existing_cases() == 1
    async with postgres_session_factory() as session:
        samples = list(await session.scalars(select(FeedbackDatasetSampleRow)))
        assert len(samples) == 3 and all(sample.source_case_id == healthy.case_id for sample in samples)
        assert await session.scalar(select(func.count()).select_from(AnalysisJobRow).where(
            AnalysisJobRow.job_type == "dataset_sample_build",
        )) == 3


async def test_historical_backfill_crosses_a_full_batch(feedback_chain, postgres_session_factory):
    chain = feedback_chain
    answers = tuple(replace(chain.answer, message_id=f"historical-answer-{index}", created_at=_now()) for index in range(201))
    await chain.chat.save_trajectory(
        session=chain.session.update(user_id=USER_ID, collection_id=COLLECTION_ID, updated_at=_now()),
        messages=(chain.question, chain.answer, *answers), tool_calls=(), tool_results=(),
    )
    now = datetime.now(timezone.utc)
    async with postgres_session_factory.begin() as session:
        session.add_all([
            FeedbackCaseRow(
                case_id=f"historical-case-{index:03d}", collection_id=COLLECTION_ID,
                session_id=SESSION_ID, anchor_message_id=answer.message_id,
                source_signal_ids=[], analysis_result_ids=[], status="needs_annotation",
                context_snapshot={"question": chain.question.content, "answer": answer.content},
                created_at=now, updated_at=now,
            )
            for index, answer in enumerate(answers)
        ])
    repository = PostgresFeedbackDatasetSampleRepository(postgres_session_factory)
    assert await repository.backfill_existing_cases() == 201
    async with postgres_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(FeedbackDatasetSampleRow)) == 603


async def test_empty_historical_collections_cross_a_full_batch(feedback_chain, postgres_session_factory):
    now = datetime.now(timezone.utc)
    async with postgres_session_factory.begin() as session:
        session.add_all([
            Collection(
                collection_id=f"historical-collection-{index:03d}", owner_user_id=USER_ID,
                name=f"Historical paper collection {index}", status="idle", created_at=now, updated_at=now,
            )
            for index in range(201)
        ])
    repository = PostgresFeedbackDatasetSampleRepository(postgres_session_factory)
    assert await repository.backfill_existing_cases() == 0
    async with postgres_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(FeedbackDatasetRow)) == 606


async def test_source_changed_between_read_and_collect_is_rejected(feedback_chain, postgres_session_factory, monkeypatch):
    chain = feedback_chain
    case = await _analyze(chain)
    service = _service(chain, postgres_session_factory)
    dataset = await service.create_for_user(
        user_id=USER_ID, collection_id=COLLECTION_ID, name="Concurrent SFT", task_type="sft", construction_spec={},
    )
    result = (await chain.cases.read_analysis_results(case.analysis_result_ids))[0]
    original = service.sample_repository.collect

    async def update_source_before_collect(**kwargs):
        await chain.cases.upsert_case_from_analysis(
            result, context_snapshot={"additional_evidence": "Source changed after the HTTP read."}, now=_now(),
        )
        return await original(**kwargs)

    monkeypatch.setattr(service.sample_repository, "collect", update_source_before_collect)
    with pytest.raises(FeedbackDatasetConflict, match="sample_source_stale"):
        await service.collect_cases_for_user(user_id=USER_ID, dataset_id=dataset.dataset_id, source_case_ids=(case.case_id,))
    assert await service.sample_repository.list_samples(dataset_id=dataset.dataset_id) == ()


@pytest.mark.parametrize("scope", ["system", "explicit"])
async def test_new_analysis_preserves_human_revision_and_requires_reconfirmation(scope, feedback_chain, postgres_session_factory):
    chain = feedback_chain
    case = await _analyze(chain)
    service = _service(chain, postgres_session_factory)
    if scope == "explicit":
        dataset = await service.create_for_user(
            user_id=USER_ID, collection_id=COLLECTION_ID, name="Explicit SFT", task_type="sft", construction_spec={},
        )
        await service.collect_cases_for_user(user_id=USER_ID, dataset_id=dataset.dataset_id, source_case_ids=(case.case_id,))
    dataset, samples = await _confirm_all_sft(chain, service)
    before = samples[0]
    result = (await chain.cases.read_analysis_results(case.analysis_result_ids))[0]
    await chain.cases.upsert_case_from_analysis(
        result, context_snapshot={"additional_evidence": "A newly checked table limits the comparison."}, now=_now(),
    )
    after = await service.sample_repository.read_sample(dataset_id=dataset.dataset_id, sample_id=before.sample_id)
    assert after.status == "needs_input"
    assert after.current_revision_id == before.current_revision_id
    assert after.confirmed_revision_id is None
    assert after.generation == before.generation + 1
    assert after.source_digest != before.source_digest
    assert after.missing_reasons == ("source_changed_since_collection",)
    assert await service.sample_repository.read_revision(before.current_revision_id) is not None


async def test_source_change_requeues_confirmed_worker_candidate(feedback_chain, postgres_session_factory):
    chain = feedback_chain
    case = await _analyze(chain)
    result = (await chain.cases.read_analysis_results(case.analysis_result_ids))[0]
    caption = chain.question.source_contexts[-1]
    case = await chain.cases.upsert_case_from_analysis(
        result, context_snapshot={"inspected_sources": [{
            "document_id": caption.document_id, "document_title": caption.document_title,
            "source_ref": caption.source_ref, "quote": caption.quote,
        }]}, now=_now(),
    )
    service = _service(chain, postgres_session_factory)
    dataset = next(record.dataset for record in await service.list_records_for_user(
        user_id=USER_ID, collection_id=COLLECTION_ID,
    ) if record.dataset.task_type == "sft")

    class Generator:
        model_name = "test-grounded-candidate"

        async def generate(self, **kwargs):
            return {"target": "Paper B records 200 C preheating in the supplied caption.", "missing_reasons": []}

    worker = DatasetSampleBuildWorker(
        job_repository=chain.jobs, dataset_repository=service.repository,
        sample_repository=service.sample_repository, case_repository=chain.cases,
        builder=SftSampleBuilder(generator=Generator()),
    )
    while await worker.run_once() is not None:
        pass
    candidate = (await service.sample_repository.list_samples(dataset_id=dataset.dataset_id))[0]
    assert candidate.status == "needs_confirmation"
    before = await service.confirm_sample(
        user_id=USER_ID, dataset_id=dataset.dataset_id, sample_id=candidate.sample_id,
        expected_revision_id=candidate.current_revision_id,
    )
    await chain.cases.upsert_case_from_analysis(
        result, context_snapshot={"additional_evidence": "A new measurement limits the earlier comparison."}, now=_now(),
    )
    after = await service.sample_repository.read_sample(dataset_id=dataset.dataset_id, sample_id=before.sample_id)
    assert after.status == "pending" and after.generation == before.generation + 1
    assert after.current_revision_id == before.current_revision_id and after.confirmed_revision_id is None
    job = await chain.jobs.read_job(after.active_job_id)
    assert job.status == "pending" and job.payload["source_digest"] == after.source_digest


async def test_timed_out_build_releases_sample_and_job_lease(feedback_chain, postgres_session_factory):
    chain = feedback_chain
    await _analyze(chain)
    service = _service(chain, postgres_session_factory)

    class HangingBuilder:
        async def build(self, **kwargs):
            await asyncio.Event().wait()

    worker = DatasetSampleBuildWorker(
        job_repository=chain.jobs, dataset_repository=service.repository,
        sample_repository=service.sample_repository, case_repository=chain.cases,
        builders={task: HangingBuilder() for task in ("sft", "preference", "evaluation")},
        build_timeout_seconds=0.05,
    )
    result = await worker.run_once()
    assert result.status == "failed" and result.error_code == "dataset_sample_build_timeout"
    assert result.worker_id is None and result.lease_expires_at is None
    sample = await service.sample_repository.read_sample(
        dataset_id=result.payload["dataset_id"], sample_id=result.payload["sample_id"],
    )
    assert sample.status == "build_failed" and sample.active_job_id is None


async def test_completion_rechecks_case_after_candidate_generation(feedback_chain, postgres_session_factory):
    chain = feedback_chain
    case = await _analyze(chain)
    repository = PostgresFeedbackDatasetSampleRepository(postgres_session_factory)
    job = await chain.jobs.claim_next_dataset_sample_build_job(_now())
    dataset_id, sample_id = job.payload["dataset_id"], job.payload["sample_id"]
    sample = await repository.read_sample(dataset_id=dataset_id, sample_id=sample_id)
    async with postgres_session_factory.begin() as session:
        row = await session.get(FeedbackCaseRow, case.case_id)
        row.context_snapshot = {**row.context_snapshot, "additional_evidence": "New evidence arrived during generation."}
    revision = SampleRevision.build_worker(
        revision_id="stale-candidate", sample_id=sample_id, revision_no=1,
        content=SftRevisionContent.from_mapping(_content()), input_digest=sample.source_digest,
        construction_spec_version=1, provenance={}, created_at=_now(), job_id=job.job_id,
    )
    completed = await repository.complete_build(
        job=job, sample_id=sample_id, generation=sample.generation, revision=revision,
        outcome="candidate", finished_at=_now(),
    )
    assert completed.status == "needs_input"
    assert completed.current_revision_id is None
    assert await repository.read_revision(revision.revision_id) is None
