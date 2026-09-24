"""Append-only human review decisions for an annotation version."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ReviewDecisionValue = Literal["accept", "reject", "insufficient", "withdraw"]
_DECISIONS = {"accept", "reject", "insufficient", "withdraw"}


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
        if len(self.annotation_digest) != 64:
            raise ValueError("review annotation digest must be sha256")
        if self.decision not in _DECISIONS:
            raise ValueError("invalid review decision")
        if self.seq < 1:
            raise ValueError("review decision sequence must be positive")
        reason = self.reason.strip() if self.reason is not None else None
        if self.decision in {"accept", "reject", "insufficient", "withdraw"} and not reason:
            raise ValueError("review decision reason is required")
        object.__setattr__(self, "reason", reason)

    def to_record(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "case_id": self.case_id,
            "annotation_digest": self.annotation_digest,
            "decision": self.decision,
            "reason": self.reason,
            "created_by": self.created_by,
            "seq": self.seq,
            "created_at": self.created_at,
        }


__all__ = ["ReviewDecision", "ReviewDecisionValue"]
