from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from domain.core.research_objective import (
    normalize_objective_confidence,
    normalize_objective_terms,
)


@dataclass(frozen=True)
class SourceSelectionHint:
    table_id: str
    document_id: str
    caption_text: str | None
    role: str
    strength: str | None
    matched_property_axes: tuple[str, ...]
    matched_variable_process_axes: tuple[str, ...]
    reason: str | None

    def __post_init__(self) -> None:
        if not self.table_id:
            raise ValueError("source selection hint requires table_id")
        if self.role not in {"result_table", "condition_context"}:
            raise ValueError(f"unsupported source selection hint role: {self.role}")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SourceSelectionHint":
        return cls(
            table_id=_text(payload.get("table_id")) or "",
            document_id=_text(payload.get("document_id")) or "",
            caption_text=_text(payload.get("caption_text")),
            role=_text(payload.get("role")) or "",
            strength=_text(payload.get("strength")),
            matched_property_axes=normalize_objective_terms(
                payload.get("matched_property_axes")
            ),
            matched_variable_process_axes=normalize_objective_terms(
                payload.get("matched_variable_process_axes")
            ),
            reason=_text(payload.get("reason")),
        )

@dataclass(frozen=True)
class ObjectiveAnalysisLens:
    """Transient extraction lens derived for one Objective analysis run."""

    objective_id: str
    question: str
    material_scope: tuple[str, ...]
    variable_process_axes: tuple[str, ...]
    process_context_axes: tuple[str, ...]
    target_property_axes: tuple[str, ...]
    excluded_property_axes: tuple[str, ...]
    mediator_axes: tuple[str, ...]
    direct_support_rules: tuple[str, ...]
    routing_hints: tuple[SourceSelectionHint, ...]
    confidence: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObjectiveAnalysisLens":
        obsolete_fields = {
            "objective_evidence_lens",
            "extraction_guidance",
        } & payload.keys()
        if obsolete_fields:
            raise ValueError(
                "obsolete Objective analysis lens fields: "
                + ", ".join(sorted(obsolete_fields))
            )
        return cls(
            objective_id=_text(payload.get("objective_id")) or "",
            question=_text(payload.get("question")) or "",
            material_scope=normalize_objective_terms(payload.get("material_scope")),
            variable_process_axes=normalize_objective_terms(
                payload.get("variable_process_axes")
            ),
            process_context_axes=normalize_objective_terms(
                payload.get("process_context_axes")
            ),
            target_property_axes=normalize_objective_terms(
                payload.get("target_property_axes")
            ),
            excluded_property_axes=normalize_objective_terms(
                payload.get("excluded_property_axes")
            ),
            mediator_axes=normalize_objective_terms(payload.get("mediator_axes")),
            direct_support_rules=normalize_objective_terms(
                payload.get("direct_support_rules")
            ),
            routing_hints=_source_selection_hints(payload.get("routing_hints")),
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )


def _source_selection_hints(value: Any) -> tuple[SourceSelectionHint, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        item
        if isinstance(item, SourceSelectionHint)
        else SourceSelectionHint.from_mapping(item)
        for item in value
        if isinstance(item, (SourceSelectionHint, Mapping))
    )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
