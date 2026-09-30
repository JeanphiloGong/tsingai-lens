from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace

import pytest

from application.chat.agent_runner import AgentCompletionReason, AgentRunResult, AgentRunStatus
from application.chat.session_service import ChatSessionService
from application.feedback.correction_signal_handler import (
    CorrectionSignalAnalysisHandler,
    CorrectionSignalAnalysisDraft,
)
from application.feedback.correction_signal_worker import CorrectionSignalAnalysisWorker
from domain.chat import ChatMessage, ChatResourceRef, ChatSession, ChatSourceContext
from domain.feedback import (
    CORRECTION_SIGNAL_JOB_TYPE,
    AnalysisJob,
    correction_signal_idempotency_key,
    is_correction_challenge,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Chat:
    def __init__(self, messages: tuple[ChatMessage, ...]):
        self.session = ChatSession.create(
            session_id="session-1",
            user_id="user-1",
            collection_id="collection-1",
            created_at="2026-09-25T00:00:00+00:00",
        )
        self.messages = messages

    async def read_session(self, session_id: str):
        return self.session if session_id == self.session.session_id else None

    async def read_messages(self, session_id: str):
        return self.messages if session_id == self.session.session_id else ()


class _Jobs:
    def __init__(self, job: AnalysisJob):
        self.job = job
        self.finished: tuple[str, str] | None = None

    async def claim_next_correction_signal_analysis_job(self, now: str):
        if self.job.status != "pending":
            return None
        self.job = replace(self.job, status="running", started_at=now, updated_at=now)
        return self.job

    async def mark_succeeded(self, job_id: str, result_id: str, finished_at: str):
        self.finished = ("succeeded", result_id)
        self.job = replace(
            self.job,
            status="succeeded",
            result_id=result_id,
            finished_at=finished_at,
            updated_at=finished_at,
        )
        return self.job

    async def mark_failed(self, job_id: str, error_code: str, finished_at: str):
        self.finished = ("failed", error_code)
        self.job = replace(
            self.job,
            status="failed",
            error_code=error_code,
            finished_at=finished_at,
            updated_at=finished_at,
        )
        return self.job

    async def mark_cancelled(self, job_id: str, error_code: str, finished_at: str):
        self.finished = ("cancelled", error_code)
        self.job = replace(
            self.job,
            status="cancelled",
            error_code=error_code,
            finished_at=finished_at,
            updated_at=finished_at,
        )
        return self.job


class _Cases:
    def __init__(self):
        self.calls = []

    async def upsert_case_from_correction_signal(
        self, result, *, context_snapshot, source_signal_ids, now
    ):
        self.calls.append(
            {
                "result": result,
                "context_snapshot": context_snapshot,
                "source_signal_ids": source_signal_ids,
            }
        )


def _messages(*, trigger_text: str = "不对，图注里有预热信息。"):
    return (
        ChatMessage.user(
            message_id="question-1",
            session_id="session-1",
            content="比较文献 A 和 B。",
            created_at="2026-09-25T00:00:01+00:00",
        ),
        ChatMessage.assistant(
            message_id="answer-1",
            session_id="session-1",
            content="文献 B 没有预热信息。",
            created_at="2026-09-25T00:00:02+00:00",
        ),
        ChatMessage.user(
            message_id="challenge-1",
            session_id="session-1",
            content=trigger_text,
            created_at="2026-09-25T00:00:03+00:00",
        ),
    )


def _job(messages: tuple[ChatMessage, ...]) -> AnalysisJob:
    trigger = messages[-1]
    digest = sha256(trigger.content.strip().encode()).hexdigest()
    return AnalysisJob(
        job_id="job-correction-1",
        job_type=CORRECTION_SIGNAL_JOB_TYPE,
        payload_version=1,
        payload={
            "session_id": "session-1",
            "anchor_message_id": "answer-1",
            "trigger_message_id": trigger.message_id,
            "trigger_digest": digest,
        },
        status="pending",
        idempotency_key=correction_signal_idempotency_key(
            session_id="session-1",
            anchor_message_id="answer-1",
            trigger_message_id=trigger.message_id,
            trigger_digest=digest,
        ),
        available_at="2026-09-25T00:00:00+00:00",
        created_at="2026-09-25T00:00:00+00:00",
        updated_at="2026-09-25T00:00:00+00:00",
    )


def test_correction_detector_is_explicit_and_does_not_capture_every_follow_up():
    assert is_correction_challenge("不对，原回答漏读了图注")
    assert is_correction_challenge("Actually, the source says otherwise")
    assert not is_correction_challenge("请继续比较两篇文献")
    assert not is_correction_challenge("")


def test_correction_signal_job_key_is_bounded_and_content_digest_is_canonicalized():
    key = correction_signal_idempotency_key(
        session_id="s" * 128,
        anchor_message_id="a" * 128,
        trigger_message_id="t" * 128,
        trigger_digest="c" * 64,
    )
    assert len(key) == len("correction-signal:") + 64


async def test_handler_accepts_surrounding_trigger_whitespace():
    messages = _messages(trigger_text="  不对，图注里有预热信息。  ")
    handler = CorrectionSignalAnalysisHandler(chat_repository=_Chat(messages))
    result, _, _ = await handler.handle(_job(messages))
    assert result.signal_id == "correction_signal:challenge-1"


async def test_handler_produces_unresolved_candidate_without_inventing_target():
    messages = _messages()
    handler = CorrectionSignalAnalysisHandler(chat_repository=_Chat(messages))
    result, snapshot, source_ids = await handler.handle(_job(messages))

    assert result.signal_id == "correction_signal:challenge-1"
    assert result.trigger_message_id == "challenge-1"
    assert result.suggested_target is None
    assert snapshot["analysis"]["resolution"] == "unresolved_candidate"
    assert source_ids == (result.signal_id,)


async def test_challenge_collects_corrected_answer_and_its_real_source_reads():
    from tests.unit.feedback.test_source_coverage import _trajectory
    from application.feedback.preference_sample_builder import PreferenceSampleBuilder, PreferenceBuildCandidate
    from domain.feedback import Dataset, DatasetSample, FeedbackCase
    from datetime import datetime, timezone

    source_turn, _, _ = _trajectory(answer_message_id="answer-2", tool_request_message_id="read-after-challenge")
    original = _messages()
    messages = original + (
        replace(source_turn[1], created_at="2026-09-25T00:00:04+00:00"),
        replace(source_turn[2], created_at="2026-09-25T00:00:05+00:00"),
        replace(source_turn[3], content="Paper B was preheated at 200 C.",
                created_at="2026-09-25T00:00:06+00:00"),
    )
    result, snapshot, _ = await CorrectionSignalAnalysisHandler(
        chat_repository=_Chat(messages)
    ).handle(_job(original))
    assert snapshot["corrected_answer"] == "Paper B was preheated at 200 C."
    assert snapshot["corrected_message_id"] == "answer-2"
    assert "answer-2" in result.related_message_ids
    assert snapshot["inspected_sources"][0]["quote"] == "The exact passage."
    now = datetime.now(timezone.utc)
    dataset = Dataset("fdset-1", "collection-1", "Preference", "preference", {}, 1, "user-1", now, now)
    sample = DatasetSample.pending(sample_id="sample-1", dataset_id="fdset-1", source_case_id="case-1",
                                   source_digest="a" * 64, active_job_id="job-1", now=now.isoformat())
    case = FeedbackCase("case-1", "collection-1", "session-1", "answer-1", (), (), snapshot,
                        "needs_annotation", now.isoformat(), now.isoformat())
    built = await PreferenceSampleBuilder().build(dataset=dataset, sample=sample, case=case, annotation=None)
    assert isinstance(built, PreferenceBuildCandidate)
    assert built.content.response_b == snapshot["corrected_answer"]
    assert built.content.human_preference is None


async def test_challenge_does_not_link_an_answer_from_a_later_question():
    original = _messages()
    messages = original + (
        ChatMessage.user(message_id="next-question", session_id="session-1", content="Another question",
                         created_at="2026-09-25T00:00:04+00:00"),
        ChatMessage.assistant(message_id="next-answer", session_id="session-1", content="Unrelated answer",
                              created_at="2026-09-25T00:00:05+00:00"),
    )
    _, snapshot, _ = await CorrectionSignalAnalysisHandler(chat_repository=_Chat(messages)).handle(_job(original))
    assert not snapshot.get("corrected_answer")


@pytest.mark.parametrize("trigger_text", [
    "不对，改为只总结 B。",
    "That's wrong. Only summarize B instead.",
])
async def test_challenge_changing_task_scope_does_not_form_a_preference_pair(trigger_text):
    original = _messages(trigger_text=trigger_text)
    messages = original + (
        ChatMessage.assistant(
            message_id="changed-task-answer", session_id="session-1",
            content="B 的独立总结。", created_at="2026-09-25T00:00:04+00:00",
        ),
    )
    _, snapshot, _ = await CorrectionSignalAnalysisHandler(
        chat_repository=_Chat(messages)
    ).handle(_job(original))
    assert snapshot["analysis"]["resolution"] == "task_scope_changed"
    assert not snapshot.get("corrected_answer")


@pytest.mark.parametrize("relation", ["different_task", "uncertain"])
async def test_task_assessment_blocks_scope_changes_without_keyword_matches(relation):
    original = _messages(trigger_text="不对，先看 B 的腐蚀表现。")
    messages = original + (
        ChatMessage.assistant(
            message_id="answer-2", session_id="session-1", content="B 的腐蚀表现。",
            created_at="2026-09-25T00:00:04+00:00",
        ),
    )

    class Engine:
        async def analyze(self, **inputs):
            assert inputs["messages"] == original
            return CorrectionSignalAnalysisDraft(
                problem_type="undetermined_dissatisfaction", confidence=0.2,
                suggested_evidence=(), suggested_target=None,
                task_relation=relation, task_relation_reason="Follow-up changes the outcome.",
            )

    _, snapshot, _ = await CorrectionSignalAnalysisHandler(
        chat_repository=_Chat(messages), engine=Engine(),
    ).handle(_job(original))
    assert snapshot["pairing_assessment"]["task_relation"] == relation
    assert not snapshot.get("corrected_message_id")


async def test_handler_keeps_selected_context_requested_until_a_read_is_verified():
    selected = ChatSourceContext(
        resource_ref=ChatResourceRef(
            resource_type="source",
            resource_id="document-1:results",
        ),
        collection_id="collection-1",
        document_id="document-1",
        document_title="Paper 1",
        source_kind="text_window",
        source_ref="results",
        page=1,
        quote="A selected excerpt.",
        source_digest="a" * 64,
    )
    messages = (
        replace(_messages()[0], source_contexts=(selected,)),
        *_messages()[1:],
    )
    result, snapshot, _ = await CorrectionSignalAnalysisHandler(
        chat_repository=_Chat(messages)
    ).handle(_job(messages))

    assert result.evidence_coverage.requested_scope[0]["origin"] == "user_selected_context"
    assert result.evidence_coverage.inspected_sources == ()
    assert result.evidence_coverage.coverage_status == "partial"
    assert result.evidence_coverage.omitted_candidates[0]["reason"] == (
        "selected_context_not_verified"
    )
    assert snapshot["inspected_sources"] == []


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda messages: (*messages[:2], replace(messages[2], session_id="other")), "cross_session"),
        (lambda messages: (messages[0], messages[2], messages[1]), "order_invalid"),
        (lambda messages: (*messages[:2], replace(messages[2], content="请继续比较")), "not_candidate"),
    ],
)
async def test_handler_rejects_cross_session_order_and_non_correction(
    mutate, error: str
):
    original = _messages()
    messages = mutate(original)
    job = _job(original) if error == "order_invalid" else _job(messages)
    with pytest.raises(ValueError, match=error):
        await CorrectionSignalAnalysisHandler(chat_repository=_Chat(messages)).handle(
            job
        )


async def test_handler_rejects_a_job_with_an_unbound_idempotency_key():
    messages = _messages()
    invalid = replace(_job(messages), idempotency_key="correction-signal:wrong")
    with pytest.raises(ValueError, match="identity_mismatch"):
        await CorrectionSignalAnalysisHandler(chat_repository=_Chat(messages)).handle(
            invalid
        )


async def test_correction_signal_result_cannot_claim_a_training_target():
    messages = _messages()
    handler_result = CorrectionSignalAnalysisHandler(chat_repository=_Chat(messages))
    result, _, _ = await handler_result.handle(_job(messages))

    with pytest.raises(ValueError, match="training target"):
        replace(result, suggested_target="invented answer")


async def test_worker_persists_case_only_after_valid_signal_analysis():
    messages = _messages()
    jobs = _Jobs(_job(messages))
    cases = _Cases()
    outcome = await CorrectionSignalAnalysisWorker(
        job_repository=jobs,
        case_repository=cases,
        handler=CorrectionSignalAnalysisHandler(chat_repository=_Chat(messages)),
    ).run_once()

    assert outcome.status == "succeeded"
    assert jobs.finished and jobs.finished[0] == "succeeded"
    assert len(cases.calls) == 1
    assert cases.calls[0]["result"].suggested_target is None
    assert cases.calls[0]["context_snapshot"]["correction_signal"]["trigger_message_id"] == "challenge-1"


async def test_worker_cancels_when_trigger_disappears_instead_of_creating_case():
    messages = _messages()
    jobs = _Jobs(_job(messages))
    cases = _Cases()
    chat = _Chat(messages[:-1])
    outcome = await CorrectionSignalAnalysisWorker(
        job_repository=jobs,
        case_repository=cases,
        handler=CorrectionSignalAnalysisHandler(chat_repository=chat),
    ).run_once()

    assert outcome.status == "cancelled"
    assert jobs.finished == ("cancelled", "correction_signal_withdrawn")
    assert cases.calls == []


async def test_chat_turn_trigger_requires_adjacent_final_answer_and_deduplicates_at_repository_boundary():
    messages = _messages()
    captured: list[dict] = []

    class _SignalJobs:
        async def enqueue_correction_signal_analysis(self, **kwargs):
            captured.append(kwargs)

    service = ChatSessionService(
        collection_service=SimpleNamespace(),
        source_artifact_repository=SimpleNamespace(),
        repository=SimpleNamespace(),
        runner=SimpleNamespace(),
        analysis_job_repository=_SignalJobs(),
    )
    result = AgentRunResult(
        status=AgentRunStatus.COMPLETED,
        messages=messages + (
            ChatMessage.assistant(
                message_id="answer-2",
                session_id="session-1",
                content="我会重新核对来源。",
                created_at="2026-09-25T00:00:04+00:00",
            ),
        ),
        completion_reason=AgentCompletionReason.MODEL_ANSWER,
    )
    session = ChatSession.create(
        session_id="session-1",
        user_id="user-1",
        collection_id="collection-1",
        created_at="2026-09-25T00:00:00+00:00",
    )
    assert await service._enqueue_correction_signal_candidate(
        session, previous_messages=messages[:2], result=result
    ) is True
    assert len(captured) == 1
    assert captured[0]["anchor_message_id"] == "answer-1"
    assert captured[0]["trigger_message_id"] == "challenge-1"

    non_adjacent = replace(result, messages=(messages[0], messages[2], messages[1]))
    assert await service._enqueue_correction_signal_candidate(
        session,
        previous_messages=(messages[0], messages[1]),
        result=non_adjacent,
    ) is None
