"""Approved publication of an Objective analysis authored by the Research Agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.chat.capabilities.evidence_authoring import (
    EvidenceAttributionScope,
    EvidenceComparisonArguments,
    EvidenceContextArguments,
    EvidenceResultArguments,
    EvidenceRole,
    EvidenceSourceKind,
    EvidenceVariableArguments,
)
from application.core.objectives.agent_analysis_service import (
    AgentObjectiveAnalysisService,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


PaperRelevance = Literal["high", "medium", "low", "irrelevant", "uncertain"]
PaperRole = Literal[
    "primary_experiment",
    "supporting_method",
    "supporting_background",
    "review",
    "modeling_only",
    "irrelevant",
    "mixed",
    "uncertain",
]
PaperInspectionOutcome = Literal[
    "evidence_recorded",
    "no_grounded_evidence",
    "excluded_after_review",
    "extraction_failed",
]


class AgentInspectedSourceArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: EvidenceSourceKind
    source_ref: str = Field(min_length=1, max_length=240)
    source_digest: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )


class AgentPaperSummaryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=240)
    relevance: PaperRelevance
    paper_role: PaperRole
    contribution_summary: str = Field(min_length=1, max_length=2_000)
    confidence: float = Field(ge=0, le=1)
    inspection_outcome: PaperInspectionOutcome = "evidence_recorded"
    inspection_outcome_reason: str | None = Field(default=None, max_length=2_000)
    inspected_source_refs: list[AgentInspectedSourceArguments] = Field(
        default_factory=list,
        max_length=24,
    )

    @model_validator(mode="after")
    def validate_inspection_outcome(self) -> "AgentPaperSummaryArguments":
        if self.inspection_outcome == "evidence_recorded":
            return self
        if not str(self.inspection_outcome_reason or "").strip():
            raise ValueError(
                "a paper without Evidence requires an inspection outcome reason"
            )
        if not self.inspected_source_refs:
            raise ValueError(
                "a paper without Evidence requires at least one inspected Source"
            )
        return self


class AgentEvidenceDraftArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1, max_length=128)
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
    confidence: float = Field(ge=0, le=1)
    authoring_note: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_shape(self) -> "AgentEvidenceDraftArguments":
        if self.evidence_role in {"direct_result", "contradictory_result"}:
            if self.reported_result is None:
                raise ValueError("result Evidence requires a reported result")
        elif self.reported_result is not None:
            raise ValueError("context Evidence cannot contain a reported result")
        return self


class PublishAgentObjectiveAnalysisArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=240)
    document_ids: list[str] = Field(min_length=1, max_length=20)
    paper_summaries: list[AgentPaperSummaryArguments] = Field(
        min_length=1, max_length=20
    )
    evidence_drafts: list[AgentEvidenceDraftArguments] = Field(
        default_factory=list, max_length=100
    )

    @model_validator(mode="after")
    def validate_scope(self) -> "PublishAgentObjectiveAnalysisArguments":
        if len(self.document_ids) != len(set(self.document_ids)):
            raise ValueError("Agent analysis document IDs must be unique")
        summary_ids = [item.document_id for item in self.paper_summaries]
        if len(summary_ids) != len(set(summary_ids)):
            raise ValueError("Agent analysis paper summaries must be unique")
        if set(summary_ids) != set(self.document_ids):
            raise ValueError(
                "Agent analysis requires one paper summary per selected document"
            )
        evidence_ids = {item.document_id for item in self.evidence_drafts}
        for summary in self.paper_summaries:
            has_evidence = summary.document_id in evidence_ids
            expects_evidence = summary.inspection_outcome == "evidence_recorded"
            if has_evidence != expects_evidence:
                raise ValueError(
                    "each selected paper must either provide Evidence or record an "
                    "explicit no-Evidence inspection outcome"
                )
        return self


class PublishAgentObjectiveAnalysisCapability:
    spec = ToolSpec(
        name="publish_agent_objective_analysis",
        description=(
            "Publish one complete Objective analysis that you authored after reading "
            "the exact canonical Sources with read_source or complete untruncated "
            "inspect_document_sources results. Include every paper in the approved "
            "scope and an honest paper-level summary. Record grounded Evidence when a "
            "Source supports a fact; otherwise record an exact inspected Source and an "
            "explicit scientific absence, exclusion, or technical extraction-failure "
            "reason. Use extraction_failed only when the Source was selected but the "
            "technical extraction could not complete; it is not scientific absence. "
            "Source digests and verbatim "
            "excerpts are revalidated by Lens. This write requires explicit user "
            "approval. It does not run automatic extraction or synthesize a Finding."
        ),
        risk=ToolRisk.WRITE,
        input_model=PublishAgentObjectiveAnalysisArguments,
    )

    def __init__(
        self,
        *,
        agent_analysis_service: AgentObjectiveAnalysisService,
        model_name: str,
        prompt_version: str,
    ) -> None:
        self.agent_analysis_service = agent_analysis_service
        self.model_name = model_name
        self.prompt_version = prompt_version

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: PublishAgentObjectiveAnalysisArguments,
    ) -> ChatToolResult:
        result = await self.agent_analysis_service.publish(
            collection_id=context.collection_id,
            objective_id=arguments.objective_id,
            document_ids=tuple(arguments.document_ids),
            paper_summaries=tuple(
                item.model_dump() for item in arguments.paper_summaries
            ),
            evidence_drafts=tuple(
                item.model_dump() for item in arguments.evidence_drafts
            ),
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            created_by_user_id=context.user_id,
            created_by_tool_call_id=context.tool_call_id,
        )
        scientific_warnings = tuple(
            dict.fromkeys(
                f"{evidence.evidence_id}: {warning}"
                for evidence in result.evidence_records
                for warning in evidence.warnings
            )
        )
        refs = [
            ChatResourceRef(
                resource_type="objective_analysis",
                resource_id=(
                    f"{arguments.objective_id}:{result.analysis.analysis_version}"
                ),
                href=(
                    f"/collections/{context.collection_id}/objectives/"
                    f"{arguments.objective_id}"
                ),
            )
        ]
        refs.extend(
            ChatResourceRef(
                resource_type="evidence",
                resource_id=(
                    f"{arguments.objective_id}:{result.analysis.analysis_version}:"
                    f"{evidence.evidence_id}"
                ),
                href=(
                    f"/collections/{context.collection_id}/documents/"
                    f"{evidence.document_id}?view=parsed-paper&source_ref="
                    f"{evidence.source_ref}"
                ),
            )
            for evidence in result.evidence_records
        )
        if getattr(result.analysis, "status", "succeeded") == "failed":
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="failed",
                data={
                    "analysis": result.analysis.to_record(),
                    "paper_contributions": [
                        item.to_record() for item in result.contributions
                    ],
                    "evidence": [
                        item.to_record() for item in result.evidence_records
                    ],
                    "evidence_count": len(result.evidence_records),
                    "finding_count": 0,
                    "next_step": (
                        "Retry the analysis after the technical extraction issue is "
                        "resolved; no scientific conclusion was published."
                    ),
                },
                resource_refs=tuple(refs),
                warnings=(
                    "The Agent analysis failed during technical Source extraction; "
                    "the previous published result, if any, remains unchanged.",
                ),
                error_code=result.analysis.error_code or "agent_analysis_failed",
                error_message=(
                    result.analysis.error_message
                    or "Agent analysis failed before publication."
                ),
            )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "analysis": result.analysis.to_record(),
                "paper_contributions": [
                    item.to_record() for item in result.contributions
                ],
                "evidence": [
                    item.to_record() for item in result.evidence_records
                ],
                "evidence_count": len(result.evidence_records),
                "finding_count": 0,
                "next_step": (
                    "Inspect the published Evidence and propose a Finding only if "
                    "the records support a defensible conclusion."
                ),
            },
            resource_refs=tuple(refs),
            warnings=scientific_warnings,
        )


__all__ = [
    "AgentEvidenceDraftArguments",
    "AgentInspectedSourceArguments",
    "AgentPaperSummaryArguments",
    "PublishAgentObjectiveAnalysisArguments",
    "PublishAgentObjectiveAnalysisCapability",
]
