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


PaperRelevance = Literal["high", "medium", "low", "uncertain"]
PaperRole = Literal[
    "primary_experiment",
    "supporting_method",
    "supporting_background",
    "review",
    "modeling_only",
    "mixed",
    "uncertain",
]


class AgentPaperSummaryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=240)
    relevance: PaperRelevance
    paper_role: PaperRole
    contribution_summary: str = Field(min_length=1, max_length=2_000)
    confidence: float = Field(ge=0, le=1)


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
        min_length=1, max_length=100
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
        if evidence_ids != set(self.document_ids):
            raise ValueError(
                "Agent analysis requires Evidence for every selected document"
            )
        return self


class PublishAgentObjectiveAnalysisCapability:
    spec = ToolSpec(
        name="publish_agent_objective_analysis",
        description=(
            "Publish one complete Objective analysis that you authored after reading "
            "the exact canonical Sources with inspect_document_sources. Include every "
            "paper in the approved scope, at least one exact grounded Evidence record "
            "per paper, and an honest paper-level summary. Source digests and verbatim "
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
        )


__all__ = [
    "AgentEvidenceDraftArguments",
    "AgentPaperSummaryArguments",
    "PublishAgentObjectiveAnalysisArguments",
    "PublishAgentObjectiveAnalysisCapability",
]
