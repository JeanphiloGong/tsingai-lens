"""Approved Agent access to canonical researcher Evidence authoring."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.core.objectives.evidence_authoring_service import (
    EvidenceAuthoringService,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


EvidenceSourceKind = Literal["text_window", "table", "figure"]
EvidenceRole = Literal[
    "direct_result",
    "condition_context",
    "mechanism_context",
    "baseline_context",
    "comparison_context",
    "background_context",
    "contradictory_result",
    "irrelevant",
]
EvidenceAttributionScope = Literal[
    "isolated_effect",
    "joint_effect",
    "association_only",
    "descriptive_only",
    "not_attributable",
]
EvidenceDirection = Literal[
    "increase",
    "decrease",
    "improve",
    "worsen",
    "changed",
    "no_change",
    "mixed",
    "unknown",
]
Scalar = str | int | float | bool


class EvidenceVariableArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=240)
    baseline_value: Scalar | None = None
    target_value: Scalar | None = None
    unit: str | None = Field(default=None, max_length=80)


class EvidenceComparisonArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_label: str = Field(min_length=1, max_length=500)
    target_label: str = Field(min_length=1, max_length=500)
    axis_names: list[str] = Field(default_factory=list, max_length=20)
    comparable: bool
    incomparability_reasons: list[str] = Field(default_factory=list, max_length=20)


class EvidenceResultArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str = Field(min_length=1, max_length=500)
    value: Scalar | None = None
    baseline_value: Scalar | None = None
    target_value: Scalar | None = None
    unit: str | None = Field(default=None, max_length=80)
    direction: EvidenceDirection
    result_text: str = Field(min_length=1, max_length=5000)


class EvidenceAttributeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=240)
    value: Scalar
    unit: str | None = Field(default=None, max_length=80)


class EvidenceContextArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material: list[EvidenceAttributeArguments] = Field(default_factory=list, max_length=40)
    sample: list[EvidenceAttributeArguments] = Field(default_factory=list, max_length=40)
    process: list[EvidenceAttributeArguments] = Field(default_factory=list, max_length=40)
    test: list[EvidenceAttributeArguments] = Field(default_factory=list, max_length=40)


class CreateEvidenceVersionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=240)
    source_analysis_version: int = Field(ge=1)
    document_id: str = Field(min_length=1, max_length=240)
    source_kind: EvidenceSourceKind
    source_ref: str = Field(min_length=1, max_length=240)
    source_excerpt: str = Field(min_length=1, max_length=20_000)
    source_digest: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    evidence_role: EvidenceRole
    changed_variables: list[EvidenceVariableArguments] = Field(
        default_factory=list, max_length=20
    )
    comparison: EvidenceComparisonArguments | None = None
    reported_result: EvidenceResultArguments | None = None
    attribution_scope: EvidenceAttributionScope
    scientific_context: EvidenceContextArguments = Field(
        default_factory=EvidenceContextArguments
    )
    supersedes_evidence_id: str | None = Field(default=None, max_length=128)
    authoring_note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_shape(self) -> "CreateEvidenceVersionArguments":
        if self.evidence_role in {"direct_result", "contradictory_result"}:
            if self.reported_result is None:
                raise ValueError("result Evidence requires a reported result")
        elif self.reported_result is not None:
            raise ValueError("context Evidence cannot contain a reported result")
        return self


class CreateEvidenceVersionCapability:
    spec = ToolSpec(
        name="create_evidence_version",
        description=(
            "Propose one structured Objective Evidence record from an exact Source "
            "returned by inspect_document_sources. The Source digest must match the "
            "complete canonical Source; never infer facts or use a truncated quote. "
            "This write requires explicit user approval and publishes a new immutable "
            "analysis version without changing old Evidence or Findings."
        ),
        risk=ToolRisk.WRITE,
        input_model=CreateEvidenceVersionArguments,
    )

    def __init__(self, *, evidence_authoring_service: EvidenceAuthoringService) -> None:
        self.evidence_authoring_service = evidence_authoring_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: CreateEvidenceVersionArguments,
    ) -> ChatToolResult:
        result = await self.evidence_authoring_service.create_version(
            collection_id=context.collection_id,
            objective_id=arguments.objective_id,
            source_analysis_version=arguments.source_analysis_version,
            document_id=arguments.document_id,
            source_kind=arguments.source_kind,
            source_ref=arguments.source_ref,
            source_excerpt=arguments.source_excerpt,
            source_digest=arguments.source_digest,
            evidence_role=arguments.evidence_role,
            changed_variables=tuple(item.model_dump() for item in arguments.changed_variables),
            comparison=(arguments.comparison.model_dump() if arguments.comparison else None),
            reported_result=(
                arguments.reported_result.model_dump()
                if arguments.reported_result
                else None
            ),
            attribution_scope=arguments.attribution_scope,
            scientific_context=arguments.scientific_context.model_dump(),
            supersedes_evidence_id=arguments.supersedes_evidence_id,
            authoring_note=arguments.authoring_note,
            created_by_user_id=context.user_id,
            created_by_tool_call_id=context.tool_call_id,
        )
        evidence = result.evidence
        refs = (
            ChatResourceRef(
                resource_type="objective_analysis",
                resource_id=f"{arguments.objective_id}:{result.analysis.analysis_version}",
                href=(
                    f"/collections/{context.collection_id}/objectives/"
                    f"{arguments.objective_id}"
                ),
            ),
            ChatResourceRef(
                resource_type="evidence",
                resource_id=(
                    f"{arguments.objective_id}:{result.analysis.analysis_version}:"
                    f"{evidence.evidence_id}"
                ),
                href=(
                    f"/collections/{context.collection_id}/documents/"
                    f"{arguments.document_id}?view=parsed-paper&source_ref="
                    f"{arguments.source_ref}&page={evidence.page_numbers[0]}"
                    if evidence.page_numbers
                    else (
                        f"/collections/{context.collection_id}/documents/"
                        f"{arguments.document_id}?view=parsed-paper&source_ref="
                        f"{arguments.source_ref}"
                    )
                ),
            ),
        )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "analysis": result.analysis.to_record(),
                "evidence": evidence.to_record(),
                "supports_finding": evidence.supports_finding,
            },
            resource_refs=refs,
        )


__all__ = [
    "CreateEvidenceVersionArguments",
    "CreateEvidenceVersionCapability",
]
