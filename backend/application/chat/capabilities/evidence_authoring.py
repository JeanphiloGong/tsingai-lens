"""Approved Agent access to canonical researcher Evidence authoring."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Literal
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, model_validator

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.core.objectives.evidence_authoring_service import (
    EvidenceAuthoringService,
    normalize_source_text,
    resolve_canonical_objective_source,
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
    axis_names: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Exact distinct names from changed_variables[].name. These are the "
            "varied comparison axes, not the measured outcome or result column."
        ),
    )
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


class CreateEvidenceDraftArguments(CreateEvidenceVersionArguments):
    draft_id: str = Field(min_length=1, max_length=128)


class CreateEvidenceDraftCapability:
    spec = ToolSpec(
        name="create_evidence_draft",
        description=(
            "Prepare a Source-grounded Evidence draft, including correction of facts "
            "underlying a disputed Finding. Lens verifies collection ownership, the canonical Source "
            "digest, and the verbatim excerpt, but does not publish Evidence or change "
            "an Objective analysis. Use the separate approved Evidence write only "
            "after the researcher reviews this draft. Use this draft first when "
            "review of a Finding exposes an incorrect Evidence extraction; identify "
            "the old Evidence with supersedes_evidence_id and retain its Source."
        ),
        risk=ToolRisk.DRAFT,
        input_model=CreateEvidenceDraftArguments,
    )

    def __init__(
        self,
        *,
        collection_service: Any,
        source_artifact_repository: Any,
    ) -> None:
        self.collection_service = collection_service
        self.source_artifact_repository = source_artifact_repository

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: CreateEvidenceDraftArguments,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        document = await self.source_artifact_repository.read_document(
            context.collection_id,
            arguments.document_id,
        )
        if document is None:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="failed",
                error_code="document_sources_not_ready",
                error_message=(
                    "The requested paper has no prepared Source content in this "
                    "collection."
                ),
            )
        try:
            canonical = resolve_canonical_objective_source(
                document,
                source_kind=arguments.source_kind,
                source_ref=arguments.source_ref,
            )
        except FileNotFoundError:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="failed",
                error_code="source_not_found",
                error_message="The requested Source was not found in this paper.",
            )

        canonical_digest = sha256(canonical.content.encode("utf-8")).hexdigest()
        if arguments.source_digest.lower() != canonical_digest:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="failed",
                error_code="source_digest_mismatch",
                error_message=(
                    "The Source changed or the draft was based on shortened content. "
                    "Inspect the complete Source again before drafting Evidence."
                ),
            )
        if normalize_source_text(arguments.source_excerpt) not in normalize_source_text(
            canonical.content
        ):
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="failed",
                error_code="source_excerpt_not_grounded",
                error_message=(
                    "The proposed excerpt is not present in the canonical Source."
                ),
            )

        draft = arguments.model_dump()
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "draft": draft,
                "source_page": canonical.page,
                "persistence": "transient_chat_result",
                "published": False,
                "requires_user_approval": True,
                "support_is_evidence": False,
            },
            resource_refs=(
                ChatResourceRef(
                    resource_type="source",
                    resource_id=(
                        f"{arguments.document_id}:{arguments.source_kind}:"
                        f"{arguments.source_ref}"
                    ),
                    href=(
                        f"/collections/{context.collection_id}/documents/"
                        f"{arguments.document_id}?"
                        + urlencode(
                            {
                                "view": "parsed-paper",
                                "source_ref": arguments.source_ref,
                            }
                        )
                    ),
                ),
            ),
        )


class CreateEvidenceVersionCapability:
    spec = ToolSpec(
        name="create_evidence_version",
        description=(
            "Propose one structured Objective Evidence record from an exact Source "
            "returned by read_source or a complete untruncated Source returned by "
            "inspect_document_sources. The Source digest must match the complete "
            "canonical Source; never infer facts or use a truncated quote. This write "
            "requires explicit user approval and publishes a new immutable analysis "
            "version without changing old Evidence or Findings."
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
                "eligible_for_finding_authoring": evidence.eligible_for_finding_authoring,
                "affected_finding_ids": list(result.affected_finding_ids),
            },
            resource_refs=refs,
            warnings=tuple(evidence.warnings),
        )


__all__ = [
    "CreateEvidenceDraftArguments",
    "CreateEvidenceDraftCapability",
    "CreateEvidenceVersionArguments",
    "CreateEvidenceVersionCapability",
]
