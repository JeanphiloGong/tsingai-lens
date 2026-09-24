"""Human confirmation of an AI feedback candidate."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Literal

from domain.feedback.analysis_result import FeedbackProblemType


AnnotationSeverity = Literal["low", "medium", "high", "critical"]
DatasetUse = Literal["evaluation", "sft", "preference"]

_SEVERITIES = {"low", "medium", "high", "critical"}
_DATASET_USES = {"evaluation", "sft", "preference"}
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
class FeedbackAnnotation:
    """A versioned human judgment; it never mutates the chat transcript."""

    annotation_id: str
    case_id: str
    version: int
    problem_type: FeedbackProblemType
    severity: AnnotationSeverity
    target: str | None
    support_source_refs: tuple[str, ...]
    dataset_uses: tuple[DatasetUse, ...]
    reason: str
    annotation_digest: str
    created_by: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if not self.annotation_id or not self.case_id or not self.created_by:
            raise ValueError("annotation identity is required")
        if self.version < 1:
            raise ValueError("annotation version must be positive")
        if self.problem_type not in _PROBLEM_TYPES:
            raise ValueError("invalid annotation problem type")
        if self.severity not in _SEVERITIES:
            raise ValueError("invalid annotation severity")
        if self.target is not None:
            target = self.target.strip()
            if not target:
                object.__setattr__(self, "target", None)
            elif len(target) > 20000:
                raise ValueError("annotation target cannot exceed 20000 characters")
            else:
                object.__setattr__(self, "target", target)
        reason = self.reason.strip()
        if not reason:
            raise ValueError("annotation reason is required")
        if len(reason) > 4000:
            raise ValueError("annotation reason cannot exceed 4000 characters")
        object.__setattr__(self, "reason", reason)
        refs = tuple(dict.fromkeys(str(item).strip() for item in self.support_source_refs if str(item).strip()))
        uses = tuple(dict.fromkeys(str(item) for item in self.dataset_uses))
        if any(item not in _DATASET_USES for item in uses):
            raise ValueError("invalid dataset use")
        if "sft" in uses and not self.target:
            raise ValueError("sft annotation requires a target")
        object.__setattr__(self, "support_source_refs", refs)
        object.__setattr__(self, "dataset_uses", uses)
        if len(self.annotation_digest) != 64:
            raise ValueError("annotation digest must be sha256")
        expected_digest = self.digest_for(
            case_id=self.case_id,
            problem_type=self.problem_type,
            severity=self.severity,
            target=self.target,
            support_source_refs=self.support_source_refs,
            dataset_uses=self.dataset_uses,
            reason=self.reason,
        )
        if self.annotation_digest != expected_digest:
            raise ValueError("annotation digest does not match content")

    @classmethod
    def digest_for(
        cls,
        *,
        case_id: str,
        problem_type: str,
        severity: str,
        target: str | None,
        support_source_refs: tuple[str, ...] | list[str],
        dataset_uses: tuple[str, ...] | list[str],
        reason: str,
    ) -> str:
        payload = {
            "case_id": case_id,
            "problem_type": problem_type,
            "severity": severity,
            "target": target.strip() if isinstance(target, str) else None,
            "support_source_refs": sorted(dict.fromkeys(str(item) for item in support_source_refs)),
            "dataset_uses": sorted(dict.fromkeys(str(item) for item in dataset_uses)),
            "reason": reason.strip(),
        }
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def build(
        cls,
        *,
        annotation_id: str,
        case_id: str,
        version: int,
        problem_type: FeedbackProblemType,
        severity: AnnotationSeverity,
        target: str | None,
        support_source_refs: tuple[str, ...],
        dataset_uses: tuple[DatasetUse, ...],
        reason: str,
        created_by: str,
        created_at: str,
    ) -> "FeedbackAnnotation":
        digest = cls.digest_for(
            case_id=case_id,
            problem_type=problem_type,
            severity=severity,
            target=target,
            support_source_refs=support_source_refs,
            dataset_uses=dataset_uses,
            reason=reason,
        )
        return cls(
            annotation_id=annotation_id,
            case_id=case_id,
            version=version,
            problem_type=problem_type,
            severity=severity,
            target=target,
            support_source_refs=support_source_refs,
            dataset_uses=dataset_uses,
            reason=reason,
            annotation_digest=digest,
            created_by=created_by,
            created_at=created_at,
            updated_at=created_at,
        )

    def content_key(self) -> tuple[Any, ...]:
        return (
            self.problem_type,
            self.severity,
            self.target,
            self.support_source_refs,
            self.dataset_uses,
            self.reason,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "annotation_id": self.annotation_id,
            "case_id": self.case_id,
            "version": self.version,
            "problem_type": self.problem_type,
            "severity": self.severity,
            "target": self.target,
            "support_source_refs": list(self.support_source_refs),
            "dataset_uses": list(self.dataset_uses),
            "reason": self.reason,
            "annotation_digest": self.annotation_digest,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


__all__ = ["AnnotationSeverity", "DatasetUse", "FeedbackAnnotation"]
