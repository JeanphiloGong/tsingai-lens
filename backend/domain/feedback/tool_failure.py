"""Domain records for failed Chat tool observations.

A failed tool result is a technical observation in the durable Chat
trajectory.  It is an analysis signal, not proof that the final answer was
wrong.  The signal and its analysis result therefore keep their own identity
instead of borrowing the thumbs-up/thumbs-down ``feedback_id`` contract.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from domain.feedback.analysis_result import FeedbackProblemType
from domain.feedback.evidence_coverage import EvidenceCoverage

TOOL_FAILURE_SIGNAL_TYPE = "tool_failure"


def tool_failure_signal_id(tool_call_id: str, result_message_id: str) -> str:
    """Return the stable identity of one persisted failed result message."""

    return f"tool_failure:{tool_call_id}:{result_message_id}"


def tool_result_digest(result_record: dict[str, Any]) -> str:
    """Digest the canonical durable result projection used by the worker."""

    canonical = json.dumps(
        result_record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


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
        if self.signal_id != tool_failure_signal_id(
            self.tool_call_id, self.result_message_id
        ):
            raise ValueError("tool failure signal identity does not match references")


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
        if self.signal_id != tool_failure_signal_id(
            self.tool_call_id, self.result_message_id
        ):
            raise ValueError("tool failure result signal identity does not match references")
        if not 0 <= self.confidence <= 1:
            raise ValueError("analysis confidence must be between zero and one")
        if self.suggested_target is not None:
            raise ValueError("tool failure analysis cannot suggest a training target")
        if len(self.input_digest) != 64:
            raise ValueError("analysis input digest must be sha256")



__all__ = [
    "TOOL_FAILURE_SIGNAL_TYPE",
    "ToolFailureAnalysisResult",
    "ToolFailureSignal",
    "tool_failure_signal_id",
    "tool_result_digest",
]
