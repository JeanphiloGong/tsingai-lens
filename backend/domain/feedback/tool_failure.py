"""Domain records for failed Chat tool observations.

A failed tool result is a technical observation in the durable Chat
trajectory.  It is an analysis signal, not proof that the final answer was
wrong.  The signal and its analysis result therefore keep their own identity
instead of borrowing the thumbs-up/thumbs-down ``feedback_id`` contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from domain.feedback.analysis_result import FeedbackProblemType
from domain.feedback.evidence_coverage import EvidenceCoverage


TOOL_FAILURE_SIGNAL_TYPE = "tool_failure"
TOOL_FAILURE_JOB_TYPE = "tool_failure_analysis"
TOOL_FAILURE_PAYLOAD_VERSION = 1


def _text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def tool_failure_signal_id(tool_call_id: str, result_message_id: str) -> str:
    """Return the stable identity of one persisted failed result message."""

    call_id = _text(tool_call_id, "tool_call_id")
    message_id = _text(result_message_id, "result_message_id")
    return f"tool_failure:{call_id}:{message_id}"


def tool_result_digest(result_record: dict[str, Any]) -> str:
    """Digest the canonical durable result projection used by the worker."""

    canonical = json.dumps(
        dict(result_record),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def tool_failure_idempotency_key(
    *,
    session_id: str,
    tool_call_id: str,
    assistant_message_id: str,
    result_message_id: str,
    result_digest: str,
) -> str:
    """Return a bounded key for one immutable tool failure observation."""

    values = tuple(
        _text(value, name)
        for name, value in (
            ("session_id", session_id),
            ("tool_call_id", tool_call_id),
            ("assistant_message_id", assistant_message_id),
            ("result_message_id", result_message_id),
            ("result_digest", result_digest),
        )
    )
    return "tool-failure:" + sha256("\x1f".join(values).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ToolFailureSignal:
    """Validated references to one failed tool result in Chat history."""

    signal_id: str
    session_id: str
    tool_call_id: str
    assistant_message_id: str
    result_message_id: str
    result_digest: str
    created_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "signal_id",
            "session_id",
            "tool_call_id",
            "assistant_message_id",
            "result_message_id",
            "created_at",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        digest = _text(self.result_digest, "result_digest").lower()
        if len(digest) != 64:
            raise ValueError("result_digest must be a SHA-256 hex digest")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ValueError("result_digest must be a SHA-256 hex digest") from exc
        object.__setattr__(self, "result_digest", digest)
        if self.signal_id != tool_failure_signal_id(
            self.tool_call_id, self.result_message_id
        ):
            raise ValueError("tool failure signal identity does not match references")

    def to_record(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "signal_type": TOOL_FAILURE_SIGNAL_TYPE,
            "session_id": self.session_id,
            "tool_call_id": self.tool_call_id,
            "assistant_message_id": self.assistant_message_id,
            "result_message_id": self.result_message_id,
            "result_digest": self.result_digest,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ToolFailureAnalysisResult:
    """AI candidate analysis for a failed tool result."""

    result_id: str
    job_id: str
    signal_id: str
    signal_type: str
    session_id: str
    collection_id: str
    tool_call_id: str
    assistant_message_id: str
    result_message_id: str
    tool_name: str
    error_code: str
    problem_type: FeedbackProblemType
    confidence: float
    related_message_ids: tuple[str, ...]
    suggested_evidence: tuple[str, ...]
    suggested_target: str | None
    evidence_coverage: EvidenceCoverage
    model: str
    input_digest: str
    created_at: str

    def __post_init__(self) -> None:
        if self.signal_type != TOOL_FAILURE_SIGNAL_TYPE:
            raise ValueError("invalid tool failure signal type")
        if self.problem_type != "tool_failure":
            raise ValueError("tool failure analysis must use tool_failure problem type")
        for field_name in (
            "result_id",
            "job_id",
            "signal_id",
            "session_id",
            "collection_id",
            "tool_call_id",
            "assistant_message_id",
            "result_message_id",
            "tool_name",
            "error_code",
            "model",
            "created_at",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        if self.signal_id != tool_failure_signal_id(
            self.tool_call_id, self.result_message_id
        ):
            raise ValueError("tool failure result signal identity does not match references")
        if not 0 <= self.confidence <= 1:
            raise ValueError("analysis confidence must be between zero and one")
        if self.suggested_target is not None:
            raise ValueError("tool failure analysis cannot suggest a training target")
        digest = _text(self.input_digest, "input_digest").lower()
        if len(digest) != 64:
            raise ValueError("analysis input digest must be sha256")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ValueError("analysis input digest must be sha256") from exc
        object.__setattr__(self, "input_digest", digest)
        object.__setattr__(self, "related_message_ids", tuple(self.related_message_ids))
        object.__setattr__(self, "suggested_evidence", tuple(self.suggested_evidence))

    def to_record(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "job_id": self.job_id,
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "session_id": self.session_id,
            "collection_id": self.collection_id,
            "tool_call_id": self.tool_call_id,
            "assistant_message_id": self.assistant_message_id,
            "result_message_id": self.result_message_id,
            "tool_name": self.tool_name,
            "error_code": self.error_code,
            "problem_type": self.problem_type,
            "confidence": self.confidence,
            "related_message_ids": list(self.related_message_ids),
            "suggested_evidence": list(self.suggested_evidence),
            "suggested_target": self.suggested_target,
            "evidence_coverage": self.evidence_coverage.to_record(),
            "model": self.model,
            "input_digest": self.input_digest,
            "created_at": self.created_at,
        }


__all__ = [
    "TOOL_FAILURE_JOB_TYPE",
    "TOOL_FAILURE_PAYLOAD_VERSION",
    "TOOL_FAILURE_SIGNAL_TYPE",
    "ToolFailureAnalysisResult",
    "ToolFailureSignal",
    "tool_failure_idempotency_key",
    "tool_failure_signal_id",
    "tool_result_digest",
]
