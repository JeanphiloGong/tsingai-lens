from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import math
import re
from typing import Any, Final, Mapping


PAPER_RELEVANCE_VALUES: Final[frozenset[str]] = frozenset(
    {"high", "medium", "low", "irrelevant", "uncertain"}
)
PAPER_ROLE_VALUES: Final[frozenset[str]] = frozenset(
    {
        "primary_experiment",
        "supporting_method",
        "supporting_background",
        "review",
        "modeling_only",
        "irrelevant",
        "mixed",
        "uncertain",
    }
)
SOURCE_KIND_VALUES: Final[frozenset[str]] = frozenset(
    {"text_window", "table", "figure"}
)
EVIDENCE_ROUTE_ROLE_VALUES: Final[frozenset[str]] = frozenset(
    {
        "current_experimental_evidence",
        "process_or_treatment",
        "test_condition",
        "composition_or_background",
        "characterization",
        "literature_comparison",
        "modeling_or_prediction",
        "low_value_or_irrelevant",
    }
)
_QUESTION_SIGNAL_TERMS: Final[tuple[str, ...]] = (
    "how ",
    "what ",
    "which ",
    "why ",
    "whether ",
    "does ",
    "do ",
    "is ",
    "are ",
    "can ",
    "affect",
    "effect",
    "impact",
    "influence",
    "compare",
    "comparison",
    "relationship",
    "versus",
    " vs ",
    "optimize",
    "improve",
)
_SLUG_NON_WORD_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class PaperSkim:
    document_id: str
    title: str | None
    source_filename: str | None
    doc_role: str
    candidate_materials: tuple[str, ...]
    candidate_processes: tuple[str, ...]
    candidate_properties: tuple[str, ...]
    changed_variables: tuple[str, ...]
    possible_objectives: tuple[str, ...]
    evidence_density: str
    confidence: float
    warnings: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperSkim":
        return cls(
            document_id=_normalize_text(payload.get("document_id") or payload.get("paper_id"))
            or "",
            title=_normalize_text(payload.get("title")),
            source_filename=_normalize_text(payload.get("source_filename")),
            doc_role=_normalize_text(payload.get("doc_role")) or "uncertain",
            candidate_materials=normalize_objective_terms(
                payload.get("candidate_materials")
            ),
            candidate_processes=normalize_objective_terms(
                payload.get("candidate_processes")
            ),
            candidate_properties=normalize_objective_terms(
                payload.get("candidate_properties")
            ),
            changed_variables=normalize_objective_terms(
                payload.get("changed_variables")
            ),
            possible_objectives=normalize_objective_terms(
                payload.get("possible_objectives")
            ),
            evidence_density=_normalize_text(payload.get("evidence_density"))
            or "unknown",
            confidence=normalize_objective_confidence(payload.get("confidence")),
            warnings=normalize_objective_terms(payload.get("warnings")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "source_filename": self.source_filename,
            "doc_role": self.doc_role,
            "candidate_materials": list(self.candidate_materials),
            "candidate_processes": list(self.candidate_processes),
            "candidate_properties": list(self.candidate_properties),
            "changed_variables": list(self.changed_variables),
            "possible_objectives": list(self.possible_objectives),
            "evidence_density": self.evidence_density,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ResearchObjective:
    objective_id: str
    question: str
    material_scope: tuple[str, ...]
    process_axes: tuple[str, ...]
    property_axes: tuple[str, ...]
    comparison_intent: str | None
    seed_document_ids: tuple[str, ...]
    excluded_document_ids: tuple[str, ...]
    confidence: float
    reason: str | None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchObjective":
        question = _normalize_text(payload.get("question")) or ""
        objective_id = _normalize_text(payload.get("objective_id")) or build_research_objective_id(
            question
        )
        return cls(
            objective_id=objective_id,
            question=question,
            material_scope=normalize_objective_terms(payload.get("material_scope")),
            process_axes=normalize_objective_terms(payload.get("process_axes")),
            property_axes=normalize_objective_terms(payload.get("property_axes")),
            comparison_intent=_normalize_text(payload.get("comparison_intent")),
            seed_document_ids=normalize_objective_terms(payload.get("seed_document_ids")),
            excluded_document_ids=normalize_objective_terms(
                payload.get("excluded_document_ids")
            ),
            confidence=normalize_objective_confidence(payload.get("confidence")),
            reason=_normalize_text(payload.get("reason")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "question": self.question,
            "material_scope": list(self.material_scope),
            "process_axes": list(self.process_axes),
            "property_axes": list(self.property_axes),
            "comparison_intent": self.comparison_intent,
            "seed_document_ids": list(self.seed_document_ids),
            "excluded_document_ids": list(self.excluded_document_ids),
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ObjectiveContext:
    objective_id: str
    question: str
    material_scope: tuple[str, ...]
    variable_process_axes: tuple[str, ...]
    process_context_axes: tuple[str, ...]
    target_property_axes: tuple[str, ...]
    excluded_property_axes: tuple[str, ...]
    routing_hints: tuple[dict[str, Any], ...]
    extraction_guidance: dict[str, Any]
    confidence: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObjectiveContext":
        return cls(
            objective_id=_normalize_text(payload.get("objective_id")) or "",
            question=_normalize_text(payload.get("question")) or "",
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
            routing_hints=_normalize_mapping_tuple(payload.get("routing_hints")),
            extraction_guidance=_normalize_mapping(payload.get("extraction_guidance")),
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "question": self.question,
            "material_scope": list(self.material_scope),
            "variable_process_axes": list(self.variable_process_axes),
            "process_context_axes": list(self.process_context_axes),
            "target_property_axes": list(self.target_property_axes),
            "excluded_property_axes": list(self.excluded_property_axes),
            "routing_hints": [dict(item) for item in self.routing_hints],
            "extraction_guidance": dict(self.extraction_guidance),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ObjectivePaperFrame:
    objective_id: str
    document_id: str
    relevance: str
    paper_role: str
    background: str | None
    material_match: tuple[str, ...]
    changed_variables: tuple[str, ...]
    measured_property_scope: tuple[str, ...]
    test_environment_scope: tuple[str, ...]
    relevant_sections: tuple[str, ...]
    relevant_tables: tuple[str, ...]
    excluded_tables: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObjectivePaperFrame":
        return cls(
            objective_id=_normalize_text(payload.get("objective_id")) or "",
            document_id=_normalize_text(payload.get("document_id") or payload.get("paper_id"))
            or "",
            relevance=_normalize_choice(
                payload.get("relevance"),
                allowed=PAPER_RELEVANCE_VALUES,
                default="uncertain",
            ),
            paper_role=_normalize_choice(
                payload.get("paper_role"),
                allowed=PAPER_ROLE_VALUES,
                default="uncertain",
            ),
            background=_normalize_text(payload.get("background")),
            material_match=normalize_objective_terms(payload.get("material_match")),
            changed_variables=normalize_objective_terms(
                payload.get("changed_variables")
            ),
            measured_property_scope=normalize_objective_terms(
                payload.get("measured_property_scope")
            ),
            test_environment_scope=normalize_objective_terms(
                payload.get("test_environment_scope")
            ),
            relevant_sections=normalize_objective_terms(
                payload.get("relevant_sections")
            ),
            relevant_tables=normalize_objective_terms(payload.get("relevant_tables")),
            excluded_tables=normalize_objective_terms(payload.get("excluded_tables")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "relevance": self.relevance,
            "paper_role": self.paper_role,
            "background": self.background,
            "material_match": list(self.material_match),
            "changed_variables": list(self.changed_variables),
            "measured_property_scope": list(self.measured_property_scope),
            "test_environment_scope": list(self.test_environment_scope),
            "relevant_sections": list(self.relevant_sections),
            "relevant_tables": list(self.relevant_tables),
            "excluded_tables": list(self.excluded_tables),
        }


@dataclass(frozen=True)
class EvidenceRoute:
    objective_id: str
    document_id: str
    source_kind: str
    source_ref: str
    role: str
    extractable: bool
    reason: str | None
    confidence: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EvidenceRoute":
        return cls(
            objective_id=_normalize_text(payload.get("objective_id")) or "",
            document_id=_normalize_text(payload.get("document_id") or payload.get("paper_id"))
            or "",
            source_kind=_normalize_choice(
                payload.get("source_kind"),
                allowed=SOURCE_KIND_VALUES,
                default="text_window",
            ),
            source_ref=_normalize_text(payload.get("source_ref")) or "",
            role=_normalize_choice(
                payload.get("role"),
                allowed=EVIDENCE_ROUTE_ROLE_VALUES,
                default="low_value_or_irrelevant",
            ),
            extractable=_normalize_bool(payload.get("extractable")),
            reason=_normalize_text(payload.get("reason")),
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
            "confidence": self.confidence,
        }


def build_research_objective_id(question: str) -> str:
    normalized_question = (_normalize_text(question) or "unspecified").lower()
    slug = _SLUG_NON_WORD_PATTERN.sub("-", normalized_question).strip("-")
    if not slug:
        slug = "unspecified"
    digest = sha1(normalized_question.encode("utf-8")).hexdigest()[:8]
    return f"obj_{slug[:72].strip('-')}_{digest}"


def normalize_objective_terms(value: Any) -> tuple[str, ...]:
    if _is_missing(value):
        return ()
    if hasattr(value, "tolist") and not isinstance(
        value,
        (str, bytes, bytearray, dict),
    ):
        value = value.tolist()
    if isinstance(value, dict):
        values = value.values()
    elif isinstance(value, set):
        values = sorted(value, key=lambda item: str(item))
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        text = _normalize_text(value)
        return (text,) if text else ()

    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _normalize_text(item)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return tuple(normalized)


def normalize_objective_confidence(value: Any) -> float:
    try:
        if _is_missing(value):
            return 0.0
        return round(min(1.0, max(0.0, float(value))), 2)
    except (TypeError, ValueError):
        return 0.0


def is_question_shaped_objective(objective: ResearchObjective) -> bool:
    question = (_normalize_text(objective.question) or "").lower()
    if len(question) < 12:
        return False
    if question in {term.lower() for term in objective.material_scope}:
        return False
    return any(term in question for term in _QUESTION_SIGNAL_TERMS)


def _normalize_text(value: Any) -> str | None:
    if _is_missing(value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            value = value.item()
        except Exception:
            pass
    text = str(value).strip()
    return text or None


def _normalize_choice(
    value: Any,
    *,
    allowed: frozenset[str],
    default: str,
) -> str:
    text = (_normalize_text(value) or "").lower().replace("-", "_").replace(" ", "_")
    return text if text in allowed else default


def _normalize_bool(value: Any) -> bool:
    if _is_missing(value):
        return False
    if isinstance(value, bool):
        return value
    text = (_normalize_text(value) or "").lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return bool(value)


def _normalize_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _normalize_mapping_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(_normalize_mapping(item) for item in value if isinstance(item, Mapping))


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


__all__ = [
    "EVIDENCE_ROUTE_ROLE_VALUES",
    "EvidenceRoute",
    "ObjectiveContext",
    "ObjectivePaperFrame",
    "PAPER_RELEVANCE_VALUES",
    "PAPER_ROLE_VALUES",
    "PaperSkim",
    "ResearchObjective",
    "SOURCE_KIND_VALUES",
    "build_research_objective_id",
    "is_question_shaped_objective",
    "normalize_objective_confidence",
    "normalize_objective_terms",
]
