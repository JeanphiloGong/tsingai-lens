from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
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
from application.feedback.tool_failure_handler import ToolFailureAnalysisHandler
from application.feedback.tool_failure_worker import ToolFailureAnalysisWorker
from application.repositories.analysis_job_repository import (
    TOOL_FAILURE_JOB_TYPE,
    correction_signal_idempotency_key,
    tool_failure_idempotency_key,
)
from application.repositories.auth_repository import AuthUserRecord
from application.repositories.collection_repository import StoredCollection
from application.source.collection_service import CollectionService
from domain.chat import (
    ChatMessage,
    ChatResourceRef,
    ChatSession,
    ChatSourceContext,
    ChatToolCall,
    ChatToolRequest,
    ChatToolResult,
    ToolResultStatus,
    ToolRisk,
)
from domain.feedback.analysis_result import AnalysisResult
from domain.feedback.correction_signal import CorrectionSignalAnalysisResult
from domain.feedback.evidence_coverage import EvidenceCoverage
from domain.feedback.tool_failure import tool_failure_signal_id, tool_result_digest
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
        StoredCollection(
            collection=Collection(
                collection_id=COLLECTION_ID,
                owner_user_id=USER_ID,
                name="Feedback chain collection",
                description="Persistent workbench integration fixture",
                status="idle",
            ),
            created_at=NOW,
            updated_at=NOW,
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
    tmp_path,
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
        selections=(DatasetSelection(case.case_id),),
        now=_current_iso(),
    )
    assert snapshot.row_count == 1
    assert snapshot.rows[0]["record_type"] == "preference"
    assert snapshot.rows[0]["chosen"] == annotation.target
    assert snapshot.rows[0]["rejected"] == chain.answer.content
    assert snapshot.rows[0]["evidence"][0]["document_title"] == "Paper B"
    assert snapshot.rows[0]["evidence"][0]["quote"].startswith("Figure 3")
    assert snapshot.provenance["items"][0]["source_refs"] == ["source-b-caption"]
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

    # Consume the actual persisted export through the offline CLI boundary.
    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps(loaded_snapshot.to_record()), encoding="utf-8")
    scripts = Path(__file__).resolve().parents[3] / "scripts/evaluation/feedback_dataset"
    prepared = tmp_path / "experiment"
    result = subprocess.run(
        [sys.executable, str(scripts / "prepare.py"), str(source), str(prepared), "--revision", "integration"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "export_manifest_schema_invalid" in result.stderr

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


async def test_tool_failure_worker_persists_an_independent_case_projection(
    feedback_chain,
):
    chain = feedback_chain
    request = ChatToolRequest(
        tool_call_id="feedback-chain-tool-call",
        name="inspect_document_sources",
        arguments={"document_id": "doc-b", "source_ref": "source-b-caption"},
        position=0,
    )
    assistant_request = ChatMessage.assistant_tool_calls(
        message_id="feedback-chain-tool-assistant",
        session_id=SESSION_ID,
        content="",
        tool_calls=(request,),
        created_at="2026-09-24T10:00:03+00:00",
    )
    call = ChatToolCall.requested(
        tool_call_id=request.tool_call_id,
        session_id=SESSION_ID,
        assistant_message_id=assistant_request.message_id,
        name=request.name,
        arguments=request.arguments,
        risk=ToolRisk.READ,
        position=request.position,
    ).start("2026-09-24T10:00:03+00:00").fail(
        "source_unavailable", "2026-09-24T10:00:04+00:00"
    )
    failed_result = ChatToolResult(
        tool_call_id=call.tool_call_id,
        status=ToolResultStatus.FAILED,
        error_code="source_unavailable",
        error_message="The selected source is unavailable.",
    )
    tool_message = ChatMessage.from_tool_result(
        message_id="feedback-chain-tool-result",
        session_id=SESSION_ID,
        result=failed_result,
        created_at="2026-09-24T10:00:04+00:00",
    )
    final_answer = ChatMessage.assistant(
        message_id="feedback-chain-tool-answer",
        session_id=SESSION_ID,
        content="I could not inspect Paper B because the source was unavailable.",
        created_at="2026-09-24T10:00:05+00:00",
    )
    trajectory = (
        chain.question,
        chain.answer,
        assistant_request,
        tool_message,
        final_answer,
    )
    await chain.chat.save_trajectory(
        session=chain.session.update(
            user_id=USER_ID,
            collection_id=COLLECTION_ID,
            updated_at="2026-09-24T10:00:05+00:00",
        ),
        messages=trajectory,
        tool_calls=(call,),
        tool_results=(failed_result,),
    )

    result_digest = tool_result_digest(failed_result.to_record())
    enqueue_kwargs = {
        "session_id": SESSION_ID,
        "tool_call_id": call.tool_call_id,
        "assistant_message_id": assistant_request.message_id,
        "result_message_id": tool_message.message_id,
        "result_digest": result_digest,
        "idempotency_key": tool_failure_idempotency_key(
            session_id=SESSION_ID,
            tool_call_id=call.tool_call_id,
            assistant_message_id=assistant_request.message_id,
            result_message_id=tool_message.message_id,
            result_digest=result_digest,
        ),
        "now": NOW,
    }
    first_job = await chain.jobs.enqueue_tool_failure_analysis(**enqueue_kwargs)
    duplicate_job = await chain.jobs.enqueue_tool_failure_analysis(**enqueue_kwargs)
    assert duplicate_job.job_id == first_job.job_id
    assert first_job.job_type == TOOL_FAILURE_JOB_TYPE

    worker = ToolFailureAnalysisWorker(
        job_repository=chain.jobs,
        case_repository=chain.cases,
        handler=ToolFailureAnalysisHandler(chat_repository=chain.chat),
    )
    terminal_job = await worker.run_once()
    assert terminal_job is not None
    assert terminal_job.status == "succeeded"
    assert terminal_job.result_id is not None
    assert await chain.jobs.read_job(first_job.job_id) == terminal_job

    saved_results = await chain.cases.read_tool_failure_analysis_results(
        (terminal_job.result_id,)
    )
    assert len(saved_results) == 1
    saved_result = saved_results[0]
    assert saved_result.job_id == first_job.job_id
    assert saved_result.tool_call_id == call.tool_call_id
    assert saved_result.result_message_id == tool_message.message_id
    assert saved_result.problem_type == "tool_failure"
    assert saved_result.suggested_target is None
    assert saved_result.evidence_coverage.coverage_status == "failed"

    stored_cases = await chain.cases.list_cases(
        collection_id=COLLECTION_ID,
        problem_type="tool_failure",
    )
    assert len(stored_cases) == 1
    case = stored_cases[0]
    assert case.anchor_message_id == final_answer.message_id
    assert case.analysis_result_ids == ()
    assert case.tool_failure_analysis_result_ids == (terminal_job.result_id,)
    assert case.source_signal_ids == (
        tool_failure_signal_id(call.tool_call_id, tool_message.message_id),
    )
    assert case.context_snapshot["answer_message_id"] == final_answer.message_id

    summaries = await chain.case_service.list_for_user(
        user_id=USER_ID,
        collection_id=COLLECTION_ID,
        problem_type="tool_failure",
    )
    assert len(summaries) == 1
    assert summaries[0].case_id == case.case_id
    assert summaries[0].problem_type == "tool_failure"

    detail = await chain.case_service.read_for_user(case.case_id, USER_ID)
    assert detail["answer"] == final_answer.content
    assert detail["source_signals"][0]["signal_type"] == "tool_failure"
    assert detail["source_signals"][0]["error_code"] == "source_unavailable"
    assert detail["analysis"]["problem_type"] == "tool_failure"
    assert detail["analysis"]["tool_call_id"] == call.tool_call_id
    assert detail["analysis"]["suggested_target"] is None
    assert detail["coverage_status"] == "failed"
    assert detail["annotation"] is None

    assert await worker.run_once() is None
    assert await chain.chat.read_messages(SESSION_ID) == trajectory


@pytest.mark.parametrize("order", [("correction", "feedback"), ("feedback", "correction")])
async def test_multiple_analysis_sources_preserve_correction_pair_and_evidence(
    feedback_chain, order
):
    chain = feedback_chain
    stored_feedback = await chain.chat_service.set_message_feedback_for_user(
        SESSION_ID, chain.answer.message_id, USER_ID, rating="not_helpful", reason="incorrect",
    )
    feedback_job = (await chain.jobs.list_jobs(job_type="feedback_analysis"))[0]
    correction_job = await chain.jobs.enqueue_correction_signal_analysis(
        session_id=SESSION_ID, anchor_message_id=chain.answer.message_id,
        trigger_message_id="challenge", trigger_digest="c" * 64,
        idempotency_key=correction_signal_idempotency_key(
            session_id=SESSION_ID, anchor_message_id=chain.answer.message_id,
            trigger_message_id="challenge", trigger_digest="c" * 64,
        ), now=_current_iso(),
    )
    common = {
        "session_id": SESSION_ID,
        "collection_id": COLLECTION_ID,
        "anchor_message_id": chain.answer.message_id,
        "problem_type": "source_missing",
        "confidence": 0.8,
        "related_message_ids": (chain.question.message_id, chain.answer.message_id),
        "suggested_evidence": (),
        "suggested_target": None,
        "evidence_coverage": EvidenceCoverage(coverage_status="partial"),
        "model": "test",
        "input_digest": "a" * 64,
        "created_at": NOW,
    }
    correction = CorrectionSignalAnalysisResult(
        **common, result_id="correction-result", job_id=correction_job.job_id,
        signal_id="correction_signal:challenge", signal_type="natural_language_correction",
        trigger_message_id="challenge",
    )
    feedback = AnalysisResult(
        **common, result_id="feedback-result", job_id=feedback_job.job_id,
        feedback_id=stored_feedback.feedback_id,
    )
    snapshots = {
        "correction": {
            "question": chain.question.content, "answer": chain.answer.content,
            "corrected_answer": "Paper B was preheated at 200 C.",
            "corrected_message_id": "corrected-answer",
            "pairing_basis": "same_case_review_input",
            "correction_signal": {"content": "Actually, the caption records preheating."},
            "inspected_sources": [{"document_title": "Paper B", "quote": "Preheated at 200 C."}],
            "analysis": {"resolution": "correction_response_available"},
        },
        "feedback": {
            "question": chain.question.content, "answer": chain.answer.content,
            "corrected_answer": None,
            "inspected_sources": [],
            "analysis": {"problem_type": "source_missing", "suggested_target": None},
        },
    }
    for source in order:
        if source == "correction":
            await chain.cases.upsert_case_from_correction_signal(
                correction, context_snapshot=snapshots[source], now=_current_iso()
            )
        else:
            await chain.cases.upsert_case_from_analysis(
                feedback, context_snapshot=snapshots[source], now=_current_iso()
            )
    cases = await chain.cases.list_cases(collection_id=COLLECTION_ID)
    assert len(cases) == 1
    snapshot = cases[0].context_snapshot
    assert snapshot["corrected_answer"] == "Paper B was preheated at 200 C."
    assert snapshot["corrected_message_id"] == "corrected-answer"
    assert snapshot["inspected_sources"][0]["quote"] == "Preheated at 200 C."
    assert snapshot["pairing_basis"] == "same_case_review_input"
    # Only the correction source can clear its own pair on a later projection.
    await chain.cases.upsert_case_from_correction_signal(
        correction, context_snapshot={"question": chain.question.content, "answer": chain.answer.content,
            "correction_signal": {"content": "Actually, only summarize B now."},
            "pairing_assessment": {"task_relation": "different_task"}}, now=_current_iso(),
    )
    current = await chain.cases.read_case(cases[0].case_id)
    assert "corrected_answer" not in current.context_snapshot
    assert "corrected_message_id" not in current.context_snapshot


async def test_analysis_result_replay_after_worker_crash_reuses_saved_result(
    feedback_chain,
):
    chain = feedback_chain
    feedback = await chain.chat_service.set_message_feedback_for_user(
        SESSION_ID,
        chain.answer.message_id,
        USER_ID,
        rating="not_helpful",
        reason="incorrect",
    )
    job = (await chain.jobs.list_jobs(job_type="feedback_analysis"))[0]
    result = AnalysisResult(
        result_id="analysis-result-first",
        job_id=job.job_id,
        feedback_id=feedback.feedback_id,
        session_id=SESSION_ID,
        collection_id=COLLECTION_ID,
        anchor_message_id=chain.answer.message_id,
        problem_type="source_missing",
        confidence=0.8,
        related_message_ids=(chain.question.message_id, chain.answer.message_id),
        suggested_evidence=(),
        suggested_target=None,
        evidence_coverage=EvidenceCoverage(coverage_status="partial"),
        model="test",
        input_digest="a" * 64,
        created_at=NOW,
    )
    snapshot = {
        "question": chain.question.content,
        "answer": chain.answer.content,
        "inspected_sources": [],
    }
    await chain.cases.upsert_case_from_analysis(
        result,
        context_snapshot=snapshot,
        now=NOW,
    )

    # Simulate the worker retrying after the result transaction committed but
    # before the job status update was observed by the worker.
    replay = replace(result, result_id="analysis-result-retry")
    await chain.cases.upsert_case_from_analysis(
        replay,
        context_snapshot=snapshot,
        now=NOW,
    )

    case = (await chain.cases.list_cases(collection_id=COLLECTION_ID))[0]
    assert case.analysis_result_ids == (result.result_id,)
    stored = await chain.cases.read_analysis_results((result.result_id,))
    assert tuple(item.result_id for item in stored) == (result.result_id,)
