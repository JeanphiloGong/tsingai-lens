from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MaterialSystemPayload(_StrictModel):
    family: str | None = None
    composition: str | None = None


class ProcessContextPayload(_StrictModel):
    temperatures_c: list[float] = Field(default_factory=list)
    durations: list[str] = Field(default_factory=list)
    atmosphere: str | None = None


class BaselineContextPayload(_StrictModel):
    control: str | None = None


class TestContextPayload(_StrictModel):
    methods: list[str] = Field(default_factory=list)
    method: str | None = None


class ConditionContextPayload(_StrictModel):
    process: ProcessContextPayload = Field(default_factory=ProcessContextPayload)
    baseline: BaselineContextPayload = Field(default_factory=BaselineContextPayload)
    test: TestContextPayload = Field(default_factory=TestContextPayload)


class EvidenceAnchorPayload(_StrictModel):
    quote: str | None = None
    source_type: Literal["text", "method", "table", "figure"] = "text"
    section_id: str | None = None
    snippet_id: str | None = None
    figure_or_table: str | None = None
    page: int | None = None


class EvidenceCardPayload(_StrictModel):
    claim_text: str
    claim_type: str
    evidence_source_type: Literal["text", "method", "table", "figure"] = "text"
    material_system: MaterialSystemPayload | None = None
    condition_context: ConditionContextPayload = Field(default_factory=ConditionContextPayload)
    anchors: list[EvidenceAnchorPayload] = Field(default_factory=list)
    confidence: float = 0.0


class SampleVariantPayload(_StrictModel):
    variant_ref: str
    variant_label: str
    host_material_system: MaterialSystemPayload | None = None
    composition: str | None = None
    variable_axis_type: str | None = None
    variable_value: str | int | float | None = None
    process_context: ProcessContextPayload = Field(default_factory=ProcessContextPayload)
    confidence: float = 0.0
    epistemic_status: str = "normalized_from_evidence"
    source_kind: Literal["section", "table_row"] = "section"


class TestConditionPayloadModel(_StrictModel):
    method: str | None = None
    methods: list[str] = Field(default_factory=list)
    temperatures_c: list[float] = Field(default_factory=list)
    durations: list[str] = Field(default_factory=list)
    atmosphere: str | None = None


class ExtractedTestConditionPayload(_StrictModel):
    test_condition_ref: str
    property_type: str
    condition_payload: TestConditionPayloadModel = Field(default_factory=TestConditionPayloadModel)
    confidence: float = 0.0
    epistemic_status: str = "normalized_from_evidence"


class BaselineReferencePayload(_StrictModel):
    baseline_ref: str
    baseline_label: str
    confidence: float = 0.0
    epistemic_status: str = "normalized_from_evidence"


class MeasurementValuePayload(_StrictModel):
    value: float | None = None
    min: float | None = None
    max: float | None = None
    retention_percent: float | None = None
    direction: str | None = None
    statement: str | None = None


class MeasurementResultPayload(_StrictModel):
    result_ref: str
    claim_text: str
    property_normalized: str
    result_type: str
    value_payload: MeasurementValuePayload = Field(default_factory=MeasurementValuePayload)
    unit: str | None = None
    variant_ref: str | None = None
    test_condition_ref: str | None = None
    baseline_ref: str | None = None
    anchors: list[EvidenceAnchorPayload] = Field(default_factory=list)
    confidence: float = 0.0


class StructuredExtractionBundle(_StrictModel):
    evidence_cards: list[EvidenceCardPayload] = Field(default_factory=list)
    sample_variants: list[SampleVariantPayload] = Field(default_factory=list)
    test_conditions: list[ExtractedTestConditionPayload] = Field(default_factory=list)
    baseline_references: list[BaselineReferencePayload] = Field(default_factory=list)
    measurement_results: list[MeasurementResultPayload] = Field(default_factory=list)


class StructuredDocumentProfile(_StrictModel):
    doc_type: str
    protocol_extractable: str
    protocol_extractability_signals: list[str] = Field(default_factory=list)
    parsing_warnings: list[str] = Field(default_factory=list)
    confidence: float = 0.0
