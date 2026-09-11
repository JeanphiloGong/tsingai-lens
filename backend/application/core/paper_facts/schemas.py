from __future__ import annotations

from collections.abc import Collection
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

ClaimScope = Literal[
    "current_work",
    "prior_work",
    "literature_summary",
    "review_summary",
    "unclear",
]

# These vocabularies describe the wire format accepted from the model. They
# are kept next to the validators so the normalization policy is visible at
# the model boundary, rather than being mistaken for domain enums.
_METHOD_FACT_METHOD_ROLES = frozenset({"process", "characterization", "test"})
_TEXT_WINDOW_METHOD_ROLES = _METHOD_FACT_METHOD_ROLES | {"other"}
_TEXT_WINDOW_CONDITION_TYPES = frozenset({
    "temperature",
    "duration",
    "atmosphere",
    "rate",
    "frequency",
    "location",
    "direction",
    "other",
})
_TEXT_WINDOW_BASELINE_TYPES = frozenset({
    "control",
    "untreated",
    "as-built",
    "reference",
    "without-treatment",
    "other",
})
_CLAIM_SCOPES = frozenset({
    "current_work",
    "prior_work",
    "literature_summary",
    "review_summary",
    "unclear",
})
_EVIDENCE_SOURCE_TYPES = frozenset({"text", "method", "table", "figure"})
_VALUE_ORIGINS = frozenset({"reported", "derived", "estimated"})


def _normalize_literal_choice(
    value: object,
    *,
    allowed: Collection[str],
    default: str,
) -> str:
    lowered = str(value or "").strip().lower()
    return lowered if lowered in allowed else default


def _normalize_hyphenated_choice(
    value: object,
    *,
    allowed: Collection[str],
    default: str,
) -> str:
    lowered = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    return lowered if lowered in allowed else default


def _normalize_underscored_choice(
    value: object,
    *,
    allowed: Collection[str],
    default: str,
) -> str:
    lowered = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return lowered if lowered in allowed else default


def _normalize_optional_underscored_choice(
    value: object,
    *,
    allowed: Collection[str],
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


class MaterialSystemModelOutput(_StrictModel):
    family: str | None = None
    composition: str | None = None


class ProcessContextModelOutput(_StrictModel):
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


class BaselineContextModelOutput(_StrictModel):
    control: str | None = None


class TestContextModelOutput(_StrictModel):
    methods: list[str] = Field(default_factory=list)
    method: str | None = None

    @field_validator("methods", mode="before")
    @classmethod
    def _normalize_methods(cls, value: object) -> object:
        return _normalize_list_container(value)


class ConditionContextModelOutput(_StrictModel):
    process: ProcessContextModelOutput = Field(default_factory=ProcessContextModelOutput)
    baseline: BaselineContextModelOutput = Field(default_factory=BaselineContextModelOutput)
    test: TestContextModelOutput = Field(default_factory=TestContextModelOutput)

    @field_validator("process", "baseline", "test", mode="before")
    @classmethod
    def _normalize_nested_objects(cls, value: object) -> object:
        return _normalize_object_container(value)


class EvidenceAnchorModelOutput(_StrictModel):
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


class MethodModelOutput(_StrictModel):
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


class MethodFactModelOutput(_StrictModel):
    method_role: Literal["process", "characterization", "test"] = "process"
    method_name: str
    method_payload: MethodModelOutput = Field(default_factory=MethodModelOutput)
    anchors: list[EvidenceAnchorModelOutput] = Field(default_factory=list)
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


class SampleVariantModelOutput(_StrictModel):
    variant_label: str
    host_material_system: MaterialSystemModelOutput | None = None
    composition: str | None = None
    variable_axis_type: str | None = None
    variable_value: str | int | float | None = None
    process_context: ProcessContextModelOutput = Field(default_factory=ProcessContextModelOutput)
    confidence: float = 0.85
    epistemic_status: str = "normalized_from_evidence"
    source_kind: Literal["text_window", "table_row"] = "text_window"

    @field_validator("process_context", mode="before")
    @classmethod
    def _normalize_process_context(cls, value: object) -> object:
        return _normalize_object_container(value)


class TestConditionModelOutput(_StrictModel):
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


class ExtractedTestConditionModelOutput(_StrictModel):
    property_type: str
    condition_payload: TestConditionModelOutput = Field(default_factory=TestConditionModelOutput)
    confidence: float = 0.85
    epistemic_status: str = "normalized_from_evidence"

    @field_validator("condition_payload", mode="before")
    @classmethod
    def _normalize_condition_payload(cls, value: object) -> object:
        return _normalize_object_container(value)


class BaselineReferenceModelOutput(_StrictModel):
    baseline_label: str
    confidence: float = 0.85
    epistemic_status: str = "normalized_from_evidence"


class MeasurementValueModelOutput(_StrictModel):
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


class MeasurementResultModelOutput(_StrictModel):
    claim_text: str
    property_normalized: str
    result_type: str
    value_payload: MeasurementValueModelOutput = Field(default_factory=MeasurementValueModelOutput)
    unit: str | None = None
    variant_label: str | None = None
    baseline_label: str | None = None
    anchors: list[EvidenceAnchorModelOutput] = Field(default_factory=list)
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


class TextWindowMethodMentionModelOutput(_StrictModel):
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


class TextWindowMaterialMentionModelOutput(_StrictModel):
    material_label: str
    family: str | None = None
    composition: str | None = None
    evidence_quote: str
    confidence: float = 0.85


class TextWindowVariantMentionModelOutput(_StrictModel):
    variant_label: str
    variable_axis_type: str | None = None
    variable_value: str | int | float | None = None
    evidence_quote: str
    confidence: float = 0.85


class TextWindowConditionMentionModelOutput(_StrictModel):
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


class TextWindowBaselineMentionModelOutput(_StrictModel):
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


class TextWindowResultClaimModelOutput(_StrictModel):
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


class TextWindowMentionsModelOutput(_StrictModel):
    method_mentions: list[TextWindowMethodMentionModelOutput] = Field(default_factory=list)
    material_mentions: list[TextWindowMaterialMentionModelOutput] = Field(default_factory=list)
    variant_mentions: list[TextWindowVariantMentionModelOutput] = Field(default_factory=list)
    condition_mentions: list[TextWindowConditionMentionModelOutput] = Field(default_factory=list)
    baseline_mentions: list[TextWindowBaselineMentionModelOutput] = Field(default_factory=list)
    result_claims: list[TextWindowResultClaimModelOutput] = Field(default_factory=list)

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


class TableRowSubjectMentionModelOutput(_StrictModel):
    variant_label: str
    family: str | None = None
    composition: str | None = None
    variable_axis_type: str | None = None
    variable_value: str | int | float | None = None
    quote: str | None = None


class TableRowFactMentionModelOutput(_StrictModel):
    name: str
    value_text: str | int | float | None = None
    unit: str | None = None
    quote: str | None = None


class TableRowBaselineMentionModelOutput(_StrictModel):
    baseline_label: str
    quote: str | None = None


class TableRowResultClaimModelOutput(_StrictModel):
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


class TableRowMentionsModelOutput(_StrictModel):
    row_subjects: list[TableRowSubjectMentionModelOutput] = Field(default_factory=list)
    process_mentions: list[TableRowFactMentionModelOutput] = Field(default_factory=list)
    test_condition_mentions: list[TableRowFactMentionModelOutput] = Field(default_factory=list)
    baseline_mentions: list[TableRowBaselineMentionModelOutput] = Field(default_factory=list)
    result_claims: list[TableRowResultClaimModelOutput] = Field(default_factory=list)

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


class TableBatchRowMentionsModelOutput(TableRowMentionsModelOutput):
    row_index: int


class TableBatchMentionsModelOutput(_StrictModel):
    row_results: list[TableBatchRowMentionsModelOutput] = Field(default_factory=list)

    @field_validator("row_results", mode="before")
    @classmethod
    def _normalize_row_results(cls, value: object) -> object:
        return _normalize_list_container(value)


class TableMatrixRepairItemModelOutput(_StrictModel):
    row_index: int | None = None
    column: str | None = None
    before: str | None = None
    after: str | None = None
    reason: str | None = None


class TableMatrixRepairModelOutput(_StrictModel):
    repaired_table_matrix: list[list[str]] = Field(default_factory=list)
    repairs: list[TableMatrixRepairItemModelOutput] = Field(default_factory=list)
    confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)

    @field_validator("repaired_table_matrix", mode="before")
    @classmethod
    def _normalize_repaired_table_matrix(cls, value: object) -> object:
        return _normalize_list_container(value)

    @field_validator("repairs", "warnings", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)



class ExtractionBundleModelOutput(_StrictModel):
    method_facts: list[MethodFactModelOutput] = Field(default_factory=list)
    sample_variants: list[SampleVariantModelOutput] = Field(default_factory=list)
    test_conditions: list[ExtractedTestConditionModelOutput] = Field(default_factory=list)
    baseline_references: list[BaselineReferenceModelOutput] = Field(default_factory=list)
    measurement_results: list[MeasurementResultModelOutput] = Field(default_factory=list)

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
