"""Human confirmation of an AI feedback candidate."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Literal

from domain.feedback.analysis_result import FeedbackProblemType


AnnotationSeverity = Literal["low", "medium", "high", "critical"]
DatasetUse = Literal["evaluation", "sft", "preference"]

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
        if not self.reason.strip():
            raise ValueError("annotation reason is required")
        if "sft" in self.dataset_uses and not self.target:
            raise ValueError("sft annotation requires a target")
        if "sft" in self.dataset_uses and not self.support_source_refs:
            raise ValueError("sft annotation requires support sources")
        if "preference" in self.dataset_uses and not self.target:
            raise ValueError("preference annotation requires a target")
        if "preference" in self.dataset_uses and not self.support_source_refs:
            raise ValueError("preference annotation requires support sources")
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
            "target": target,
            "support_source_refs": sorted(set(support_source_refs)),
            "dataset_uses": sorted(set(dataset_uses)),
            "reason": reason,
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


__all__ = ["AnnotationSeverity", "DatasetUse", "FeedbackAnnotation"]
