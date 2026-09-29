"""Persisted sample recovery from a real feedback case and source context."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from application.feedback.analysis_handler import FeedbackAnalysisHandler
from application.feedback.analysis_worker import FeedbackAnalysisWorker
from application.feedback.dataset_service import FeedbackDatasetService
from application.feedback.sample_build_worker import DatasetSampleBuildWorker
from application.feedback.sft_sample_builder import SftSampleBuilder
from application.repositories.feedback_dataset_sample_repository import DatasetSampleActionConflict
from domain.feedback.sample_revision import SampleRevision
from infra.persistence.postgres.feedback_dataset_repository import PostgresFeedbackDatasetRepository
from infra.persistence.postgres.feedback_dataset_sample_repository import PostgresFeedbackDatasetSampleRepository
from tests.integration.persistence.test_feedback_workbench import (
    COLLECTION_ID,
    SESSION_ID,
    USER_ID,
    feedback_chain,
)


pytestmark = pytest.mark.anyio


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def test_rebuild_discard_restore_and_late_worker_result(
    feedback_chain, postgres_session_factory
) -> None:
    chain = feedback_chain
    await chain.chat_service.set_message_feedback_for_user(
        SESSION_ID,
        chain.answer.message_id,
        USER_ID,
        rating="not_helpful",
        reason="incorrect",
        comment="Paper B's figure caption records preheating at 200 C.",
    )
    await FeedbackAnalysisWorker(
        job_repository=chain.jobs,
        case_repository=chain.cases,
        handler=FeedbackAnalysisHandler(chat_repository=chain.chat),
    ).run_once()
    case = (await chain.cases.list_cases(collection_id=COLLECTION_ID))[0]
    await chain.case_service.save_annotation_for_user(
        case_id=case.case_id,
        user_id=USER_ID,
        expected_digest=None,
        problem_type="source_missing",
        severity="high",
        target="Paper B records preheating at 200 C in Figure 3.",
        support_source_refs=("source-b-caption",),
        dataset_uses=("sft",),
        reason="The figure caption provides the omitted condition.",
        now=_now(),
    )

    datasets = PostgresFeedbackDatasetRepository(postgres_session_factory)
    samples = PostgresFeedbackDatasetSampleRepository(postgres_session_factory)
    service = FeedbackDatasetService(
        repository=datasets,
        collection_service=chain.collection_service,
        sample_repository=samples,
        case_repository=chain.cases,
    )
    dataset = await service.create_for_user(
        user_id=USER_ID,
        collection_id=COLLECTION_ID,
        name="Preheating SFT",
        task_type="sft",
        construction_spec={},
    )
    collected = await service.collect_cases_for_user(
        user_id=USER_ID, dataset_id=dataset.dataset_id, source_case_ids=(case.case_id,)
    )
    sample_id = collected.items[0].sample.sample_id
    worker = DatasetSampleBuildWorker(
        job_repository=chain.jobs,
        dataset_repository=datasets,
        sample_repository=samples,
        case_repository=chain.cases,
        builder=SftSampleBuilder(),
    )
    built = await worker.run_once()
    assert built is not None and built.status == "succeeded"
    candidate = await samples.read_sample(dataset_id=dataset.dataset_id, sample_id=sample_id)
    assert candidate is not None and candidate.status == "needs_confirmation"
    original_revision_id = candidate.current_revision_id
    assert original_revision_id is not None

    rebuilt = await service.apply_sample_action_for_user(
        user_id=USER_ID, dataset_id=dataset.dataset_id, sample_id=sample_id,
        action="rebuild", expected_revision_id=original_revision_id,
        reason="Recheck the figure caption against the reported condition.",
        idempotency_key="rebuild-1",
    )
    assert rebuilt.generation == 2 and rebuilt.status == "pending"
    rebuild_job = await chain.jobs.claim_next_dataset_sample_build_job(_now())
    assert rebuild_job is not None and rebuild_job.status == "running"

    discarded = await service.apply_sample_action_for_user(
        user_id=USER_ID, dataset_id=dataset.dataset_id, sample_id=sample_id,
        action="discard", expected_revision_id=original_revision_id,
        reason=None, idempotency_key="discard-1",
    )
    assert discarded.status == "discarded" and discarded.generation == 3
    previous = await samples.read_revision(original_revision_id)
    assert previous is not None
    late_revision = SampleRevision.build_worker(
        revision_id=f"revision_{uuid4().hex[:32]}",
        sample_id=sample_id,
        revision_no=previous.revision_no + 1,
        content=previous.content,
        input_digest=previous.input_digest,
        construction_spec_version=dataset.spec_version,
        provenance=previous.provenance,
        created_at=_now(),
        job_id=rebuild_job.job_id,
    )
    assert await samples.complete_build(
        job=rebuild_job, sample_id=sample_id, generation=2,
        revision=late_revision, outcome="candidate", finished_at=_now(),
    ) is None
    assert (await chain.jobs.read_job(rebuild_job.job_id)).status == "cancelled"
    unchanged = await samples.read_sample(dataset_id=dataset.dataset_id, sample_id=sample_id)
    assert unchanged is not None and unchanged.current_revision_id == original_revision_id
    assert unchanged.status == "discarded"

    restored = await service.apply_sample_action_for_user(
        user_id=USER_ID, dataset_id=dataset.dataset_id, sample_id=sample_id,
        action="restore", expected_revision_id=original_revision_id,
        reason=None, idempotency_key="restore-1",
    )
    assert restored.status == "needs_confirmation" and restored.confirmed_revision_id is None
    confirmed = await service.confirm_sft_sample(
        user_id=USER_ID, dataset_id=dataset.dataset_id, sample_id=sample_id,
        expected_revision_id=original_revision_id,
    )
    assert confirmed.status == "confirmed"
    assert confirmed.confirmed_revision_id == original_revision_id
    assert await service.apply_sample_action_for_user(
        user_id=USER_ID, dataset_id=dataset.dataset_id, sample_id=sample_id,
        action="discard", expected_revision_id=original_revision_id,
        reason=None, idempotency_key="discard-1",
    ) == discarded

    with pytest.raises(DatasetSampleActionConflict, match="sample_action_identity_conflict"):
        await samples.apply_action(
            dataset_id=dataset.dataset_id, sample_id=sample_id,
            expected_revision_id=original_revision_id, expected_generation=4,
            action="restore", reason=None, actor_id=USER_ID,
            idempotency_key="discard-1", request_digest="a" * 64,
            source_digest=None, job=None, now=_now(),
        )

    concurrent_discards = await asyncio.gather(*(
        service.apply_sample_action_for_user(
            user_id=USER_ID, dataset_id=dataset.dataset_id, sample_id=sample_id,
            action="discard", expected_revision_id=original_revision_id,
            reason=None, idempotency_key="concurrent-discard",
        )
        for _ in range(2)
    ))
    assert concurrent_discards[0] == concurrent_discards[1]
    assert concurrent_discards[0].status == "discarded"
    assert concurrent_discards[0].generation == restored.generation + 1

    # Different keys race against the same generation; only one can restore it.
    from domain.feedback.dataset_sample import sample_action_digest

    restored_in_race = await asyncio.gather(*(
        samples.apply_action(
            dataset_id=dataset.dataset_id, sample_id=sample_id,
            expected_revision_id=original_revision_id,
            expected_generation=concurrent_discards[0].generation,
            action="restore", reason=None, actor_id=USER_ID,
            idempotency_key=f"concurrent-restore-{index}",
            request_digest=sample_action_digest(
                action="restore", expected_revision_id=original_revision_id, reason=None,
            ),
            source_digest=concurrent_discards[0].source_digest,
            job=None, now=_now(),
        )
        for index in range(2)
    ), return_exceptions=True)
    assert sum(isinstance(result, DatasetSampleActionConflict) for result in restored_in_race) == 1
    assert sum(getattr(result, "status", None) == "needs_confirmation" for result in restored_in_race) == 1
