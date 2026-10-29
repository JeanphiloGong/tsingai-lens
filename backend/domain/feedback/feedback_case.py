"""A human-facing work item assembled from analysis signals."""

from __future__ import annotations

from copy import deepcopy
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
    tool_failure_analysis_result_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.case_id or not self.collection_id or not self.session_id:
            raise ValueError("feedback case identity is required")
        object.__setattr__(self, "context_snapshot", deepcopy(self.context_snapshot))
