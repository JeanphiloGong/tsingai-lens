from __future__ import annotations

from application.feedback import analysis_handler

from dataclasses import replace

import pytest

from application.feedback.analysis_handler import (
    FeedbackAnalysisHandler,
    conversation_before_answer,
)
from application.feedback.analysis_worker import FeedbackAnalysisWorker
from domain.chat import ChatMessage, ChatSession
from domain.chat.feedback import ChatMessageFeedback
from repositories.analysis_job_repository import AnalysisJob

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Chat:
    def __init__(self, *, feedback: ChatMessageFeedback | None) -> None:
        self.feedback = feedback
        self.session = ChatSession.create(
            session_id="session-1",
            user_id="user-1",
            collection_id="collection-1",
            created_at="2026-09-24T00:00:00+00:00",
        )
        self.question = ChatMessage.user(
            message_id="question-1",
            session_id="session-1",
            content="Compare papers A and B.",
            created_at="2026-09-24T00:00:01+00:00",
        )
        self.answer = ChatMessage.assistant(
            message_id="answer-1",
            session_id="session-1",
            content="Paper B has no preheating information.",
            created_at="2026-09-24T00:00:02+00:00",
        )

    async def read_feedback_by_id(self, feedback_id: str):
        return self.feedback if self.feedback and self.feedback.feedback_id == feedback_id else None

    async def read_session(self, session_id: str):
        return self.session if session_id == self.session.session_id else None

    async def read_message(self, message_id: str):
        return {"question-1": self.question, "answer-1": self.answer}.get(message_id)

    async def read_messages(self, session_id: str):
        return (self.question, self.answer) if session_id == self.session.session_id else ()


class _Jobs:
    def __init__(self, job: AnalysisJob):
        self.job = job
        self.finished: tuple[str, str | None] | None = None

    async def recover_expired_jobs(self, *, now):
        return 0

    async def read_job(self, job_id):
        return self.job if self.job.job_id == job_id else None

    async def renew_lease(self, **kwargs):
        assert kwargs["worker_id"] == self.job.worker_id
        assert kwargs["lease_version"] == self.job.lease_version
        return self.job

    async def claim_next_feedback_analysis_job(self, now: str):
        if self.job.status != "pending":
            return None
        self.job = replace(self.job, status="running", started_at=now, updated_at=now, worker_id="worker-1", lease_version=1)
        return self.job

    async def mark_succeeded(self, job_id: str, result_id: str, finished_at: str, **_lease):
        self.finished = ("succeeded", result_id)
        self.job = replace(self.job, status="succeeded", result_id=result_id, finished_at=finished_at, updated_at=finished_at)
        return self.job

    async def mark_failed(self, job_id: str, error_code: str, finished_at: str, **_lease):
        self.finished = ("failed", error_code)
        self.job = replace(self.job, status="failed", error_code=error_code, finished_at=finished_at, updated_at=finished_at)
        return self.job

    async def mark_cancelled(self, job_id: str, error_code: str, finished_at: str, **_lease):
        self.finished = ("cancelled", error_code)
        self.job = replace(self.job, status="cancelled", error_code=error_code, finished_at=finished_at, updated_at=finished_at)
        return self.job


class _Cases:
    def __init__(self, *, fail_on_save: bool = False):
        self.results = []
        self.cases = []
        self.fail_on_save = fail_on_save

    async def save_analysis_result(self, result):
        if self.fail_on_save:
            raise RuntimeError("database unavailable")
        self.results.append(result)
        return result

    async def upsert_case_from_analysis(self, result, *, context_snapshot, source_signal_ids, now):
        if self.fail_on_save:
            raise RuntimeError("database unavailable")
        self.results.append(result)
        self.cases.append({"result": result, "context_snapshot": context_snapshot, "source_signal_ids": source_signal_ids})
        return self.cases[-1]


def _job(feedback_id: str, *, idempotency_key: str | None = None) -> AnalysisJob:
    return AnalysisJob(
        job_id="job-1",
        job_type="feedback_analysis",
        payload_version=1,
        payload={"feedback_id": feedback_id},
        status="pending",
        idempotency_key=idempotency_key or "feedback-version-1",
        available_at="2026-09-24T00:00:00+00:00",
        created_at="2026-09-24T00:00:00+00:00",
        updated_at="2026-09-24T00:00:00+00:00",
    )


async def test_worker_creates_candidate_result_and_case_without_mutating_chat() -> None:
    chat = _Chat(feedback=None)
    feedback = ChatMessageFeedback.for_answer(
        message=chat.answer,
        feedback_id="feedback-1",
        user_id="user-1",
        rating="not_helpful",
        reason="incorrect",
        comment="The caption contains the missing information.",
        now="2026-09-24T00:00:03+00:00",
    )
    chat.feedback = feedback
    jobs = _Jobs(_job(feedback.feedback_id, idempotency_key=feedback.analysis_version_key))
    cases = _Cases()
    before = (chat.question, chat.answer)
    analysis_handler.ChatRepo = chat
    result = await FeedbackAnalysisWorker(
        job_repository=jobs,
        case_repository=cases,
        handler=FeedbackAnalysisHandler(),
    ).run_once()
    assert result.status == "succeeded"
    assert jobs.finished and jobs.finished[0] == "succeeded"
    assert len(cases.results) == 1
    assert cases.results[0].problem_type == "fact_error"
    assert cases.results[0].evidence_coverage.coverage_status == "unknown"
    assert cases.cases[0]["context_snapshot"]["answer"] == chat.answer.content
    assert (chat.question, chat.answer) == before


def test_conversation_capture_excludes_target_and_later_corrections() -> None:
    chat = _Chat(feedback=None)
    followup = replace(chat.question, message_id="followup", content="Summarize that decision.")
    target = replace(chat.answer, message_id="target", content="Target answer")
    correction = replace(chat.question, message_id="correction", content="Later correction")
    history = conversation_before_answer((chat.question, chat.answer, followup, target, correction), target)
    assert history == [
        {"role": "user", "content": chat.question.content},
        {"role": "assistant", "content": chat.answer.content},
        {"role": "user", "content": followup.content},
    ]


async def test_worker_cancels_withdrawn_feedback_without_case() -> None:
    jobs = _Jobs(_job("feedback-withdrawn"))
    cases = _Cases()
    analysis_handler.ChatRepo = _Chat(feedback=None)
    worker = FeedbackAnalysisWorker(
        job_repository=jobs,
        case_repository=cases,
        handler=FeedbackAnalysisHandler(),
    )
    result = await worker.run_once()
    assert result.status == "cancelled"
    assert jobs.finished == ("cancelled", "feedback_withdrawn")
    assert cases.results == []
    assert cases.cases == []


async def test_worker_cancels_a_superseded_feedback_version() -> None:
    chat = _Chat(feedback=None)
    feedback = ChatMessageFeedback.for_answer(
        message=chat.answer,
        feedback_id="feedback-1",
        user_id="user-1",
        rating="not_helpful",
        reason="incorrect",
        comment="The caption contains the missing information.",
        now="2026-09-24T00:00:03+00:00",
    )
    chat.feedback = feedback
    jobs = _Jobs(_job(feedback.feedback_id, idempotency_key="older-version"))
    cases = _Cases()

    analysis_handler.ChatRepo = chat
    result = await FeedbackAnalysisWorker(
        job_repository=jobs,
        case_repository=cases,
        handler=FeedbackAnalysisHandler(),
    ).run_once()

    assert result.status == "cancelled"
    assert jobs.finished == ("cancelled", "feedback_version_superseded")
    assert cases.results == []


async def test_worker_marks_persistence_failure_as_failed() -> None:
    chat = _Chat(feedback=None)
    feedback = ChatMessageFeedback.for_answer(
        message=chat.answer,
        feedback_id="feedback-1",
        user_id="user-1",
        rating="not_helpful",
        reason="incorrect",
        comment="The caption contains the missing information.",
        now="2026-09-24T00:00:03+00:00",
    )
    chat.feedback = feedback
    jobs = _Jobs(_job(feedback.feedback_id, idempotency_key=feedback.analysis_version_key))
    cases = _Cases(fail_on_save=True)

    analysis_handler.ChatRepo = chat
    result = await FeedbackAnalysisWorker(
        job_repository=jobs,
        case_repository=cases,
        handler=FeedbackAnalysisHandler(),
    ).run_once()

    assert result.status == "failed"
    assert jobs.finished == ("failed", "feedback_analysis_persistence_failed")


async def test_worker_rejects_unknown_payload_and_keeps_no_result() -> None:
    jobs = _Jobs(replace(_job("feedback-1"), payload_version=2))
    cases = _Cases()
    analysis_handler.ChatRepo = _Chat(feedback=None)
    worker = FeedbackAnalysisWorker(
        job_repository=jobs,
        case_repository=cases,
        handler=FeedbackAnalysisHandler(),
    )
    result = await worker.run_once()
    assert result.status == "failed"
    assert jobs.finished == ("failed", "unsupported_feedback_analysis_job")
    assert not cases.results


async def test_feedback_digest_is_stable_when_the_same_version_is_reanalysed():
    chat = _Chat(feedback=None)
    chat.feedback = ChatMessageFeedback.for_answer(
        message=chat.answer, feedback_id="feedback-1", user_id="user-1",
        rating="not_helpful", reason="incorrect", comment="Check the caption.",
        now="2026-09-24T00:00:03+00:00",
    )
    job = _job(chat.feedback.feedback_id, idempotency_key=chat.feedback.analysis_version_key)
    analysis_handler.ChatRepo = chat
    handler = FeedbackAnalysisHandler()
    first, snapshot, _ = await handler.handle(job)
    second, repeated_snapshot, _ = await handler.handle(job)
    assert second.input_digest == first.input_digest
    assert repeated_snapshot == snapshot
    assert first.input_digest == "07566d4a74c484c6acf31619676b04f6b6ba01313e7222a55d654f92c3253c58"
