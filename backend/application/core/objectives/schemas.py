from __future__ import annotations

import json
from typing import Annotated, Literal, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

_PAPER_SKIM_DOC_ROLES = {
    "experimental",
    "review",
    "modeling",
    "mixed",
    "uncertain",
}
_PAPER_SKIM_EVIDENCE_DENSITIES = {"high", "medium", "low", "unknown"}
PAPER_OBJECTIVE_CANDIDATE_OUTPUT_LIMITS = {
    "material_scope": (8, 80),
    "process_context": (4, 80),
    "variables": (4, 80),
    "outcomes": (8, 80),
}
PAPER_SKIM_WARNING_LIMIT = (2, 240)
PAPER_SKIM_STUDY_LIMIT = 8
PAPER_SKIM_RELATIONSHIP_LIMIT = 8
PAPER_SKIM_UNRESOLVED_SIGNAL_LIMIT = 12
_OBJECTIVE_FRAME_RELEVANCE = {"high", "medium", "low", "irrelevant", "uncertain"}
_OBJECTIVE_FRAME_PAPER_ROLES = {
    "primary_experiment",
    "supporting_method",
    "supporting_background",
    "review",
    "modeling_only",
    "irrelevant",
    "mixed",
    "uncertain",
}
_OBJECTIVE_EVIDENCE_ROUTE_ROLES = {
    "current_experimental_evidence",
    "process_or_treatment",
    "test_condition",
    "composition_or_background",
    "characterization",
    "literature_comparison",
    "modeling_or_prediction",
    "low_value_or_irrelevant",
}
_OBJECTIVE_EVIDENCE_ROLES = {
    "direct_result",
    "condition_context",
    "mechanism_context",
    "baseline_context",
    "comparison_context",
    "background_context",
    "contradictory_result",
    "irrelevant",
}
_OBJECTIVE_EVIDENCE_ATTRIBUTION_SCOPES = {
    "isolated_effect",
    "joint_effect",
    "association_only",
    "descriptive_only",
    "not_attributable",
}
_OBJECTIVE_EVIDENCE_RESULT_DIRECTIONS = {
    "increase",
    "decrease",
    "improve",
    "worsen",
    "no_change",
    "mixed",
    "unknown",
}
_OBJECTIVE_EVIDENCE_RESOLUTION_STATUSES = {
    "resolved",
    "partial",
    "unresolved",
    "skipped",
    "unknown",
}
_FINDING_DIRECTIONS = {
    "increase",
    "decrease",
    "improve",
    "worsen",
    "no_change",
    "mixed",
    "unknown",
}
_FINDING_ASSERTION_STRENGTHS = {"causal", "associative", "descriptive"}


def _normalize_underscored_choice(value: object, *, allowed: set[str], default: str) -> str:
    lowered = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return lowered if lowered in allowed else default


def _normalize_list_container(value: object) -> object:
    return [] if value is None else value


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("confidence", mode="before", check_fields=False)
    @classmethod
    def _normalize_default_confidence(cls, value: object) -> object:
        if value is not None:
            return value
        return cls.model_fields["confidence"].get_default(call_default_factory=True)

    @field_validator("epistemic_status", mode="before", check_fields=False)
    @classmethod
    def _normalize_default_epistemic_status(cls, value: object) -> object:
        if value is not None:
            return value
        return cls.model_fields["epistemic_status"].get_default(
            call_default_factory=True
        )


class StructuredPaperStudyRelationship(_StrictModel):
    varied_factors: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(min_length=1, max_length=8)
    outcome: Annotated[str, Field(min_length=1, max_length=80)]
    source_unit_ids: list[Annotated[str, Field(max_length=160)]] = Field(
        min_length=1,
        max_length=12,
    )
    confidence: float = 0.0

    @field_validator("varied_factors", "source_unit_ids", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredPaperStudy(_StrictModel):
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
    ] = Field(default_factory=list, max_length=8)
    process_context: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=4)
    sample_context: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=4)
    test_context: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=4)
    comparator: str | None = Field(default=None, max_length=160)
    fixed_conditions: list[
        Annotated[str, Field(max_length=120)]
    ] = Field(default_factory=list, max_length=12)
    relationships: list[StructuredPaperStudyRelationship] = Field(
        min_length=1,
        max_length=PAPER_SKIM_RELATIONSHIP_LIMIT,
    )
    confidence: float = 0.0

    @field_validator(
        "material_scope",
        "process_context",
        "sample_context",
        "test_context",
        "fixed_conditions",
        "relationships",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)

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
            normalized_values(self.sample_context),
            normalized_values(self.test_context),
            self.comparator.strip().casefold() if self.comparator else None,
            normalized_values(self.fixed_conditions),
            relationships,
        )


class StructuredPaperStudySignal(_StrictModel):
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
    ] = Field(default_factory=list, max_length=8)
    process_context: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=4)
    sample_context: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=4)
    test_context: list[
        Annotated[str, Field(max_length=80)]
    ] = Field(default_factory=list, max_length=4)
    comparator: str | None = Field(default=None, max_length=160)
    fixed_conditions: list[
        Annotated[str, Field(max_length=120)]
    ] = Field(default_factory=list, max_length=12)
    source_unit_ids: list[Annotated[str, Field(max_length=160)]] = Field(
        min_length=1,
        max_length=4,
    )
    confidence: float = 0.0

    @field_validator(
        "material_scope",
        "process_context",
        "sample_context",
        "test_context",
        "fixed_conditions",
        "source_unit_ids",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredPaperSkim(_StrictModel):
    doc_role: Literal["experimental", "review", "modeling", "mixed", "uncertain"] = (
        "uncertain"
    )
    studies: list[StructuredPaperStudy] = Field(
        default_factory=list,
        max_length=PAPER_SKIM_STUDY_LIMIT,
    )
    unresolved_signals: list[StructuredPaperStudySignal] = Field(
        default_factory=list,
        max_length=PAPER_SKIM_UNRESOLVED_SIGNAL_LIMIT,
    )
    output_saturated: bool = False
    evidence_density: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence: float = 0.0
    warnings: list[
        Annotated[str, Field(max_length=PAPER_SKIM_WARNING_LIMIT[1])]
    ] = Field(
        default_factory=list,
        max_length=PAPER_SKIM_WARNING_LIMIT[0],
    )

    @field_validator(
        "studies",
        "unresolved_signals",
        "warnings",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)

    @field_validator("doc_role", mode="before")
    @classmethod
    def _normalize_doc_role(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_PAPER_SKIM_DOC_ROLES,
            default="uncertain",
        )

    @field_validator("evidence_density", mode="before")
    @classmethod
    def _normalize_evidence_density(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_PAPER_SKIM_EVIDENCE_DENSITIES,
            default="unknown",
        )

    @model_validator(mode="after")
    def _validate_study_identities(self) -> "StructuredPaperSkim":
        study_identities = [study.identity_key() for study in self.studies]
        if len(study_identities) != len(set(study_identities)):
            raise ValueError("studies contain duplicate study identities")
        return self


class StructuredPaperSignalRelationship(_StrictModel):
    signal_ids: list[Annotated[str, Field(max_length=80)]] = Field(
        min_length=2,
        max_length=12,
    )
    confidence: float = 0.0

    @field_validator("signal_ids", mode="before")
    @classmethod
    def _normalize_signal_ids(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredUnresolvedPaperSignal(_StrictModel):
    signal_id: Annotated[str, Field(min_length=1, max_length=80)]
    reason: Annotated[str, Field(min_length=1, max_length=240)]


class StructuredPaperSignalStudy(_StrictModel):
    relationships: list[StructuredPaperSignalRelationship] = Field(
        min_length=1,
        max_length=11,
    )

    @field_validator("relationships", mode="before")
    @classmethod
    def _normalize_relationships(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredPaperSignalReconciliation(_StrictModel):
    studies: list[StructuredPaperSignalStudy] = Field(
        default_factory=list,
        max_length=1,
    )
    unresolved_signals: list[StructuredUnresolvedPaperSignal] = Field(
        default_factory=list,
        max_length=12,
    )

    @field_validator("studies", "unresolved_signals", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredAxisPairDecision(_StrictModel):
    pair_id: Annotated[str, Field(min_length=1, max_length=80)]
    equivalent: bool


class StructuredAxisCanonicalizationPlan(_StrictModel):
    decisions: list[StructuredAxisPairDecision] = Field(default_factory=list)

    @field_validator("decisions", mode="before")
    @classmethod
    def _normalize_decisions(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredPaperFrameBatch(_StrictModel):
    relevance: Literal["high", "medium", "low", "irrelevant", "uncertain"] = (
        "uncertain"
    )
    paper_role: Literal[
        "primary_experiment",
        "supporting_method",
        "supporting_background",
        "review",
        "modeling_only",
        "irrelevant",
        "mixed",
        "uncertain",
    ] = "uncertain"
    background: str | None = Field(default=None, max_length=320)
    material_match: list[Annotated[str, Field(max_length=120)]] = Field(
        default_factory=list,
        max_length=8,
    )
    changed_variables: list[Annotated[str, Field(max_length=120)]] = Field(
        default_factory=list,
        max_length=8,
    )
    measured_property_scope: list[Annotated[str, Field(max_length=120)]] = Field(
        default_factory=list,
        max_length=8,
    )
    test_environment_scope: list[Annotated[str, Field(max_length=160)]] = Field(
        default_factory=list,
        max_length=8,
    )
    relevant_source_unit_ids: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list,
        max_length=8,
    )
    excluded_source_unit_ids: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list,
        max_length=8,
    )

    @field_validator(
        "material_match",
        "changed_variables",
        "measured_property_scope",
        "test_environment_scope",
        "relevant_source_unit_ids",
        "excluded_source_unit_ids",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)

    @model_validator(mode="after")
    def _validate_source_partition(self) -> "StructuredPaperFrameBatch":
        relevant = self.relevant_source_unit_ids
        excluded = self.excluded_source_unit_ids
        if len(relevant) != len(set(relevant)) or len(excluded) != len(set(excluded)):
            raise ValueError("paper frame source-unit ids must be unique")
        if set(relevant) & set(excluded):
            raise ValueError("paper frame source-unit ids cannot be both relevant and excluded")
        return self

    @field_validator("relevance", mode="before")
    @classmethod
    def _normalize_relevance(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_FRAME_RELEVANCE,
            default="uncertain",
        )

    @field_validator("paper_role", mode="before")
    @classmethod
    def _normalize_paper_role(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_FRAME_PAPER_ROLES,
            default="uncertain",
        )


class StructuredEvidenceSelection(_StrictModel):
    role: Literal[
        "current_experimental_evidence",
        "process_or_treatment",
        "test_condition",
        "composition_or_background",
        "characterization",
        "literature_comparison",
        "modeling_or_prediction",
        "low_value_or_irrelevant",
    ] = "low_value_or_irrelevant"
    extractable: bool = False
    confidence: float = 0.0

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_ROUTE_ROLES,
            default="low_value_or_irrelevant",
        )


class StructuredEvidenceSelections(_StrictModel):
    selections: list[StructuredEvidenceSelection] = Field(
        default_factory=list,
        max_length=1,
    )

    @field_validator("selections", mode="before")
    @classmethod
    def _normalize_selections(cls, value: object) -> object:
        return _normalize_list_container(value)


ScientificScalar = str | int | float | bool


class StructuredEvidenceAttribute(_StrictModel):
    name: str
    value: ScientificScalar
    unit: str | None = None


class StructuredEvidenceVariable(_StrictModel):
    name: str
    baseline_value: ScientificScalar | None = None
    target_value: ScientificScalar | None = None
    unit: str | None = None


class StructuredEvidenceComparison(_StrictModel):
    baseline_label: str
    target_label: str
    axis_names: list[str] = Field(min_length=1)
    comparable: bool
    incomparability_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_comparability(self) -> "StructuredEvidenceComparison":
        if not self.comparable and not self.incomparability_reasons:
            raise ValueError("incomparable evidence requires reasons")
        if self.comparable and self.incomparability_reasons:
            raise ValueError("comparable evidence cannot have incomparability reasons")
        return self


class StructuredEvidenceResult(_StrictModel):
    outcome: str
    value: ScientificScalar | None = None
    unit: str | None = None
    direction: Literal[
        "increase",
        "decrease",
        "improve",
        "worsen",
        "no_change",
        "mixed",
        "unknown",
    ] = "unknown"
    result_text: str

    @field_validator("direction", mode="before")
    @classmethod
    def _normalize_direction(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_RESULT_DIRECTIONS,
            default="unknown",
        )


class StructuredEvidenceContext(_StrictModel):
    material: list[StructuredEvidenceAttribute] = Field(default_factory=list)
    sample: list[StructuredEvidenceAttribute] = Field(default_factory=list)
    process: list[StructuredEvidenceAttribute] = Field(default_factory=list)
    test: list[StructuredEvidenceAttribute] = Field(default_factory=list)

    @field_validator("material", "sample", "process", "test", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object, info: ValidationInfo) -> object:
        items = _normalize_list_container(value)
        if not isinstance(items, list):
            return items
        normalized_items: list[object] = []
        for item in items:
            if isinstance(item, StructuredEvidenceAttribute):
                normalized_items.append(item)
                continue
            if isinstance(item, (str, int, float, bool)):
                normalized_items.append(
                    {"name": info.field_name, "value": item, "unit": None}
                )
                continue
            if not isinstance(item, dict):
                normalized_items.append(item)
                continue

            name = str(item.get("name") or info.field_name).strip()
            unit = item.get("unit")
            if "value" in item:
                attribute_value = item["value"]
                if isinstance(attribute_value, (dict, list)):
                    attribute_value = json.dumps(
                        attribute_value,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                normalized_items.append(
                    {"name": name, "value": attribute_value, "unit": unit}
                )
                continue

            details = {
                key: detail
                for key, detail in item.items()
                if key not in {"name", "unit"}
            }
            normalized_items.append(
                {
                    "name": name if details else info.field_name,
                    "value": (
                        json.dumps(
                            details,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                        if details
                        else name
                    ),
                    "unit": unit,
                }
            )
        return normalized_items


class StructuredEvidenceExtraction(_StrictModel):
    evidence_role: Literal[
        "direct_result",
        "condition_context",
        "mechanism_context",
        "baseline_context",
        "comparison_context",
        "background_context",
        "contradictory_result",
        "irrelevant",
    ] = "irrelevant"
    changed_variables: list[StructuredEvidenceVariable] = Field(
        default_factory=list,
        max_length=12,
    )
    comparison: StructuredEvidenceComparison | None = None
    reported_result: StructuredEvidenceResult | None = None
    attribution_scope: Literal[
        "isolated_effect",
        "joint_effect",
        "association_only",
        "descriptive_only",
        "not_attributable",
    ] = "not_attributable"
    scientific_context: StructuredEvidenceContext = Field(
        default_factory=StructuredEvidenceContext
    )
    resolution_status: Literal[
        "resolved",
        "partial",
        "unresolved",
        "skipped",
        "unknown",
    ] = "partial"
    confidence: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def _normalize_attribution_cardinality(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        attribution_scope = _normalize_underscored_choice(
            value.get("attribution_scope"),
            allowed=_OBJECTIVE_EVIDENCE_ATTRIBUTION_SCOPES,
            default="not_attributable",
        )
        changed_variables = value.get("changed_variables")
        if (
            attribution_scope == "joint_effect"
            and isinstance(changed_variables, list)
            and len(changed_variables) == 1
        ):
            attribution_scope = "isolated_effect"
        if (
            attribution_scope in {"isolated_effect", "joint_effect"}
            and isinstance(changed_variables, list)
            and any(
                (
                    item.get("baseline_value") is None
                    or item.get("target_value") is None
                )
                for item in changed_variables
                if isinstance(item, dict)
            )
        ):
            attribution_scope = "association_only"
        if attribution_scope != value.get("attribution_scope"):
            return {**value, "attribution_scope": attribution_scope}
        return value

    @field_validator("evidence_role", mode="before")
    @classmethod
    def _normalize_evidence_role(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_ROLES,
            default="irrelevant",
        )

    @field_validator("attribution_scope", mode="before")
    @classmethod
    def _normalize_attribution_scope(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_ATTRIBUTION_SCOPES,
            default="not_attributable",
        )

    @field_validator("resolution_status", mode="before")
    @classmethod
    def _normalize_resolution_status(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_RESOLUTION_STATUSES,
            default="partial",
        )

    @field_validator("changed_variables", mode="before")
    @classmethod
    def _normalize_changed_variables(cls, value: object) -> object:
        return _normalize_list_container(value)

    @model_validator(mode="after")
    def _validate_scientific_contract(self) -> "StructuredEvidenceExtraction":
        result_role = self.evidence_role in {"direct_result", "contradictory_result"}
        if result_role and self.reported_result is None:
            raise ValueError("result evidence requires one reported result")
        if not result_role and self.reported_result is not None:
            raise ValueError("context evidence cannot report an experimental result")
        if not result_role and self.attribution_scope in {
            "isolated_effect",
            "joint_effect",
        }:
            raise ValueError("context evidence cannot claim experimental attribution")
        if self.comparison is not None and not self.comparison.comparable:
            if self.attribution_scope != "not_attributable":
                raise ValueError("incomparable evidence cannot be attributed")
        variable_names = [
            item.name.casefold() for item in self.changed_variables
        ]
        if len(variable_names) != len(set(variable_names)):
            raise ValueError(
                "changed variable names must be unique per extraction"
            )
        if self.attribution_scope in {"isolated_effect", "joint_effect"}:
            if self.comparison is None or not self.comparison.comparable:
                raise ValueError("experimental attribution requires comparison")
            variables = set(variable_names)
            axes = {item.casefold() for item in self.comparison.axis_names}
            if variables != axes:
                raise ValueError("comparison axes must match changed variables")
            if any(
                item.baseline_value is None or item.target_value is None
                for item in self.changed_variables
            ):
                raise ValueError(
                    "experimental attribution requires baseline and target values"
                )
            if any(
                item.baseline_value == item.target_value
                for item in self.changed_variables
            ):
                raise ValueError(
                    "experimental attribution requires changed variable values"
                )
            if self.attribution_scope == "isolated_effect" and len(variables) != 1:
                raise ValueError("isolated effect requires one changed variable")
            if self.attribution_scope == "joint_effect" and len(variables) < 2:
                raise ValueError("joint effect requires multiple changed variables")
        return self


class StructuredEvidenceExtractions(_StrictModel):
    extractions: list[StructuredEvidenceExtraction] = Field(
        default_factory=list,
        max_length=1,
    )

    @field_validator("extractions", mode="before")
    @classmethod
    def _normalize_extractions(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredFindingMechanism(_StrictModel):
    source_term: str = Field(min_length=1)
    relation_type: str = Field(min_length=1)
    target_term: str = Field(min_length=1)
    direction: str | None = None
    assertion_strength: Literal["causal", "associative", "descriptive"] = (
        "descriptive"
    )
    supporting_evidence_ids: list[str] = Field(min_length=1, max_length=16)

    @field_validator("source_term", "relation_type", "target_term")
    @classmethod
    def _require_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("finding mechanism terms cannot be blank")
        return text

    @field_validator("supporting_evidence_ids")
    @classmethod
    def _require_unique_evidence(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("finding mechanism evidence ids must be unique")
        return value

    @field_validator("assertion_strength", mode="before")
    @classmethod
    def _normalize_assertion_strength(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_FINDING_ASSERTION_STRENGTHS,
            default="descriptive",
        )


class StructuredFindingSynthesisItem(_StrictModel):
    result_set_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    direction: Literal[
        "increase",
        "decrease",
        "improve",
        "worsen",
        "no_change",
        "mixed",
        "unknown",
    ] = "unknown"
    assertion_strength: Literal["causal", "associative", "descriptive"] = (
        "descriptive"
    )
    condition_boundary_evidence_ids: list[str] = Field(
        default_factory=list, max_length=24
    )
    context_evidence_ids: list[str] = Field(default_factory=list, max_length=24)
    mechanisms: list[StructuredFindingMechanism] = Field(
        default_factory=list, max_length=8
    )

    @field_validator("direction", mode="before")
    @classmethod
    def _normalize_direction(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_FINDING_DIRECTIONS,
            default="unknown",
        )

    @field_validator("assertion_strength", mode="before")
    @classmethod
    def _normalize_assertion_strength(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_FINDING_ASSERTION_STRENGTHS,
            default="descriptive",
        )

    @field_validator(
        "condition_boundary_evidence_ids",
        "context_evidence_ids",
    )
    @classmethod
    def _require_unique_evidence(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("finding evidence ids must be unique within each role")
        return value


class StructuredFindingSynthesis(_StrictModel):
    findings: list[StructuredFindingSynthesisItem] = Field(
        default_factory=list,
        max_length=1,
    )

    @field_validator("findings", mode="before")
    @classmethod
    def _normalize_findings(cls, value: object) -> object:
        return _normalize_list_container(value)
