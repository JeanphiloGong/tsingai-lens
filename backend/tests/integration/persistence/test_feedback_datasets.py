"""Persisted sample recovery from a real feedback case and source context."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from application.feedback.analysis_handler import FeedbackAnalysisHandler
from application.feedback.analysis_worker import FeedbackAnalysisWorker
from application.feedback.dataset_export_service import FeedbackDatasetExportService
from application.feedback.dataset_service import FeedbackDatasetService
from application.feedback.sample_build_worker import DatasetSampleBuildWorker
from application.feedback.sft_sample_builder import SftSampleBuilder
from application.repositories.feedback_dataset_sample_repository import (
    DatasetSampleActionConflict,
)
from domain.feedback.sample_revision import SampleRevision, SftRevisionContent
from infra.persistence.postgres.analysis_job_repository import (
    PostgresAnalysisJobRepository,
)
from infra.persistence.postgres.feedback_dataset_export_repository import (
    PostgresFeedbackDatasetExportRepository,
)
from infra.persistence.postgres.feedback_dataset_repository import (
    PostgresFeedbackDatasetRepository,
)
from infra.persistence.postgres.feedback_dataset_sample_repository import (
    PostgresFeedbackDatasetSampleRepository,
)
from infra.persistence.postgres.models.feedback import (
    FeedbackAnnotationRow,
    FeedbackCaseRow,
    FeedbackDatasetSnapshotRow,
    FeedbackReviewDecisionRow,
)
from infra.persistence.postgres.models.feedback_dataset import (
    FeedbackDatasetMigrationRunRow,
    FeedbackDatasetRow,
    FeedbackDatasetSampleRow,
    FeedbackSampleRevisionRow,
)
from scripts.migrate_feedback_task_datasets import _legacy_digest, stable_id
from tests.integration.persistence.test_feedback_workbench import (
    COLLECTION_ID,
    SESSION_ID,
    USER_ID,
    feedback_chain,
)

pytestmark = pytest.mark.anyio


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def test_feedback_analysis_worker_auto_creates_three_task_samples(
    feedback_chain, postgres_session_factory
) -> None:
    chain = feedback_chain
    feedback = await chain.chat_service.set_message_feedback_for_user(
        SESSION_ID,
        chain.answer.message_id,
        USER_ID,
        rating="not_helpful",
        reason="incorrect",
        comment="The figure caption contains the missing preheating condition.",
    )
    assert feedback is not None

    datasets = PostgresFeedbackDatasetRepository(postgres_session_factory)
    samples = PostgresFeedbackDatasetSampleRepository(postgres_session_factory)
    service = FeedbackDatasetService(
        repository=datasets,
        collection_service=chain.collection_service,
        sample_repository=samples,
        case_repository=chain.cases,
    )
    worker = FeedbackAnalysisWorker(
        job_repository=chain.jobs,
        case_repository=chain.cases,
        handler=FeedbackAnalysisHandler(chat_repository=chain.chat),
    )

    terminal = await worker.run_once()
    assert terminal is not None and terminal.status == "succeeded"
    listed = await service.list_records_for_user(
        user_id=USER_ID, collection_id=COLLECTION_ID
    )
    system = {item.dataset.task_type: item.dataset for item in listed}
    assert {"sft", "preference", "evaluation"} <= set(system)
    for dataset in system.values():
        queued = await samples.list_samples(dataset_id=dataset.dataset_id)
        assert len(queued) == 1
        assert queued[0].source_case_id
        assert queued[0].status == "pending"


@pytest.mark.parametrize("task_type", ["sft", "preference", "evaluation"])
async def test_missing_candidate_first_revision_confirmation_and_export(
    task_type, feedback_chain, postgres_session_factory
) -> None:
    chain = feedback_chain
    await chain.chat_service.set_message_feedback_for_user(
        SESSION_ID, chain.answer.message_id, USER_ID, rating="not_helpful", reason="incorrect", comment="Check preheating.")
    await FeedbackAnalysisWorker(job_repository=chain.jobs, case_repository=chain.cases,
        handler=FeedbackAnalysisHandler(chat_repository=chain.chat)).run_once()
    case = (await chain.cases.list_cases(collection_id=COLLECTION_ID))[0]
    datasets = PostgresFeedbackDatasetRepository(postgres_session_factory)
    samples = PostgresFeedbackDatasetSampleRepository(postgres_session_factory)
    service = FeedbackDatasetService(repository=datasets, collection_service=chain.collection_service,
        sample_repository=samples, case_repository=chain.cases)
    dataset = await service.create_for_user(user_id=USER_ID, collection_id=COLLECTION_ID,
        name=f"Preheating {task_type}", task_type=task_type, construction_spec={})
    stored = await service.read_record_for_user(
        user_id=USER_ID, dataset_id=dataset.dataset_id
    )
    assert stored.dataset == dataset
    assert stored.created_at.tzinfo is not None
    assert stored.updated_at == stored.created_at
    listed = await service.list_records_for_user(
        user_id=USER_ID, collection_id=COLLECTION_ID
    )
    listed_by_id = {item.dataset.dataset_id: item for item in listed}
    assert listed_by_id[stored.dataset.dataset_id] == stored
    assert {item.dataset.task_type for item in listed} >= {
        "sft",
        "preference",
        "evaluation",
    }
    collected = await service.collect_cases_for_user(user_id=USER_ID, dataset_id=dataset.dataset_id, source_case_ids=(case.case_id,))
    sample_id = collected.items[0].sample.sample_id
    build_worker = DatasetSampleBuildWorker(
        job_repository=chain.jobs,
        dataset_repository=datasets,
        sample_repository=samples,
        case_repository=chain.cases,
        builder=SftSampleBuilder(),
    )
    # The automatic Collection workbenches may have queued their own samples
    # first. Drain the queue until this explicitly created dataset is built.
    for _ in range(4):
        await build_worker.run_once()
        sample = await samples.read_sample(dataset_id=dataset.dataset_id, sample_id=sample_id)
        if sample is not None and sample.status != "pending":
            break
    sample = await samples.read_sample(dataset_id=dataset.dataset_id, sample_id=sample_id)
    assert sample.status == "needs_input" and sample.current_revision_id is None
    content = {"schema_version": f"literature-{task_type}.v1",
        "messages": [{"role": "user", "content": "Compare A and B's preheating."}],
        "context": [{"document_title": "Paper B", "text": "Preheated at 200 C."}],
        "evidence": [{"document_title": "Paper B", "text": "Preheated at 200 C."}]}
    if task_type == "sft":
        content["target"] = "Paper B was preheated at 200 C."
    elif task_type == "preference":
        content.update(response_a="No preheating.", response_b="Preheated at 200 C.",
            suggested_preference=None, human_preference="b", rationale="Supported by the caption.")
    else:
        content.update(reference="Preheated at 200 C.", criteria=["Reports 200 C without inventing A's condition."],
            evaluation_mode="reference")
    from application.feedback.dataset_service import FeedbackDatasetConflict
    with pytest.raises(FeedbackDatasetConflict, match="stale"):
        await service.update_sample(user_id=USER_ID, dataset_id=dataset.dataset_id, sample_id=sample_id,
            expected_revision_id=None, expected_generation=sample.generation + 1, content=content)
    saved = await service.update_sample(user_id=USER_ID, dataset_id=dataset.dataset_id, sample_id=sample_id,
        expected_revision_id=None, expected_generation=sample.generation, content=content)
    assert saved.status == "needs_confirmation" and saved.confirmed_revision_id is None
    with pytest.raises(FeedbackDatasetConflict, match="stale"):
        await service.update_sample(user_id=USER_ID, dataset_id=dataset.dataset_id, sample_id=sample_id,
            expected_revision_id=None, expected_generation=sample.generation, content=content)
    await service.confirm_sample(user_id=USER_ID, dataset_id=dataset.dataset_id, sample_id=sample_id,
        expected_revision_id=saved.current_revision_id)
    exports = FeedbackDatasetExportService(dataset_service=service, sample_repository=samples,
        repository=PostgresFeedbackDatasetExportRepository(postgres_session_factory))
    preview = await exports.preview_for_user(user_id=USER_ID, dataset_id=dataset.dataset_id, sample_ids=[sample_id])
    assert preview.exportable_count == 1 and not preview.issues
    published = await exports.publish_for_user(user_id=USER_ID, dataset_id=dataset.dataset_id,
        preview_id=preview.preview_id, preview_digest=preview.preview_digest, allow_partial=False, idempotency_key="first-export")
    _, data, _, _ = await exports.download_for_user(user_id=USER_ID, dataset_id=dataset.dataset_id,
        export_id=published.export_id, format="jsonl")
    row = json.loads(data)
    assert "sample_id" not in row and "source_ref" not in json.dumps(row)

    # A withdrawn source invalidates this member only; it must not make the
    # confirmed-member query fail for the whole workbench.
    async with postgres_session_factory.begin() as session:
        source_row = await session.get(FeedbackCaseRow, case.case_id)
        assert source_row is not None
        source_row.status = "withdrawn"
    assert await samples.read_confirmed_members(dataset_id=dataset.dataset_id) == ()

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
    # Drain automatic and superseded jobs before checking the explicitly collected sample.
    while await worker.run_once() is not None:
        pass
    assert (await chain.jobs.read_job(collected.items[0].job.job_id)).status == "succeeded"
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
    recovery_time = datetime.now(timezone.utc) + timedelta(hours=1)
    assert await chain.jobs.recover_expired_jobs(recovery_time.isoformat()) == 1
    recovered_sample = await samples.read_sample(
        dataset_id=dataset.dataset_id, sample_id=sample_id
    )
    assert recovered_sample is not None and recovered_sample.status == "pending"
    reclaimed_job = await chain.jobs.claim_next_dataset_sample_build_job(
        (recovery_time + timedelta(seconds=1)).isoformat()
    )
    assert reclaimed_job is not None and reclaimed_job.status == "running"
    assert reclaimed_job.lease_version == rebuild_job.lease_version + 1

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
        created_at=(recovery_time + timedelta(seconds=2)).isoformat(),
        job_id=rebuild_job.job_id,
    )
    assert await samples.complete_build(
        job=rebuild_job, sample_id=sample_id, generation=2,
        revision=late_revision,
        outcome="candidate",
        finished_at=(recovery_time + timedelta(seconds=2)).isoformat(),
    ) is None
    # The old lease must not cancel or otherwise mutate the replacement lease.
    assert (await chain.jobs.read_job(rebuild_job.job_id)).status == "running"
    unchanged = await samples.read_sample(dataset_id=dataset.dataset_id, sample_id=sample_id)
    assert unchanged is not None and unchanged.current_revision_id == original_revision_id
    assert unchanged.status == "discarded"

    restored = await service.apply_sample_action_for_user(
        user_id=USER_ID, dataset_id=dataset.dataset_id, sample_id=sample_id,
        action="restore", expected_revision_id=original_revision_id,
        reason=None, idempotency_key="restore-1",
    )
    assert restored.status == "needs_confirmation" and restored.confirmed_revision_id is None
    confirmed = await service.confirm_sample(
        user_id=USER_ID, dataset_id=dataset.dataset_id, sample_id=sample_id,
        expected_revision_id=original_revision_id,
    )
    assert confirmed.status == "confirmed"
    assert confirmed.confirmed_revision_id == original_revision_id

    exports = PostgresFeedbackDatasetExportRepository(postgres_session_factory)
    export_service = FeedbackDatasetExportService(
        dataset_service=service,
        sample_repository=samples,
        repository=exports,
    )
    preview = await export_service.preview_for_user(
        user_id=USER_ID, dataset_id=dataset.dataset_id, sample_ids=[sample_id]
    )
    assert preview.requested_count == 1
    assert preview.exportable_count == 1
    assert preview.issues == ()
    published = await export_service.publish_for_user(
        user_id=USER_ID,
        dataset_id=dataset.dataset_id,
        preview_id=preview.preview_id,
        preview_digest=preview.preview_digest,
        allow_partial=False,
        idempotency_key="export-integration-1",
    )
    replayed = await export_service.publish_for_user(
        user_id=USER_ID,
        dataset_id=dataset.dataset_id,
        preview_id=preview.preview_id,
        preview_digest=preview.preview_digest,
        allow_partial=False,
        idempotency_key="export-integration-1",
    )
    assert replayed == published
    assert published.row_count == 1
    model_payload = json.loads(
        (await export_service.download_for_user(
            user_id=USER_ID,
            dataset_id=dataset.dataset_id,
            export_id=published.export_id,
            format="jsonl",
        ))[1].decode("utf-8")
    )
    assert model_payload["context"][0]["document_title"] == "Paper B"
    assert model_payload["messages"][-1]["role"] == "assistant"
    assert "source-b-caption" not in json.dumps(model_payload, ensure_ascii=False)
    trace_payload = json.loads(
        (await export_service.download_for_user(
            user_id=USER_ID,
            dataset_id=dataset.dataset_id,
            export_id=published.export_id,
            format="provenance",
        ))[1].decode("utf-8")
    )
    assert trace_payload["source_refs"] == ["source-b-caption"]

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
    from application.repositories.feedback_dataset_sample_repository import (
        sample_action_digest,
    )

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


@pytest.mark.parametrize("stale_outcome", ["candidate", "failed", "needs_input"])
async def test_reclaimed_build_rejects_old_lease_completion(
    feedback_chain, postgres_session_factory, stale_outcome
) -> None:
    chain = feedback_chain
    await chain.chat_service.set_message_feedback_for_user(
        SESSION_ID, chain.answer.message_id, USER_ID, rating="not_helpful", reason="incorrect",
    )
    await FeedbackAnalysisWorker(
        job_repository=chain.jobs, case_repository=chain.cases,
        handler=FeedbackAnalysisHandler(chat_repository=chain.chat),
    ).run_once()
    case = (await chain.cases.list_cases(collection_id=COLLECTION_ID))[0]
    datasets = PostgresFeedbackDatasetRepository(postgres_session_factory)
    samples = PostgresFeedbackDatasetSampleRepository(postgres_session_factory)
    service = FeedbackDatasetService(
        repository=datasets, collection_service=chain.collection_service,
        sample_repository=samples, case_repository=chain.cases,
    )
    dataset = await service.create_for_user(
        user_id=USER_ID, collection_id=COLLECTION_ID, name="Lease test", task_type="sft",
        construction_spec={},
    )
    collected = await service.collect_cases_for_user(
        user_id=USER_ID, dataset_id=dataset.dataset_id, source_case_ids=(case.case_id,),
    )
    sample = collected.items[0].sample
    # Keep the recovery scenario focused on this sample's lease.
    async with postgres_session_factory.begin() as session:
        from infra.persistence.postgres.models.feedback import AnalysisJobRow
        other_jobs = await session.scalars(select(AnalysisJobRow).where(
            AnalysisJobRow.job_type == "dataset_sample_build",
            AnalysisJobRow.job_id != collected.items[0].job.job_id,
        ))
        for job in other_jobs:
            job.available_at = datetime.now(timezone.utc) + timedelta(days=1)
    old = await chain.jobs.claim_next_dataset_sample_build_job(_now())
    assert old is not None
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    assert await chain.jobs.recover_expired_jobs(later.isoformat()) == 1
    assert await samples.complete_build(
        job=old, sample_id=sample.sample_id, generation=sample.generation,
        revision=None, outcome="failed", error_code="old_worker_failed", finished_at=later.isoformat(),
    ) is None
    assert (await chain.jobs.read_job(old.job_id)).status == "pending"
    next_worker = PostgresAnalysisJobRepository(postgres_session_factory, worker_id="replacement-worker")
    new = await next_worker.claim_next_dataset_sample_build_job(later.isoformat())
    assert new is not None and new.lease_version == old.lease_version + 1
    revision = SampleRevision.build_worker(
        revision_id=f"revision_{uuid4().hex[:32]}", sample_id=sample.sample_id, revision_no=1,
        content=SftRevisionContent.from_mapping({
            "schema_version": "literature-sft.v1",
            "messages": [{"role": "user", "content": "Compare A and B."}],
            "context": [{"document_title": "B", "text": "Preheated at 200 C."}],
            "target": "B used 200 C.",
            "evidence": [{"document_title": "B", "text": "Preheated at 200 C."}],
        }),
        input_digest=sample.source_digest, construction_spec_version=dataset.spec_version,
        provenance={}, created_at=later.isoformat(), job_id=old.job_id,
    )
    assert await samples.complete_build(
        job=old, sample_id=sample.sample_id, generation=sample.generation,
        revision=revision if stale_outcome == "candidate" else None, outcome=stale_outcome,
        error_code="old_worker_failed" if stale_outcome == "failed" else None,
        finished_at=later.isoformat(),
    ) is None
    stored = await samples.read_sample(dataset_id=dataset.dataset_id, sample_id=sample.sample_id)
    assert stored.status == "building" and stored.current_revision_id is None
    assert await samples.read_revision(revision.revision_id) is None
    assert await chain.jobs.read_job(new.job_id) == new
    assert await samples.complete_build(
        job=replace(new, worker_id="wrong-worker"), sample_id=sample.sample_id,
        generation=sample.generation, revision=None, outcome="failed", error_code="wrong_worker",
        finished_at=later.isoformat(),
    ) is None
    assert await samples.complete_build(
        job=new, sample_id=sample.sample_id, generation=sample.generation,
        revision=None, outcome="failed", error_code="expired_worker",
        finished_at=new.lease_expires_at,
    ) is None
    assert await chain.jobs.read_job(new.job_id) == new
    finished = await samples.complete_build(
        job=new, sample_id=sample.sample_id, generation=sample.generation,
        revision=revision, outcome="candidate", finished_at=(later + timedelta(seconds=1)).isoformat(),
    )
    assert finished.status == "needs_confirmation"
    assert await samples.complete_build(
        job=old, sample_id=sample.sample_id, generation=sample.generation,
        revision=None, outcome="failed", error_code="old_worker_failed",
        finished_at=(later + timedelta(seconds=2)).isoformat(),
    ) is None
    assert (await chain.jobs.read_job(new.job_id)).status == "succeeded"


async def test_d7_migration_cli_is_one_way_idempotent_and_audited(
    feedback_chain, postgres_session_factory
) -> None:
    """Exercise the real legacy-to-maintained-dataset cutover in PostgreSQL."""

    chain = feedback_chain
    legacy_snapshot_id = "legacy_snapshot_migration"
    case_id = "legacy_case_migration"
    annotation_id = "legacy_annotation_migration"
    review_id = "legacy_review_migration"
    created_at = datetime.fromisoformat("2026-09-28T00:00:00+00:00")
    annotation_digest = "c" * 64
    row = {
        "messages": [
            {"role": "user", "content": "Compare the preheating evidence in Paper A and Paper B."}
        ],
        "target": "Paper B reports preheating at 200 C in Figure 3.",
        "evidence": [
            {"document_title": "Paper B", "quote": "Figure 3 caption records preheating at 200 C."}
        ],
    }
    async with postgres_session_factory() as session:
        session.add(
            FeedbackCaseRow(
                case_id=case_id,
                collection_id=COLLECTION_ID,
                session_id=SESSION_ID,
                anchor_message_id=chain.answer.message_id,
                source_signal_ids=[],
                analysis_result_ids=[],
                signal_analysis_result_ids=[],
                tool_failure_analysis_result_ids=[],
                context_snapshot={
                    "question": "Compare the preheating evidence in Paper A and Paper B.",
                    "answer": "Paper B has no preheating information.",
                },
                status="accepted",
                created_at=created_at,
                updated_at=created_at,
                annotation_digest=annotation_digest,
            )
        )
        await session.flush()
        session.add(
            FeedbackAnnotationRow(
                annotation_id=annotation_id,
                case_id=case_id,
                version=1,
                problem_type="source_missing",
                severity="high",
                target=row["target"],
                support_source_refs=["source-b-caption"],
                dataset_uses=["sft"],
                reason="The figure caption supplies the omitted evidence.",
                annotation_digest=annotation_digest,
                created_by=USER_ID,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        session.add(
            FeedbackReviewDecisionRow(
                decision_id=review_id,
                case_id=case_id,
                annotation_digest=annotation_digest,
                decision="accept",
                reason="Checked before the legacy snapshot was published.",
                created_by=USER_ID,
                seq=1,
                created_at=created_at,
            )
        )
        session.add(
            FeedbackDatasetSnapshotRow(
                dataset_id=legacy_snapshot_id,
                owner_id=USER_ID,
                collection_id=COLLECTION_ID,
                dataset_type="sft",
                rows=[row],
                exclusions=[],
                provenance={"items": [{"case_id": case_id, "row_digest": _legacy_digest(row)}]},
                manifest={"dataset_id": legacy_snapshot_id},
                manifest_digest="a" * 64,
                provenance_digest="b" * 64,
                content_digest="d" * 64,
                row_count=1,
                excluded_count=0,
                created_at=created_at,
            )
        )
        await session.commit()

    backend_root = Path(__file__).resolve().parents[3]
    migration_script = backend_root / "scripts" / "migrate_feedback_task_datasets.py"
    environment = os.environ.copy()
    environment["LENS_DATABASE_URL"] = environment["LENS_TEST_DATABASE_URL"]

    def run(*args: str) -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, str(migration_script), *args],
            cwd=backend_root,
            env=environment,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    dry_run = run()
    assert dry_run["mode"] == "dry_run"
    assert dry_run["sample_candidates"] == 1
    assert dry_run["created_datasets"] == 0

    first_apply = run("--apply")
    assert first_apply["mode"] == "apply"
    assert first_apply["created_datasets"] == 1
    assert first_apply["created_samples"] == 1
    assert first_apply["created_revisions"] == 1

    migrated_dataset_id = stable_id("fdset_mig", legacy_snapshot_id)
    async with postgres_session_factory() as session:
        dataset = await session.get(FeedbackDatasetRow, migrated_dataset_id)
        sample = await session.scalar(
            select(FeedbackDatasetSampleRow).where(
                FeedbackDatasetSampleRow.dataset_id == migrated_dataset_id,
                FeedbackDatasetSampleRow.source_case_id == case_id,
            )
        )
        assert dataset is not None
        assert dataset.dataset_id != legacy_snapshot_id
        assert sample is not None
        assert sample.status == "needs_confirmation"
        assert sample.current_revision_id is not None
        original_revision_id = sample.current_revision_id
        revision = await session.get(FeedbackSampleRevisionRow, original_revision_id)
        assert revision is not None
        assert revision.content["target"] == row["target"]

    second_apply = run("--apply")
    assert second_apply["mode"] == "apply"
    assert second_apply["created_datasets"] == 0
    assert second_apply["created_samples"] == 0
    assert second_apply["created_revisions"] == 0
    assert second_apply["existing_datasets"] == 1
    assert second_apply["existing_samples"] == 1

    async with postgres_session_factory() as session:
        sample = await session.scalar(
            select(FeedbackDatasetSampleRow).where(
                FeedbackDatasetSampleRow.dataset_id == migrated_dataset_id,
                FeedbackDatasetSampleRow.source_case_id == case_id,
            )
        )
        assert sample is not None
        assert sample.current_revision_id == original_revision_id
        runs = list(
            (
                await session.scalars(
                    select(FeedbackDatasetMigrationRunRow).order_by(
                        FeedbackDatasetMigrationRunRow.created_at
                    )
                )
            ).all()
        )
        assert [item.mode for item in runs] == ["dry_run", "apply", "apply"]
        assert [item.status for item in runs] == ["planned", "applied", "applied"]
