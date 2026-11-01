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
        for name, value in (
            ("observation_id", self.observation_id),
            ("collection_id", self.collection_id),
            ("objective_id", self.objective_id),
            ("document_id", self.document_id),
            ("source_kind", self.source_kind),
            ("source_ref", self.source_ref),
            ("observation_role", self.observation_role),
        ):
            if not value.strip():
                raise ValueError(f"source observation requires {name}")
        if not 0 <= self.confidence <= 1:
            raise ValueError("source observation confidence must be between 0 and 1")
        parents = self.derived_from_observation_ids
        if (
            any(not item.strip() for item in parents)
            or self.observation_id in parents
            or len(parents) != len(set(parents))
        ):
            raise ValueError(
                "observation derivation requires distinct parent observations"
            )

    @property
    def evidence_id(self) -> str:
        """Stable identifier used by the persisted ObjectiveEvidence format."""
        return self.observation_id

    @property
    def evidence_role(self) -> str:
        """Legacy extraction spelling for the observation's scientific role."""
        return self.observation_role

    @property
    def has_scientific_content(self) -> bool:
        return bool(
            self.changed_variables
            or self.comparison
            or self.reported_result
            or self.scientific_context.has_content
        )


def build_source_observation_id(
    *,
    objective_id: str | None,
    document_id: str | None,
    source_kind: str | None,
    source_ref: str | None,
    observation_role: str | None,
    reported_result: Mapping[str, Any] | None,
    scientific_context: Mapping[str, Any] | None,
) -> str:
    """Preserve the identity of a captured Source fact before normalization."""
    identity = json.dumps(
        [
            objective_id,
            document_id,
            source_kind,
            source_ref,
            observation_role,
            reported_result,
            scientific_context,
        ],
        ensure_ascii=True,
        sort_keys=True,
        default=str,
    )
    return f"evd_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"


__all__ = [
    "SOURCE_OBSERVATION_STATUSES",
    "SourceObservation",
    "build_source_observation_id",
]
