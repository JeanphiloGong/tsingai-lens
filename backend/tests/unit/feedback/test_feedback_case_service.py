from __future__ import annotations

import pytest

from application.feedback.feedback_case_service import FeedbackCaseService
from domain.chat import ChatMessage, ChatSession
from domain.chat.feedback import ChatMessageFeedback
from domain.feedback import (
    AnalysisResult,
    CorrectionSignalAnalysisResult,
    EvidenceCoverage,
    FeedbackCase,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Collections:
    async def get_collection_for_user(self, collection_id: str, user_id: str):
        if collection_id != "collection-1" or user_id != "user-1":
            raise FileNotFoundError("collection not found")
        return {"collection_id": collection_id}

    async def list_collections(self, user_id: str):
        return (type("CollectionSummary", (), {"collection_id": "collection-1"})(),)


class _Chat:
    def __init__(self, feedback, messages):
        self.feedback = feedback
        self.messages = messages

    async def read_messages(self, session_id: str):
        return self.messages

    async def read_session(self, session_id: str):
        return ChatSession.create(
            session_id=session_id,
            user_id="user-1",
            collection_id="collection-1",
            created_at="2026-09-24T00:00:00+00:00",
        )

    async def read_feedback_by_id(self, feedback_id: str):
        return self.feedback if self.feedback.feedback_id == feedback_id else None


class _Cases:
    def __init__(self, case, result, signal_result=None):
        self.case = case
        self.result = result
        self.signal_result = signal_result

    async def list_cases(self, **kwargs):
        ids = kwargs.get("collection_ids")
        return (self.case,) if ids and self.case.collection_id in ids else ()

    async def read_case(self, case_id: str):
        return self.case if case_id == self.case.case_id else None

    async def read_analysis_results(self, result_ids):
        return (self.result,) if self.result.result_id in result_ids else ()

    async def read_correction_signal_analysis_results(self, result_ids):
        if self.signal_result is not None and self.signal_result.result_id in result_ids:
            return (self.signal_result,)
        return ()


def _fixture():
    session = ChatSession.create(
        session_id="session-1",
        user_id="user-1",
        collection_id="collection-1",
        created_at="2026-09-24T00:00:00+00:00",
    )
    question = ChatMessage.user(
        message_id="question-1",
        session_id=session.session_id,
        content="Compare papers A and B.",
        created_at="2026-09-24T00:00:01+00:00",
    )
    answer = ChatMessage.assistant(
        message_id="answer-1",
        session_id=session.session_id,
        content="Paper B has no preheating information.",
        created_at="2026-09-24T00:00:02+00:00",
    )
    feedback = ChatMessageFeedback.for_answer(
        message=answer,
        feedback_id="feedback-1",
        user_id="user-1",
        rating="not_helpful",
        reason="incorrect",
        comment="The figure caption contains it.",
        now="2026-09-24T00:00:03+00:00",
    )
    result = AnalysisResult(
        result_id="result-1",
        job_id="job-1",
        feedback_id=feedback.feedback_id,
        session_id=session.session_id,
        collection_id=session.collection_id,
        anchor_message_id=answer.message_id,
        problem_type="source_missing",
        confidence=0.87,
        related_message_ids=(question.message_id, answer.message_id),
        suggested_evidence=("source-b-caption",),
        suggested_target=None,
        evidence_coverage=EvidenceCoverage(
            requested_scope=({"document_id": "paper-a"}, {"document_id": "paper-b"}),
            inspected_sources=({
                "document_id": "paper-a",
                "document_title": "Paper A",
                "source_ref": "results",
                "quote": "A result",
            },),
            omitted_candidates=({
                "document_id": "paper-b",
                "document_title": "Paper B",
                "source_ref": "figure-3-caption",
                "reason": "not_read",
            },),
            gaps=("paper B caption was not inspected",),
            coverage_status="partial",
        ),
        model="rule-based-v1",
        input_digest="a" * 64,
        created_at="2026-09-24T00:00:04+00:00",
    )
    case = FeedbackCase(
        case_id="case-1",
        collection_id=session.collection_id,
        session_id=session.session_id,
        anchor_message_id=answer.message_id,
        source_signal_ids=(feedback.feedback_id,),
        analysis_result_ids=(result.result_id,),
        context_snapshot={"answer": answer.content},
        status="needs_annotation",
        created_at="2026-09-24T00:00:04+00:00",
        updated_at="2026-09-24T00:00:04+00:00",
    )
    return case, result, feedback, (question, answer)


async def test_case_service_returns_user_readable_detail_and_summary() -> None:
    case, result, feedback, messages = _fixture()
    service = FeedbackCaseService(
        case_repository=_Cases(case, result),
        chat_repository=_Chat(feedback, messages),
        collection_service=_Collections(),
    )

    summaries = await service.list_for_user(user_id="user-1", needs_human_review=True)
    detail = await service.read_for_user(case.case_id, "user-1")

    assert summaries[0].problem_type == "source_missing"
    assert summaries[0].confidence == 0.87
    assert detail["question"] == "Compare papers A and B."
    assert detail["answer"].startswith("Paper B")
    assert detail["source_signals"][0]["feedback_id"] == "feedback-1"
    assert detail["omitted_candidates"][0]["source_ref"] == "figure-3-caption"
    assert detail["coverage_status"] == "partial"
    assert detail["analysis"]["coverage_status"] == "partial"
    assert detail["technical_error"] is None
    assert summaries[0].answer_preview.startswith("Paper B")
    assert summaries[0].document_titles == ("Paper A", "Paper B")


async def test_case_service_hides_a_case_from_another_collection_owner() -> None:
    case, result, feedback, messages = _fixture()
    service = FeedbackCaseService(
        case_repository=_Cases(case, result),
        chat_repository=_Chat(feedback, messages),
        collection_service=_Collections(),
    )

    with pytest.raises(FileNotFoundError):
        await service.read_for_user(case.case_id, "other-user")


async def test_case_service_exports_candidate_analysis_with_lifecycle_marker() -> None:
    case, result, feedback, messages = _fixture()
    service = FeedbackCaseService(
        case_repository=_Cases(case, result),
        chat_repository=_Chat(feedback, messages),
        collection_service=_Collections(),
    )

    records = await service.export_for_user(
        user_id="user-1", collection_id="collection-1", status=None
    )

    assert len(records) == 1
    assert records[0]["export_kind"] == "candidate_analysis"
    assert records[0]["training_ready"] is False
    assert records[0]["question"] == "Compare papers A and B."


async def test_case_service_exposes_message_correction_signal_without_claiming_target() -> None:
    case, result, feedback, messages = _fixture()
    challenge = ChatMessage.user(
        message_id="challenge-1",
        session_id="session-1",
        content="不对，图注里有预热信息。",
        created_at="2026-09-24T00:00:05+00:00",
    )
    signal_result = CorrectionSignalAnalysisResult(
        result_id="signal-result-1",
        job_id="signal-job-1",
        signal_id="correction_signal:challenge-1",
        signal_type="natural_language_correction",
        session_id="session-1",
        collection_id="collection-1",
        anchor_message_id="answer-1",
        trigger_message_id="challenge-1",
        problem_type="fact_error",
        confidence=0.58,
        related_message_ids=("question-1", "answer-1", "challenge-1"),
        suggested_evidence=("figure-3-caption",),
        suggested_target=None,
        evidence_coverage=result.evidence_coverage,
        model="rule-based-correction-v1",
        input_digest="b" * 64,
        created_at="2026-09-24T00:00:06+00:00",
    )
    signal_case = FeedbackCase(
        **{
            **case.to_record(),
            "source_signal_ids": (feedback.feedback_id, signal_result.signal_id),
            "signal_analysis_result_ids": (signal_result.result_id,),
        }
    )
    service = FeedbackCaseService(
        case_repository=_Cases(signal_case, result, signal_result),
        chat_repository=_Chat(feedback, (*messages, challenge)),
        collection_service=_Collections(),
    )

    detail = await service.read_for_user(signal_case.case_id, "user-1")

    correction = next(
        item
        for item in detail["source_signals"]
        if item.get("signal_type") == "natural_language_correction"
    )
    assert correction["trigger_message_id"] == "challenge-1"
    assert correction["content"].startswith("不对")
    assert detail["analysis"]["signal_type"] == "natural_language_correction"
    assert detail["analysis"]["suggested_target"] is None
    assert detail["analysis"]["resolution"] == "unresolved_candidate"
