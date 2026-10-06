"""Validate and analyze failed tool observations from durable Chat history."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Protocol
from uuid import uuid4

from application.feedback.analysis_handler import AnalysisInputError
from application.repositories.analysis_job_repository import (
    TOOL_FAILURE_JOB_TYPE,
    TOOL_FAILURE_PAYLOAD_VERSION,
    tool_failure_idempotency_key,
)
from domain.chat import ChatMessage, ChatMessageRole, ToolCallStatus, ToolResultStatus
from domain.feedback import (
    EvidenceCoverage,
    ToolFailureAnalysisResult,
    ToolFailureSignal,
    tool_result_digest,
)


@dataclass(frozen=True)
class ToolFailureAnalysisDraft:
    confidence: float = 0.99
    suggested_evidence: tuple[str, ...] = ()
    suggested_target: str | None = None


class ToolFailureAnalysisEngine(Protocol):
    async def analyze(
        self,
        *,
        signal: ToolFailureSignal,
        session: Any,
        call: Any,
        result_message: ChatMessage,
        result: Any,
        messages: tuple[ChatMessage, ...],
        coverage: EvidenceCoverage,
    ) -> ToolFailureAnalysisDraft: ...


class RuleBasedToolFailureAnalysisEngine:
    """Record the observed technical failure without inventing a target."""

    async def analyze(
        self,
        *,
        signal: ToolFailureSignal,
        session: Any,
        call: Any,
        result_message: ChatMessage,
        result: Any,
        messages: tuple[ChatMessage, ...],
        coverage: EvidenceCoverage,
    ) -> ToolFailureAnalysisDraft:
        return ToolFailureAnalysisDraft()


class ToolFailureAnalysisHandler:
    def __init__(
        self,
        *,
        chat_repository: Any,
        engine: ToolFailureAnalysisEngine | None = None,
        model_name: str = "rule-based-tool-failure-v1",
    ) -> None:
        self.chat_repository = chat_repository
        self.engine = engine or RuleBasedToolFailureAnalysisEngine()
        self.model_name = model_name

    async def handle(
        self, job: Any
    ) -> tuple[ToolFailureAnalysisResult, dict[str, Any], tuple[str, ...]]:
        if (
            job.job_type != TOOL_FAILURE_JOB_TYPE
            or job.payload_version != TOOL_FAILURE_PAYLOAD_VERSION
        ):
            raise AnalysisInputError("unsupported_tool_failure_analysis_job")
        payload = dict(job.payload or {})
        values = {
            name: str(payload.get(name) or "").strip()
            for name in (
                "session_id",
                "tool_call_id",
                "assistant_message_id",
                "result_message_id",
                "result_digest",
            )
        }
        if any(not value for value in values.values()):
            raise AnalysisInputError("tool_failure_payload_invalid")
        expected_key = tool_failure_idempotency_key(**values)
        if job.idempotency_key != expected_key:
            raise AnalysisInputError("tool_failure_identity_mismatch")

        session = await self.chat_repository.read_session(values["session_id"])
        messages = await self.chat_repository.read_messages(values["session_id"])
        call = await self.chat_repository.read_tool_call(values["tool_call_id"])
        if session is None or not messages or call is None:
            raise AnalysisInputError("tool_failure_withdrawn")
        if call.session_id != values["session_id"]:
            raise AnalysisInputError("tool_failure_cross_session")
        by_id = {message.message_id: message for message in messages}
        assistant = by_id.get(values["assistant_message_id"])
        result_message = by_id.get(values["result_message_id"])
        if assistant is None or result_message is None:
            raise AnalysisInputError("tool_failure_withdrawn")
        if assistant.session_id != values["session_id"] or result_message.session_id != values["session_id"]:
            raise AnalysisInputError("tool_failure_cross_session")
        if assistant.role is not ChatMessageRole.ASSISTANT or result_message.role is not ChatMessageRole.TOOL:
            raise AnalysisInputError("tool_failure_message_invalid")
        positions = {message.message_id: index for index, message in enumerate(messages)}
        assistant_position = positions.get(assistant.message_id)
        result_position = positions.get(result_message.message_id)
        if (
            assistant_position is None
            or result_position is None
            or assistant_position >= result_position
            or any(
                message.role is ChatMessageRole.USER
                for message in messages[assistant_position + 1 : result_position]
            )
        ):
            raise AnalysisInputError("tool_failure_order_invalid")
        if call.assistant_message_id != assistant.message_id:
            raise AnalysisInputError("tool_failure_identity_mismatch")
        request = next(
            (
                item
                for item in assistant.tool_calls
                if item.tool_call_id == call.tool_call_id
            ),
            None,
        )
        if (
            request is None
            or request.name != call.name
            or dict(request.arguments) != dict(call.arguments)
            or request.position != call.position
        ):
            raise AnalysisInputError("tool_failure_identity_mismatch")
        if result_message.tool_call_id != call.tool_call_id or result_message.tool_result is None:
            raise AnalysisInputError("tool_failure_identity_mismatch")
        result = result_message.tool_result
        actual_digest = tool_result_digest(result.to_record())
        if actual_digest != values["result_digest"]:
            raise AnalysisInputError("tool_failure_superseded")
        if result.status is not ToolResultStatus.FAILED or call.status is not ToolCallStatus.FAILED:
            raise AnalysisInputError("tool_failure_not_candidate")
        if not result.error_code:
            raise AnalysisInputError("tool_failure_result_invalid")
        signal = ToolFailureSignal(
            signal_id=f"tool_failure:{call.tool_call_id}:{result_message.message_id}",
            session_id=session.session_id,
            tool_call_id=call.tool_call_id,
            assistant_message_id=assistant.message_id,
            result_message_id=result_message.message_id,
            result_digest=actual_digest,
            created_at=result_message.created_at,
        )
        coverage = _tool_failure_coverage(call, result, result_message)
        draft = await self.engine.analyze(
            signal=signal,
            session=session,
            call=call,
            result_message=result_message,
            result=result,
            messages=messages,
            coverage=coverage,
        )
        answer = _following_answer(messages, result_message)
        answer_message_id = answer.message_id if answer is not None else assistant.message_id
        related = tuple(message.message_id for message in messages[: result_position + 1])
        input_payload = {
            "signal": signal.to_record(),
            "call": {
                "tool_call_id": call.tool_call_id,
                "assistant_message_id": call.assistant_message_id,
                "name": call.name,
                "arguments_digest": call.arguments_digest,
                "status": call.status.value,
                "error_code": call.error_code,
            },
            "result": result.to_record(),
            "coverage": asdict(coverage),
            "related_message_ids": list(related),
            "answer_message_id": answer_message_id,
        }
        input_digest = sha256(
            json.dumps(input_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        analysis = ToolFailureAnalysisResult(
            result_id=f"tool_failure_analysis_{uuid4().hex[:20]}",
            job_id=job.job_id,
            signal_id=signal.signal_id,
            signal_type="tool_failure",
            session_id=session.session_id,
            collection_id=session.collection_id,
            tool_call_id=call.tool_call_id,
            assistant_message_id=assistant.message_id,
            result_message_id=result_message.message_id,
            tool_name=call.name,
            error_code=result.error_code,
            problem_type="tool_failure",
            confidence=draft.confidence,
            related_message_ids=related,
            suggested_evidence=draft.suggested_evidence,
            suggested_target=draft.suggested_target,
            evidence_coverage=coverage,
            model=self.model_name,
            input_digest=input_digest,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        snapshot = {
            "question": _previous_user_question(messages, result_message),
            "answer": answer.content if answer is not None else assistant.content,
            # The failed tool call is the signal anchor.  A later final answer
            # is the user-facing case anchor when the run produced one.
            "answer_message_id": answer_message_id,
            "tool_failure": {
                **signal.to_record(),
                "tool_name": call.name,
                "error_code": result.error_code,
                "error_message": result.error_message,
            },
            "requested_scope": list(coverage.requested_scope),
            "inspected_sources": list(coverage.inspected_sources),
            "omitted_candidates": list(coverage.omitted_candidates),
            "claim_support": list(coverage.claim_support),
            "gaps": list(coverage.gaps),
            "analysis": {
                "signal_type": analysis.signal_type,
                "signal_id": analysis.signal_id,
                "problem_type": analysis.problem_type,
                "confidence": analysis.confidence,
                "suggested_target": None,
                "resolution": "unresolved_candidate",
            },
        }
        return analysis, snapshot, (signal.signal_id,)


def _tool_failure_coverage(call: Any, result: Any, result_message: ChatMessage) -> EvidenceCoverage:
    return EvidenceCoverage(
        omitted_candidates=(
            {
                "tool_call_id": call.tool_call_id,
                "tool_name": call.name,
                "result_message_id": result_message.message_id,
                "error_code": result.error_code,
                "reason": "tool_failed_before_source_observation",
            },
        ),
        gaps=(
            f"tool {call.name} failed with {result.error_code}; source evidence is unavailable",
        ),
        coverage_status="failed",
    )


def _previous_user_question(messages: tuple[ChatMessage, ...], boundary: ChatMessage) -> str:
    prior = [
        message.content
        for message in messages
        if message.role is ChatMessageRole.USER and message.created_at <= boundary.created_at
    ]
    return prior[-1] if prior else ""


def _following_answer(messages: tuple[ChatMessage, ...], result_message: ChatMessage) -> ChatMessage | None:
    try:
        index = next(index for index, message in enumerate(messages) if message.message_id == result_message.message_id)
    except StopIteration:
        return None
    for message in messages[index + 1 :]:
        if message.role is ChatMessageRole.USER:
            return None
        if (
            message.role is ChatMessageRole.ASSISTANT
            and message.content
            and not message.tool_calls
        ):
            return message
    return None


__all__ = [
    "RuleBasedToolFailureAnalysisEngine",
    "ToolFailureAnalysisDraft",
    "ToolFailureAnalysisEngine",
    "ToolFailureAnalysisHandler",
]
