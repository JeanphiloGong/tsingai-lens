from dataclasses import dataclass, field
from typing import Any, Literal

ValueStatus = Literal["reported", "inferred", "not_reported", "ambiguous"]
MaterialRole = Literal[
    "precursor",
    "solvent",
    "additive",
    "matrix",
    "filler",
    "sample",
    "product",
    "other",
]
ControlType = Literal[
    "baseline",
    "blank",
    "untreated",
    "literature",
    "ablation",
    "other",
]
StepPhase = Literal[
    "preparation",
    "synthesis",
    "post_treatment",
    "characterization",
    "property_test",
    "analysis",
    "other",
]
ReviewStatus = Literal[
    "draft",
    "human_review_required",
    "approved",
    "changes_requested",
    "rejected",
]


@dataclass
class NormalizedValue:
    value: float | None = None
    unit: str | None = None
    raw_value: str | None = None
    operator: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    status: ValueStatus = "not_reported"


@dataclass
class Condition:
    temperature: NormalizedValue | None = None
    duration: NormalizedValue | None = None
    pressure: NormalizedValue | None = None
    heating_rate: NormalizedValue | None = None
    cooling_rate: NormalizedValue | None = None
    ph: NormalizedValue | None = None
    atmosphere: str | None = None
    environment: str | None = None
    raw_text: str | None = None


@dataclass
class MaterialRef:
    name: str
    formula: str | None = None
    role: MaterialRole = "other"
    amount: NormalizedValue | None = None
    composition_note: str | None = None
    grade: str | None = None
    source_text: str | None = None


@dataclass
class MeasurementSpec:
    method: str
    instrument: str | None = None
    target_property: str | None = None
    metrics: list[str] = field(default_factory=list)
    conditions: dict[str, Any] = field(default_factory=dict)
    output_ref: str | None = None
    source_text: str | None = None


@dataclass
class ControlSpec:
    control_type: ControlType = "other"
    description: str = ""
    rationale: str | None = None
    source_text: str | None = None


@dataclass
class EvidenceRef:
    paper_id: str
    section_id: str | None = None
    block_id: str | None = None
    snippet_id: str | None = None
    section_type: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    figure_or_table: str | None = None
    quote_span: str | None = None
    source_text: str | None = None
    confidence_score: float | None = None


@dataclass
class ProtocolStep:
    step_id: str
    paper_id: str
    order: int
    action: str
    section_id: str | None = None
    block_id: str | None = None
    phase: StepPhase = "other"
    materials: list[MaterialRef] = field(default_factory=list)
    conditions: Condition = field(default_factory=Condition)
    purpose: str | None = None
    expected_output: str | None = None
    characterization: list[MeasurementSpec] = field(default_factory=list)
    controls: list[ControlSpec] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    confidence_score: float | None = None


@dataclass
class SOPDraft:
    sop_id: str
    objective: str
    hypothesis: str | None = None
    variables: list[str] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    controls: list[ControlSpec] = field(default_factory=list)
    steps: list[ProtocolStep] = field(default_factory=list)
    measurement_plan: list[MeasurementSpec] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    review_status: ReviewStatus = "draft"
