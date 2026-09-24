"""Candidate analysis produced by a worker; never a human decision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from domain.feedback.evidence_coverage import EvidenceCoverage


FeedbackProblemType = Literal[
    "fact_error",
    "source_missing",
    "evidence_mismatch",
    "retrieval_failure",
    "tool_failure",
    "intent_mismatch",
    "incomplete_answer",
    "style_or_format",
    "undetermined_dissatisfaction",
]


_PROBLEM_TYPES = {
    "fact_error",
    "source_missing",
    "evidence_mismatch",
    "retrieval_failure",
    "tool_failure",
    "intent_mismatch",
    "incomplete_answer",
    "style_or_format",
    "undetermined_dissatisfaction",
}


@dataclass(frozen=True)
class AnalysisResult:
    result_id: str
    job_id: str
    feedback_id: str
    session_id: str
    collection_id: str
    anchor_message_id: str
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
        if self.problem_type not in _PROBLEM_TYPES:
            raise ValueError("invalid feedback problem type")
        if not 0 <= self.confidence <= 1:
            raise ValueError("analysis confidence must be between zero and one")
        if len(self.input_digest) != 64:
            raise ValueError("analysis input digest must be sha256")
        object.__setattr__(self, "related_message_ids", tuple(self.related_message_ids))
        object.__setattr__(self, "suggested_evidence", tuple(self.suggested_evidence))

    def to_record(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "job_id": self.job_id,
            "feedback_id": self.feedback_id,
            "session_id": self.session_id,
            "collection_id": self.collection_id,
            "anchor_message_id": self.anchor_message_id,
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
