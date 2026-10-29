"""Validate and analyze message-derived correction candidates."""

from __future__ import annotations

from domain.feedback.correction_signal import CORRECTION_SIGNAL_TYPE

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Literal, Protocol
from uuid import uuid4

from application.feedback.analysis_handler import (
    AnalysisInputError,
    conversation_before_answer,
    read_chat_coverage_audit,
)
from application.feedback.source_coverage import build_evidence_coverage
from domain.chat import ChatMessage, ChatMessageRole
from domain.feedback import (
    CorrectionSignal,
    CorrectionSignalAnalysisResult,
    EvidenceCoverage,
    is_correction_challenge,
)
from repositories.analysis_job_repository import (
    CORRECTION_SIGNAL_JOB_TYPE,
    CORRECTION_SIGNAL_PAYLOAD_VERSION,
    correction_signal_idempotency_key,
)


@dataclass(frozen=True)
class CorrectionSignalAnalysisDraft:
    problem_type: str
    confidence: float
    suggested_evidence: tuple[str, ...]
    suggested_target: str | None
    task_relation: Literal["same_task", "different_task", "uncertain"] = "uncertain"
    task_relation_reason: str = ""


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
                item["source_ref"]
                for item in coverage.inspected_sources
                if item.get("source_ref")
            ),
            # A user challenge is not a verified corrected answer.  Human
            # annotation must supply a target before any dataset use.
            suggested_target=None,
            task_relation=_rule_task_relation(_previous_user_question(messages, anchor), trigger.content),
            task_relation_reason="Conservative correction-only rule; ambiguous instructions require review.",
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
        payload = job.payload
        session_id = payload.get("session_id")
        anchor_id = payload.get("anchor_message_id")
        trigger_id = payload.get("trigger_message_id")
        trigger_digest = payload.get("trigger_digest")
        if any(not isinstance(value, str) or not value for value in (session_id, anchor_id, trigger_id, trigger_digest)):
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
        # Correction-signal identity hashes the challenge without surrounding
        # transport whitespace; preserve that established digest representation.
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
        original_question = _previous_user_question(messages, anchor)
        challenge_messages = messages[:positions[trigger_id] + 1]
        audit = await read_chat_coverage_audit(self.chat_repository, session_id, challenge_messages)
        coverage = build_evidence_coverage(challenge_messages, anchor, audit=audit)
        draft = await self.engine.analyze(
            signal=signal, session=session, anchor=anchor, trigger=trigger,
            messages=challenge_messages, coverage=coverage,
        )
        if draft.task_relation not in {"same_task", "different_task", "uncertain"}:
            raise ValueError("correction_signal_task_relation_invalid")
        task_relation = draft.task_relation if original_question.strip() else "uncertain"
        same_task = task_relation == "same_task"
        corrected = None
        if same_task:
            for item in messages[positions[trigger_id] + 1:]:
                if item.role is ChatMessageRole.USER:
                    break
                if item.role is ChatMessageRole.ASSISTANT and item.content and not item.tool_calls:
                    if item.session_id != session_id:
                        raise AnalysisInputError("correction_signal_cross_session")
                    corrected = item
                    break
        related_end = positions[corrected.message_id] + 1 if corrected else positions[trigger_id] + 1
        related_messages = messages[:related_end]
        audit = await read_chat_coverage_audit(self.chat_repository, session_id, related_messages)
        coverage = build_evidence_coverage(related_messages, anchor, audit=audit)
        corrected_coverage = build_evidence_coverage(related_messages, corrected, audit=audit) if corrected else None
        pairing_assessment = {
            "task_relation": task_relation,
            "reason": draft.task_relation_reason,
            "original_question": original_question,
            "followup": canonical_trigger_content,
        }
        input_payload = {
            "signal": {
                "signal_id": signal.signal_id,
                "signal_type": CORRECTION_SIGNAL_TYPE,
                "session_id": signal.session_id,
                "anchor_message_id": signal.anchor_message_id,
                "trigger_message_id": signal.trigger_message_id,
                "trigger_digest": signal.trigger_digest,
                "content": signal.content,
                "created_at": signal.created_at,
            },
            "anchor": {
                "message_id": anchor.message_id,
                "session_id": anchor.session_id,
                "role": anchor.role.value,
                "content": anchor.content,
                "created_at": anchor.created_at,
                "tool_call_id": anchor.tool_call_id,
                "tool_calls": [
                    {
                        "tool_call_id": call.tool_call_id,
                        "name": call.name,
                        "arguments": call.arguments,
                        "position": call.position,
                    }
                    for call in anchor.tool_calls
                ],
                "tool_result": (
                    {
                        "tool_call_id": anchor.tool_result.tool_call_id,
                        "status": anchor.tool_result.status.value,
                        "data": anchor.tool_result.data,
                        "resource_refs": [
                            {
                                "resource_type": item.resource_type,
                                "resource_id": item.resource_id,
                                "href": item.href,
                            }
                            for item in anchor.tool_result.resource_refs
                        ],
                        "warnings": list(anchor.tool_result.warnings),
                        "error_code": anchor.tool_result.error_code,
                        "error_message": anchor.tool_result.error_message,
                    }
                    if anchor.tool_result is not None
                    else None
                ),
                "source_contexts": [
                    {
                        "resource_ref": {
                            "resource_type": source.resource_ref.resource_type,
                            "resource_id": source.resource_ref.resource_id,
                            "href": source.resource_ref.href,
                        },
                        "collection_id": source.collection_id,
                        "document_id": source.document_id,
                        "document_title": source.document_title,
                        "source_kind": source.source_kind,
                        "source_ref": source.source_ref,
                        "page": source.page,
                        "quote": source.quote,
                        "heading_path": source.heading_path,
                        "quote_truncated": source.quote_truncated,
                        "source_digest": source.source_digest,
                    }
                    for source in anchor.source_contexts
                ],
            },
            "coverage": asdict(coverage),
            "related_message_ids": [item.message_id for item in related_messages],
            "corrected_answer": (
                {
                    "message_id": corrected.message_id,
                    "session_id": corrected.session_id,
                    "role": corrected.role.value,
                    "content": corrected.content,
                    "created_at": corrected.created_at,
                    "tool_call_id": corrected.tool_call_id,
                    "tool_calls": [
                        {
                            "tool_call_id": call.tool_call_id,
                            "name": call.name,
                            "arguments": call.arguments,
                            "position": call.position,
                        }
                        for call in corrected.tool_calls
                    ],
                    "tool_result": (
                        {
                            "tool_call_id": corrected.tool_result.tool_call_id,
                            "status": corrected.tool_result.status.value,
                            "data": corrected.tool_result.data,
                            "resource_refs": [
                                {
                                    "resource_type": item.resource_type,
                                    "resource_id": item.resource_id,
                                    "href": item.href,
                                }
                                for item in corrected.tool_result.resource_refs
                            ],
                            "warnings": list(corrected.tool_result.warnings),
                            "error_code": corrected.tool_result.error_code,
                            "error_message": corrected.tool_result.error_message,
                        }
                        if corrected.tool_result is not None
                        else None
                    ),
                    "source_contexts": [
                        {
                            "resource_ref": {
                                "resource_type": source.resource_ref.resource_type,
                                "resource_id": source.resource_ref.resource_id,
                                "href": source.resource_ref.href,
                            },
                            "collection_id": source.collection_id,
                            "document_id": source.document_id,
                            "document_title": source.document_title,
                            "source_kind": source.source_kind,
                            "source_ref": source.source_ref,
                            "page": source.page,
                            "quote": source.quote,
                            "heading_path": source.heading_path,
                            "quote_truncated": source.quote_truncated,
                            "source_digest": source.source_digest,
                        }
                        for source in corrected.source_contexts
                    ],
                }
                if corrected
                else None
            ),
            "corrected_coverage": (
                asdict(corrected_coverage) if corrected_coverage else None
            ),
            "pairing_assessment": pairing_assessment,
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
                item.message_id for item in related_messages
            ),
            suggested_evidence=draft.suggested_evidence,
            suggested_target=draft.suggested_target,
            evidence_coverage=coverage,
            model=self.model_name,
            input_digest=input_digest,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        context_snapshot = {
            "question": original_question,
            "messages": conversation_before_answer(messages, anchor),
            "answer": anchor.content,
            "correction_signal": {
                "signal_id": signal.signal_id,
                "signal_type": CORRECTION_SIGNAL_TYPE,
                "session_id": signal.session_id,
                "anchor_message_id": signal.anchor_message_id,
                "trigger_message_id": signal.trigger_message_id,
                "trigger_digest": signal.trigger_digest,
                "content": signal.content,
                "created_at": signal.created_at,
            },
            "pairing_assessment": pairing_assessment,
            "requested_scope": list(coverage.requested_scope),
            "inspected_sources": list(coverage.inspected_sources)
            + (
                list(corrected_coverage.inspected_sources) if corrected_coverage else []
            ),
            "omitted_candidates": list(coverage.omitted_candidates),
            "claim_support": list(coverage.claim_support),
            "gaps": list(coverage.gaps),
            "analysis": {
                "signal_type": result.signal_type,
                "signal_id": result.signal_id,
                "problem_type": result.problem_type,
                "confidence": result.confidence,
                "suggested_target": None,
                "resolution": (
                    "correction_response_available"
                    if corrected
                    else (
                        "unresolved_candidate"
                        if same_task
                        else (
                            "task_scope_changed"
                            if task_relation == "different_task"
                            else "task_scope_uncertain"
                        )
                    )
                ),
            },
        }
        if corrected is not None:
            context_snapshot.update(
                {
                    "corrected_answer": corrected.content,
                    "corrected_message_id": corrected.message_id,
                    "corrected_evidence_coverage": asdict(corrected_coverage),
                    "original_message_id": anchor.message_id,
                    "corrected_question": original_question,
                    "pairing_basis": "task_scope_assessed_review_input",
                }
            )
        return result, context_snapshot, (signal.signal_id,)


def _previous_user_question(
    messages: tuple[ChatMessage, ...], answer: ChatMessage
) -> str:
    answer_position = next(
        (index for index, item in enumerate(messages) if item.message_id == answer.message_id), 0
    )
    prior = [
        item.content
        for item in messages[:answer_position]
        if item.role is ChatMessageRole.USER
    ]
    return prior[-1] if prior else ""


_TASK_SCOPE_CHANGE_MARKERS = (
    "只总结",
    "仅总结",
    "只介绍",
    "仅介绍",
    "只回答",
    "仅回答",
    "只说",
    "仅说",
    "改为",
    "改成",
    "换成",
    "另一个问题",
    "换个问题",
    "only summarize",
    "just summarize",
    "answer only",
    "focus only on",
    "change the question",
)


def _rule_task_relation(
    question: str, challenge: str
) -> Literal["same_task", "different_task", "uncertain"]:
    """Accept only explicit corrections without a new task instruction."""

    if not question.strip():
        return "uncertain"
    normalized = " ".join(challenge.casefold().split())
    if any(marker.casefold() in normalized for marker in _TASK_SCOPE_CHANGE_MARKERS):
        return "different_task"
    if re.search(r"[?？]|比较|总结|分析|生成|计算|怎么|为什么|\b(compare|summarize|calculate|instead|how|what|which)\b", normalized):
        return "uncertain"
    return "same_task" if is_correction_challenge(normalized) else "uncertain"


__all__ = [
    "CorrectionSignalAnalysisDraft",
    "CorrectionSignalAnalysisEngine",
    "CorrectionSignalAnalysisHandler",
    "RuleBasedCorrectionSignalAnalysisEngine",
]
