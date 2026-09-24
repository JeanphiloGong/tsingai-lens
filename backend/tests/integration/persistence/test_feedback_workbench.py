from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from application.chat.session_service import ChatSessionService
from application.feedback.analysis_handler import FeedbackAnalysisHandler
from application.feedback.analysis_worker import FeedbackAnalysisWorker
from application.feedback.dataset_snapshot_service import (
    DatasetSelection,
    DatasetSnapshotService,
    jsonl_bytes_for_rows,
)
from application.feedback.feedback_case_service import FeedbackCaseService
from application.repositories.auth_repository import AuthUserRecord
from application.source.collection_service import CollectionService
from domain.chat import ChatMessage, ChatResourceRef, ChatSession, ChatSourceContext
from domain.source import Collection
from infra.persistence.file.collection_workspace import FileCollectionWorkspace
from infra.persistence.postgres.analysis_job_repository import (
    PostgresAnalysisJobRepository,
)
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.chat_repository import PostgresChatRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from infra.persistence.postgres.dataset_snapshot_repository import (
    PostgresDatasetSnapshotRepository,
)
from infra.persistence.postgres.feedback_case_repository import (
    PostgresFeedbackCaseRepository,
)


pytestmark = pytest.mark.anyio

NOW = "2026-09-24T10:00:00+00:00"
USER_ID = "feedback-chain-user"
COLLECTION_ID = "feedback-chain-collection"
SESSION_ID = "feedback-chain-session"


def _current_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
async def feedback_chain(postgres_session_factory, tmp_path):
    auth = PostgresAuthRepository(postgres_session_factory)
    await auth.add_user(
        AuthUserRecord(
            user_id=USER_ID,
            email="feedback-chain@example.test",
            display_name="Feedback chain researcher",
            password_hash="synthetic-password-hash",
            created_at=NOW,
        )
    )

    collections = PostgresCollectionRepository(postgres_session_factory)
    await collections.add_collection(
        Collection.create(
            collection_id=COLLECTION_ID,
            owner_user_id=USER_ID,
            name="Feedback chain collection",
            description="Persistent workbench integration fixture",
            now_iso=NOW,
        )
    )
    collection_service = CollectionService(
        collections, FileCollectionWorkspace(tmp_path)
    )

    chat = PostgresChatRepository(postgres_session_factory)
    session = ChatSession.create(
        session_id=SESSION_ID,
        user_id=USER_ID,
        collection_id=COLLECTION_ID,
        created_at=NOW,
    )
    await chat.add_session(session)
    source_contexts = (
        ChatSourceContext(
            resource_ref=ChatResourceRef(
                resource_type="source",
                resource_id="doc-a:source-a-results",
                href="/collections/feedback-chain-collection/documents/doc-a",
            ),
            collection_id=COLLECTION_ID,
            document_id="doc-a",
            document_title="Paper A",
            source_kind="text_window",
            source_ref="source-a-results",
            page=2,
            quote="Paper A reports the measured preheating condition.",
            heading_path="Results",
            source_digest="a" * 64,
        ),
        ChatSourceContext(
            resource_ref=ChatResourceRef(
                resource_type="source",
                resource_id="doc-b:source-b-caption",
                href="/collections/feedback-chain-collection/documents/doc-b",
            ),
            collection_id=COLLECTION_ID,
            document_id="doc-b",
            document_title="Paper B",
            source_kind="figure_caption",
            source_ref="source-b-caption",
            page=4,
            quote="Figure 3 caption records preheating at 200 C.",
            heading_path="Results > Figure 3",
            source_digest="b" * 64,
        ),
    )
    question = ChatMessage.user(
        message_id="feedback-chain-question",
        session_id=SESSION_ID,
        content="Compare the preheating evidence in Paper A and Paper B.",
        created_at="2026-09-24T10:00:01+00:00",
        source_contexts=source_contexts,
    )
    answer = ChatMessage.assistant(
        message_id="feedback-chain-answer",
        session_id=SESSION_ID,
        content="Paper B has no preheating information.",
        created_at="2026-09-24T10:00:02+00:00",
    )
    await chat.save_trajectory(
        session=session.update(
            user_id=USER_ID,
            collection_id=COLLECTION_ID,
            updated_at="2026-09-24T10:00:02+00:00",
        ),
        messages=(question, answer),
        tool_calls=(),
        tool_results=(),
    )

    jobs = PostgresAnalysisJobRepository(postgres_session_factory)
    chat_service = ChatSessionService(
        collection_service=collection_service,
        source_artifact_repository=None,
        repository=chat,
        runner=None,
        analysis_job_repository=jobs,
    )
    cases = PostgresFeedbackCaseRepository(postgres_session_factory)
    case_service = FeedbackCaseService(
        case_repository=cases,
        chat_repository=chat,
        collection_service=collection_service,
    )
    snapshots = PostgresDatasetSnapshotRepository(postgres_session_factory)
    snapshot_service = DatasetSnapshotService(
        repository=snapshots,
        case_repository=cases,
        chat_repository=chat,
        collection_service=collection_service,
    )
    return SimpleNamespace(
        auth=auth,
        chat=chat,
        chat_service=chat_service,
        cases=cases,
        case_service=case_service,
        jobs=jobs,
        snapshots=snapshots,
        snapshot_service=snapshot_service,
        collection_service=collection_service,
        session=session,
        question=question,
        answer=answer,
    )


async def test_feedback_workbench_persists_the_complete_reviewed_export_chain(
    feedback_chain,
):
    chain = feedback_chain

    feedback = await chain.chat_service.set_message_feedback_for_user(
        SESSION_ID,
        chain.answer.message_id,
        USER_ID,
        rating="not_helpful",
        reason="incorrect",
        comment="The Paper B figure caption contains the missing evidence.",
    )
    assert feedback is not None
    stored_feedback = await chain.chat.read_feedback_by_id(feedback.feedback_id)
    assert stored_feedback == feedback

    jobs = await chain.jobs.list_jobs(job_type="feedback_analysis", status="pending")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.payload == {"feedback_id": feedback.feedback_id}
    assert job.payload_version == 1
    assert job.idempotency_key == feedback.analysis_version_key

    worker = FeedbackAnalysisWorker(
        job_repository=chain.jobs,
        case_repository=chain.cases,
        handler=FeedbackAnalysisHandler(chat_repository=chain.chat),
    )
    terminal_job = await worker.run_once()
    assert terminal_job is not None
    assert terminal_job.status == "succeeded"
    assert terminal_job.result_id is not None
    saved_job = await chain.jobs.read_job(job.job_id)
    assert saved_job is not None
    assert saved_job.status == "succeeded"
    assert saved_job.result_id == terminal_job.result_id

    cases = await chain.cases.list_cases(
        collection_id=COLLECTION_ID, status="needs_annotation"
    )
    assert len(cases) == 1
    case = cases[0]
    assert case.session_id == SESSION_ID
    assert case.anchor_message_id == chain.answer.message_id
    assert case.source_signal_ids == (feedback.feedback_id,)
    assert case.analysis_result_ids == (terminal_job.result_id,)
    results = await chain.cases.read_analysis_results(case.analysis_result_ids)
    assert len(results) == 1
    result = results[0]
    assert result.feedback_id == feedback.feedback_id
    assert result.problem_type == "fact_error"
    assert result.evidence_coverage.coverage_status == "partial"
    assert {item["document_id"] for item in result.evidence_coverage.requested_scope} == {
        "doc-a",
        "doc-b",
    }

    detail = await chain.case_service.read_for_user(case.case_id, USER_ID)
    assert detail["question"] == chain.question.content
    assert detail["answer"] == chain.answer.content
    assert detail["source_signals"][0]["feedback_id"] == feedback.feedback_id
    assert detail["annotation"] is None
    assert detail["review_decisions"] == []

    annotation = await chain.case_service.save_annotation_for_user(
        case_id=case.case_id,
        user_id=USER_ID,
        expected_digest=None,
        problem_type="source_missing",
        severity="high",
        target="Paper B reports preheating at 200 C in Figure 3.",
        support_source_refs=("source-b-caption",),
        dataset_uses=("evaluation", "sft", "preference"),
        reason="The figure caption supplies evidence omitted by the answer.",
        now=_current_iso(),
    )
    assert annotation.version == 1
    stored_annotation = await chain.cases.read_annotation(case.case_id)
    assert stored_annotation == annotation
    annotated_case = await chain.cases.read_case(case.case_id)
    assert annotated_case is not None
    assert annotated_case.status == "ready_for_review"
    assert annotated_case.annotation_digest == annotation.annotation_digest

    review = await chain.case_service.submit_review_for_user(
        case_id=case.case_id,
        user_id=USER_ID,
        expected_annotation_digest=annotation.annotation_digest,
        decision="accept",
        reason="The cited source and corrected target were checked.",
        now=_current_iso(),
    )
    assert review.seq == 1
    assert review.annotation_digest == annotation.annotation_digest
    reviewed_case = await chain.cases.read_case(case.case_id)
    assert reviewed_case is not None
    assert reviewed_case.status == "accepted"
    assert await chain.cases.read_review_decisions(case.case_id) == (review,)

    snapshot = await chain.snapshot_service.create_for_user(
        owner_id=USER_ID,
        collection_id=COLLECTION_ID,
        dataset_type="preference",
        selections=(DatasetSelection(case.case_id, "eval"),),
        paper_families={"doc-a": "family-a", "doc-b": "family-b"},
        now=_current_iso(),
    )
    assert snapshot.row_count == 1
    assert snapshot.rows[0]["record_type"] == "preference"
    assert snapshot.rows[0]["chosen"] == annotation.target
    assert snapshot.rows[0]["rejected"] == chain.answer.content
    assert snapshot.rows[0]["source_refs"] == ["source-b-caption"]
    assert snapshot.provenance["items"][0]["case_id"] == case.case_id

    persisted_snapshot = await chain.snapshots.read(snapshot.dataset_id)
    assert persisted_snapshot == snapshot
    payload = jsonl_bytes_for_rows(snapshot.rows)
    assert payload.endswith(b"\n")
    assert len(payload) > 0
    loaded_snapshot, loaded_payload = await chain.snapshot_service.jsonl_for_user(
        owner_id=USER_ID, dataset_id=snapshot.dataset_id
    )
    assert loaded_snapshot == snapshot
    assert loaded_payload == payload

    # The worker and the review pipeline must never rewrite the authoritative
    # chat trajectory while creating downstream records.
    assert await chain.chat.read_messages(SESSION_ID) == (
        chain.question,
        chain.answer,
    )


async def test_withdrawn_feedback_cancels_pending_job_without_creating_a_case(
    feedback_chain,
):
    chain = feedback_chain
    feedback = await chain.chat_service.set_message_feedback_for_user(
        SESSION_ID,
        chain.answer.message_id,
        USER_ID,
        rating="not_helpful",
        reason="incomplete",
        comment="Please include the source condition.",
    )
    assert feedback is not None
    assert len(
        await chain.jobs.list_jobs(job_type="feedback_analysis", status="pending")
    ) == 1

    withdrawn = await chain.chat_service.set_message_feedback_for_user(
        SESSION_ID,
        chain.answer.message_id,
        USER_ID,
        rating=None,
    )
    assert withdrawn is None
    cancelled = await chain.jobs.list_jobs(
        job_type="feedback_analysis", status="cancelled"
    )
    assert len(cancelled) == 1
    assert cancelled[0].error_code == "feedback_withdrawn"
    assert await chain.chat.read_feedback_by_id(feedback.feedback_id) is None
    assert await chain.cases.list_cases(collection_id=COLLECTION_ID) == ()

    worker = FeedbackAnalysisWorker(
        job_repository=chain.jobs,
        case_repository=chain.cases,
        handler=FeedbackAnalysisHandler(chat_repository=chain.chat),
    )
    assert await worker.run_once() is None
