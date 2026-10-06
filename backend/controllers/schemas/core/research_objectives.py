from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AnalysisStatus = Literal["queued", "running", "succeeded", "failed"]


EvidenceAttributionScope = Literal[
    "isolated_effect",
    "joint_effect",
    "association_only",
    "descriptive_only",
    "not_attributable",
]


EvidenceStatus = Literal[
    "comparable",
    "association_only",
    "descriptive",
    "needs_context",
    "non_comparable",
    "extraction_failed",
]


EvidenceResultDirection = Literal[
    "increase",
    "decrease",
    "improve",
    "worsen",
    "changed",
    "no_change",
    "mixed",
    "unknown",
]


EvidenceResultKind = Literal[
    "measured",
    "observed",
    "predicted",
    "simulated",
    "modeled",
    "unknown",
]


EvidenceContextScope = Literal[
    "experimental",
    "simulation",
    "background",
    "unknown",
]


class TokenUsageResponse(BaseModel):
    input_tokens: int = Field(..., ge=0)
    output_tokens: int = Field(..., ge=0)
    total_tokens: int = Field(..., ge=0)


class ModelUsageResponse(BaseModel):
    model_name: str
    request_count: int = Field(..., ge=0)
    token_usage: TokenUsageResponse | None = None
    unreported_request_count: int = Field(default=0, ge=0)


class ExecutionStatsResponse(BaseModel):
    duration_ms: int | None = Field(default=None, ge=0)
    token_usage: TokenUsageResponse | None = None
    model_usage: list[ModelUsageResponse] = Field(default_factory=list)
    unreported_request_count: int = Field(default=0, ge=0)
    prompt_versions: dict[str, str] = Field(default_factory=dict)


class PreparedDocumentInputResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    preparation_fingerprint: str


class ObjectiveAnalysisStateResponse(BaseModel):
    collection_id: str
    objective_id: str
    analysis_version: int
    document_inputs: list[PreparedDocumentInputResponse]
    pipeline_version: str
    model_name: str | None = None
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    stats: ExecutionStatsResponse = Field(default_factory=ExecutionStatsResponse)
    status: AnalysisStatus
    phase: str
    processed_document_count: int = 0
    total_document_count: int = 0
    current_document_id: str | None = None
    progress_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    origin: Literal[
        "system_generated", "human_authored", "agent_authored", "hybrid"
    ] = "system_generated"
    source_analysis_version: int | None = Field(default=None, ge=1)
    created_by_user_id: str | None = None
    created_by_tool_call_id: str | None = None
    abstention_reason: (
        Literal[
            "no_comparable_evidence",
            "no_grounded_evidence",
            "insufficient_evidence",
        ]
        | None
    ) = None
    abstention_note: str | None = None


class FindingMechanismResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_term: str
    relation_type: str
    target_term: str
    direction: EvidenceResultDirection | None = None
    assertion_strength: Literal["causal", "associative", "descriptive"]
    supporting_evidence_ids: list[str]


class FindingPaperContributionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    analysis_status: Literal["analyzed", "excluded", "failed"]
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    context_evidence_ids: list[str]
    condition_boundary_evidence_ids: list[str]


class ObjectiveEvidenceAttributeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: str | int | float | bool
    unit: str | None = None
    context_scope: EvidenceContextScope = "unknown"
    applies_to_outcomes: list[str] = Field(default_factory=list, max_length=4)


class ObjectiveEvidenceVariableResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    baseline_value: str | int | float | bool | None = None
    target_value: str | int | float | bool | None = None
    unit: str | None = None


class ObjectiveEvidenceComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_label: str
    target_label: str
    axis_names: list[str] = Field(default_factory=list)
    comparable: bool
    incomparability_reasons: list[str] = Field(default_factory=list)


class ObjectiveEvidenceResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str
    result_kind: EvidenceResultKind = "observed"
    value: str | int | float | bool | None = None
    baseline_value: str | int | float | bool | None = None
    target_value: str | int | float | bool | None = None
    unit: str | None = None
    direction: EvidenceResultDirection
    result_text: str


class ObjectiveEvidenceContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material: list[ObjectiveEvidenceAttributeResponse]
    sample: list[ObjectiveEvidenceAttributeResponse]
    process: list[ObjectiveEvidenceAttributeResponse]
    test: list[ObjectiveEvidenceAttributeResponse]


class FindingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str
    objective_id: str
    analysis_version: int = Field(..., ge=1)
    finding_id: str
    statement: str
    factors: list[str] = Field(..., min_length=1)
    outcome: str
    direction: EvidenceResultDirection
    assertion_strength: Literal["causal", "associative", "descriptive"]
    attribution_scope: Literal[
        "isolated_effect",
        "joint_effect",
        "association_only",
        "descriptive_only",
    ]
    synthesis_status: Literal[
        "single_study",
        "agreement",
        "conflict",
        "condition_dependent",
        "insufficient_confirmation",
    ]
    certainty: float = Field(..., ge=0, le=1)
    display_rank: int = Field(..., ge=0)
    mechanisms: list[FindingMechanismResponse]
    scientific_context: ObjectiveEvidenceContextResponse
    limitations: list[str]
    paper_contributions: list[FindingPaperContributionResponse]
    selection_ids: list[str] = Field(default_factory=list)
    comparison_group_ids: list[str] = Field(default_factory=list)
    origin: Literal[
        "system_generated", "human_authored", "agent_authored", "hybrid"
    ] = "system_generated"
    source_analysis_version: int | None = Field(default=None, ge=1)
    parent_finding_id: str | None = None
    created_by_user_id: str | None = None
    created_by_tool_call_id: str | None = None
    created_at: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source_links(self) -> "FindingResponse":
        if not self.paper_contributions and not self.selection_ids:
            raise ValueError(
                "Finding requires paper contributions or experiment selections"
            )
        return self


class ObjectiveEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: str
    objective_id: str
    analysis_version: int
    evidence_id: str
    document_id: str
    source_kind: str
    source_ref: str
    source_excerpt: str
    page_numbers: list[int] = Field(default_factory=list)
    related_source_refs: list[dict[str, Any]] = Field(default_factory=list)
    evidence_role: str
    selection_status: str
    selection_reason: str | None = None
    evidence_status: EvidenceStatus | None = None
    evidence_status_reason: str | None = None
    changed_variables: list[ObjectiveEvidenceVariableResponse] = Field(
        default_factory=list
    )
    comparison: ObjectiveEvidenceComparisonResponse | None = None
    reported_result: ObjectiveEvidenceResultResponse | None = None
    attribution_scope: EvidenceAttributionScope
    scientific_context: ObjectiveEvidenceContextResponse
    resolution_status: str
    failure_reason: str | None = None
    confidence: float
    supports_finding: bool = False
    eligible_for_finding_authoring: bool = False
    warnings: list[str] = Field(default_factory=list)
    origin: Literal[
        "system_generated", "human_authored", "human_revised", "agent_authored"
    ] = "system_generated"
    source_analysis_version: int | None = Field(default=None, ge=1)
    supersedes_evidence_id: str | None = None
    superseded_by_evidence_id: str | None = None
    created_by_user_id: str | None = None
    created_by_tool_call_id: str | None = None
    created_at: str | None = None
    authoring_note: str | None = None
