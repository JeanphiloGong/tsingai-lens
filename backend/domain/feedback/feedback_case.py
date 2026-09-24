"""A human-facing work item assembled from analysis signals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


FeedbackCaseStatus = Literal[
    "detected",
    "collecting_context",
    "needs_annotation",
    "ready_for_review",
    "rejected",
    "insufficient",
    "accepted",
    "withdrawn",
]


@dataclass(frozen=True)
class FeedbackCase:
    case_id: str
    collection_id: str
    session_id: str
    anchor_message_id: str
    source_signal_ids: tuple[str, ...]
    analysis_result_ids: tuple[str, ...]
    context_snapshot: dict[str, Any]
    status: FeedbackCaseStatus
    created_at: str
    updated_at: str
    annotation_digest: str | None = None
    signal_analysis_result_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {
            "detected", "collecting_context", "needs_annotation", "ready_for_review",
            "rejected", "insufficient", "accepted", "withdrawn",
        }:
            raise ValueError("invalid feedback case status")
        if not self.case_id or not self.collection_id or not self.session_id:
            raise ValueError("feedback case identity is required")
        object.__setattr__(self, "source_signal_ids", tuple(self.source_signal_ids))
        object.__setattr__(self, "analysis_result_ids", tuple(self.analysis_result_ids))
        object.__setattr__(
            self,
            "signal_analysis_result_ids",
            tuple(self.signal_analysis_result_ids),
        )
        object.__setattr__(self, "context_snapshot", dict(self.context_snapshot))

    def to_record(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "collection_id": self.collection_id,
            "session_id": self.session_id,
            "anchor_message_id": self.anchor_message_id,
            "source_signal_ids": list(self.source_signal_ids),
            "analysis_result_ids": list(self.analysis_result_ids),
            "context_snapshot": dict(self.context_snapshot),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "annotation_digest": self.annotation_digest,
            "signal_analysis_result_ids": list(self.signal_analysis_result_ids),
        }
