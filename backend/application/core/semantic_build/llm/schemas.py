from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


def _normalize_literal_choice(value: object, *, allowed: set[str], default: str) -> str:
    lowered = str(value or "").strip().lower()
    return lowered if lowered in allowed else default


def _normalize_hyphenated_choice(value: object, *, allowed: set[str], default: str) -> str:
    lowered = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    return lowered if lowered in allowed else default


def _normalize_underscored_choice(value: object, *, allowed: set[str], default: str) -> str:
    lowered = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return lowered if lowered in allowed else default


def _normalize_list_container(value: object) -> object:
    return [] if value is None else value


def _normalize_object_container(value: object) -> object:
    return {} if value is None else value


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MaterialSystemPayload(_StrictModel):
    family: str | None = None
    composition: str | None = None


class ProcessContextPayload(_StrictModel):
    temperatures_c: list[float] = Field(default_factory=list)
    durations: list[str] = Field(default_factory=list)
    atmosphere: str | None = None

    @field_validator("temperatures_c", "durations", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)


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

    @field_validator("temperatures_c", "durations", "methods", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return _normalize_list_container(value)


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


class StructuredExtractionBundle(_StrictModel):
    method_facts: list[MethodFactPayload] = Field(default_factory=list)
    sample_variants: list[SampleVariantPayload] = Field(default_factory=list)
    test_conditions: list[ExtractedTestConditionPayload] = Field(default_factory=list)
    baseline_references: list[BaselineReferencePayload] = Field(default_factory=list)
    measurement_results: list[MeasurementResultPayload] = Field(default_factory=list)

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
    protocol_extractable: Literal["yes", "partial", "no", "uncertain"] = "uncertain"
    protocol_extractability_signals: list[str] = Field(default_factory=list)
    parsing_warnings: list[
        Literal["insufficient_content", "classification_uncertain"]
    ] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("protocol_extractability_signals")
    @classmethod
    def _validate_empty_signals(cls, value: list[str]) -> list[str]:
        if value:
            raise ValueError(
                "protocol_extractability_signals must be empty for document triage"
            )
        return value
