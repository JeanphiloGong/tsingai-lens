"""Build a candidate feedback analysis from authoritative Chat records."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Protocol
from uuid import uuid4

from application.feedback.source_coverage import (
    ChatCoverageAudit,
    build_evidence_coverage,
)
from application.repositories.chat_repository import ChatRepository
from domain.chat import ChatMessage, ChatMessageRole
from domain.chat.feedback import ChatMessageFeedback
from domain.feedback import AnalysisResult, EvidenceCoverage, FeedbackProblemType


class AnalysisInputError(ValueError):
    """The feedback version cannot be analysed without inventing context."""


class FeedbackVersionSupersededError(AnalysisInputError):
    """A newer persisted feedback version superseded this job."""


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
        if job.idempotency_key != feedback.analysis_version_key:
            raise FeedbackVersionSupersededError("feedback_version_superseded")
        session = await self.chat_repository.read_session(feedback.session_id)
        answer = await self.chat_repository.read_message(feedback.message_id)
        if session is None or answer is None or answer.session_id != feedback.session_id:
            raise AnalysisInputError("feedback_context_missing")
        if answer.content == "":
            raise AnalysisInputError("feedback_answer_empty")
        messages = await self.chat_repository.read_messages(feedback.session_id)
        coverage = build_evidence_coverage(
            messages,
            answer,
            audit=await read_chat_coverage_audit(
                self.chat_repository,
                feedback.session_id,
                messages,
            ),
        )
        draft = await self.engine.analyze(
            feedback=feedback,
            session=session,
            answer=answer,
            messages=messages,
            coverage=coverage,
        )
        # The engine may be slow enough for the user to edit the feedback while
        # it runs. Re-read the mutable source before creating a durable result.
        current_feedback = await self.chat_repository.read_feedback_by_id(feedback_id)
        if current_feedback is None:
            raise AnalysisInputError("feedback_withdrawn")
        if current_feedback.analysis_version_key != job.idempotency_key:
            raise FeedbackVersionSupersededError("feedback_version_superseded")
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
            "coverage": asdict(coverage),
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
                message.message_id
                for message in messages
                if message.created_at <= answer.created_at
                and message.role in {ChatMessageRole.USER, ChatMessageRole.ASSISTANT}
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


async def read_chat_coverage_audit(
    repository: ChatRepository,
    session_id: str,
    messages: tuple[ChatMessage, ...],
) -> ChatCoverageAudit:
    """Read optional audit records without making legacy trajectories fail.

    P1 trajectories may predate model-call/tool-call persistence.  In that
    case ``None`` is passed to the projection, which keeps selected context as
    a request signal and leaves inspection status unknown/partial.
    """

    model_reader = getattr(repository, "read_model_calls", None)
    model_calls: tuple[Any, ...] | None
    if not callable(model_reader):
        model_calls = None
    else:
        try:
            collected: list[Any] = []
            offset = 0
            while True:
                try:
                    batch = await model_reader(session_id, limit=200, offset=offset)
                except TypeError:
                    batch = await model_reader(session_id)
                values = tuple(batch or ())
                collected.extend(values)
                if len(values) < 200:
                    break
                offset += len(values)
                if offset >= 10_000:
                    break
            model_calls = tuple(collected)
        except Exception:  # noqa: BLE001
            # Coverage must never turn a readable feedback record into a
            # fabricated successful audit because the optional audit read failed.
            model_calls = None

    tool_reader = getattr(repository, "read_tool_call", None)
    if not callable(tool_reader):
        return ChatCoverageAudit(model_calls=model_calls, tool_calls=None)

    tool_ids = {
        request.tool_call_id
        for message in messages
        for request in message.tool_calls
    }
    tool_calls: dict[str, Any] = {}
    tool_audit_error = False
    for tool_call_id in tool_ids:
        try:
            record = await tool_reader(tool_call_id)
        except Exception:  # noqa: BLE001
            tool_audit_error = True
            continue
        if record is not None:
            tool_calls[tool_call_id] = record
    return ChatCoverageAudit(
        model_calls=model_calls,
        tool_calls=tool_calls,
        tool_audit_error=tool_audit_error,
    )


__all__ = [
    "AnalysisInputError",
    "FeedbackVersionSupersededError",
    "FeedbackAnalysisDraft",
    "FeedbackAnalysisEngine",
    "FeedbackAnalysisHandler",
    "RuleBasedFeedbackAnalysisEngine",
    "read_chat_coverage_audit",
]
