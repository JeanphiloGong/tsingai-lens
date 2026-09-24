"""Build a candidate feedback analysis from authoritative Chat records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Protocol
from uuid import uuid4

from application.repositories.chat_repository import ChatRepository
from domain.chat import ChatMessage, ChatMessageRole
from domain.chat.feedback import ChatMessageFeedback
from domain.feedback import AnalysisResult, EvidenceCoverage, FeedbackProblemType


class AnalysisInputError(ValueError):
    """The feedback version cannot be analysed without inventing context."""


@dataclass(frozen=True)
class FeedbackAnalysisDraft:
    problem_type: FeedbackProblemType
    confidence: float
    suggested_evidence: tuple[str, ...]
    suggested_target: str | None


class FeedbackAnalysisEngine(Protocol):
    async def analyze(
        self,
        *,
        feedback: ChatMessageFeedback,
        session: Any,
        answer: ChatMessage,
        messages: tuple[ChatMessage, ...],
        coverage: EvidenceCoverage,
    ) -> FeedbackAnalysisDraft: ...


class RuleBasedFeedbackAnalysisEngine:
    """Deterministic fallback used for the first production checkpoint.

    It keeps the worker runnable without a second provider dependency. A later
    model-backed engine must return the same draft contract and remains a
    candidate opinion until a human annotation is saved.
    """

    async def analyze(
        self,
        *,
        feedback: ChatMessageFeedback,
        session: Any,
        answer: ChatMessage,
        messages: tuple[ChatMessage, ...],
        coverage: EvidenceCoverage,
    ) -> FeedbackAnalysisDraft:
        if feedback.rating == "helpful":
            return FeedbackAnalysisDraft(
                problem_type="undetermined_dissatisfaction",
                confidence=0.05,
                suggested_evidence=(),
                suggested_target=None,
            )
        mapping: dict[str, FeedbackProblemType] = {
            "incorrect": "fact_error",
            "incomplete": "incomplete_answer",
            "unclear": "style_or_format",
        }
        problem_type = mapping.get(feedback.reason or "", "undetermined_dissatisfaction")
        confidence = 0.72 if feedback.reason else 0.28
        if not coverage.inspected_sources:
            confidence = min(confidence, 0.4)
        return FeedbackAnalysisDraft(
            problem_type=problem_type,
            confidence=confidence,
            suggested_evidence=tuple(
                str(item.get("source_ref"))
                for item in coverage.inspected_sources
                if item.get("source_ref")
            ),
            suggested_target=None,
        )


class FeedbackAnalysisHandler:
    def __init__(
        self,
        *,
        chat_repository: ChatRepository,
        engine: FeedbackAnalysisEngine | None = None,
        model_name: str = "rule-based-v1",
    ) -> None:
        self.chat_repository = chat_repository
        self.engine = engine or RuleBasedFeedbackAnalysisEngine()
        self.model_name = model_name

    async def handle(self, job: Any) -> tuple[AnalysisResult, dict[str, Any], tuple[str, ...]]:
        if job.job_type != "feedback_analysis" or job.payload_version != 1:
            raise AnalysisInputError("unsupported_feedback_analysis_job")
        feedback_id = str(job.payload.get("feedback_id") or "")
        if not feedback_id:
            raise AnalysisInputError("feedback_id_missing")
        feedback = await self.chat_repository.read_feedback_by_id(feedback_id)
        if feedback is None:
            raise AnalysisInputError("feedback_withdrawn")
        session = await self.chat_repository.read_session(feedback.session_id)
        answer = await self.chat_repository.read_message(feedback.message_id)
        if session is None or answer is None or answer.session_id != feedback.session_id:
            raise AnalysisInputError("feedback_context_missing")
        if answer.content == "":
            raise AnalysisInputError("feedback_answer_empty")
        messages = await self.chat_repository.read_messages(feedback.session_id)
        coverage = _coverage_from_messages(messages, answer)
        draft = await self.engine.analyze(
            feedback=feedback,
            session=session,
            answer=answer,
            messages=messages,
            coverage=coverage,
        )
        input_payload = {
            "feedback": {
                "feedback_id": feedback.feedback_id,
                "rating": feedback.rating,
                "reason": feedback.reason,
                "comment": feedback.comment,
                "response_digest": feedback.response_digest,
            },
            "session_id": feedback.session_id,
            "answer": answer.to_record(),
            "coverage": coverage.to_record(),
        }
        input_digest = sha256(
            json.dumps(input_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        result = AnalysisResult(
            result_id=f"analysis_{uuid4().hex[:20]}",
            job_id=job.job_id,
            feedback_id=feedback.feedback_id,
            session_id=feedback.session_id,
            collection_id=session.collection_id,
            anchor_message_id=answer.message_id,
            problem_type=draft.problem_type,
            confidence=draft.confidence,
            related_message_ids=tuple(
                message.message_id for message in messages
                if message.message_id in {feedback.message_id, answer.message_id}
            ),
            suggested_evidence=draft.suggested_evidence,
            suggested_target=draft.suggested_target,
            evidence_coverage=coverage,
            model=self.model_name,
            input_digest=input_digest,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        context_snapshot = {
            "question": _previous_user_question(messages, answer),
            "answer": answer.content,
            "requested_scope": list(coverage.requested_scope),
            "inspected_sources": list(coverage.inspected_sources),
            "omitted_candidates": list(coverage.omitted_candidates),
            "claim_support": list(coverage.claim_support),
            "gaps": list(coverage.gaps),
            "analysis": {
                "problem_type": result.problem_type,
                "confidence": result.confidence,
                "suggested_target": result.suggested_target,
            },
        }
        return result, context_snapshot, (feedback.feedback_id,)


def _previous_user_question(messages: tuple[ChatMessage, ...], answer: ChatMessage) -> str:
    prior = [
        message.content for message in messages
        if message.role is ChatMessageRole.USER and message.created_at <= answer.created_at
    ]
    return prior[-1] if prior else ""


def _coverage_from_messages(
    messages: tuple[ChatMessage, ...], answer: ChatMessage
) -> EvidenceCoverage:
    source_records: list[dict[str, Any]] = []
    requested: dict[str, dict[str, Any]] = {}
    for message in messages:
        for source in message.source_contexts:
            record = source.to_record()
            key = str(record.get("source_ref") or record.get("resource_ref", {}).get("resource_id") or "")
            if key and key not in {item.get("source_ref") for item in source_records}:
                source_records.append(record)
            document_id = str(record.get("document_id") or "")
            if document_id:
                requested.setdefault(document_id, {"document_id": document_id})
    gaps: tuple[str, ...] = () if source_records else ("no verifiable Source context was recorded",)
    return EvidenceCoverage(
        requested_scope=tuple(requested.values()),
        inspected_sources=tuple(source_records),
        omitted_candidates=(),
        claim_support=(),
        gaps=gaps,
        coverage_status="complete" if source_records else "unknown",
    )


__all__ = [
    "AnalysisInputError",
    "FeedbackAnalysisDraft",
    "FeedbackAnalysisEngine",
    "FeedbackAnalysisHandler",
    "RuleBasedFeedbackAnalysisEngine",
]
