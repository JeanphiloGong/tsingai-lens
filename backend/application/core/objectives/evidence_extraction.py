from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import json
from typing import Any, Mapping

from domain.core import (
    ObjectiveEvidenceComparison,
    ObjectiveEvidenceContext,
    ObjectiveEvidenceResult,
    ObjectiveEvidenceVariable,
    normalize_objective_confidence,
    normalize_objective_terms,
)


@dataclass(frozen=True)
class ExtractedEvidenceDraft:
    """Transient structured extraction before Source text is attached."""

    evidence_id: str
    objective_id: str
    document_id: str
    source_kind: str | None
    source_ref: str | None
    evidence_role: str | None
    selection_reason: str | None
    selection_status: str
    changed_variables: tuple[ObjectiveEvidenceVariable, ...]
    comparison: ObjectiveEvidenceComparison | None
    reported_result: ObjectiveEvidenceResult | None
    attribution_scope: str
    scientific_context: ObjectiveEvidenceContext
    source_refs: tuple[dict[str, Any], ...]
    evidence_anchor_ids: tuple[str, ...]
    resolution_status: str
    failure_reason: str | None
    confidence: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExtractedEvidenceDraft":
        source_refs = _mapping_tuple(payload.get("source_refs"))
        first_source_ref = source_refs[0] if source_refs else {}
        objective_id = _text(payload.get("objective_id"))
        document_id = _text(payload.get("document_id"))
        source_kind = _optional_text(
            payload.get("source_kind") or first_source_ref.get("source_kind")
        )
        source_ref = _optional_text(
            payload.get("source_ref") or first_source_ref.get("source_ref")
        )
        evidence_role = _optional_text(
            payload.get("evidence_role") or first_source_ref.get("evidence_role")
        )
        reported_result_payload = payload.get("reported_result")
        reported_result = (
            ObjectiveEvidenceResult.from_mapping(reported_result_payload)
            if isinstance(reported_result_payload, Mapping)
            else None
        )
        evidence_id = _optional_text(payload.get("evidence_id"))
        if evidence_id is None:
            identity = json.dumps(
                [
                    objective_id,
                    document_id,
                    evidence_role,
                    source_refs,
                    payload.get("changed_variables"),
                    payload.get("comparison"),
                    payload.get("reported_result"),
                ],
                ensure_ascii=True,
                sort_keys=True,
                default=str,
            )
            evidence_id = f"evd_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
        return cls(
            evidence_id=evidence_id,
            objective_id=objective_id,
            document_id=document_id,
            source_kind=source_kind,
            source_ref=source_ref,
            evidence_role=evidence_role,
            selection_reason=_optional_text(
                payload.get("selection_reason")
                or first_source_ref.get("selection_reason")
            ),
            selection_status=_text(payload.get("selection_status")) or "extracted",
            changed_variables=tuple(
                ObjectiveEvidenceVariable.from_mapping(item)
                for item in payload.get("changed_variables", ())
                if isinstance(item, Mapping)
            ),
            comparison=(
                ObjectiveEvidenceComparison.from_mapping(payload["comparison"])
                if isinstance(payload.get("comparison"), Mapping)
                else None
            ),
            reported_result=reported_result,
            attribution_scope=_text(payload.get("attribution_scope"))
            or "not_attributable",
            scientific_context=(
                ObjectiveEvidenceContext.from_mapping(payload["scientific_context"])
                if isinstance(payload.get("scientific_context"), Mapping)
                else ObjectiveEvidenceContext()
            ),
            source_refs=source_refs,
            evidence_anchor_ids=normalize_objective_terms(
                payload.get("evidence_anchor_ids")
            ),
            resolution_status=_text(payload.get("resolution_status")) or "unknown",
            failure_reason=_optional_text(payload.get("failure_reason")),
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "evidence_role": self.evidence_role,
            "selection_reason": self.selection_reason,
            "selection_status": self.selection_status,
            "changed_variables": [
                item.to_record() for item in self.changed_variables
            ],
            "comparison": self.comparison.to_record() if self.comparison else None,
            "reported_result": (
                self.reported_result.to_record() if self.reported_result else None
            ),
            "attribution_scope": self.attribution_scope,
            "scientific_context": self.scientific_context.to_record(),
            "source_refs": [dict(item) for item in self.source_refs],
            "evidence_anchor_ids": list(self.evidence_anchor_ids),
            "resolution_status": self.resolution_status,
            "failure_reason": self.failure_reason,
            "confidence": self.confidence,
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    return _text(value) or None


def _mapping_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))
