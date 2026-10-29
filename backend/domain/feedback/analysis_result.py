"""Candidate analysis produced by a worker; never a human decision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
        if not 0 <= self.confidence <= 1:
            raise ValueError("analysis confidence must be between zero and one")
        if len(self.input_digest) != 64:
            raise ValueError("analysis input digest must be sha256")
