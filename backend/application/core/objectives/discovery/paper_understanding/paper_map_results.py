from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .common import (
    PAPER_RESEARCH_MAP_RELATIONSHIP_LIMIT,
    PAPER_RESEARCH_MAP_SCOPE_LIMIT,
    PAPER_RESEARCH_MAP_UNRESOLVED_SIGNAL_LIMIT,
    PAPER_RESEARCH_MAP_WARNING_LIMIT,
    _PAPER_MAP_CONTEXT_LIMIT,
    _REVIEW_CITATION_LEAD_LIMIT,
    _REVIEW_KNOWLEDGE_ITEM_LIMIT,
    _PaperResearchMapResponse,
    _STUDY_CONTEXT_VALUE_CHARS,
    _VARIED_FACTOR_LIMIT,
    _normalize_list,
    _normalize_warnings,
)
from .normalization import _downgrade_unresolved_relationships


class StructuredPaperResearchRelationship(_PaperResearchMapResponse):
    varied_factors: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(min_length=1, max_length=_VARIED_FACTOR_LIMIT)
    outcome: Annotated[str, Field(min_length=1, max_length=80)]
    source_unit_ids: list[
        Annotated[str, Field(min_length=1, max_length=160)]
    ] = Field(min_length=1)
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
    ] = Field(default_factory=list, max_length=_PAPER_MAP_CONTEXT_LIMIT)
    process_context: list[
        Annotated[str, Field(max_length=_STUDY_CONTEXT_VALUE_CHARS)]
    ] = Field(default_factory=list, max_length=_PAPER_MAP_CONTEXT_LIMIT)
    source_unit_ids: list[
        Annotated[str, Field(min_length=1, max_length=160)]
    ] = Field(min_length=1)
    confidence: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def _default_persisted_variable_role(cls, value: object) -> object:
        if not isinstance(value, Mapping) or value.get("variable_role") is not None:
            return value
        normalized = dict(value)
        normalized["variable_role"] = (
            "not_applicable"
            if str(value.get("signal_type") or "").strip() == "outcome"
            else "uncertain"
        )
        return normalized

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
        if self.signal_type == "variable" and self.variable_role == "not_applicable":
            raise ValueError("variable signal requires a scientific variable role")
        if self.signal_type == "outcome" and self.variable_role != "not_applicable":
            raise ValueError("outcome signal variable role must be not_applicable")
        return self


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
        return _downgrade_unresolved_relationships(value)

    @field_validator("studies", "unresolved_signals", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list(value)

    @field_validator("warnings", mode="before")
    @classmethod
    def _normalize_warnings(cls, value: object) -> object:
        return _normalize_warnings(value)

    @model_validator(mode="after")
    def _validate_study_identities(self) -> StructuredPaperResearchMap:
        study_identities = [study.identity_key() for study in self.studies]
        if len(study_identities) != len(set(study_identities)):
            raise ValueError("studies contain duplicate study identities")
        return self
