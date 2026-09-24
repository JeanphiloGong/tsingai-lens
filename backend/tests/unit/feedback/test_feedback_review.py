from __future__ import annotations

import pytest

from application.feedback.feedback_case_service import FeedbackCaseService
from domain.chat import ChatMessage, ChatSession
from domain.feedback import AnalysisResult, EvidenceCoverage, FeedbackAnnotation, FeedbackCase, ReviewDecision


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Collections:
    async def get_collection_for_user(self, collection_id: str, user_id: str):
        if user_id != "user-1":
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


class _Cases:
    def __init__(self, case, result, annotation):
        self.case = case
        self.result = result
        self.annotation = annotation
        self.decisions: list[ReviewDecision] = []

    async def read_case(self, case_id: str):
        return self.case if case_id == self.case.case_id else None

    async def read_analysis_results(self, result_ids):
        return (self.result,) if self.result.result_id in result_ids else ()

    async def read_annotation(self, case_id: str):
        return self.annotation if case_id == self.case.case_id else None

    async def read_review_decisions(self, case_id: str):
        return tuple(self.decisions)

    async def append_review_decision(self, decision, *, expected_annotation_digest, now):
        if expected_annotation_digest != self.annotation.annotation_digest:
            raise ValueError("feedback_case_stale")
        actual = ReviewDecision(
            decision_id=decision.decision_id, case_id=decision.case_id,
            annotation_digest=decision.annotation_digest, decision=decision.decision,
            reason=decision.reason, created_by=decision.created_by,
            seq=len(self.decisions) + 1, created_at=now,
        )
        self.decisions.append(actual)
        status = {"accept": "accepted", "reject": "rejected", "insufficient": "insufficient", "withdraw": "withdrawn"}[actual.decision]
        self.case = FeedbackCase(**{**self.case.to_record(), "status": status, "updated_at": now})
        return actual


def _fixture():
    session = ChatSession.create(session_id="session-1", user_id="user-1", collection_id="collection-1", created_at="2026-09-24T00:00:00+00:00")
    question = ChatMessage.user(message_id="question-1", session_id=session.session_id, content="Compare", created_at="2026-09-24T00:00:01+00:00")
    answer = ChatMessage.assistant(message_id="answer-1", session_id=session.session_id, content="Answer", created_at="2026-09-24T00:00:02+00:00")
    result = AnalysisResult(result_id="result-1", job_id="job-1", feedback_id="feedback-1", session_id=session.session_id, collection_id=session.collection_id, anchor_message_id=answer.message_id, problem_type="source_missing", confidence=.8, related_message_ids=(question.message_id,), suggested_evidence=(), suggested_target=None, evidence_coverage=EvidenceCoverage(coverage_status="partial"), model="test", input_digest="a" * 64, created_at="2026-09-24T00:00:03+00:00")
    case = FeedbackCase(case_id="case-1", collection_id=session.collection_id, session_id=session.session_id, anchor_message_id=answer.message_id, source_signal_ids=(), analysis_result_ids=(result.result_id,), context_snapshot={}, status="ready_for_review", created_at="2026-09-24T00:00:03+00:00", updated_at="2026-09-24T00:00:03+00:00")
    annotation = FeedbackAnnotation.build(annotation_id="annotation-1", case_id=case.case_id, version=1, problem_type="source_missing", severity="high", target=None, support_source_refs=(), dataset_uses=("evaluation",), reason="checked", created_by="user-1", created_at="2026-09-24T00:00:04+00:00")
    case = FeedbackCase(**{**case.to_record(), "annotation_digest": annotation.annotation_digest})
    repo = _Cases(case, result, annotation)
    service = FeedbackCaseService(case_repository=repo, chat_repository=_Chat(session, (question, answer)), collection_service=_Collections())
    return service, repo, annotation


async def test_review_is_append_only_and_projects_withdrawal() -> None:
    service, repo, annotation = _fixture()
    accepted = await service.submit_review_for_user(case_id="case-1", user_id="user-1", expected_annotation_digest=annotation.annotation_digest, decision="accept", reason="evidence checked", now="2026-09-24T00:05:00+00:00")
    assert accepted.seq == 1
    assert repo.case.status == "accepted"
    withdrawn = await service.submit_review_for_user(case_id="case-1", user_id="user-1", expected_annotation_digest=annotation.annotation_digest, decision="withdraw", reason="new concern", now="2026-09-24T00:06:00+00:00")
    assert withdrawn.seq == 2
    assert repo.case.status == "withdrawn"
    assert [item.decision for item in repo.decisions] == ["accept", "withdraw"]


async def test_review_requires_current_annotation_digest() -> None:
    service, _, _ = _fixture()
    with pytest.raises(ValueError, match="feedback_case_stale"):
        await service.submit_review_for_user(case_id="case-1", user_id="user-1", expected_annotation_digest="b" * 64, decision="accept", reason="stale")
