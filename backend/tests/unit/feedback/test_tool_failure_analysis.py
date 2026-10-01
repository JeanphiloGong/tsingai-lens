from __future__ import annotations

from dataclasses import replace

import pytest

from application.feedback.tool_failure_handler import ToolFailureAnalysisHandler
from application.feedback.tool_failure_worker import ToolFailureAnalysisWorker
from application.repositories.analysis_job_repository import (
    TOOL_FAILURE_JOB_TYPE,
    AnalysisJob,
    tool_failure_idempotency_key,
)
from domain.chat import (
    ChatMessage,
    ChatSession,
    ChatToolCall,
    ChatToolRequest,
    ChatToolResult,
    ToolResultStatus,
    ToolRisk,
)
from domain.feedback import tool_failure_signal_id, tool_result_digest

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Chat:
    def __init__(self, messages, call, session):
        self.messages = messages
        self.call = call
        self.session = session

    async def read_session(self, session_id: str):
        return self.session if session_id == self.session.session_id else None

    async def read_messages(self, session_id: str):
        return self.messages if session_id == self.session.session_id else ()

    async def read_tool_call(self, tool_call_id: str):
        return self.call if tool_call_id == self.call.tool_call_id else None


class _Jobs:
    def __init__(self, job: AnalysisJob):
        self.job = job
        self.finished = None

    async def claim_next_tool_failure_analysis_job(self, now: str):
        if self.job.status != "pending":
            return None
        self.job = replace(self.job, status="running", started_at=now, updated_at=now)
        return self.job

    async def mark_succeeded(self, job_id: str, result_id: str, finished_at: str):
        self.finished = ("succeeded", result_id)
        self.job = replace(self.job, status="succeeded", result_id=result_id,
                           finished_at=finished_at, updated_at=finished_at)
        return self.job

    async def mark_failed(self, job_id: str, error_code: str, finished_at: str):
        self.finished = ("failed", error_code)
        self.job = replace(self.job, status="failed", error_code=error_code,
                           finished_at=finished_at, updated_at=finished_at)
        return self.job

    async def mark_cancelled(self, job_id: str, error_code: str, finished_at: str):
        self.finished = ("cancelled", error_code)
        self.job = replace(self.job, status="cancelled", error_code=error_code,
                           finished_at=finished_at, updated_at=finished_at)
        return self.job


class _Cases:
    def __init__(self):
        self.calls = []

    async def upsert_case_from_tool_failure(self, result, *, context_snapshot,
                                            source_signal_ids, now):
        self.calls.append({
            "result": result,
            "context_snapshot": context_snapshot,
            "source_signal_ids": source_signal_ids,
        })


class _FailingCases(_Cases):
    async def upsert_case_from_tool_failure(self, result, *, context_snapshot,
                                            source_signal_ids, now):
        raise RuntimeError("database unavailable")


def _fixture():
    session = ChatSession.create(
        session_id="session-1", user_id="user-1", collection_id="collection-1",
        created_at="2026-09-25T00:00:00+00:00",
    )
    request = ChatToolRequest(
        tool_call_id="call-1", name="read_source", arguments={"document_id": "doc-1"}, position=0,
    )
    assistant = ChatMessage.assistant_tool_calls(
        message_id="assistant-1", session_id=session.session_id, content="",
        tool_calls=(request,), created_at="2026-09-25T00:00:01+00:00",
    )
    call = ChatToolCall.requested(
        tool_call_id="call-1", session_id=session.session_id,
        assistant_message_id=assistant.message_id, name=request.name,
        arguments=request.arguments, risk=ToolRisk.READ,
    ).start("2026-09-25T00:00:01+00:00").fail(
        "source_unavailable", "2026-09-25T00:00:02+00:00"
    )
    result = ChatToolResult(
        tool_call_id=call.tool_call_id, status=ToolResultStatus.FAILED,
        error_code="source_unavailable", error_message="The source is unavailable.",
    )
    result_message = ChatMessage.from_tool_result(
        message_id="tool-result-1", session_id=session.session_id,
        result=result, created_at="2026-09-25T00:00:02+00:00",
    )
    answer = ChatMessage.assistant(
        message_id="answer-1", session_id=session.session_id,
        content="I could not inspect the source.", created_at="2026-09-25T00:00:03+00:00",
    )
    messages = (assistant, result_message, answer)
    digest = tool_result_digest(result.to_record())
    job = AnalysisJob(
        job_id="job-tool-1", job_type=TOOL_FAILURE_JOB_TYPE, payload_version=1,
        payload={
            "session_id": session.session_id,
            "tool_call_id": call.tool_call_id,
            "assistant_message_id": assistant.message_id,
            "result_message_id": result_message.message_id,
            "result_digest": digest,
        }, status="pending",
        idempotency_key=tool_failure_idempotency_key(
            session_id=session.session_id, tool_call_id=call.tool_call_id,
            assistant_message_id=assistant.message_id,
            result_message_id=result_message.message_id, result_digest=digest,
        ), available_at="2026-09-25T00:00:00+00:00",
        created_at="2026-09-25T00:00:00+00:00", updated_at="2026-09-25T00:00:00+00:00",
    )
    return session, messages, call, job


async def test_handler_builds_independent_tool_failure_result():
    session, messages, call, job = _fixture()
    result, snapshot, source_ids = await ToolFailureAnalysisHandler(
        chat_repository=_Chat(messages, call, session)
    ).handle(job)

    assert result.signal_id == tool_failure_signal_id(call.tool_call_id, "tool-result-1")
    assert result.tool_call_id == call.tool_call_id
    assert result.result_message_id == "tool-result-1"
    assert result.problem_type == "tool_failure"
    assert result.suggested_target is None
    assert snapshot["tool_failure"]["error_code"] == "source_unavailable"
    assert snapshot["answer_message_id"] == "answer-1"
    assert source_ids == (result.signal_id,)


async def test_worker_cancels_when_result_is_no_longer_a_failure():
    session, messages, call, job = _fixture()
    successful = ChatToolResult(tool_call_id=call.tool_call_id, status="succeeded", data={"ok": True})
    changed_messages = (messages[0], ChatMessage.from_tool_result(
        message_id=messages[1].message_id, session_id=session.session_id,
        result=successful, created_at=messages[1].created_at,
    ), messages[2])
    changed_digest = tool_result_digest(successful.to_record())
    changed_job = replace(
        job,
        payload={**job.payload, "result_digest": changed_digest},
        idempotency_key=tool_failure_idempotency_key(
            session_id=session.session_id,
            tool_call_id=call.tool_call_id,
            assistant_message_id=messages[0].message_id,
            result_message_id=messages[1].message_id,
            result_digest=changed_digest,
        ),
    )
    jobs = _Jobs(changed_job)
    cases = _Cases()
    outcome = await ToolFailureAnalysisWorker(
        job_repository=jobs, case_repository=cases,
        handler=ToolFailureAnalysisHandler(chat_repository=_Chat(changed_messages, call, session)),
    ).run_once()

    assert outcome.status == "cancelled"
    assert jobs.job.status == "cancelled"
    assert jobs.finished == ("cancelled", "tool_failure_not_candidate")
    assert cases.calls == []


async def test_worker_marks_persistence_failure_without_claiming_success():
    session, messages, call, job = _fixture()
    jobs = _Jobs(job)
    outcome = await ToolFailureAnalysisWorker(
        job_repository=jobs,
        case_repository=_FailingCases(),
        handler=ToolFailureAnalysisHandler(
            chat_repository=_Chat(messages, call, session)
        ),
    ).run_once()

    assert outcome.status == "failed"
    assert jobs.finished == ("failed", "tool_failure_persistence_failed")
    assert jobs.job.result_id is None


async def test_handler_rejects_changed_result_digest():
    session, messages, call, job = _fixture()
    changed = replace(job, payload={**job.payload, "result_digest": "f" * 64})
    with pytest.raises(ValueError, match="identity_mismatch"):
        await ToolFailureAnalysisHandler(chat_repository=_Chat(messages, call, session)).handle(changed)


async def test_handler_rejects_tool_result_persisted_before_its_assistant_request():
    session, messages, call, job = _fixture()
    reordered = (messages[1], messages[0], messages[2])

    with pytest.raises(ValueError, match="order_invalid"):
        await ToolFailureAnalysisHandler(
            chat_repository=_Chat(reordered, call, session)
        ).handle(job)


async def test_handler_rejects_a_user_message_between_request_and_tool_result():
    session, messages, call, job = _fixture()
    follow_up = ChatMessage.user(
        message_id="user-interruption",
        session_id=session.session_id,
        content="Please answer this separate question.",
        created_at="2026-09-25T00:00:01.500000+00:00",
    )
    interrupted = (messages[0], follow_up, messages[1], messages[2])

    with pytest.raises(ValueError, match="order_invalid"):
        await ToolFailureAnalysisHandler(
            chat_repository=_Chat(interrupted, call, session)
        ).handle(job)


async def test_handler_rejects_a_persisted_call_that_is_missing_from_assistant_requests():
    session, messages, call, job = _fixture()
    mismatched_request = ChatToolRequest(
        tool_call_id=call.tool_call_id,
        name="different_tool",
        arguments={"document_id": "doc-1"},
        position=0,
    )
    assistant = ChatMessage.assistant_tool_calls(
        message_id=messages[0].message_id,
        session_id=session.session_id,
        content="",
        tool_calls=(mismatched_request,),
        created_at=messages[0].created_at,
    )
    mismatched = (assistant, messages[1], messages[2])

    with pytest.raises(ValueError, match="identity_mismatch"):
        await ToolFailureAnalysisHandler(
            chat_repository=_Chat(mismatched, call, session)
        ).handle(job)


async def test_handler_does_not_attach_an_answer_from_a_later_user_turn():
    session, messages, call, job = _fixture()
    later_user = ChatMessage.user(
        message_id="later-user",
        session_id=session.session_id,
        content="Start another turn.",
        created_at="2026-09-25T00:00:04+00:00",
    )
    later_answer = ChatMessage.assistant(
        message_id="later-answer",
        session_id=session.session_id,
        content="The later turn answer.",
        created_at="2026-09-25T00:00:05+00:00",
    )
    result, snapshot, _ = await ToolFailureAnalysisHandler(
        chat_repository=_Chat(
            (*messages[:2], later_user, later_answer), call, session
        )
    ).handle(job)

    assert result.related_message_ids == (messages[0].message_id, messages[1].message_id)
    assert snapshot["answer_message_id"] == messages[0].message_id
