from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from application.core.objectives import property_matching
from application.core.objectives.llm.structured_response import (
    StructuredOutputSaturatedError,
    StructuredResponseClient,
)

PAPER_RESEARCH_MAP_PROMPT_VERSION = "paper_map.v5"
PAPER_SOURCE_SIGNAL_PROMPT_VERSION = "paper_source_signal.v2"
PAPER_RESEARCH_MAP_PROMPT_TOKEN_LIMIT = 12_288
PAPER_RESEARCH_MAP_SOURCE_UNIT_LIMIT = 12
PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT = 4
PAPER_RESEARCH_MAP_WARNING_LIMIT = (2, 240)
PAPER_RESEARCH_MAP_SCOPE_LIMIT = 4
PAPER_RESEARCH_MAP_RELATIONSHIP_LIMIT = 6
PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT = 8

_STUDY_CONTEXT_LIMIT = 12
_STUDY_CONTEXT_VALUE_CHARS = 160
_VARIED_FACTOR_LIMIT = 12
_PAPER_MAP_STUDY_LIMIT = 2
_PAPER_MAP_RELATIONSHIP_LIMIT = 6
_PAPER_MAP_SIGNAL_LIMIT = 4
_PAPER_MAP_CONTEXT_LIMIT = 4
_PAPER_MAP_VARIED_FACTOR_LIMIT = 6
_SOURCE_SIGNAL_CONTEXT_LIMIT = 4
_SOURCE_SIGNAL_LIMIT = 8
_REVIEW_KNOWLEDGE_ITEM_LIMIT = 2
_REVIEW_CITATION_LEAD_LIMIT = 3

_MODEL_HIDDEN_CONTENT_KEYS = {
    "block_id",
    "cell_id",
    "collection_id",
    "column_id",
    "column_index",
    "document_id",
    "end_col",
    "end_row",
    "figure_id",
    "fragment_start",
    "page_index",
    "row_id",
    "row_index",
    "source_kind",
    "source_ref",
    "source_unit_id",
    "start_col",
    "start_row",
    "structured_path",
    "table_id",
    "window_id",
}

_MAX_COMPLETION_TOKENS = 2048
_SOURCE_SIGNAL_MAX_COMPLETION_TOKENS = 2048
_DOC_ROLES = {"experimental", "review", "modeling", "mixed", "uncertain"}
_EVIDENCE_DENSITIES = {"high", "medium", "low", "unknown"}

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are mapping one paper's stated research scope for traceable Objective discovery.

Non-negotiable rules:
- This is lightweight paper mapping, not experiment reconstruction or Evidence extraction.
- Return exactly one JSON object and nothing else.
- Scientific labels must be supported by supplied Source-unit content.
- Copy only supplied short `source_labels`; the backend owns real Source identity.
- Do not infer material systems from filenames or section names.
""".strip()

_REVIEW_SYSTEM_PROMPT = """
You screen one bounded Source window from a review paper for traceable
review-author scientific synthesis.

Non-negotiable rules:
- This is synthesis screening, not reconstruction of every cited experiment.
- Return exactly one JSON object and nothing else.
- Scientific labels must be supported by supplied Source-unit content.
- Copy only supplied short `source_labels`; the backend owns real Source identity.
- A citation points to primary literature; it is not review-owned evidence.
""".strip()


def _normalize_choice(value: object, *, allowed: set[str], default: str) -> str:
    lowered = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return lowered if lowered in allowed else default


def _normalize_list(value: object) -> object:
    return [] if value is None else value


def _normalize_warnings(value: object) -> object:
    if value is None:
        return []
    if not isinstance(value, list):
        return value
    normalized: list[object] = []
    for item in value[: PAPER_RESEARCH_MAP_WARNING_LIMIT[0]]:
        if not isinstance(item, str):
            normalized.append(item)
            continue
        text = item.strip()
        if text:
            normalized.append(text[: PAPER_RESEARCH_MAP_WARNING_LIMIT[1]])
    return normalized


class _PaperResearchMapResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("confidence", mode="before", check_fields=False)
    @classmethod
    def _normalize_default_confidence(cls, value: object) -> object:
        if value is not None:
            return value
        return cls.model_fields["confidence"].get_default(call_default_factory=True)


class StructuredPaperResearchRelationship(_PaperResearchMapResponse):
    varied_factors: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(min_length=1, max_length=_VARIED_FACTOR_LIMIT)
    outcome: Annotated[str, Field(min_length=1, max_length=80)]
    source_unit_ids: list[
        Annotated[str, Field(min_length=1, max_length=160)]
    ] = Field(min_length=1, max_length=PAPER_RESEARCH_MAP_SOURCE_UNIT_LIMIT)
    confidence: float = 0.0

    @field_validator("varied_factors", "source_unit_ids", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    @model_validator(mode="after")
    def _validate_source_unit_ids(self) -> StructuredPaperResearchRelationship:
        normalized = [value.strip() for value in self.source_unit_ids]
        if any(not value for value in normalized):
            raise ValueError("paper relationship source-unit ids cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("paper relationship source-unit ids must be unique")
        return self


class StructuredPaperResearchScope(_PaperResearchMapResponse):
    experiment_label: str | None = Field(default=None, max_length=120)
    design_type: Literal[
        "experimental",
        "observational",
        "modeling",
        "mixed",
        "uncertain",
    ] = "uncertain"
    claim_scope: Literal[
        "current_work",
        "synthesis",
        "background",
        "uncertain",
    ] = "uncertain"
    material_scope: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=_PAPER_MAP_CONTEXT_LIMIT)
    process_context: list[
        Annotated[str, Field(max_length=_STUDY_CONTEXT_VALUE_CHARS)]
    ] = Field(default_factory=list, max_length=_PAPER_MAP_CONTEXT_LIMIT)
    relationships: list[StructuredPaperResearchRelationship] = Field(
        min_length=1,
        max_length=PAPER_RESEARCH_MAP_RELATIONSHIP_LIMIT,
    )
    confidence: float = 0.0

    @field_validator(
        "material_scope",
        "process_context",
        "relationships",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    def identity_key(
        self,
        source_keys: Mapping[str, tuple[str, str]] | None = None,
    ) -> tuple[object, ...]:
        def normalized_values(values: list[str]) -> tuple[str, ...]:
            return tuple(
                sorted(
                    {
                        str(value).strip().casefold()
                        for value in values
                        if str(value).strip()
                    }
                )
            )

        relationships = tuple(
            sorted(
                (
                    normalized_values(relationship.varied_factors),
                    relationship.outcome.strip().casefold(),
                    tuple(
                        sorted(
                            {
                                source_keys.get(
                                    source_unit_id.strip(),
                                    ("source_unit", source_unit_id.strip()),
                                )
                                if source_keys is not None
                                else ("source_unit", source_unit_id.strip())
                                for source_unit_id in relationship.source_unit_ids
                                if source_unit_id.strip()
                            }
                        )
                    ),
                )
                for relationship in self.relationships
            )
        )
        return (
            self.design_type,
            self.claim_scope,
            self.experiment_label.strip().casefold()
            if self.experiment_label
            else None,
            normalized_values(self.material_scope),
            normalized_values(self.process_context),
            relationships,
        )


class StructuredPaperResearchSignal(_PaperResearchMapResponse):
    signal_type: Literal["variable", "outcome"]
    label: Annotated[str, Field(min_length=1, max_length=80)]
    experiment_label: str | None = Field(default=None, max_length=120)
    design_type: Literal[
        "experimental",
        "observational",
        "modeling",
        "mixed",
        "uncertain",
    ] = "uncertain"
    claim_scope: Literal[
        "current_work",
        "synthesis",
        "background",
        "uncertain",
    ] = "uncertain"
    material_scope: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=_PAPER_MAP_CONTEXT_LIMIT)
    process_context: list[
        Annotated[str, Field(max_length=_STUDY_CONTEXT_VALUE_CHARS)]
    ] = Field(default_factory=list, max_length=_PAPER_MAP_CONTEXT_LIMIT)
    source_unit_ids: list[
        Annotated[str, Field(min_length=1, max_length=160)]
    ] = Field(min_length=1, max_length=PAPER_RESEARCH_MAP_SOURCE_UNIT_LIMIT)
    confidence: float = 0.0

    @field_validator(
        "material_scope",
        "process_context",
        "source_unit_ids",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    @model_validator(mode="after")
    def _validate_source_unit_ids(self) -> StructuredPaperResearchSignal:
        normalized = [value.strip() for value in self.source_unit_ids]
        if any(not value for value in normalized):
            raise ValueError("paper signal source-unit ids cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("paper signal source-unit ids must be unique")
        return self


class StructuredPaperMapRelationship(_PaperResearchMapResponse):
    """One compact factor-to-outcome axis used only during paper mapping."""

    varied_factors: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(min_length=1, max_length=_PAPER_MAP_VARIED_FACTOR_LIMIT)
    outcome: Annotated[str, Field(min_length=1, max_length=80)]
    source_labels: list[
        Annotated[str, Field(pattern=r"^S[1-9][0-9]*$", max_length=8)]
    ] = Field(min_length=1, max_length=PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT)
    confidence: float = 0.0

    @field_validator("varied_factors", "source_labels", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    @model_validator(mode="after")
    def _validate_source_labels(self) -> "StructuredPaperMapRelationship":
        normalized = [value.strip() for value in self.source_labels]
        if any(not value for value in normalized):
            raise ValueError("paper-map relationship Source labels cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("paper-map relationship Source labels must be unique")
        return self


class StructuredPaperMapStudy(_PaperResearchMapResponse):
    """Paper-owned scope without experiment reconstruction fields."""

    experiment_label: str | None = Field(default=None, max_length=120)
    design_type: Literal[
        "experimental",
        "observational",
        "modeling",
        "mixed",
        "uncertain",
    ] = "uncertain"
    claim_scope: Literal[
        "current_work",
        "background",
        "uncertain",
    ] = "uncertain"
    material_scope: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=_PAPER_MAP_CONTEXT_LIMIT)
    process_context: list[
        Annotated[str, Field(max_length=_STUDY_CONTEXT_VALUE_CHARS)]
    ] = Field(default_factory=list, max_length=_PAPER_MAP_CONTEXT_LIMIT)
    relationships: list[StructuredPaperMapRelationship] = Field(
        min_length=1,
        max_length=_PAPER_MAP_RELATIONSHIP_LIMIT,
    )
    confidence: float = 0.0

    @field_validator(
        "material_scope",
        "process_context",
        "relationships",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)


class StructuredPaperMapSignal(_PaperResearchMapResponse):
    """One incomplete paper-owned variable or outcome axis."""

    signal_type: Literal["variable", "outcome"]
    label: Annotated[str, Field(min_length=1, max_length=80)]
    experiment_label: str | None = Field(default=None, max_length=120)
    design_type: Literal[
        "experimental",
        "observational",
        "modeling",
        "mixed",
        "uncertain",
    ] = "uncertain"
    claim_scope: Literal[
        "current_work",
        "background",
        "uncertain",
    ] = "uncertain"
    material_scope: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=_PAPER_MAP_CONTEXT_LIMIT)
    process_context: list[
        Annotated[str, Field(max_length=_STUDY_CONTEXT_VALUE_CHARS)]
    ] = Field(default_factory=list, max_length=_PAPER_MAP_CONTEXT_LIMIT)
    source_labels: list[
        Annotated[str, Field(pattern=r"^S[1-9][0-9]*$", max_length=8)]
    ] = Field(min_length=1, max_length=PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT)
    confidence: float = 0.0

    @field_validator(
        "material_scope",
        "process_context",
        "source_labels",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    @model_validator(mode="after")
    def _validate_source_labels(self) -> "StructuredPaperMapSignal":
        normalized = [value.strip() for value in self.source_labels]
        if any(not value for value in normalized):
            raise ValueError("paper-map signal Source labels cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("paper-map signal Source labels must be unique")
        return self


class StructuredExperimentalPaperMap(_PaperResearchMapResponse):
    """Compact high-level scope contract for non-review papers."""

    doc_role: Literal["experimental", "modeling", "mixed", "uncertain"] = "uncertain"
    studies: list[StructuredPaperMapStudy] = Field(
        default_factory=list,
        max_length=_PAPER_MAP_STUDY_LIMIT,
    )
    unresolved_signals: list[StructuredPaperMapSignal] = Field(
        default_factory=list,
        max_length=_PAPER_MAP_SIGNAL_LIMIT,
    )
    output_saturated: bool = False
    evidence_density: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence: float = 0.0
    warnings: list[
        Annotated[str, Field(max_length=PAPER_RESEARCH_MAP_WARNING_LIMIT[1])]
    ] = Field(default_factory=list, max_length=PAPER_RESEARCH_MAP_WARNING_LIMIT[0])

    @model_validator(mode="before")
    @classmethod
    def _downgrade_unresolved_relationships(cls, value: object) -> object:
        return StructuredPaperResearchMap._downgrade_unresolved_relationships(value)

    @field_validator("studies", "unresolved_signals", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    @field_validator("warnings", mode="before")
    @classmethod
    def _normalize_diagnostic_warnings(cls, value: object) -> object:
        return _normalize_warnings(value)

    @field_validator("doc_role", mode="before")
    @classmethod
    def _normalize_doc_role(cls, value: object) -> str:
        return _normalize_choice(
            value,
            allowed={"experimental", "modeling", "mixed", "uncertain"},
            default="uncertain",
        )

    @field_validator("evidence_density", mode="before")
    @classmethod
    def _normalize_evidence_density(cls, value: object) -> str:
        return _normalize_choice(value, allowed=_EVIDENCE_DENSITIES, default="unknown")


class StructuredPaperSourceSignal(_PaperResearchMapResponse):
    """One explicit scientific axis from one Source, before relationship assembly."""

    signal_type: Literal["variable", "outcome"]
    label: Annotated[str, Field(min_length=1, max_length=80)]
    experiment_label: str | None = Field(default=None, max_length=120)
    design_type: Literal[
        "experimental",
        "observational",
        "modeling",
        "mixed",
        "uncertain",
    ] = "uncertain"
    claim_scope: Literal[
        "current_work",
        "synthesis",
        "background",
        "uncertain",
    ] = "uncertain"
    material_scope: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=_SOURCE_SIGNAL_CONTEXT_LIMIT)
    process_context: list[
        Annotated[str, Field(max_length=_STUDY_CONTEXT_VALUE_CHARS)]
    ] = Field(default_factory=list, max_length=_SOURCE_SIGNAL_CONTEXT_LIMIT)
    confidence: float = 0.0

    @field_validator(
        "material_scope",
        "process_context",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    def identity_key(self) -> tuple[object, ...]:
        def normalized_values(values: list[str]) -> tuple[str, ...]:
            return tuple(
                sorted(
                    {
                        value.strip().casefold()
                        for value in values
                        if value.strip()
                    }
                )
            )

        return (
            self.signal_type,
            self.label.strip().casefold(),
            self.experiment_label.strip().casefold()
            if self.experiment_label
            else None,
            self.design_type,
            self.claim_scope,
            normalized_values(self.material_scope),
            normalized_values(self.process_context),
        )


class StructuredPaperSourceSignalScreen(_PaperResearchMapResponse):
    """Bounded source-local signals used when paper-scope mapping fails."""

    doc_role: Literal["experimental", "review", "modeling", "mixed", "uncertain"] = (
        "uncertain"
    )
    signals: list[StructuredPaperSourceSignal] = Field(
        default_factory=list,
        max_length=_SOURCE_SIGNAL_LIMIT,
    )
    output_saturated: bool = False
    evidence_density: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence: float = 0.0
    warnings: list[
        Annotated[str, Field(max_length=PAPER_RESEARCH_MAP_WARNING_LIMIT[1])]
    ] = Field(default_factory=list, max_length=PAPER_RESEARCH_MAP_WARNING_LIMIT[0])

    @model_validator(mode="before")
    @classmethod
    def _isolate_malformed_signals(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        raw_signals = value.get("signals")
        if not isinstance(raw_signals, list):
            return value

        signals: list[StructuredPaperSourceSignal] = []
        malformed_count = 0
        for raw_signal in raw_signals:
            try:
                signals.append(StructuredPaperSourceSignal.model_validate(raw_signal))
            except ValidationError:
                malformed_count += 1
        if not malformed_count:
            return value

        signal_label = "signal" if malformed_count == 1 else "signals"
        warning = (
            f"Omitted {malformed_count} malformed source {signal_label}; retained "
            "the valid source-local signals."
        )
        existing_warnings = (
            value.get("warnings") if isinstance(value.get("warnings"), list) else []
        )
        updated = dict(value)
        updated["signals"] = signals
        updated["warnings"] = [warning, *existing_warnings][
            : PAPER_RESEARCH_MAP_WARNING_LIMIT[0]
        ]
        if raw_signals and not signals:
            updated["output_saturated"] = True
        return updated

    @field_validator("signals", mode="before")
    @classmethod
    def _normalize_signals(cls, value: object) -> object:
        return _normalize_list(value)

    @field_validator("warnings", mode="before")
    @classmethod
    def _normalize_diagnostic_warnings(cls, value: object) -> object:
        return _normalize_warnings(value)

    @field_validator("doc_role", mode="before")
    @classmethod
    def _normalize_doc_role(cls, value: object) -> str:
        return _normalize_choice(value, allowed=_DOC_ROLES, default="uncertain")

    @field_validator("evidence_density", mode="before")
    @classmethod
    def _normalize_evidence_density(cls, value: object) -> str:
        return _normalize_choice(value, allowed=_EVIDENCE_DENSITIES, default="unknown")

    @model_validator(mode="after")
    def _validate_signal_identities(self) -> StructuredPaperSourceSignalScreen:
        identities = [signal.identity_key() for signal in self.signals]
        if len(identities) != len(set(identities)):
            raise ValueError("source signal screen contains duplicate signal identities")
        return self


class StructuredReviewMapKnowledgeItem(_PaperResearchMapResponse):
    """One model-returned review statement linked by a short Source label."""

    content: Annotated[str, Field(min_length=1, max_length=240)]
    material_scope: list[Annotated[str, Field(max_length=120)]] = Field(
        default_factory=list,
        max_length=3,
    )
    variables: list[Annotated[str, Field(max_length=120)]] = Field(
        default_factory=list,
        max_length=3,
    )
    outcomes: list[Annotated[str, Field(max_length=120)]] = Field(
        default_factory=list,
        max_length=3,
    )
    conditions: list[Annotated[str, Field(max_length=160)]] = Field(
        default_factory=list,
        max_length=3,
    )
    source_labels: list[
        Annotated[str, Field(pattern=r"^S[1-9][0-9]*$", max_length=8)]
    ] = Field(min_length=1, max_length=4)
    confidence: float = 0.0

    @field_validator(
        "material_scope",
        "variables",
        "outcomes",
        "conditions",
        "source_labels",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    @model_validator(mode="after")
    def _validate_source_labels(self) -> "StructuredReviewMapKnowledgeItem":
        normalized = [value.strip() for value in self.source_labels]
        if len(normalized) != len(set(normalized)):
            raise ValueError("review knowledge Source labels must be unique")
        return self


class StructuredReviewMapSynthesis(_PaperResearchMapResponse):
    synthesis_claims: list[StructuredReviewMapKnowledgeItem] = Field(
        default_factory=list,
        max_length=_REVIEW_KNOWLEDGE_ITEM_LIMIT,
    )
    disputes: list[StructuredReviewMapKnowledgeItem] = Field(
        default_factory=list,
        max_length=_REVIEW_KNOWLEDGE_ITEM_LIMIT,
    )
    evidence_gaps: list[StructuredReviewMapKnowledgeItem] = Field(
        default_factory=list,
        max_length=_REVIEW_KNOWLEDGE_ITEM_LIMIT,
    )
    citation_leads: list[StructuredReviewMapKnowledgeItem] = Field(
        default_factory=list,
        max_length=_REVIEW_CITATION_LEAD_LIMIT,
    )

    @field_validator(
        "synthesis_claims",
        "disputes",
        "evidence_gaps",
        "citation_leads",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)


class StructuredReviewKnowledgeItem(_PaperResearchMapResponse):
    """One review-author statement rebound to backend Source identity."""

    content: Annotated[str, Field(min_length=1, max_length=240)]
    material_scope: list[Annotated[str, Field(max_length=120)]] = Field(
        default_factory=list,
        max_length=3,
    )
    variables: list[Annotated[str, Field(max_length=120)]] = Field(
        default_factory=list,
        max_length=3,
    )
    outcomes: list[Annotated[str, Field(max_length=120)]] = Field(
        default_factory=list,
        max_length=3,
    )
    conditions: list[Annotated[str, Field(max_length=160)]] = Field(
        default_factory=list,
        max_length=3,
    )
    source_unit_ids: list[
        Annotated[str, Field(min_length=1, max_length=160)]
    ] = Field(min_length=1, max_length=4)
    confidence: float = 0.0

    @field_validator(
        "material_scope",
        "variables",
        "outcomes",
        "conditions",
        "source_unit_ids",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    @model_validator(mode="after")
    def _validate_source_unit_ids(self) -> "StructuredReviewKnowledgeItem":
        normalized = [value.strip() for value in self.source_unit_ids]
        if len(normalized) != len(set(normalized)):
            raise ValueError("review knowledge Source-unit ids must be unique")
        return self


class StructuredReviewSynthesisMap(_PaperResearchMapResponse):
    synthesis_claims: list[StructuredReviewKnowledgeItem] = Field(
        default_factory=list,
        max_length=_REVIEW_KNOWLEDGE_ITEM_LIMIT,
    )
    disputes: list[StructuredReviewKnowledgeItem] = Field(
        default_factory=list,
        max_length=_REVIEW_KNOWLEDGE_ITEM_LIMIT,
    )
    evidence_gaps: list[StructuredReviewKnowledgeItem] = Field(
        default_factory=list,
        max_length=_REVIEW_KNOWLEDGE_ITEM_LIMIT,
    )
    citation_leads: list[StructuredReviewKnowledgeItem] = Field(
        default_factory=list,
        max_length=_REVIEW_CITATION_LEAD_LIMIT,
    )

    @field_validator(
        "synthesis_claims",
        "disputes",
        "evidence_gaps",
        "citation_leads",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)


class StructuredReviewPaperMap(_PaperResearchMapResponse):
    """Review-author knowledge without duplicate study or signal output."""

    doc_role: Literal["review"] = "review"
    review_synthesis: StructuredReviewMapSynthesis = Field(
        default_factory=StructuredReviewMapSynthesis
    )
    output_saturated: bool = False
    evidence_density: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence: float = 0.0
    warnings: list[
        Annotated[str, Field(max_length=PAPER_RESEARCH_MAP_WARNING_LIMIT[1])]
    ] = Field(default_factory=list, max_length=PAPER_RESEARCH_MAP_WARNING_LIMIT[0])

    @field_validator("warnings", mode="before")
    @classmethod
    def _normalize_diagnostic_warnings(cls, value: object) -> object:
        return _normalize_warnings(value)

    @field_validator("evidence_density", mode="before")
    @classmethod
    def _normalize_evidence_density(cls, value: object) -> str:
        return _normalize_choice(value, allowed=_EVIDENCE_DENSITIES, default="unknown")


class StructuredPaperResearchMap(_PaperResearchMapResponse):
    doc_role: Literal["experimental", "review", "modeling", "mixed", "uncertain"] = (
        "uncertain"
    )
    studies: list[StructuredPaperResearchScope] = Field(
        default_factory=list,
        max_length=PAPER_RESEARCH_MAP_SCOPE_LIMIT,
    )
    unresolved_signals: list[StructuredPaperResearchSignal] = Field(
        default_factory=list,
        max_length=PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT,
    )
    review_synthesis: StructuredReviewSynthesisMap = Field(
        default_factory=StructuredReviewSynthesisMap
    )
    output_saturated: bool = False
    evidence_density: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence: float = 0.0
    warnings: list[
        Annotated[str, Field(max_length=PAPER_RESEARCH_MAP_WARNING_LIMIT[1])]
    ] = Field(default_factory=list, max_length=PAPER_RESEARCH_MAP_WARNING_LIMIT[0])

    @model_validator(mode="before")
    @classmethod
    def _downgrade_unresolved_relationships(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        studies = value.get("studies")
        unresolved_signals = value.get("unresolved_signals")
        if not isinstance(studies, list):
            return value
        if unresolved_signals is not None and not isinstance(
            unresolved_signals,
            list,
        ):
            return value

        retained_studies: list[object] = []
        downgraded_signals: list[dict[str, object]] = []
        changed = False
        for study in studies:
            if not isinstance(study, Mapping):
                retained_studies.append(study)
                continue
            relationships = study.get("relationships")
            if not isinstance(relationships, list):
                retained_studies.append(study)
                continue

            retained_relationships: list[object] = []
            study_changed = False
            for relationship in relationships:
                if not isinstance(relationship, Mapping):
                    retained_relationships.append(relationship)
                    continue
                varied_factors = relationship.get("varied_factors")
                has_varied_factor = not isinstance(varied_factors, list) or (
                    bool(varied_factors)
                    and all(
                        0 < len(str(item).strip()) <= 80
                        for item in varied_factors
                    )
                )
                outcome = str(relationship.get("outcome") or "").strip()
                if has_varied_factor and not (
                    property_matching.outcome_label_requires_resolution(outcome)
                ):
                    retained_relationships.append(relationship)
                    continue
                lineage_field = (
                    "source_labels"
                    if "source_labels" in relationship
                    else "source_unit_ids"
                )
                lineage_values = relationship.get(lineage_field)
                if (
                    not outcome
                    or len(outcome) > 80
                    or not isinstance(lineage_values, list)
                    or not any(str(item).strip() for item in lineage_values)
                ):
                    retained_relationships.append(relationship)
                    continue

                signal = {
                    "signal_type": "outcome",
                    "label": outcome,
                    lineage_field: list(lineage_values),
                    "confidence": relationship.get(
                        "confidence",
                        study.get("confidence"),
                    ),
                }
                for field_name in (
                    "experiment_label",
                    "design_type",
                    "claim_scope",
                    "material_scope",
                    "process_context",
                ):
                    if field_name in study:
                        signal[field_name] = study[field_name]
                downgraded_signals.append(signal)
                study_changed = True
                changed = True

            if retained_relationships or not study_changed:
                retained_study = dict(study)
                retained_study["relationships"] = retained_relationships
                retained_studies.append(retained_study)

        if not changed:
            return value
        normalized = dict(value)
        normalized["studies"] = retained_studies
        normalized["unresolved_signals"] = [
            *(unresolved_signals or []),
            *downgraded_signals,
        ]
        return normalized

    @field_validator("studies", "unresolved_signals", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    @field_validator("warnings", mode="before")
    @classmethod
    def _normalize_warnings(cls, value: object) -> object:
        return _normalize_warnings(value)

    @field_validator("doc_role", mode="before")
    @classmethod
    def _normalize_doc_role(cls, value: object) -> str:
        return _normalize_choice(value, allowed=_DOC_ROLES, default="uncertain")

    @field_validator("evidence_density", mode="before")
    @classmethod
    def _normalize_evidence_density(cls, value: object) -> str:
        return _normalize_choice(value, allowed=_EVIDENCE_DENSITIES, default="unknown")

    @model_validator(mode="after")
    def _validate_study_identities(self) -> StructuredPaperResearchMap:
        study_identities = [study.identity_key() for study in self.studies]
        if len(study_identities) != len(set(study_identities)):
            raise ValueError("studies contain duplicate study identities")
        return self


def _review_synthesis_only(response: StructuredPaperResearchMap) -> StructuredPaperResearchMap:
    """Keep only scientific synthesis owned by a review's authors."""

    return response.model_copy(
        update={
            "doc_role": "review",
            "studies": [
                study for study in response.studies if study.claim_scope == "synthesis"
            ],
            "unresolved_signals": [
                signal
                for signal in response.unresolved_signals
                if signal.claim_scope == "synthesis"
            ],
        }
    )


def _model_visible_content(value: object) -> object:
    """Remove backend identity and slicing coordinates from scientific content."""

    if isinstance(value, Mapping):
        return {
            str(key): _model_visible_content(item)
            for key, item in value.items()
            if str(key) not in _MODEL_HIDDEN_CONTENT_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_model_visible_content(item) for item in value]
    return value


def _paper_map_model_payload(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    """Project backend input into the scientific contract visible to the model."""

    source_units_by_label: dict[str, Mapping[str, Any]] = {}
    source_unit_ids: set[str] = set()
    model_sources: list[dict[str, Any]] = []
    for source_unit in payload.get("source_units") or ():
        if not isinstance(source_unit, Mapping):
            continue
        source_unit_id = str(source_unit.get("source_unit_id") or "").strip()
        if not source_unit_id:
            raise ValueError("paper map Source-unit ids must be non-empty")
        if source_unit_id in source_unit_ids:
            raise ValueError("paper map Source-unit ids must be unique")
        source_unit_ids.add(source_unit_id)
        label = f"S{len(model_sources) + 1}"
        source_units_by_label[label] = source_unit
        model_sources.append(
            {
                "label": label,
                "section_path": str(source_unit.get("section_path") or "").strip(),
                "content": _model_visible_content(source_unit.get("content")),
            }
        )

    profile = payload.get("document_profile")
    document_type = (
        str(profile.get("doc_type") or "").strip()
        if isinstance(profile, Mapping)
        else ""
    )
    return (
        {
            "title": str(payload.get("title") or "").strip(),
            "document_type": document_type,
            "window_role": str(payload.get("window_role") or "unknown").strip()
            or "unknown",
            "sources": model_sources,
        },
        source_units_by_label,
    )


def _source_unit_ids_from_labels(
    source_labels: list[str],
    source_units_by_label: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    unknown_labels = sorted(set(source_labels) - source_units_by_label.keys())
    if unknown_labels:
        raise ValueError(
            "paper research map references unknown Source labels: "
            f"{unknown_labels}"
        )
    return [
        str(source_units_by_label[label].get("source_unit_id") or "").strip()
        for label in source_labels
    ]


def _paper_map_response_model(
    payload: Mapping[str, Any],
) -> type[StructuredExperimentalPaperMap] | type[StructuredReviewPaperMap]:
    profile = payload.get("document_profile")
    if (
        isinstance(profile, Mapping)
        and str(profile.get("doc_type") or "").strip() == "review"
    ):
        return StructuredReviewPaperMap
    return StructuredExperimentalPaperMap


def _paper_map_response(
    response: StructuredExperimentalPaperMap | StructuredReviewPaperMap,
    source_units_by_label: Mapping[str, Mapping[str, Any]],
) -> StructuredPaperResearchMap:
    if isinstance(response, StructuredExperimentalPaperMap):
        payload = response.model_dump()
        for study in payload["studies"]:
            for relationship in study["relationships"]:
                relationship["source_unit_ids"] = _source_unit_ids_from_labels(
                    relationship.pop("source_labels"),
                    source_units_by_label,
                )
        for signal in payload["unresolved_signals"]:
            signal["source_unit_ids"] = _source_unit_ids_from_labels(
                signal.pop("source_labels"),
                source_units_by_label,
            )
        return StructuredPaperResearchMap.model_validate(payload)

    studies: list[dict[str, Any]] = []
    unresolved_signals: list[dict[str, Any]] = []
    study_keys: set[tuple[object, ...]] = set()
    signal_keys: set[tuple[object, ...]] = set()
    candidate_items = (
        *response.review_synthesis.synthesis_claims,
        *response.review_synthesis.disputes,
    )
    for item in candidate_items:
        variables = tuple(
            dict.fromkeys(value.strip() for value in item.variables if value.strip())
        )
        outcomes = tuple(
            dict.fromkeys(value.strip() for value in item.outcomes if value.strip())
        )
        source_unit_ids = tuple(
            _source_unit_ids_from_labels(
                list(dict.fromkeys(item.source_labels)),
                source_units_by_label,
            )
        )
        material_scope = tuple(
            dict.fromkeys(value.strip() for value in item.material_scope if value.strip())
        )
        if variables and outcomes:
            study_key = (variables, outcomes, source_unit_ids, material_scope)
            if study_key in study_keys:
                continue
            study_keys.add(study_key)
            studies.append(
                {
                    "design_type": "observational",
                    "claim_scope": "synthesis",
                    "material_scope": list(material_scope),
                    "relationships": [
                        {
                            "varied_factors": list(variables),
                            "outcome": outcome,
                            "source_unit_ids": list(source_unit_ids),
                            "confidence": item.confidence,
                        }
                        for outcome in outcomes
                    ],
                    "confidence": item.confidence,
                }
            )
            continue

        for signal_type, labels in (("variable", variables), ("outcome", outcomes)):
            for label in labels:
                signal_key = (signal_type, label, source_unit_ids, material_scope)
                if signal_key in signal_keys:
                    continue
                signal_keys.add(signal_key)
                unresolved_signals.append(
                    {
                        "signal_type": signal_type,
                        "label": label,
                        "design_type": "observational",
                        "claim_scope": "synthesis",
                        "material_scope": list(material_scope),
                        "source_unit_ids": list(source_unit_ids),
                        "confidence": item.confidence,
                    }
                )

    derived_saturated = len(unresolved_signals) > PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT
    return StructuredPaperResearchMap.model_validate(
        {
            "doc_role": "review",
            "studies": studies,
            "unresolved_signals": unresolved_signals[
                :PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT
            ],
            "review_synthesis": {
                field_name: [
                    {
                        **item.model_dump(exclude={"source_labels"}),
                        "source_unit_ids": _source_unit_ids_from_labels(
                            item.source_labels,
                            source_units_by_label,
                        ),
                    }
                    for item in getattr(response.review_synthesis, field_name)
                ]
                for field_name in (
                    "synthesis_claims",
                    "disputes",
                    "evidence_gaps",
                    "citation_leads",
                )
            },
            "output_saturated": response.output_saturated or derived_saturated,
            "evidence_density": response.evidence_density,
            "confidence": response.confidence,
            "warnings": response.warnings,
        }
    )


def _build_review_synthesis_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    allowed_source_labels = [
        str(source.get("label") or "").strip()
        for source in payload.get("sources") or ()
        if isinstance(source, Mapping) and str(source.get("label") or "").strip()
    ]
    allowed_source_labels_json = json.dumps(
        allowed_source_labels,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    user_prompt = (
        "TASK MODEL\n"
        "Map only scientific synthesis authored by one review paper from one bounded "
        "high-level Source window. This is thematic review screening, not reconstruction "
        "of cited experiments, primary Evidence extraction, or Objective wording. The "
        "backend derives candidate factor/outcome pairs from the returned review-author "
        "statements; do not return a second study representation.\n\n"
        "INPUT SCHEMA\n"
        "- `title` identifies the review paper; `document_type` is a coarse role hint.\n"
        "- `window_role` describes this incomplete reading view but is not scientific "
        "evidence.\n"
        "- `sources` contain review text, table summaries, or figure captions. Content "
        "is the authority; each short label lets the backend restore lineage.\n"
        "- Named authors and numbered citations are navigation to primary literature, "
        "not review-owned experimental Evidence.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. Separate review-author synthesis from descriptions of individual cited "
        "studies. Phrases such as 'across studies', 'overall', explicit agreement or "
        "disagreement, taxonomies, and review conclusions can establish synthesis.\n"
        "2. Record each retained statement exactly once in `review_synthesis`: use "
        "`synthesis_claims` for cross-study judgments, `disputes` for explicit conflict, "
        "`evidence_gaps` for missing evidence or validation, and `citation_leads` for "
        "primary papers worth inspecting.\n"
        "3. For claims and disputes, record neutral variable and outcome axes only when "
        "the review authors explicitly connect them. Preserve the full joint variable "
        "set and keep specific outcomes separate. The backend derives candidate scope "
        "relationships from these fields.\n"
        "4. Preserve a partial variable-only or outcome-only statement in the same "
        "knowledge item. Do not borrow its missing axis from another Source.\n"
        "5. Copy only the Source labels that directly support each retained statement. "
        "Use confidence and warnings for ambiguity instead of filling gaps.\n\n"
        "HARD RULES\n"
        "- Do not return `studies` or `unresolved_signals`; those are derived by the "
        "backend so the same review judgment is not generated twice.\n"
        "- Do not reconstruct samples, controls, conditions, or outcomes of one cited "
        "paper. Those facts require its primary Source.\n"
        "- Citation leads are navigation only and never primary Evidence.\n"
        "- Do not infer scientific content from titles, filenames, section names, or "
        "general knowledge.\n"
        "- Return empty arrays when no eligible review-author statement is supplied.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- Cited result only: 'Miranda et al. [20] reported lower residual stress.' "
        "Return it only as a citation lead when it is useful navigation.\n"
        "- Review synthesis: 'Across studies, preheating generally reduced residual "
        "stress.' Return one synthesis claim with variable='preheating condition' and "
        "outcome='residual stress'.\n"
        "- Conflict: 'Porosity trends disagree across scan strategies.' Return one "
        "dispute with variable='scan strategy' and outcome='porosity'; do not invent a "
        "direction.\n"
        "- Review method only: 'We searched Web of Science.' Return empty arrays.\n\n"
        "OUTPUT CONTRACT\n"
        "- Return doc_role='review', `review_synthesis`, evidence_density, confidence, "
        "warnings, and output_saturated.\n"
        f"- Return at most {_REVIEW_KNOWLEDGE_ITEM_LIMIT} synthesis claims, "
        f"{_REVIEW_KNOWLEDGE_ITEM_LIMIT} disputes, "
        f"{_REVIEW_KNOWLEDGE_ITEM_LIMIT} evidence gaps, and "
        f"{_REVIEW_CITATION_LEAD_LIMIT} citation leads.\n"
        "- Each item contains one concise review-author statement, compact scientific "
        "scope, confidence, and 1-4 allowed `source_labels`.\n"
        "- Set output_saturated=true when eligible review-author knowledge exceeds "
        "these limits. Return only compact schema-valid JSON.\n\n"
        "BATCH LINEAGE CONTRACT\n"
        f"ALLOWED SOURCE LABELS: {allowed_source_labels_json}\n"
        "Copy labels only from this exact list."
    )
    return _REVIEW_SYSTEM_PROMPT, user_prompt


def build_paper_research_map_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    model_payload, _ = _paper_map_model_payload(payload)
    document_profile = payload.get("document_profile")
    if isinstance(document_profile, Mapping) and (
        str(document_profile.get("doc_type") or "").strip() == "review"
    ):
        return _build_review_synthesis_prompt(model_payload)

    allowed_source_labels = [
        str(source.get("label") or "").strip()
        for source in model_payload.get("sources") or ()
        if isinstance(source, Mapping) and str(source.get("label") or "").strip()
    ]
    allowed_source_labels_json = json.dumps(
        allowed_source_labels,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    user_prompt = (
        "TASK MODEL\n"
        "Map the paper's stated research scope from one bounded high-level Source "
        "window for Objective discovery. This is candidate-scope extraction, not "
        "full experiment reconstruction, Evidence extraction, causal synthesis, or "
        "Objective wording. A relationship is candidate scope, not proven Evidence.\n\n"
        "INPUT SCHEMA\n"
        "- `title` identifies the paper and `document_type` is a coarse role hint.\n"
        "- `window_role` describes this bounded reading view.\n"
        "- `sources` contains high-level abstract, conclusion, overview, or caption "
        "content. Each Source has a short label for backend lineage. Source content "
        "is the scientific authority.\n"
        "This is one incomplete view of the paper; absence from this window is not "
        "evidence of absence elsewhere. Detailed Methods, Results, and table rows are "
        "inspected after Objective confirmation.\n\n"
        f"Input JSON:\n{json.dumps(model_payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. First decide whether the Source reports or proposes a scientific "
        "investigation: an explicit change, comparison, model, measurement, or "
        "observation. General statements of prevalence, use, importance, or motivation "
        "do not name a research variable or outcome; return empty studies and signals "
        "for them.\n"
        "2. Identify whose work is described. Use claim_scope=current_work only for "
        "this paper; synthesis and named citations remain separate. Never label a "
        "cited study current_work.\n"
        "3. Keep only explicitly changed, compared, or modeled factors and explicitly "
        "measured, observed, or predicted outcomes. Use neutral scientific axis names, "
        "not levels, values, directions, settings, samples, controls, or test details.\n"
        "4. When the Source explicitly links factors to outcomes, return one "
        "relationship per outcome. Preserve the full jointly varied, compared, or "
        "modeled factor set. Do not demote an explicit configuration-to-outcome link "
        "to unresolved signals.\n"
        "5. Do not promote causal explanations or intermediate mechanisms introduced "
        "by phrases such as 'attributed to', 'due to', or 'allowing' unless the Source "
        "separately states that they were measured, observed, or predicted outcomes.\n"
        "6. If only one axis is explicit, or an outcome is a broad family such as "
        "microstructure or mechanical properties or combines distinct measurements, "
        "return the explicit axis in `unresolved_signals` instead of inventing a "
        "metric or link.\n"
        "7. Keep one study unless the Source explicitly names distinct experiments or "
        "designs. Do not invent an experiment label to split one paper-owned study by "
        "Source or axis family.\n"
        "8. Record material_scope and concise process_context only when explicit. "
        "Detailed experiment fields are intentionally absent.\n"
        "9. Copy every directly supporting Source label. Use uncertainty or empty "
        "arrays rather than filling gaps.\n\n"
        "HARD RULES\n"
        "- Use only supplied Source content; do not infer from filenames, headings, or "
        "general knowledge.\n"
        "- Do not merge cited work with current work or move axes between studies.\n"
        "- Do not treat factor levels, fixed settings, result values, or result "
        "direction as research axes.\n"
        "- Do not repeat an axis as unresolved when it is already in a relationship.\n"
        "- Unresolved signals represent incomplete links, not relationship overflow. "
        "If a supported relationship exceeds the relationship limit, set "
        "output_saturated=true.\n"
        "- Copy `source_labels` only from the allowed list, without duplicates, at "
        f"most {PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT} per item.\n"
        "- Return empty arrays rather than guessing unsupported study structure.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- Joint factors: power and speed changed together. Keep "
        "varied_factors=['power','speed'] and return one relationship per outcome.\n"
        "- Explicit configuration effect: 'PTA leading with front wire feeding gave "
        "stable deposition and good bead appearance.' Return two relationships with "
        "the full factors ['heat-source configuration','wire-feeding direction'] and "
        "outcomes 'deposition stability' and 'bead appearance'.\n"
        "- Broad outcome: 'Heat treatment changed the microstructure.' Return the "
        "outcome as unresolved; do not invent grain size or phase fraction.\n"
        "- Mechanism clause: 'Higher deposition rate is attributed to extended energy "
        "distribution and melt pool size.' Keep deposition rate; do not create energy "
        "distribution or melt pool size outcomes unless the Source says they were "
        "measured, observed, or predicted.\n"
        "- Factor levels: L-VED, M-VED, and H-VED are levels. Return "
        "varied_factors=['volumetric energy density'].\n"
        "- Result direction: 'fatigue strength decreases with lower VED.' Return "
        "outcome='fatigue strength'; result direction, value, or comparison sentence "
        "belongs to later Evidence extraction.\n"
        "- Incomplete link: a Methods Source names laser power but no response. Return "
        "`studies=[]`; do not borrow an outcome. Return the explicit axis in "
        "`unresolved_signals`.\n"
        "- Cited result: 'Miranda et al. [20] increased laser power and reduced "
        "porosity.' Keep claim_scope=background.\n"
        "- General background: 'Additive manufacturing is widely used in aerospace.' "
        "Return empty studies and unresolved_signals; usage context is not a measured "
        "outcome.\n"
        "- Fixed settings only: 'sample A used 200 W and 900 mm/s.' Return no axis.\n\n"
        "OUTPUT CONTRACT\n"
        "Return one compact schema object with doc_role, studies, unresolved_signals, "
        "output_saturated, evidence_density, confidence, and warnings.\n"
        "A study contains optional experiment_label only when explicitly named, plus "
        "design_type, claim_scope, material_scope, process_context, relationships, and "
        "confidence. A relationship contains varied_factors, one outcome, "
        "source_labels, and confidence.\n"
        f"Limits: up to {_PAPER_MAP_STUDY_LIMIT} studies, up to "
        f"{_PAPER_MAP_RELATIONSHIP_LIMIT} relationships per study, up to "
        f"{_PAPER_MAP_SIGNAL_LIMIT} unresolved signals, at most "
        f"{_PAPER_MAP_VARIED_FACTOR_LIMIT} varied-factor labels, at most "
        f"{PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT} unique `source_labels`, and up to 2 "
        "`warnings`, each at most 240 characters. Set output_saturated=true only if a "
        "distinct supported item exceeds these limits.\n\n"
        "BATCH LINEAGE\n"
        f"ALLOWED SOURCE LABELS: {allowed_source_labels_json}\n"
        "Copy labels only from this exact list."
    )
    return _SYSTEM_PROMPT, user_prompt


_SOURCE_SIGNAL_SYSTEM_PROMPT = """
You screen one Source from a scientific paper for explicit research signals.
Return one compact JSON object. Preserve uncertainty and Source-local meaning.
Do not construct experiments, relationships, findings, or research objectives.
""".strip()


def build_paper_source_signal_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    model_payload, _ = _paper_map_model_payload(payload)
    user_prompt = (
        "TASK MODEL\n"
        "Perform source-local scientific signal screening after paper-scope mapping "
        "could not produce bounded structured output. This is explicit-axis "
        "extraction for later paper-level reconciliation, not relationship "
        "construction, causal interpretation, evidence synthesis, or objective "
        "generation.\n\n"
        "INPUT SCHEMA\n"
        "- The input contains exactly one Source unit from one paper.\n"
        "- Source content is the scientific authority. Document and section metadata "
        "provide provenance and orientation only.\n"
        "- The downstream backend binds Source identity and performs paper-level "
        "reconciliation.\n\n"
        f"Input JSON:\n{json.dumps(model_payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. Decide whether the Source explicitly names a changed, compared, or modeled "
        "variable and/or a measured, observed, or predicted outcome.\n"
        "2. Return each explicit research axis as one neutral, concise signal. An "
        "axis is what was changed or measured, not a value, direction, phase, grain "
        "shape, or other observation on that axis. Group multiple morphology or phase "
        "observations from one characterization result under one outcome such as "
        "microstructure or phase constitution. Keep genuinely different measurements, "
        "such as tensile strength and hardness, as separate outcomes. Do not return an "
        "umbrella outcome and its explicitly named members together.\n"
        "3. Classify whose work the statement describes. Use "
        "claim_scope=current_work only for this paper's own work, synthesis for the "
        "review authors' explicit synthesis, and claim_scope=background for a cited "
        "or named prior study.\n"
        "4. Copy only context explicitly supported by this Source. Use a concise "
        "experiment label when the Source supplies an author name, group label, or "
        "other identity needed to keep studies separate.\n"
        "5. If no explicit scientific axis is present, return signals=[].\n\n"
        "HARD RULES\n"
        "- Do not infer a causal relationship or pair variable and outcome signals.\n"
        "- Do not turn fixed settings, material identity, or test conditions into "
        "variables.\n"
        "- Do not return or copy Source-unit IDs; the backend owns identity and "
        "lineage.\n"
        "- Do not complete missing experiment context from general knowledge.\n"
        "- Open-list words such as 'etc.' or 'including' do not name hidden axes and "
        "must not cause output_saturated=true.\n"
        "- Keep cited studies in reviews separate from the review authors' synthesis "
        "and from this paper's own experiments.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- Primary result: 'We varied laser power and measured porosity.' Return a "
        "current_work variable signal 'laser power' and outcome signal 'porosity'.\n"
        "- Review citation: 'Miranda et al. increased build plate temperature and "
        "reported lower residual stress.' Return background signals with "
        "experiment_label='Miranda et al.'; do not treat them as current_work.\n"
        "- Synthesis: 'Across the reviewed studies, preheating generally reduced "
        "residual stress.' Return synthesis signals only for axes explicitly named.\n"
        "- One characterization axis: 'After three reheats, the CGHAZ contained "
        "equiaxed ferrite, refined ferrite, and scattered lamellar pearlite.' Return "
        "variable='reheating cycles' and outcome='microstructure'; the named "
        "morphologies are observations, not separate outcome axes.\n"
        "- Explicit measurement list: 'IHT enhanced tensile strength, hardness, "
        "ductility, and fatigue.' Return one IHT variable and four distinct outcome "
        "signals; do not also return 'mechanical properties'.\n"
        "- Background only: 'Additive manufacturing is widely used in aerospace.' "
        "Return signals=[].\n\n"
        "OUTPUT CONTRACT\n"
        "Return doc_role, signals, output_saturated, evidence_density, confidence, and "
        f"warnings. Return at most {_SOURCE_SIGNAL_LIMIT} signals and at most four "
        "values in each context list. Set output_saturated=true only when more than "
        f"{_SOURCE_SIGNAL_LIMIT} distinct explicit "
        "research axes are present; omitted descriptive details do not count as omitted "
        "axes. Return only schema-valid JSON."
    )
    return _SOURCE_SIGNAL_SYSTEM_PROMPT, user_prompt


class PaperResearchMapExtractor:
    """Map supported paper scope from one bounded high-level Source window."""

    def __init__(self, response_client: StructuredResponseClient) -> None:
        self.response_client = response_client

    def extract(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
        system_prompt, user_prompt = build_paper_research_map_prompt(payload)
        _, source_units_by_label = _paper_map_model_payload(payload)
        allowed_source_labels_json = json.dumps(
            list(source_units_by_label),
            ensure_ascii=True,
            separators=(",", ":"),
        )
        is_review = (
            isinstance(payload.get("document_profile"), Mapping)
            and str(payload["document_profile"].get("doc_type") or "").strip()
            == "review"
        )

        def build_repair_instruction(repair_detail: str) -> str:
            if is_review:
                return (
                    "Previous review synthesis output was invalid: "
                    f"{repair_detail}. Retain only explicit scientific synthesis "
                    "authored by the review. Return each judgment once inside "
                    "review_synthesis; do not return studies or unresolved_signals. "
                    "Discard reconstructions of individually cited experiments. Copy "
                    "only unique Source labels from the input and return compact "
                    "schema-valid JSON.\n"
                    f"ALLOWED SOURCE LABELS: {allowed_source_labels_json}"
                )
            return (
                "Previous paper-map output was invalid: "
                f"{repair_detail}. Preserve every distinct supported paper-scope "
                "group, relationship, and unresolved signal. Do not reconstruct "
                "samples, tests, comparators, fixed conditions, or factor levels. "
                "Those detailed fields are not part of this output contract. Copy only "
                "unique Source labels from the input, with at most "
                f"{PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT} labels per relationship or signal. "
                f"Keep at most {_PAPER_MAP_VARIED_FACTOR_LIMIT} varied factors per "
                "relationship. Set output_saturated=true "
                "instead of silently omitting a scientific item. Return only compact "
                "schema-valid JSON.\n"
                f"ALLOWED SOURCE LABELS: {allowed_source_labels_json}"
            )

        def validate_output_contract(response: BaseModel) -> BaseModel | None:
            if not isinstance(
                response,
                (StructuredExperimentalPaperMap, StructuredReviewPaperMap),
            ):
                raise TypeError("unexpected paper research map response type")
            paper_map = _paper_map_response(response, source_units_by_label)
            source_keys = {
                str(source_unit.get("source_unit_id") or "").strip(): (
                    str(source_unit.get("source_kind") or "").strip(),
                    str(source_unit.get("source_ref") or "").strip(),
                )
                for source_unit in payload.get("source_units") or ()
                if isinstance(source_unit, Mapping)
                and str(source_unit.get("source_unit_id") or "").strip()
            }
            study_identities = [
                study.identity_key(source_keys) for study in paper_map.studies
            ]
            if len(study_identities) != len(set(study_identities)):
                raise ValueError("studies contain duplicate study identities")
            return paper_map

        def parse_json_text_with_contract(**kwargs: Any) -> tuple[BaseModel, str | None]:
            return self.response_client.complete_json(
                **kwargs,
                repair_instruction_builder=build_repair_instruction,
                parsed_validator=validate_output_contract,
                fail_on_output_saturation=True,
            )

        try:
            response_model = _paper_map_response_model(payload)
            response = self.response_client.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
                max_completion_tokens=_MAX_COMPLETION_TOKENS,
                json_text_parser=parse_json_text_with_contract,
                parsed_validator=validate_output_contract,
                fail_on_output_saturation=True,
                task_type="paper_map",
                prompt_version=PAPER_RESEARCH_MAP_PROMPT_VERSION,
            )
        except StructuredOutputSaturatedError:
            self._log_saturation_trace(payload, contract="paper_map")
            raise
        if not isinstance(response, StructuredPaperResearchMap):
            raise TypeError("unexpected paper research map response type")
        return response

    def extract_source_signals(self, payload: dict[str, Any]) -> StructuredPaperResearchMap:
        source_units = [
            unit
            for unit in payload.get("source_units") or ()
            if isinstance(unit, Mapping)
        ]
        if len(source_units) != 1:
            raise ValueError("source signal screening requires exactly one Source unit")
        source_unit_id = str(source_units[0].get("source_unit_id") or "").strip()
        if not source_unit_id:
            raise ValueError("source signal screening requires a Source-unit id")

        system_prompt, user_prompt = build_paper_source_signal_prompt(payload)
        try:
            response = self.response_client.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=StructuredPaperSourceSignalScreen,
                max_completion_tokens=_SOURCE_SIGNAL_MAX_COMPLETION_TOKENS,
                fail_on_output_saturation=True,
                task_type="paper_source_signal",
                prompt_version=PAPER_SOURCE_SIGNAL_PROMPT_VERSION,
            )
        except StructuredOutputSaturatedError:
            self._log_saturation_trace(payload, contract="paper_source_signal")
            raise
        if not isinstance(response, StructuredPaperSourceSignalScreen):
            raise TypeError("unexpected paper source signal response type")
        if response.output_saturated:
            self._log_saturation_trace(payload, contract="paper_source_signal")
            raise StructuredOutputSaturatedError(
                "Paper source signal output omitted visible scientific axes"
            )

        return StructuredPaperResearchMap.model_validate(
            {
                "doc_role": response.doc_role,
                "unresolved_signals": [
                    {
                        **signal.model_dump(),
                        "source_unit_ids": [source_unit_id],
                    }
                    for signal in response.signals
                ],
                "evidence_density": response.evidence_density,
                "confidence": response.confidence,
                "warnings": response.warnings,
            }
        )

    def _log_saturation_trace(
        self,
        payload: Mapping[str, Any],
        *,
        contract: str,
    ) -> None:
        source_units = [
            unit
            for unit in payload.get("source_units") or ()
            if isinstance(unit, Mapping)
        ]
        source_unit_ids = [
            str(unit.get("source_unit_id") or "").strip()
            for unit in source_units
            if str(unit.get("source_unit_id") or "").strip()
        ]
        input_chars = sum(
            self._source_content_chars(unit.get("content"))
            for unit in source_units
        )
        trace = self.response_client.peek_last_trace() or {}
        attempts = []
        for attempt in trace.get("attempts") or ():
            if not isinstance(attempt, Mapping):
                continue
            attempts.append(
                {
                    "attempt": attempt.get("attempt"),
                    "finish_reason": attempt.get("finish_reason"),
                    "response_chars": attempt.get("response_chars"),
                    "response_preview": str(
                        attempt.get("response_preview") or ""
                    )[:1000],
                }
            )
        logger.warning(
            "Paper research map saturation trace contract=%s window_id=%s "
            "source_unit_ids=%s input_chars=%s attempts=%s",
            contract,
            payload.get("window_id"),
            json.dumps(source_unit_ids, ensure_ascii=True, separators=(",", ":")),
            input_chars,
            json.dumps(attempts, ensure_ascii=True, separators=(",", ":")),
        )

    @staticmethod
    def _source_content_chars(content: object) -> int:
        if isinstance(content, str):
            return len(content)
        if content is None:
            return 0
        return len(json.dumps(content, ensure_ascii=False, separators=(",", ":")))

    def estimate_prompt_tokens(self, payload: dict[str, Any]) -> int:
        """Count the complete repair-capable prompt before model execution."""

        system_prompt, user_prompt = build_paper_research_map_prompt(payload)
        return self.response_client.estimate_prompt_tokens(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=_paper_map_response_model(payload),
        )


__all__ = [
    "PAPER_RESEARCH_MAP_PROMPT_TOKEN_LIMIT",
    "PAPER_RESEARCH_MAP_SOURCE_UNIT_LIMIT",
    "PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT",
    "PAPER_SOURCE_SIGNAL_PROMPT_VERSION",
    "PaperResearchMapExtractor",
    "StructuredPaperResearchMap",
    "StructuredPaperSourceSignal",
    "StructuredPaperSourceSignalScreen",
    "StructuredPaperResearchScope",
    "StructuredPaperResearchRelationship",
    "StructuredPaperResearchSignal",
    "build_paper_research_map_prompt",
    "build_paper_source_signal_prompt",
]
