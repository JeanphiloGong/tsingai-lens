from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from .common import (
    PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT,
    PAPER_RESEARCH_MAP_RELATIONSHIP_LIMIT,
    PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT,
    PAPER_RESEARCH_MAP_WARNING_LIMIT,
    _PaperResearchMapResponse,
    _PAPER_MAP_CONTEXT_LIMIT,
    _PAPER_MAP_STUDY_LIMIT,
    _PAPER_MAP_VARIED_FACTOR_LIMIT,
    _REVIEW_CITATION_LEAD_LIMIT,
    _REVIEW_KNOWLEDGE_ITEM_LIMIT,
    _SOURCE_SIGNAL_CONTEXT_LIMIT,
    _SOURCE_SIGNAL_LIMIT,
    _STUDY_CONTEXT_VALUE_CHARS,
    _normalize_list,
    _normalize_warnings,
)
from .normalization import _downgrade_unresolved_relationships


class StructuredPaperMapFactorAssertion(_PaperResearchMapResponse):
    """One Source-linked factor role inside a candidate paper relationship."""

    label: Annotated[str, Field(min_length=1, max_length=80)]
    role: Literal["varied", "compared", "modeled"]
    source_labels: list[
        Annotated[str, Field(pattern=r"^S[1-9][0-9]*$", max_length=8)]
    ] = Field(min_length=1, max_length=PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT)

    @field_validator("source_labels", mode="before")
    @classmethod
    def _normalize_source_labels(cls, value: object) -> object:
        return _normalize_list(value)

    @model_validator(mode="after")
    def _validate_source_labels(self) -> "StructuredPaperMapFactorAssertion":
        normalized = [value.strip() for value in self.source_labels]
        if any(not value for value in normalized):
            raise ValueError("paper-map factor Source labels cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("paper-map factor Source labels must be unique")
        return self


class StructuredPaperMapRelationship(_PaperResearchMapResponse):
    """One compact factor-to-outcome axis used only during paper mapping."""

    factor_assertions: list[
        StructuredPaperMapFactorAssertion
    ] = Field(min_length=1, max_length=_PAPER_MAP_VARIED_FACTOR_LIMIT)
    outcome: Annotated[str, Field(min_length=1, max_length=80)]
    source_labels: list[
        Annotated[str, Field(pattern=r"^S[1-9][0-9]*$", max_length=8)]
    ] = Field(min_length=1, max_length=PAPER_MAP_WINDOW_SOURCE_UNIT_LIMIT)
    confidence: float = 0.0

    @field_validator("factor_assertions", "source_labels", mode="before")
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
        factor_labels = [
            assertion.label.strip().casefold()
            for assertion in self.factor_assertions
        ]
        if len(factor_labels) != len(set(factor_labels)):
            raise ValueError("paper-map relationship factors must be unique")
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


class StructuredPaperMapSignal(_PaperResearchMapResponse):
    """One incomplete paper-owned variable or outcome axis."""

    signal_type: Literal["variable", "outcome"]
    label: Annotated[str, Field(min_length=1, max_length=80)]
    variable_role: Literal[
        "varied",
        "compared",
        "modeled",
        "fixed",
        "context",
        "uncertain",
        "not_applicable",
    ]
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
        if self.signal_type == "variable" and self.variable_role == "not_applicable":
            raise ValueError("variable signal requires a scientific variable role")
        if self.signal_type == "outcome" and self.variable_role != "not_applicable":
            raise ValueError("outcome signal variable role must be not_applicable")
        return self


class ExperimentalPaperMapModelOutput(_PaperResearchMapResponse):
    """Compact high-level scope contract for non-review papers."""

    doc_role: Literal["experimental", "modeling", "mixed", "uncertain"] = "uncertain"
    studies: list[StructuredPaperMapStudy] = Field(
        default_factory=list,
        max_length=_PAPER_MAP_STUDY_LIMIT,
    )
    unresolved_signals: list[StructuredPaperMapSignal] = Field(
        default_factory=list,
        max_length=PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT,
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
        return _downgrade_unresolved_relationships(value)

    @field_validator("studies", "unresolved_signals", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    @field_validator("warnings", mode="before")
    @classmethod
    def _normalize_diagnostic_warnings(cls, value: object) -> object:
        return _normalize_warnings(value)


class StructuredPaperSourceSignal(_PaperResearchMapResponse):
    """One explicit scientific axis from one Source, before relationship assembly."""

    signal_type: Literal["variable", "outcome"]
    label: Annotated[str, Field(min_length=1, max_length=80)]
    variable_role: Literal[
        "varied",
        "compared",
        "modeled",
        "fixed",
        "context",
        "uncertain",
        "not_applicable",
    ]
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
            self.variable_role,
            self.experiment_label.strip().casefold()
            if self.experiment_label
            else None,
            self.design_type,
            self.claim_scope,
            normalized_values(self.material_scope),
            normalized_values(self.process_context),
        )

    @model_validator(mode="after")
    def _validate_variable_role(self) -> "StructuredPaperSourceSignal":
        if self.signal_type == "variable" and self.variable_role == "not_applicable":
            raise ValueError("variable signal requires a scientific variable role")
        if self.signal_type == "outcome" and self.variable_role != "not_applicable":
            raise ValueError("outcome signal variable role must be not_applicable")
        return self


class PaperSourceSignalScreenModelOutput(_PaperResearchMapResponse):
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

    @model_validator(mode="after")
    def _validate_signal_identities(self) -> PaperSourceSignalScreenModelOutput:
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


class ReviewPaperMapModelOutput(_PaperResearchMapResponse):
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
