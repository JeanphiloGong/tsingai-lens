from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from domain.core import normalize_objective_confidence


@dataclass(frozen=True)
class EvidenceCandidate:
    """Transient source-selection decision keyed by its stable Source locator."""

    objective_id: str
    document_id: str
    source_kind: str
    source_ref: str
    role: str
    extractable: bool
    reason: str | None
    table_schema: dict[str, Any]
    column_roles: dict[str, Any]
    join_plan: dict[str, Any]
    confidence: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EvidenceCandidate":
        return cls(
            objective_id=_text(payload.get("objective_id")),
            document_id=_text(payload.get("document_id")),
            source_kind=_text(payload.get("source_kind")) or "text_window",
            source_ref=_text(payload.get("source_ref")),
            role=_text(payload.get("role")) or "low_value_or_irrelevant",
            extractable=bool(payload.get("extractable")),
            reason=_optional_text(payload.get("reason")),
            table_schema=_mapping(payload.get("table_schema")),
            column_roles=_mapping(payload.get("column_roles")),
            join_plan=_mapping(payload.get("join_plan")),
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "role": self.role,
            "extractable": self.extractable,
            "reason": self.reason,
            "table_schema": dict(self.table_schema),
            "column_roles": dict(self.column_roles),
            "join_plan": dict(self.join_plan),
            "confidence": self.confidence,
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    return _text(value) or None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
