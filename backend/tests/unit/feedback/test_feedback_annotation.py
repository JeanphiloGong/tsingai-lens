from __future__ import annotations

import asyncio

import pytest

from application.feedback.feedback_case_service import FeedbackCaseService
from domain.chat import ChatMessage, ChatSession
from domain.chat.feedback import ChatMessageFeedback
from domain.feedback import AnalysisResult, EvidenceCoverage, FeedbackAnnotation, FeedbackCase


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Collections:
    async def get_collection_for_user(self, collection_id: str, user_id: str):
        if (collection_id, user_id) != ("collection-1", "user-1"):
            raise FileNotFoundError("collection not found")
        return {"collection_id": collection_id}


class _Chat:
    def __init__(self, session, messages):
        self.session = session
        self.messages = messages

    async def read_session(self, session_id: str):
        return self.session if session_id == self.session.session_id else None

    async def read_messages(self, session_id: str):
        return self.messages

    async def read_feedback_by_id(self, feedback_id: str):
        return None


class _Cases:
    def __init__(self, case, result):
        self.case = case
        self.result = result
        self.annotation: FeedbackAnnotation | None = None

    async def read_case(self, case_id: str):
        return self.case if case_id == self.case.case_id else None

    async def read_analysis_results(self, result_ids):
        return (self.result,) if self.result.result_id in result_ids else ()

    async def read_annotation(self, case_id: str):
        return self.annotation if case_id == self.case.case_id else None

    async def save_annotation(self, annotation, *, expected_digest, now):
        if expected_digest != self.case.annotation_digest:
            raise ValueError("feedback_case_stale")
        if self.annotation is not None and self.annotation.annotation_digest == annotation.annotation_digest:
            return self.annotation
        if self.case.status not in {"needs_annotation", "ready_for_review", "rejected", "insufficient"}:
            raise ValueError("feedback_case_not_annotatable")
        expected_version = self.annotation.version + 1 if self.annotation is not None else 1
        if annotation.version != expected_version:
            raise ValueError("annotation_version_conflict")
        self.annotation = annotation
        self.case = FeedbackCase(
            **{**self.case.to_record(), "status": "ready_for_review", "annotation_digest": annotation.annotation_digest, "updated_at": now}
        )
        return annotation


def _fixture():
    session = ChatSession.create(
        session_id="session-1", user_id="user-1", collection_id="collection-1", created_at="2026-09-24T00:00:00+00:00"
    )
    question = ChatMessage.user(message_id="question-1", session_id=session.session_id, content="Compare A and B", created_at="2026-09-24T00:00:01+00:00")
    answer = ChatMessage.assistant(message_id="answer-1", session_id=session.session_id, content="B has no preheating", created_at="2026-09-24T00:00:02+00:00")
    feedback = ChatMessageFeedback.for_answer(message=answer, feedback_id="feedback-1", user_id="user-1", rating="not_helpful", reason="incorrect", comment=None, now="2026-09-24T00:00:03+00:00")
    result = AnalysisResult(
        result_id="result-1", job_id="job-1", feedback_id=feedback.feedback_id, session_id=session.session_id,
        collection_id=session.collection_id, anchor_message_id=answer.message_id, problem_type="source_missing", confidence=.8,
        related_message_ids=(question.message_id, answer.message_id), suggested_evidence=("source-b",), suggested_target=None,
        evidence_coverage=EvidenceCoverage(inspected_sources=({"source_ref": "source-a", "document_title": "A"},), gaps=("B omitted",), coverage_status="partial"),
        model="test", input_digest="a" * 64, created_at="2026-09-24T00:00:04+00:00",
    )
    case = FeedbackCase(case_id="case-1", collection_id=session.collection_id, session_id=session.session_id, anchor_message_id=answer.message_id, source_signal_ids=(feedback.feedback_id,), analysis_result_ids=(result.result_id,), context_snapshot={}, status="needs_annotation", created_at="2026-09-24T00:00:04+00:00", updated_at="2026-09-24T00:00:04+00:00")
    repo = _Cases(case, result)
    service = FeedbackCaseService(case_repository=repo, chat_repository=_Chat(session, (question, answer)), collection_service=_Collections())
    return service, repo


async def test_annotation_is_versioned_and_source_scoped() -> None:
    service, repo = _fixture()
    annotation = await service.save_annotation_for_user(
        case_id="case-1", user_id="user-1", expected_digest=None, problem_type="source_missing", severity="high",
        target=None, support_source_refs=("source-a",), dataset_uses=("evaluation",), reason="B was not inspected.", now="2026-09-24T00:01:00+00:00"
    )
    assert annotation.version == 1
    assert len(annotation.annotation_digest) == 64
    assert repo.case.status == "ready_for_review"

    with pytest.raises(ValueError, match="annotation_source_not_in_case"):
        await service.save_annotation_for_user(
            case_id="case-1", user_id="user-1", expected_digest=annotation.annotation_digest, problem_type="source_missing", severity="high",
            target=None, support_source_refs=("foreign-source",), dataset_uses=("evaluation",), reason="wrong source", now="2026-09-24T00:02:00+00:00"
        )


async def test_annotation_rejects_stale_digest_and_missing_sft_target() -> None:
    service, _ = _fixture()
    with pytest.raises(ValueError, match="feedback_case_stale"):
        await service.save_annotation_for_user(
            case_id="case-1", user_id="user-1", expected_digest="b" * 64, problem_type="source_missing", severity="medium",
            target=None, support_source_refs=(), dataset_uses=("evaluation",), reason="stale", now="2026-09-24T00:01:00+00:00"
        )
    with pytest.raises(ValueError, match="sft annotation requires a target"):
        await service.save_annotation_for_user(
            case_id="case-1", user_id="user-1", expected_digest=None, problem_type="source_missing", severity="medium",
            target=None, support_source_refs=(), dataset_uses=("sft",), reason="needs target", now="2026-09-24T00:01:00+00:00"
        )
    with pytest.raises(ValueError, match="sft annotation requires support sources"):
        await service.save_annotation_for_user(
            case_id="case-1", user_id="user-1", expected_digest=None,
            problem_type="source_missing", severity="medium", target="Corrected answer",
            support_source_refs=(), dataset_uses=("sft",), reason="needs source", now="2026-09-24T00:01:00+00:00"
        )


async def test_rejected_case_can_be_revised_without_erasing_review_history() -> None:
    service, repo = _fixture()
    first = await service.save_annotation_for_user(
        case_id="case-1", user_id="user-1", expected_digest=None,
        problem_type="source_missing", severity="high", target=None,
        support_source_refs=("source-a",), dataset_uses=("evaluation",),
        reason="Initial review needs a better explanation.",
        now="2026-09-24T00:01:00+00:00",
    )
    repo.case = FeedbackCase(**{**repo.case.to_record(), "status": "rejected"})
    second = await service.save_annotation_for_user(
        case_id="case-1", user_id="user-1", expected_digest=first.annotation_digest,
        problem_type="source_missing", severity="critical", target=None,
        support_source_refs=("source-a",), dataset_uses=("evaluation",),
        reason="The source omission is now documented precisely.",
        now="2026-09-24T00:02:00+00:00",
    )
    assert second.version == 2
    assert second.annotation_digest != first.annotation_digest
    assert repo.case.status == "ready_for_review"


async def test_annotation_revision_rejects_terminal_accepted_case() -> None:
    service, repo = _fixture()
    first = await service.save_annotation_for_user(
        case_id="case-1", user_id="user-1", expected_digest=None,
        problem_type="source_missing", severity="high", target=None,
        support_source_refs=("source-a",), dataset_uses=("evaluation",),
        reason="Accepted baseline.", now="2026-09-24T00:01:00+00:00",
    )
    repo.case = FeedbackCase(**{**repo.case.to_record(), "status": "accepted"})
    with pytest.raises(ValueError, match="feedback_case_not_annotatable"):
        await service.save_annotation_for_user(
            case_id="case-1", user_id="user-1", expected_digest=first.annotation_digest,
            problem_type="source_missing", severity="critical", target=None,
            support_source_refs=("source-a",), dataset_uses=("evaluation",),
            reason="Must not silently replace accepted material.",
            now="2026-09-24T00:02:00+00:00",
        )


async def test_concurrent_first_annotations_allow_one_digest_winner() -> None:
    service, repo = _fixture()
    original_save = repo.save_annotation
    gate = asyncio.Event()
    entered = 0

    async def racing_save(annotation, *, expected_digest, now):
        nonlocal entered
        entered += 1
        if entered == 2:
            gate.set()
        await gate.wait()
        return await original_save(annotation, expected_digest=expected_digest, now=now)

    repo.save_annotation = racing_save  # type: ignore[method-assign]

    async def write(reason: str):
        try:
            return await service.save_annotation_for_user(
                case_id="case-1", user_id="user-1", expected_digest=None,
                problem_type="source_missing", severity="high", target=None,
                support_source_refs=("source-a",), dataset_uses=("evaluation",),
                reason=reason, now="2026-09-24T00:01:00+00:00",
            )
        except ValueError as exc:
            return exc

    first, second = await asyncio.gather(write("first"), write("second"))
    winners = [item for item in (first, second) if isinstance(item, FeedbackAnnotation)]
    failures = [item for item in (first, second) if isinstance(item, ValueError)]
    assert len(winners) == 1
    assert len(failures) == 1
    assert str(failures[0]) == "feedback_case_stale"
    assert repo.annotation is winners[0]


def test_annotation_digest_must_be_hex_sha256() -> None:
    with pytest.raises(ValueError, match="annotation digest must be sha256"):
        FeedbackAnnotation(
            annotation_id="annotation-1", case_id="case-1", version=1,
            problem_type="source_missing", severity="high", target=None,
            support_source_refs=(), dataset_uses=("evaluation",), reason="checked",
            annotation_digest="z" * 64, created_by="user-1",
            created_at="2026-09-24T00:00:00+00:00", updated_at="2026-09-24T00:00:00+00:00",
        )
