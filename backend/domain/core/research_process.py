"""Domain aggregates for reconstructing one paper's research process.

These records describe scientific observations and experiment structure.  They
do not contain model prompts, retry state, window positions, or persistence
details.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha1
from typing import Any, Final, Mapping

from domain.core.scientific_fact import (
    ScientificComparison,
    ScientificContext,
    ScientificResult,
    ScientificVariable,
)

SOURCE_OBSERVATION_STATUSES: Final[frozenset[str]] = frozenset(
    {"unvalidated", "validated", "uncertain", "rejected"}
)
_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {"text_window", "table", "figure", "block", "section"}
)


@dataclass(frozen=True)
class SourceObservation:
    """A fact copied from one exact Source before it becomes ObjectiveEvidence."""

    observation_id: str
    collection_id: str
    objective_id: str
    document_id: str
    source_kind: str
    source_ref: str
    observation_role: str
    source_excerpt: str
    confidence: float
    selection_status: str = "extracted"
    selection_reason: str | None = None
    attribution_scope: str = "not_attributable"
    resolution_status: str = "unknown"
    failure_reason: str | None = None
    changed_variables: tuple[ScientificVariable, ...] = ()
    comparison: ScientificComparison | None = None
    reported_result: ScientificResult | None = None
    scientific_context: ScientificContext = field(default_factory=ScientificContext)
    status: str = "unvalidated"
    source_refs: tuple[dict[str, Any], ...] = ()
    derived_from_observation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "collection_id",
            "objective_id",
            "document_id",
            "source_kind",
            "source_ref",
            "observation_role",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"source observation requires {name}")
        if self.source_kind not in _SOURCE_KINDS:
            raise ValueError(f"unsupported source observation kind: {self.source_kind}")
        if self.status not in SOURCE_OBSERVATION_STATUSES:
            raise ValueError(f"unsupported source observation status: {self.status}")
        if not 0 <= self.confidence <= 1:
            raise ValueError("source observation confidence must be between 0 and 1")
        object.__setattr__(self, "changed_variables", tuple(self.changed_variables))
        parents = tuple(self.derived_from_observation_ids)
        if (
            any(not str(item).strip() for item in parents)
            or self.observation_id in parents
            or len(parents) != len(set(parents))
        ):
            raise ValueError(
                "observation derivation requires distinct parent observations"
            )
        object.__setattr__(self, "derived_from_observation_ids", parents)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SourceObservation":
        source_refs = tuple(
            dict(item)
            for item in payload.get("source_refs") or ()
            if isinstance(item, Mapping)
        )
        first_source_ref = source_refs[0] if source_refs else {}
        observation_id = str(
            payload.get("observation_id") or payload.get("evidence_id") or ""
        ).strip()
        if not observation_id:
            identity = json.dumps(
                [
                    payload.get("objective_id"),
                    payload.get("document_id"),
                    payload.get("source_kind") or first_source_ref.get("source_kind"),
                    payload.get("source_ref") or first_source_ref.get("source_ref"),
                    payload.get("observation_role") or payload.get("evidence_role"),
                    payload.get("reported_result"),
                    payload.get("scientific_context"),
                ],
                ensure_ascii=True,
                sort_keys=True,
                default=str,
            )
            observation_id = f"evd_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
        selection_status = str(payload.get("selection_status") or "extracted").strip()
        status = str(payload.get("status") or "").strip()
        if not status:
            status = "unvalidated"
        source_excerpt = str(
            payload.get("source_excerpt")
            or first_source_ref.get("source_excerpt")
            or ""
        ).strip()
        return cls(
            observation_id=observation_id,
            collection_id=str(payload.get("collection_id") or "unknown").strip(),
            objective_id=str(payload.get("objective_id") or "").strip(),
            document_id=str(payload.get("document_id") or "").strip(),
            source_kind=str(
                payload.get("source_kind")
                or first_source_ref.get("source_kind")
                or "text_window"
            ).strip(),
            source_ref=str(
                payload.get("source_ref")
                or first_source_ref.get("source_ref")
                or (observation_id if status == "rejected" else "")
            ).strip(),
            observation_role=str(
                payload.get("observation_role")
                or payload.get("evidence_role")
                or "unknown"
            ).strip(),
            source_excerpt=source_excerpt,
            changed_variables=tuple(
                ScientificVariable.from_mapping(item)
                for item in payload.get("changed_variables") or ()
                if isinstance(item, Mapping)
            ),
            comparison=(
                ScientificComparison.from_mapping(payload["comparison"])
                if isinstance(payload.get("comparison"), Mapping)
                else None
            ),
            reported_result=(
                ScientificResult.from_mapping(payload["reported_result"])
                if isinstance(payload.get("reported_result"), Mapping)
                else None
            ),
            scientific_context=(
                ScientificContext.from_mapping(payload["scientific_context"])
                if isinstance(payload.get("scientific_context"), Mapping)
                else ScientificContext()
            ),
            confidence=float(payload.get("confidence") or 0),
            selection_status=selection_status,
            selection_reason=(
                str(payload["selection_reason"]).strip()
                if payload.get("selection_reason")
                else None
            ),
            attribution_scope=str(
                payload.get("attribution_scope") or "not_attributable"
            ).strip(),
            resolution_status=str(
                payload.get("resolution_status") or "unknown"
            ).strip(),
            failure_reason=(
                str(payload["failure_reason"]).strip()
                if payload.get("failure_reason")
                else None
            ),
            status=status,
            source_refs=source_refs,
            derived_from_observation_ids=tuple(
                payload.get("derived_from_observation_ids") or ()
            ),
        )

    @property
    def evidence_id(self) -> str:
        """Stable identifier used by the persisted ObjectiveEvidence format."""
        return self.observation_id

    @property
    def evidence_role(self) -> str:
        """Legacy extraction spelling for the observation's scientific role."""
        return self.observation_role

    def to_record(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "evidence_id": self.observation_id,
            "collection_id": self.collection_id,
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "observation_role": self.observation_role,
            "evidence_role": self.observation_role,
            "source_excerpt": self.source_excerpt,
            "changed_variables": [item.to_record() for item in self.changed_variables],
            "comparison": self.comparison.to_record() if self.comparison else None,
            "reported_result": (
                self.reported_result.to_record() if self.reported_result else None
            ),
            "scientific_context": self.scientific_context.to_record(),
            "confidence": self.confidence,
            "selection_status": self.selection_status,
            "selection_reason": self.selection_reason,
            "attribution_scope": self.attribution_scope,
            "resolution_status": self.resolution_status,
            "failure_reason": self.failure_reason,
            "status": self.status,
            "source_refs": [dict(item) for item in self.source_refs],
            "derived_from_observation_ids": list(self.derived_from_observation_ids),
        }

    @property
    def has_scientific_content(self) -> bool:
        return bool(
            self.changed_variables
            or self.comparison
            or self.reported_result
            or self.scientific_context.has_content
        )


__all__ = [
    "SOURCE_OBSERVATION_STATUSES",
    "SourceObservation",
]
