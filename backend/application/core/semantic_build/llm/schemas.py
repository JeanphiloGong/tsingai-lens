from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ClaimScope = Literal[
    "current_work",
    "prior_work",
    "literature_summary",
    "review_summary",
    "unclear",
]

_METHOD_FACT_METHOD_ROLES = {"process", "characterization", "test"}
_TEXT_WINDOW_METHOD_ROLES = _METHOD_FACT_METHOD_ROLES | {"other"}
_TEXT_WINDOW_CONDITION_TYPES = {
    "temperature",
    "duration",
    "atmosphere",
    "rate",
    "frequency",
    "location",
    "direction",
    "other",
}
_TEXT_WINDOW_BASELINE_TYPES = {
    "control",
    "untreated",
    "as-built",
    "reference",
    "without-treatment",
    "other",
}
_CLAIM_SCOPES = {
    "current_work",
    "prior_work",
    "literature_summary",
    "review_summary",
    "unclear",
}
_EVIDENCE_SOURCE_TYPES = {"text", "method", "table", "figure"}
_VALUE_ORIGINS = {"reported", "derived", "estimated"}
_PAPER_SKIM_DOC_ROLES = {
    "experimental",
    "review",
    "modeling",
    "mixed",
    "uncertain",
}
_PAPER_SKIM_EVIDENCE_DENSITIES = {"high", "medium", "low", "unknown"}
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
_OBJECTIVE_SOURCE_KINDS = {"text_window", "table", "figure"}
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
_OBJECTIVE_EVIDENCE_UNIT_KINDS = {
    "measurement",
    "test_condition",
    "sample_context",
    "process_context",
    "characterization",
    "baseline_reference",
    "comparison",
    "interpretation",
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


def _normalize_literal_choice(value: object, *, allowed: set[str], default: str) -> str:
    lowered = str(value or "").strip().lower()
    return lowered if lowered in allowed else default


def _normalize_hyphenated_choice(value: object, *, allowed: set[str], default: str) -> str:
    lowered = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    return lowered if lowered in allowed else default


def _normalize_underscored_choice(value: object, *, allowed: set[str], default: str) -> str:
    lowered = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return lowered if lowered in allowed else default


def _normalize_optional_underscored_choice(
    value: object,
    *,
    allowed: set[str],
) -> str | None:
    lowered = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return lowered if lowered in allowed else None


def _normalize_list_container(value: object) -> object:
    return [] if value is None else value


def _normalize_object_container(value: object) -> object:
    return {} if value is None else value


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


class MaterialSystemPayload(_StrictModel):
    family: str | None = None
    composition: str | None = None


class ProcessContextPayload(_StrictModel):
    temperatures_c: list[float] = Field(default_factory=list)
    durations: list[str] = Field(default_factory=list)
    atmosphere: str | None = None
    laser_power_w: float | None = None
    scan_speed_mm_s: float | None = None
    layer_thickness_um: float | None = None
    hatch_spacing_um: float | None = None
    spot_size_um: float | None = None
    energy_density_j_mm3: float | None = None
    energy_density_origin: Literal["reported", "derived", "estimated"] | None = None
    scan_strategy: str | None = None
    build_orientation: str | None = None
    preheat_temperature_c: float | None = None
    shielding_gas: str | None = None
    oxygen_level_ppm: float | None = None
    powder_size_distribution_um: str | list[float] | None = None
    post_treatment_summary: str | None = None

    @field_validator("temperatures_c", "durations", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)

    @field_validator("energy_density_origin", mode="before")
    @classmethod
    def _normalize_energy_density_origin(cls, value: object) -> str | None:
        return _normalize_optional_underscored_choice(
            value,
            allowed=_VALUE_ORIGINS,
        )


class BaselineContextPayload(_StrictModel):
    control: str | None = None


class TestContextPayload(_StrictModel):
    methods: list[str] = Field(default_factory=list)
    method: str | None = None

    @field_validator("methods", mode="before")
    @classmethod
    def _normalize_methods(cls, value: object) -> object:
        return _normalize_list_container(value)


class ConditionContextPayload(_StrictModel):
    process: ProcessContextPayload = Field(default_factory=ProcessContextPayload)
    baseline: BaselineContextPayload = Field(default_factory=BaselineContextPayload)
    test: TestContextPayload = Field(default_factory=TestContextPayload)

    @field_validator("process", "baseline", "test", mode="before")
    @classmethod
    def _normalize_nested_objects(cls, value: object) -> object:
        return _normalize_object_container(value)


class EvidenceAnchorPayload(_StrictModel):
    quote: str | None = None
    source_type: Literal["text", "method", "table", "figure"] = "text"
    page: int | None = None

    @field_validator("source_type", mode="before")
    @classmethod
    def _normalize_source_type(cls, value: object) -> str:
        lowered = str(value or "").strip().lower()
        if lowered in {"row", "cell"}:
            return "table"
        if lowered in {"text_window", "paragraph", "snippet"}:
            return "text"
        if lowered == "fig":
            return "figure"
        return lowered if lowered in _EVIDENCE_SOURCE_TYPES else "text"


class MethodPayloadModel(_StrictModel):
    temperatures_c: list[float] = Field(default_factory=list)
    durations: list[str] = Field(default_factory=list)
    atmosphere: str | None = None
    methods: list[str] = Field(default_factory=list)
    details: str | None = None
    laser_power_w: float | None = None
    scan_speed_mm_s: float | None = None
    layer_thickness_um: float | None = None
    hatch_spacing_um: float | None = None
    spot_size_um: float | None = None
    energy_density_j_mm3: float | None = None
    energy_density_origin: Literal["reported", "derived", "estimated"] | None = None
    scan_strategy: str | None = None
    build_orientation: str | None = None
    preheat_temperature_c: float | None = None
    shielding_gas: str | None = None
    oxygen_level_ppm: float | None = None
    powder_size_distribution_um: str | list[float] | None = None
    post_treatment_summary: str | None = None

    @field_validator("temperatures_c", "durations", "methods", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)

    @field_validator("energy_density_origin", mode="before")
    @classmethod
    def _normalize_energy_density_origin(cls, value: object) -> str | None:
        return _normalize_optional_underscored_choice(
            value,
            allowed=_VALUE_ORIGINS,
        )


class MethodFactPayload(_StrictModel):
    method_role: Literal["process", "characterization", "test"] = "process"
    method_name: str
    method_payload: MethodPayloadModel = Field(default_factory=MethodPayloadModel)
    anchors: list[EvidenceAnchorPayload] = Field(default_factory=list)
    confidence: float = 0.85
    epistemic_status: str = "normalized_from_evidence"

    @field_validator("method_role", mode="before")
    @classmethod
    def _normalize_method_role(cls, value: object) -> str:
        return _normalize_literal_choice(
            value,
            allowed=_METHOD_FACT_METHOD_ROLES,
            default="process",
        )

    @field_validator("method_payload", mode="before")
    @classmethod
    def _normalize_method_payload(cls, value: object) -> object:
        return _normalize_object_container(value)

    @field_validator("anchors", mode="before")
    @classmethod
    def _normalize_anchors(cls, value: object) -> object:
        return _normalize_list_container(value)


class SampleVariantPayload(_StrictModel):
    variant_label: str
    host_material_system: MaterialSystemPayload | None = None
    composition: str | None = None
    variable_axis_type: str | None = None
    variable_value: str | int | float | None = None
    process_context: ProcessContextPayload = Field(default_factory=ProcessContextPayload)
    confidence: float = 0.85
    epistemic_status: str = "normalized_from_evidence"
    source_kind: Literal["text_window", "table_row"] = "text_window"

    @field_validator("process_context", mode="before")
    @classmethod
    def _normalize_process_context(cls, value: object) -> object:
        return _normalize_object_container(value)


class TestConditionPayloadModel(_StrictModel):
    method: str | None = None
    methods: list[str] = Field(default_factory=list)
    temperatures_c: list[float] = Field(default_factory=list)
    durations: list[str] = Field(default_factory=list)
    atmosphere: str | None = None
    test_method: str | None = None
    test_temperature_c: float | None = None
    strain_rate_s_1: float | str | None = Field(default=None, alias="strain_rate_s-1")
    loading_direction: str | None = None
    sample_orientation: str | None = None
    environment: str | None = None
    frequency_hz: float | None = None
    specimen_geometry: str | None = None
    surface_state: str | None = None
    standard: str | None = None
    instrument: str | None = None
    load: str | None = None
    holding_time: str | None = None
    readings_per_sample: str | None = None
    section_orientation: str | None = None
    magnification: str | None = None
    details: str | None = None

    @field_validator("methods", "temperatures_c", "durations", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)


class ExtractedTestConditionPayload(_StrictModel):
    property_type: str
    condition_payload: TestConditionPayloadModel = Field(default_factory=TestConditionPayloadModel)
    confidence: float = 0.85
    epistemic_status: str = "normalized_from_evidence"

    @field_validator("condition_payload", mode="before")
    @classmethod
    def _normalize_condition_payload(cls, value: object) -> object:
        return _normalize_object_container(value)


class BaselineReferencePayload(_StrictModel):
    baseline_label: str
    confidence: float = 0.85
    epistemic_status: str = "normalized_from_evidence"


class MeasurementValuePayload(_StrictModel):
    value: float | None = None
    min: float | None = None
    max: float | None = None
    retention_percent: float | None = None
    direction: str | None = None
    statement: str | None = None
    value_origin: Literal["reported", "derived", "estimated"] | None = None
    source_value_text: str | None = None
    source_unit_text: str | None = None
    derivation_formula: str | None = None
    derivation_inputs: dict[str, Any] | None = None

    @field_validator("value_origin", mode="before")
    @classmethod
    def _normalize_value_origin(cls, value: object) -> str | None:
        return _normalize_optional_underscored_choice(
            value,
            allowed=_VALUE_ORIGINS,
        )


class MeasurementResultPayload(_StrictModel):
    claim_text: str
    property_normalized: str
    result_type: str
    value_payload: MeasurementValuePayload = Field(default_factory=MeasurementValuePayload)
    unit: str | None = None
    variant_label: str | None = None
    baseline_label: str | None = None
    anchors: list[EvidenceAnchorPayload] = Field(default_factory=list)
    claim_scope: ClaimScope = "current_work"
    confidence: float = 0.85

    @field_validator("claim_scope", mode="before")
    @classmethod
    def _normalize_claim_scope(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_CLAIM_SCOPES,
            default="unclear",
        )

    @field_validator("value_payload", mode="before")
    @classmethod
    def _normalize_value_payload(cls, value: object) -> object:
        return _normalize_object_container(value)

    @field_validator("anchors", mode="before")
    @classmethod
    def _normalize_anchors(cls, value: object) -> object:
        return _normalize_list_container(value)


class TextWindowMethodMentionPayload(_StrictModel):
    method_role: Literal["process", "characterization", "test", "other"] = "process"
    method_name: str
    details: str | None = None
    evidence_quote: str
    confidence: float = 0.85

    @field_validator("method_role", mode="before")
    @classmethod
    def _normalize_method_role(cls, value: object) -> str:
        return _normalize_literal_choice(
            value,
            allowed=_TEXT_WINDOW_METHOD_ROLES,
            default="other",
        )


class TextWindowMaterialMentionPayload(_StrictModel):
    material_label: str
    family: str | None = None
    composition: str | None = None
    evidence_quote: str
    confidence: float = 0.85


class TextWindowVariantMentionPayload(_StrictModel):
    variant_label: str
    variable_axis_type: str | None = None
    variable_value: str | int | float | None = None
    evidence_quote: str
    confidence: float = 0.85


class TextWindowConditionMentionPayload(_StrictModel):
    condition_type: Literal[
        "temperature",
        "duration",
        "atmosphere",
        "rate",
        "frequency",
        "location",
        "direction",
        "other",
    ] = "other"
    condition_text: str
    normalized_value: str | int | float | None = None
    unit: str | None = None
    evidence_quote: str
    confidence: float = 0.85

    @field_validator("condition_type", mode="before")
    @classmethod
    def _normalize_condition_type(cls, value: object) -> str:
        return _normalize_literal_choice(
            value,
            allowed=_TEXT_WINDOW_CONDITION_TYPES,
            default="other",
        )


class TextWindowBaselineMentionPayload(_StrictModel):
    baseline_label: str
    baseline_type: Literal[
        "control",
        "untreated",
        "as-built",
        "reference",
        "without-treatment",
        "other",
    ] = "other"
    evidence_quote: str
    confidence: float = 0.85

    @field_validator("baseline_type", mode="before")
    @classmethod
    def _normalize_baseline_type(cls, value: object) -> str:
        return _normalize_hyphenated_choice(
            value,
            allowed=_TEXT_WINDOW_BASELINE_TYPES,
            default="other",
        )


class TextWindowResultClaimPayload(_StrictModel):
    claim_text: str
    property_normalized: str
    result_type: str
    value_text: str | None = None
    unit: str | None = None
    claim_scope: ClaimScope = "unclear"
    eligible_for_measurement_result: bool = False
    evidence_quote: str
    confidence: float = 0.85

    @field_validator("claim_scope", mode="before")
    @classmethod
    def _normalize_claim_scope(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_CLAIM_SCOPES,
            default="unclear",
        )

    @field_validator("property_normalized", mode="before")
    @classmethod
    def _normalize_property_normalized(cls, value: object) -> str:
        return str(value or "").strip()


class StructuredTextWindowMentions(_StrictModel):
    method_mentions: list[TextWindowMethodMentionPayload] = Field(default_factory=list)
    material_mentions: list[TextWindowMaterialMentionPayload] = Field(default_factory=list)
    variant_mentions: list[TextWindowVariantMentionPayload] = Field(default_factory=list)
    condition_mentions: list[TextWindowConditionMentionPayload] = Field(default_factory=list)
    baseline_mentions: list[TextWindowBaselineMentionPayload] = Field(default_factory=list)
    result_claims: list[TextWindowResultClaimPayload] = Field(default_factory=list)

    @field_validator(
        "method_mentions",
        "material_mentions",
        "variant_mentions",
        "condition_mentions",
        "baseline_mentions",
        "result_claims",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)


class TableRowSubjectMentionPayload(_StrictModel):
    variant_label: str
    family: str | None = None
    composition: str | None = None
    variable_axis_type: str | None = None
    variable_value: str | int | float | None = None
    quote: str | None = None


class TableRowFactMentionPayload(_StrictModel):
    name: str
    value_text: str | int | float | None = None
    unit: str | None = None
    quote: str | None = None


class TableRowBaselineMentionPayload(_StrictModel):
    baseline_label: str
    quote: str | None = None


class TableRowResultClaimPayload(_StrictModel):
    property_normalized: str
    result_type: str = "scalar"
    value_text: str | int | float | None = None
    unit: str | None = None
    variant_label: str | None = None
    baseline_label: str | None = None
    claim_scope: ClaimScope = "current_work"
    claim_text: str | None = None
    quote: str | None = None

    @field_validator("claim_scope", mode="before")
    @classmethod
    def _normalize_claim_scope(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_CLAIM_SCOPES,
            default="unclear",
        )

    @field_validator("property_normalized", mode="before")
    @classmethod
    def _normalize_property_normalized(cls, value: object) -> str:
        return str(value or "").strip()


class StructuredTableRowMentions(_StrictModel):
    row_subjects: list[TableRowSubjectMentionPayload] = Field(default_factory=list)
    process_mentions: list[TableRowFactMentionPayload] = Field(default_factory=list)
    test_condition_mentions: list[TableRowFactMentionPayload] = Field(default_factory=list)
    baseline_mentions: list[TableRowBaselineMentionPayload] = Field(default_factory=list)
    result_claims: list[TableRowResultClaimPayload] = Field(default_factory=list)

    @field_validator(
        "row_subjects",
        "process_mentions",
        "test_condition_mentions",
        "baseline_mentions",
        "result_claims",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredTableBatchRowMentions(StructuredTableRowMentions):
    row_index: int


class StructuredTableBatchMentions(_StrictModel):
    row_results: list[StructuredTableBatchRowMentions] = Field(default_factory=list)

    @field_validator("row_results", mode="before")
    @classmethod
    def _normalize_row_results(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredPaperSkim(_StrictModel):
    doc_role: Literal["experimental", "review", "modeling", "mixed", "uncertain"] = (
        "uncertain"
    )
    candidate_materials: list[str] = Field(default_factory=list)
    candidate_processes: list[str] = Field(default_factory=list)
    candidate_properties: list[str] = Field(default_factory=list)
    changed_variables: list[str] = Field(default_factory=list)
    possible_objectives: list[str] = Field(default_factory=list)
    evidence_density: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)

    @field_validator(
        "candidate_materials",
        "candidate_processes",
        "candidate_properties",
        "changed_variables",
        "possible_objectives",
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


class StructuredResearchObjective(_StrictModel):
    question: str
    material_scope: list[str] = Field(default_factory=list)
    process_axes: list[str] = Field(default_factory=list)
    property_axes: list[str] = Field(default_factory=list)
    comparison_intent: str | None = None
    seed_document_ids: list[str] = Field(default_factory=list)
    excluded_document_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    reason: str | None = None

    @field_validator(
        "material_scope",
        "process_axes",
        "property_axes",
        "seed_document_ids",
        "excluded_document_ids",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredResearchObjectives(_StrictModel):
    objectives: list[StructuredResearchObjective] = Field(default_factory=list)

    @field_validator("objectives", mode="before")
    @classmethod
    def _normalize_objectives(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredAxisCanonicalizationGroup(_StrictModel):
    axis_type: Literal["material", "process", "property"]
    canonical: str
    aliases: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    reason: str

    @field_validator("aliases", mode="before")
    @classmethod
    def _normalize_aliases(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredAxisCanonicalizationPlan(_StrictModel):
    axis_groups: list[StructuredAxisCanonicalizationGroup] = Field(
        default_factory=list
    )

    @field_validator("axis_groups", mode="before")
    @classmethod
    def _normalize_axis_groups(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredObjectiveMergeGroup(_StrictModel):
    source_objective_ids: list[str] = Field(default_factory=list)
    question: str
    material_scope: list[str] = Field(default_factory=list)
    process_axes: list[str] = Field(default_factory=list)
    property_axes: list[str] = Field(default_factory=list)
    comparison_intent: str
    confidence: float = 0.0
    reason: str

    @field_validator(
        "source_objective_ids",
        "material_scope",
        "process_axes",
        "property_axes",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredObjectivePaperFrame(_StrictModel):
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
    background: str | None = None
    material_match: list[str] = Field(default_factory=list)
    changed_variables: list[str] = Field(default_factory=list)
    measured_property_scope: list[str] = Field(default_factory=list)
    test_environment_scope: list[str] = Field(default_factory=list)
    relevant_sections: list[str] = Field(default_factory=list)
    relevant_tables: list[str] = Field(default_factory=list)
    excluded_tables: list[str] = Field(default_factory=list)

    @field_validator(
        "material_match",
        "changed_variables",
        "measured_property_scope",
        "test_environment_scope",
        "relevant_sections",
        "relevant_tables",
        "excluded_tables",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)

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


class StructuredObjectiveEvidenceRoute(_StrictModel):
    source_kind: Literal["text_window", "table", "figure"] = "text_window"
    source_ref: str
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
    reason: str | None = None
    table_schema: dict[str, Any] = Field(default_factory=dict)
    column_roles: dict[str, Any] = Field(default_factory=dict)
    join_keys: dict[str, Any] = Field(default_factory=dict)
    join_plan: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0

    @field_validator("source_kind", mode="before")
    @classmethod
    def _normalize_source_kind(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_SOURCE_KINDS,
            default="text_window",
        )

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_ROUTE_ROLES,
            default="low_value_or_irrelevant",
        )

    @field_validator("table_schema", "column_roles", "join_keys", "join_plan", mode="before")
    @classmethod
    def _normalize_objects(cls, value: object) -> object:
        return _normalize_object_container(value)


class StructuredObjectiveEvidenceRoutes(_StrictModel):
    routes: list[StructuredObjectiveEvidenceRoute] = Field(default_factory=list)

    @field_validator("routes", mode="before")
    @classmethod
    def _normalize_routes(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredObjectiveEvidenceUnit(_StrictModel):
    unit_kind: Literal[
        "measurement",
        "test_condition",
        "sample_context",
        "process_context",
        "characterization",
        "baseline_reference",
        "comparison",
        "interpretation",
        "mixed",
        "unknown",
    ] = "unknown"
    property_normalized: str | None = None
    material_system: dict[str, Any] = Field(default_factory=dict)
    sample_context: dict[str, Any] = Field(default_factory=dict)
    process_context: dict[str, Any] = Field(default_factory=dict)
    resolved_condition: dict[str, Any] = Field(default_factory=dict)
    test_condition: dict[str, Any] = Field(default_factory=dict)
    value_payload: dict[str, Any] = Field(default_factory=dict)
    unit: str | None = None
    baseline_context: dict[str, Any] = Field(default_factory=dict)
    interpretation: str | None = None
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    evidence_anchor_ids: list[str] = Field(default_factory=list)
    join_keys: dict[str, Any] = Field(default_factory=dict)
    resolution_status: Literal[
        "resolved",
        "partial",
        "unresolved",
        "skipped",
        "unknown",
    ] = "partial"
    confidence: float = 0.0

    @field_validator("unit_kind", mode="before")
    @classmethod
    def _normalize_unit_kind(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_UNIT_KINDS,
            default="unknown",
        )

    @field_validator("resolution_status", mode="before")
    @classmethod
    def _normalize_resolution_status(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_RESOLUTION_STATUSES,
            default="partial",
        )

    @field_validator(
        "material_system",
        "sample_context",
        "process_context",
        "resolved_condition",
        "test_condition",
        "value_payload",
        "baseline_context",
        "join_keys",
        mode="before",
    )
    @classmethod
    def _normalize_objects(cls, value: object) -> object:
        return _normalize_object_container(value)

    @field_validator("source_refs", "evidence_anchor_ids", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredObjectiveEvidenceUnits(_StrictModel):
    evidence_units: list[StructuredObjectiveEvidenceUnit] = Field(default_factory=list)

    @field_validator("evidence_units", mode="before")
    @classmethod
    def _normalize_evidence_units(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredObjectiveMergePlan(_StrictModel):
    merged_objectives: list[StructuredObjectiveMergeGroup] = Field(default_factory=list)

    @field_validator("merged_objectives", mode="before")
    @classmethod
    def _normalize_merged_objectives(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredExtractionBundle(_StrictModel):
    method_facts: list[MethodFactPayload] = Field(default_factory=list)
    sample_variants: list[SampleVariantPayload] = Field(default_factory=list)
    test_conditions: list[ExtractedTestConditionPayload] = Field(default_factory=list)
    baseline_references: list[BaselineReferencePayload] = Field(default_factory=list)
    measurement_results: list[MeasurementResultPayload] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _drop_misplaced_nested_payloads(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        misplaced_nested_keys = {
            "method_payload",
            "process_context",
            "condition_payload",
            "value_payload",
        }
        if not misplaced_nested_keys.intersection(value):
            return value
        return {
            key: item
            for key, item in value.items()
            if key not in misplaced_nested_keys
        }

    @field_validator(
        "method_facts",
        "sample_variants",
        "test_conditions",
        "baseline_references",
        "measurement_results",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredDocumentProfile(_StrictModel):
    doc_type: Literal["experimental", "review", "mixed", "uncertain"] = "uncertain"
    parsing_warnings: list[
        Literal["insufficient_content", "classification_uncertain"]
    ] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
