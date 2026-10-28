from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .common import (
    PAPER_RESEARCH_MAP_RELATIONSHIP_LIMIT,
    PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT,
    PAPER_RESEARCH_MAP_WARNING_LIMIT,
    _PaperResearchMapResponse,
    _PAPER_MAP_CONTEXT_LIMIT,
    _PAPER_MAP_STUDY_LIMIT,
    _PAPER_MAP_VARIED_FACTOR_LIMIT,
    _REVIEW_CITATION_LEAD_LIMIT,
    _REVIEW_KNOWLEDGE_ITEM_LIMIT,
    _STUDY_CONTEXT_VALUE_CHARS,
    _normalize_warnings,
    _bounded_mapping_list,
    _mark_bounded_output,
)
from .normalization import _downgrade_unresolved_relationships


class PaperMapFactorAssertionModelOutput(_PaperResearchMapResponse):
    """One Source-linked factor role inside a candidate paper relationship."""

    label: Annotated[str, Field(min_length=1, max_length=80)]
    role: Literal["varied", "compared", "modeled"]
    source_labels: list[
        Annotated[str, Field(pattern=r"^S[1-9][0-9]*$", max_length=8)]
    ] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_source_labels(self) -> "PaperMapFactorAssertionModelOutput":
        normalized = [value.strip() for value in self.source_labels]
        if any(not value for value in normalized):
            raise ValueError("paper-map factor Source labels cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("paper-map factor Source labels must be unique")
        return self


class PaperMapRelationshipModelOutput(_PaperResearchMapResponse):
    """One compact factor-to-outcome axis used only during paper mapping."""

    factor_assertions: list[
        PaperMapFactorAssertionModelOutput
    ] = Field(min_length=1, max_length=_PAPER_MAP_VARIED_FACTOR_LIMIT)
    outcome: Annotated[str, Field(min_length=1, max_length=80)]
    source_labels: list[
        Annotated[str, Field(pattern=r"^S[1-9][0-9]*$", max_length=8)]
    ] = Field(min_length=1)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_source_labels(self) -> "PaperMapRelationshipModelOutput":
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


class PaperMapStudyModelOutput(_PaperResearchMapResponse):
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
    relationships: list[PaperMapRelationshipModelOutput] = Field(
        min_length=1,
        max_length=PAPER_RESEARCH_MAP_RELATIONSHIP_LIMIT,
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class PaperMapSignalModelOutput(_PaperResearchMapResponse):
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
    ] = Field(min_length=1)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_source_labels(self) -> "PaperMapSignalModelOutput":
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
    studies: list[PaperMapStudyModelOutput] = Field(
        default_factory=list,
        max_length=_PAPER_MAP_STUDY_LIMIT,
    )
    unresolved_signals: list[PaperMapSignalModelOutput] = Field(
        default_factory=list,
        max_length=PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT,
    )
    output_saturated: bool = False
    evidence_density: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[
        Annotated[str, Field(max_length=PAPER_RESEARCH_MAP_WARNING_LIMIT[1])]
    ] = Field(default_factory=list, max_length=PAPER_RESEARCH_MAP_WARNING_LIMIT[0])

    @model_validator(mode="before")
    @classmethod
    def _downgrade_unresolved_relationships(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        downgraded = _downgrade_unresolved_relationships(value)
        payload = dict(downgraded)
        overflows: list[str] = []
        studies = _bounded_mapping_list(
            payload,
            "studies",
            limit=_PAPER_MAP_STUDY_LIMIT,
            path="studies",
            overflows=overflows,
        )
        normalized_studies: list[object] = []
        for study_index, study in enumerate(studies or ()):
            if not isinstance(study, Mapping):
                normalized_studies.append(study)
                continue
            normalized_study = dict(study)
            for field_name in ("material_scope", "process_context"):
                _bounded_mapping_list(
                    normalized_study,
                    field_name,
                    limit=_PAPER_MAP_CONTEXT_LIMIT,
                    path=f"studies[{study_index}].{field_name}",
                    overflows=overflows,
                )
            relationships = _bounded_mapping_list(
                normalized_study,
                "relationships",
                limit=PAPER_RESEARCH_MAP_RELATIONSHIP_LIMIT,
                path=f"studies[{study_index}].relationships",
                overflows=overflows,
            )
            if relationships is None:
                normalized_studies.append(normalized_study)
                continue
            normalized_relationships: list[object] = []
            for relationship_index, relationship in enumerate(relationships):
                if not isinstance(relationship, Mapping):
                    normalized_relationships.append(relationship)
                    continue
                normalized_relationship = dict(relationship)
                overflow_count = len(overflows)
                _bounded_mapping_list(
                    normalized_relationship,
                    "factor_assertions",
                    limit=_PAPER_MAP_VARIED_FACTOR_LIMIT,
                    path=(
                        f"studies[{study_index}].relationships[{relationship_index}]"
                        ".factor_assertions"
                    ),
                    overflows=overflows,
                )
                if len(overflows) > overflow_count:
                    # A truncated joint factor set describes a different study.
                    # Omit that relationship, not individual factors within it.
                    continue
                normalized_relationships.append(normalized_relationship)
            if relationships and not normalized_relationships:
                continue
            normalized_study["relationships"] = normalized_relationships
            normalized_studies.append(normalized_study)
        if studies is not None:
            payload["studies"] = normalized_studies

        signals = _bounded_mapping_list(
            payload,
            "unresolved_signals",
            limit=PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT,
            path="unresolved_signals",
            overflows=overflows,
        )
        normalized_signals: list[object] = []
        for signal_index, signal in enumerate(signals or ()):
            if not isinstance(signal, Mapping):
                normalized_signals.append(signal)
                continue
            normalized_signal = dict(signal)
            for field_name in ("material_scope", "process_context"):
                _bounded_mapping_list(
                    normalized_signal,
                    field_name,
                    limit=_PAPER_MAP_CONTEXT_LIMIT,
                    path=f"unresolved_signals[{signal_index}].{field_name}",
                    overflows=overflows,
                )
            normalized_signals.append(normalized_signal)
        if signals is not None:
            payload["unresolved_signals"] = normalized_signals
        return _mark_bounded_output(payload, overflows=overflows)

    @field_validator("warnings", mode="before")
    @classmethod
    def _normalize_diagnostic_warnings(cls, value: object) -> object:
        return _normalize_warnings(value)


class ReviewMapKnowledgeItemModelOutput(_PaperResearchMapResponse):
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
    ] = Field(min_length=1)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_source_labels(self) -> "ReviewMapKnowledgeItemModelOutput":
        normalized = [value.strip() for value in self.source_labels]
        if len(normalized) != len(set(normalized)):
            raise ValueError("review knowledge Source labels must be unique")
        return self


class ReviewMapSynthesisModelOutput(_PaperResearchMapResponse):
    synthesis_claims: list[ReviewMapKnowledgeItemModelOutput] = Field(
        default_factory=list,
        max_length=_REVIEW_KNOWLEDGE_ITEM_LIMIT,
    )
    disputes: list[ReviewMapKnowledgeItemModelOutput] = Field(
        default_factory=list,
        max_length=_REVIEW_KNOWLEDGE_ITEM_LIMIT,
    )
    evidence_gaps: list[ReviewMapKnowledgeItemModelOutput] = Field(
        default_factory=list,
        max_length=_REVIEW_KNOWLEDGE_ITEM_LIMIT,
    )
    citation_leads: list[ReviewMapKnowledgeItemModelOutput] = Field(
        default_factory=list,
        max_length=_REVIEW_CITATION_LEAD_LIMIT,
    )


class ReviewPaperMapModelOutput(_PaperResearchMapResponse):
    """Review-author knowledge without duplicate study or signal output."""

    doc_role: Literal["review"] = "review"
    review_synthesis: ReviewMapSynthesisModelOutput = Field(
        default_factory=ReviewMapSynthesisModelOutput
    )
    output_saturated: bool = False
    evidence_density: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[
        Annotated[str, Field(max_length=PAPER_RESEARCH_MAP_WARNING_LIMIT[1])]
    ] = Field(default_factory=list, max_length=PAPER_RESEARCH_MAP_WARNING_LIMIT[0])

    @field_validator("warnings", mode="before")
    @classmethod
    def _normalize_diagnostic_warnings(cls, value: object) -> object:
        return _normalize_warnings(value)
