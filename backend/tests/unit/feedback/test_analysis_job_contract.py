from __future__ import annotations

from dataclasses import replace

import pytest

from application.chat.session_service import ChatSessionService
from domain.chat import ChatMessage, ChatSession
from domain.chat.feedback import ChatMessageFeedback
from domain.feedback import AnalysisJob


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Collections:
    async def get_collection_for_user(self, collection_id: str, user_id: str):
        if collection_id != "collection-1" or user_id != "user-1":
            raise FileNotFoundError("collection not found")
        return {"collection_id": collection_id}


class _Chat:
    def __init__(self) -> None:
        self.session = ChatSession.create(
            session_id="session-1",
            user_id="user-1",
            collection_id="collection-1",
            created_at="2026-09-24T00:00:00+00:00",
        )
        self.answer = ChatMessage.assistant(
            message_id="answer-1",
            session_id=self.session.session_id,
            content="The answer is traceable.",
            created_at="2026-09-24T00:00:01+00:00",
        )
        self.feedback: ChatMessageFeedback | None = None

    async def read_session(self, session_id: str):
        return self.session if session_id == self.session.session_id else None

    async def read_message(self, message_id: str):
        return self.answer if message_id == self.answer.message_id else None

    async def read_feedback(self, session_id: str, user_id: str):
        if (
            self.feedback is not None
            and self.feedback.session_id == session_id
            and self.feedback.user_id == user_id
        ):
            return (self.feedback,)
        return ()

    async def save_feedback(self, feedback: ChatMessageFeedback):
        if self.feedback is not None:
            # PostgreSQL keeps the identity and timestamps for an identical
            # upsert; changed fields receive the new updated_at value.
            same_payload = (
                self.feedback.rating == feedback.rating
                and self.feedback.reason == feedback.reason
                and self.feedback.comment == feedback.comment
                and self.feedback.response_digest == feedback.response_digest
            )
            feedback = replace(
                feedback,
                feedback_id=self.feedback.feedback_id,
                created_at=self.feedback.created_at,
                updated_at=(
                    self.feedback.updated_at if same_payload else feedback.updated_at
                ),
            )
        self.feedback = feedback
        return feedback

    async def delete_feedback(self, *, session_id: str, message_id: str, user_id: str):
        if self.feedback is not None and (
            self.feedback.session_id,
            self.feedback.message_id,
            self.feedback.user_id,
        ) == (session_id, message_id, user_id):
            self.feedback = None


class _Jobs:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, str]] = []
        self.cancelled: list[dict[str, str]] = []

    async def enqueue_feedback_analysis(self, **kwargs):
        self.enqueued.append(kwargs)
        return None

    async def cancel_feedback_analysis_jobs(self, **kwargs):
        self.cancelled.append(kwargs)
        return 1


def _service(chat: _Chat, jobs: _Jobs) -> ChatSessionService:
    return ChatSessionService(
        collection_service=_Collections(),
        source_artifact_repository=object(),
        repository=chat,
        runner=None,
        analysis_job_repository=jobs,
    )


async def test_feedback_version_is_the_idempotent_analysis_job_identity() -> None:
    chat = _Chat()
    jobs = _Jobs()
    service = _service(chat, jobs)

    first = await service.set_message_feedback_for_user(
        "session-1",
        "answer-1",
        "user-1",
        rating="not_helpful",
        reason="incorrect",
        comment="The source says otherwise.",
    )
    second = await service.set_message_feedback_for_user(
        "session-1",
        "answer-1",
        "user-1",
        rating="not_helpful",
        reason="incorrect",
        comment="The source says otherwise.",
    )
    changed = await service.set_message_feedback_for_user(
        "session-1",
        "answer-1",
        "user-1",
        rating="not_helpful",
        reason="incomplete",
        comment="The source says otherwise.",
    )

    assert first is not None and second is not None and changed is not None
    assert first.feedback_id == second.feedback_id == changed.feedback_id
    assert len(jobs.enqueued) == 3
    assert jobs.enqueued[0]["idempotency_key"] == jobs.enqueued[1]["idempotency_key"]
    assert jobs.enqueued[2]["idempotency_key"] != jobs.enqueued[0]["idempotency_key"]
    assert all(item["feedback_id"] == first.feedback_id for item in jobs.enqueued)

    await service.set_message_feedback_for_user(
        "session-1", "answer-1", "user-1", rating=None
    )
    assert len(jobs.cancelled) == 1
    assert jobs.cancelled[0]["feedback_id"] == first.feedback_id
    assert chat.feedback is None


def test_terminal_analysis_job_requires_a_finish_time() -> None:
    with pytest.raises(ValueError, match="terminal analysis jobs require finished_at"):
        AnalysisJob(
            job_id="job-1",
            job_type="feedback_analysis",
            payload_version=1,
            payload={"feedback_id": "feedback-1"},
            status="succeeded",
            idempotency_key="feedback-version-1",
            available_at="2026-09-24T00:00:00+00:00",
            created_at="2026-09-24T00:00:00+00:00",
            updated_at="2026-09-24T00:00:00+00:00",
        )
