"""Domain records for natural-language correction candidates.

These records deliberately stay separate from :class:`AnalysisResult`, which
continues to describe the thumbs-up/thumbs-down feedback contract.  A
follow-up message is only a candidate signal until a human annotates the case;
it is never treated as a correction or a training target by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from domain.feedback.analysis_result import FeedbackProblemType
from domain.feedback.evidence_coverage import EvidenceCoverage

CORRECTION_SIGNAL_TYPE = "natural_language_correction"

# The detector is intentionally conservative.  Ordinary follow-up questions
# remain ordinary Chat turns; only an explicit challenge/retraction marker
# creates a candidate job.  The worker repeats the structural checks before it
# persists anything, so this heuristic is never an authorization boundary.
_CORRECTION_MARKERS = (
    "不对",
    "不正确",
    "错了",
    "错误",
    "你漏了",
    "漏掉",
    "没有看",
    "请重新检查",
    "应该是",
    "实际是",
    "事实上",
    "更正",
    "纠正",
    "来源不对",
    "依据不对",
    "not correct",
    "that's wrong",
    "that is wrong",
    "you missed",
    "incorrect",
    "actually",
    "recheck",
    "correction",
)


def is_correction_challenge(text: str) -> bool:
    """Return whether a user message is an explicit correction candidate.

    This is a trigger hint, not an AI decision.  It requires non-empty text
    and a known challenge marker after whitespace/case normalization.  The
    original message remains the evidence shown to a human annotator.
    """

    normalized = " ".join(text.strip().casefold().split())
    return bool(normalized) and any(marker.casefold() in normalized for marker in _CORRECTION_MARKERS)


def correction_signal_id(trigger_message_id: str) -> str:
    """Build the stable source-signal identity for one trigger message."""

    value = trigger_message_id
    if not value:
        raise ValueError("trigger_message_id is required")
    return f"correction_signal:{value}"


@dataclass(frozen=True)
class CorrectionSignal:
    """A validated reference to one user challenge in an append-only Chat."""

    signal_id: str
    session_id: str
    anchor_message_id: str
    trigger_message_id: str
    trigger_digest: str
    content: str
    created_at: str

    def __post_init__(self) -> None:
        if self.anchor_message_id == self.trigger_message_id:
            raise ValueError("anchor and trigger messages must differ")
        if sha256(self.content.encode("utf-8")).hexdigest() != self.trigger_digest:
            raise ValueError("trigger_digest does not match content")


@dataclass(frozen=True)
class CorrectionSignalAnalysisResult:
    """AI candidate analysis for a natural-language correction signal."""

    result_id: str
    job_id: str
    signal_id: str
    signal_type: str
    session_id: str
    collection_id: str
    anchor_message_id: str
    trigger_message_id: str
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
        if self.signal_type != CORRECTION_SIGNAL_TYPE:
            raise ValueError("invalid correction signal type")
        if not self.signal_id or not self.job_id or not self.session_id:
            raise ValueError("correction analysis identity is required")
        if not 0 <= self.confidence <= 1:
            raise ValueError("analysis confidence must be between zero and one")
        if self.suggested_target is not None:
            raise ValueError("correction signal cannot suggest a training target")
        if len(self.input_digest) != 64:
            raise ValueError("analysis input digest must be sha256")



__all__ = [
    "CORRECTION_SIGNAL_TYPE",
    "CorrectionSignal",
    "CorrectionSignalAnalysisResult",
    "correction_signal_id",
    "is_correction_challenge",
]
