from __future__ import annotations

import asyncio

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
        if decision.decision == "withdraw":
            if self.case.status != "accepted":
                raise ValueError("feedback_case_not_withdrawable")
        elif self.case.status != "ready_for_review":
            raise ValueError("feedback_case_not_reviewable")
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


async def test_accept_requires_a_declared_dataset_use() -> None:
    service, repo, annotation = _fixture()
    empty = FeedbackAnnotation.build(
        annotation_id=annotation.annotation_id, case_id=annotation.case_id,
        version=annotation.version, problem_type=annotation.problem_type,
        severity=annotation.severity, target=annotation.target,
        support_source_refs=annotation.support_source_refs, dataset_uses=(),
        reason=annotation.reason, created_by=annotation.created_by,
        created_at=annotation.created_at,
    )
    repo.annotation = empty
    repo.case = FeedbackCase(**{**repo.case.to_record(), "annotation_digest": empty.annotation_digest})
    with pytest.raises(ValueError, match="review_dataset_use_missing"):
        await service.submit_review_for_user(
            case_id="case-1", user_id="user-1",
            expected_annotation_digest=empty.annotation_digest,
            decision="accept", reason="nothing selected",
        )


async def test_preference_accept_requires_a_distinct_corrected_answer() -> None:
    service, repo, annotation = _fixture()
    preference = FeedbackAnnotation.build(
        annotation_id=annotation.annotation_id, case_id=annotation.case_id,
        version=annotation.version, problem_type=annotation.problem_type,
        severity=annotation.severity, target="Answer",
        support_source_refs=("source-ref",), dataset_uses=("preference",),
        reason=annotation.reason, created_by=annotation.created_by,
        created_at=annotation.created_at,
    )
    repo.annotation = preference
    repo.case = FeedbackCase(**{**repo.case.to_record(), "annotation_digest": preference.annotation_digest})
    with pytest.raises(ValueError, match="review_preference_pair_missing"):
        await service.submit_review_for_user(
            case_id="case-1", user_id="user-1",
            expected_annotation_digest=preference.annotation_digest,
            decision="accept", reason="chosen answer is unchanged",
        )


async def test_review_history_keeps_old_digest_when_new_annotation_is_reviewed() -> None:
    service, repo, first = _fixture()
    rejected = await service.submit_review_for_user(
        case_id="case-1", user_id="user-1",
        expected_annotation_digest=first.annotation_digest,
        decision="reject", reason="needs a clearer source explanation",
        now="2026-09-24T00:05:00+00:00",
    )
    second = FeedbackAnnotation.build(
        annotation_id="annotation-2", case_id=first.case_id, version=2,
        problem_type=first.problem_type, severity="critical", target=None,
        support_source_refs=(), dataset_uses=("evaluation",),
        reason="The source omission is now explicit.", created_by="user-1",
        created_at="2026-09-24T00:06:00+00:00",
    )
    repo.annotation = second
    repo.case = FeedbackCase(**{
        **repo.case.to_record(), "status": "ready_for_review",
        "annotation_digest": second.annotation_digest,
    })
    accepted = await service.submit_review_for_user(
        case_id="case-1", user_id="user-1",
        expected_annotation_digest=second.annotation_digest,
        decision="accept", reason="updated evidence checked",
        now="2026-09-24T00:07:00+00:00",
    )
    assert rejected.seq == 1
    assert accepted.seq == 2
    assert rejected.annotation_digest != accepted.annotation_digest
    assert tuple(item.decision for item in repo.decisions) == ("reject", "accept")


async def test_concurrent_accepts_have_one_history_winner() -> None:
    service, repo, annotation = _fixture()
    original_append = repo.append_review_decision
    gate = asyncio.Event()
    entered = 0

    async def racing_append(decision, *, expected_annotation_digest, now):
        nonlocal entered
        entered += 1
        if entered == 2:
            gate.set()
        await gate.wait()
        return await original_append(
            decision, expected_annotation_digest=expected_annotation_digest, now=now
        )

    repo.append_review_decision = racing_append  # type: ignore[method-assign]

    async def submit(reason: str):
        try:
            return await service.submit_review_for_user(
                case_id="case-1", user_id="user-1",
                expected_annotation_digest=annotation.annotation_digest,
                decision="accept", reason=reason,
            )
        except ValueError as exc:
            return exc

    first, second = await asyncio.gather(submit("first"), submit("second"))
    winners = [item for item in (first, second) if isinstance(item, ReviewDecision)]
    failures = [item for item in (first, second) if isinstance(item, ValueError)]
    assert len(winners) == 1
    assert len(failures) == 1
    assert str(failures[0]) == "feedback_case_not_reviewable"
    assert repo.case.status == "accepted"


def test_review_digest_must_be_hex_sha256() -> None:
    with pytest.raises(ValueError, match="review annotation digest must be sha256"):
        ReviewDecision(
            decision_id="review-1", case_id="case-1", annotation_digest="z" * 64,
            decision="accept", reason="checked", created_by="user-1", seq=1,
            created_at="2026-09-24T00:00:00+00:00",
        )
