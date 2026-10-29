"""Append-only human review decisions for an annotation version."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ReviewDecisionValue = Literal["accept", "reject", "insufficient", "withdraw"]


@dataclass(frozen=True)
class ReviewDecision:
    decision_id: str
    case_id: str
    annotation_digest: str
    decision: ReviewDecisionValue
    reason: str | None
    created_by: str
    seq: int
    created_at: str

    def __post_init__(self) -> None:
        if not self.decision_id or not self.case_id or not self.created_by:
            raise ValueError("review decision identity is required")
        if self.seq < 1:
            raise ValueError("review decision sequence must be positive")
        if not self.reason or not self.reason.strip():
            raise ValueError("review decision reason is required")


__all__ = ["ReviewDecision", "ReviewDecisionValue"]
