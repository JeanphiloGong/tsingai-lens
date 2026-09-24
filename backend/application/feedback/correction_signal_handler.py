"""Validate and analyze message-derived correction candidates."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Protocol
from uuid import uuid4

from application.feedback.analysis_handler import AnalysisInputError
from domain.chat import ChatMessage, ChatMessageRole
from domain.feedback import (
    CORRECTION_SIGNAL_JOB_TYPE,
    CORRECTION_SIGNAL_PAYLOAD_VERSION,
    CorrectionSignal,
    CorrectionSignalAnalysisResult,
    EvidenceCoverage,
    correction_signal_idempotency_key,
    is_correction_challenge,
)


@dataclass(frozen=True)
class CorrectionSignalAnalysisDraft:
    problem_type: str
    confidence: float
    suggested_evidence: tuple[str, ...]
    suggested_target: str | None


class CorrectionSignalAnalysisEngine(Protocol):
    async def analyze(
        self,
        *,
        signal: CorrectionSignal,
        session: Any,
        anchor: ChatMessage,
        trigger: ChatMessage,
        messages: tuple[ChatMessage, ...],
        coverage: EvidenceCoverage,
    ) -> CorrectionSignalAnalysisDraft: ...


class RuleBasedCorrectionSignalAnalysisEngine:
    """Produce a conservative candidate opinion without inventing a target."""

    async def analyze(
        self,
        *,
        signal: CorrectionSignal,
        session: Any,
        anchor: ChatMessage,
        trigger: ChatMessage,
        messages: tuple[ChatMessage, ...],
        coverage: EvidenceCoverage,
    ) -> CorrectionSignalAnalysisDraft:
        explicit_target = any(
            marker in trigger.content.casefold()
            for marker in ("应该", "实际", "actually", "the answer is")
        )
        return CorrectionSignalAnalysisDraft(
            problem_type="fact_error" if explicit_target else "undetermined_dissatisfaction",
            confidence=0.58 if explicit_target else 0.24,
            suggested_evidence=tuple(
                str(item.get("source_ref"))
                for item in coverage.inspected_sources
                if item.get("source_ref")
            ),
            # A user challenge is not a verified corrected answer.  Human
            # annotation must supply a target before any dataset use.
            suggested_target=None,
        )


class CorrectionSignalAnalysisHandler:
    def __init__(
        self,
        *,
        chat_repository: Any,
        engine: CorrectionSignalAnalysisEngine | None = None,
        model_name: str = "rule-based-correction-v1",
    ) -> None:
        self.chat_repository = chat_repository
        self.engine = engine or RuleBasedCorrectionSignalAnalysisEngine()
        self.model_name = model_name

    async def handle(
        self, job: Any
    ) -> tuple[CorrectionSignalAnalysisResult, dict[str, Any], tuple[str, ...]]:
        if (
            job.job_type != CORRECTION_SIGNAL_JOB_TYPE
            or job.payload_version != CORRECTION_SIGNAL_PAYLOAD_VERSION
        ):
            raise AnalysisInputError("unsupported_correction_signal_job")
        payload = dict(job.payload or {})
        session_id = str(payload.get("session_id") or "").strip()
        anchor_id = str(payload.get("anchor_message_id") or "").strip()
        trigger_id = str(payload.get("trigger_message_id") or "").strip()
        trigger_digest = str(payload.get("trigger_digest") or "").strip().lower()
        if not all((session_id, anchor_id, trigger_id, trigger_digest)):
            raise AnalysisInputError("correction_signal_payload_invalid")
        expected_idempotency_key = correction_signal_idempotency_key(
            session_id=session_id,
            anchor_message_id=anchor_id,
            trigger_message_id=trigger_id,
            trigger_digest=trigger_digest,
        )
        if job.idempotency_key != expected_idempotency_key:
            raise AnalysisInputError("correction_signal_identity_mismatch")
        session = await self.chat_repository.read_session(session_id)
        messages = await self.chat_repository.read_messages(session_id)
        if session is None or not messages:
            raise AnalysisInputError("correction_signal_withdrawn")
        positions = {message.message_id: index for index, message in enumerate(messages)}
        anchor = next((item for item in messages if item.message_id == anchor_id), None)
        trigger = next((item for item in messages if item.message_id == trigger_id), None)
        if anchor is None or trigger is None:
            raise AnalysisInputError("correction_signal_withdrawn")
        if anchor.session_id != session_id or trigger.session_id != session_id:
            raise AnalysisInputError("correction_signal_cross_session")
        if (
            anchor.role is not ChatMessageRole.ASSISTANT
            or not anchor.content
            or anchor.tool_calls
        ):
            raise AnalysisInputError("correction_signal_anchor_not_final")
        if trigger.role is not ChatMessageRole.USER or not trigger.content:
            raise AnalysisInputError("correction_signal_trigger_invalid")
        if positions.get(trigger_id) != positions.get(anchor_id, -2) + 1:
            raise AnalysisInputError("correction_signal_order_invalid")
        # ``CorrectionSignal`` canonicalizes message content by trimming the
        # transport whitespace.  Hash the same representation here so a user
        # message with accidental surrounding whitespace is not withdrawn.
        canonical_trigger_content = trigger.content.strip()
        actual_digest = sha256(canonical_trigger_content.encode("utf-8")).hexdigest()
        if actual_digest != trigger_digest:
            raise AnalysisInputError("correction_signal_superseded")
        if not is_correction_challenge(canonical_trigger_content):
            raise AnalysisInputError("correction_signal_not_candidate")
        signal = CorrectionSignal(
            signal_id=f"correction_signal:{trigger_id}",
            session_id=session_id,
            anchor_message_id=anchor_id,
            trigger_message_id=trigger_id,
            trigger_digest=trigger_digest,
            content=canonical_trigger_content,
            created_at=trigger.created_at,
        )
        coverage = _coverage_from_messages(messages, anchor)
        draft = await self.engine.analyze(
            signal=signal,
            session=session,
            anchor=anchor,
            trigger=trigger,
            messages=messages,
            coverage=coverage,
        )
        input_payload = {
            "signal": signal.to_record(),
            "anchor": anchor.to_record(),
            "coverage": coverage.to_record(),
            "related_message_ids": [item.message_id for item in messages[: positions[trigger_id] + 1]],
        }
        input_digest = sha256(
            json.dumps(
                input_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        result = CorrectionSignalAnalysisResult(
            result_id=f"signal_analysis_{uuid4().hex[:20]}",
            job_id=job.job_id,
            signal_id=signal.signal_id,
            signal_type="natural_language_correction",
            session_id=session_id,
            collection_id=session.collection_id,
            anchor_message_id=anchor_id,
            trigger_message_id=trigger_id,
            problem_type=draft.problem_type,  # type: ignore[arg-type]
            confidence=draft.confidence,
            related_message_ids=tuple(
                item.message_id for item in messages[: positions[trigger_id] + 1]
            ),
            suggested_evidence=draft.suggested_evidence,
            suggested_target=draft.suggested_target,
            evidence_coverage=coverage,
            model=self.model_name,
            input_digest=input_digest,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        context_snapshot = {
            "question": _previous_user_question(messages, anchor),
            "answer": anchor.content,
            "correction_signal": signal.to_record(),
            "requested_scope": list(coverage.requested_scope),
            "inspected_sources": list(coverage.inspected_sources),
            "omitted_candidates": list(coverage.omitted_candidates),
            "claim_support": list(coverage.claim_support),
            "gaps": list(coverage.gaps),
            "analysis": {
                "signal_type": result.signal_type,
                "signal_id": result.signal_id,
                "problem_type": result.problem_type,
                "confidence": result.confidence,
                "suggested_target": None,
                "resolution": "unresolved_candidate",
            },
        }
        return result, context_snapshot, (signal.signal_id,)


def _previous_user_question(
    messages: tuple[ChatMessage, ...], answer: ChatMessage
) -> str:
    prior = [
        item.content
        for item in messages
        if item.role is ChatMessageRole.USER and item.created_at <= answer.created_at
    ]
    return prior[-1] if prior else ""


def _coverage_from_messages(
    messages: tuple[ChatMessage, ...], answer: ChatMessage
) -> EvidenceCoverage:
    requested: dict[str, dict[str, Any]] = {}
    for message in messages:
        if message.role is not ChatMessageRole.USER or message.created_at > answer.created_at:
            continue
        for source in message.source_contexts:
            record = source.to_record()
            document_id = str(record.get("document_id") or "")
            if document_id:
                requested_key = ":".join(
                    str(record.get(field) or "")
                    for field in ("document_id", "source_kind", "source_ref")
                )
                requested.setdefault(
                    requested_key,
                    {
                        **record,
                        "origin": "user_selected_context",
                        "verified_by_tool": False,
                    },
                )
    requested_scope = tuple(requested.values())
    omitted = tuple(
        {
            **item,
            "reason": "selected_context_not_verified",
        }
        for item in requested_scope
    )
    gaps = (
        (
            "model Source-read audit is unavailable; selected context is only a "
            "coverage signal",
        )
        if requested_scope
        else ("no verifiable Source context was recorded",)
    )
    return EvidenceCoverage(
        requested_scope=requested_scope,
        inspected_sources=(),
        omitted_candidates=omitted,
        claim_support=(),
        gaps=gaps,
        coverage_status="partial" if requested_scope else "unknown",
    )


__all__ = [
    "CorrectionSignalAnalysisDraft",
    "CorrectionSignalAnalysisEngine",
    "CorrectionSignalAnalysisHandler",
    "RuleBasedCorrectionSignalAnalysisEngine",
]
