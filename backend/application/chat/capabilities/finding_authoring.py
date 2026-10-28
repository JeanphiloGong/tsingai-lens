"""Approved Agent access to canonical researcher Finding authoring."""

from __future__ import annotations

from dataclasses import asdict

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)

from application.core.objectives.finding_authoring_service import (
    FindingAuthoringService,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CreateFindingVersionToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=240)
    source_analysis_version: int = Field(ge=1)
    selection_ids: list[str] = Field(default_factory=list, max_length=100)
    comparison_group_ids: list[str] = Field(default_factory=list, max_length=20)
    parent_finding_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_authoring_mode(self) -> "CreateFindingVersionToolRequest":
        selected = self.selection_ids + self.comparison_group_ids
        if any(not value.strip() or len(value) > 128 for value in selected):
            raise ValueError("experiment reference IDs must be non-empty and at most 128 characters")
        if not self.selection_ids:
            raise ValueError("Finding requires experiment selections")
        return self


class CreateFindingDraftToolRequest(CreateFindingVersionToolRequest):
    draft_id: str = Field(min_length=1, max_length=128)


class CreateFindingDraftCapability:
    spec = ToolSpec(
        name="create_finding_draft",
        description=(
            "Record one transient Finding draft that selects experiment results and "
            "optional ComparisonGroups for researcher review. selection_ids must be "
            "canonical ObjectiveExperimentSelection IDs returned by the experiment "
            "graph; never use Evidence projection IDs, evidence-* IDs, or document IDs."
            " Inspect the current published analysis and exact eligible selections "
            "first; when deriving from a saved Finding, inspect and name that parent. "
            "If no inspected selection supports the requested conclusion, explain "
            "the unsupported claim rather than inventing a supporting selection. "
            "Draft success does not publish a Finding; saving is a separate write."
        ),
        risk=ToolRisk.DRAFT,
        input_model=CreateFindingDraftToolRequest,
    )

    def __init__(self, *, finding_authoring_service: FindingAuthoringService | None = None) -> None:
        self.finding_authoring_service = finding_authoring_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: CreateFindingDraftToolRequest,
    ) -> ChatToolResult:
        if self.finding_authoring_service is not None:
            await self.finding_authoring_service.validate_selection_references(
                collection_id=context.collection_id,
                objective_id=arguments.objective_id,
                source_analysis_version=arguments.source_analysis_version,
                selection_ids=tuple(arguments.selection_ids),
                comparison_group_ids=tuple(arguments.comparison_group_ids),
                user_id=context.user_id,
            )
        draft = arguments.model_dump()
        refs = [
            ChatResourceRef(
                resource_type="research_objective",
                resource_id=arguments.objective_id,
                href=(
                    f"/collections/{context.collection_id}/objectives/"
                    f"{arguments.objective_id}"
                ),
            )
        ]
        refs.extend(
            ChatResourceRef(
                resource_type="objective_selection",
                resource_id=(
                    f"{arguments.objective_id}:{arguments.source_analysis_version}:{selection_id}"
                ),
                href=(
                    f"/collections/{context.collection_id}/objectives/"
                    f"{arguments.objective_id}?selection_id={selection_id}"
                ),
            )
            for selection_id in arguments.selection_ids
        )
        refs.extend(
            ChatResourceRef(
                resource_type="comparison_group",
                resource_id=(
                    f"{arguments.objective_id}:{arguments.source_analysis_version}:{group_id}"
                ),
                href=(
                    f"/collections/{context.collection_id}/objectives/"
                    f"{arguments.objective_id}?comparison_group_id={group_id}"
                ),
            )
            for group_id in arguments.comparison_group_ids
        )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "draft": draft,
                "persistence": "transient_chat_result",
                "published": False,
                "requires_user_approval": True,
                "requires_experiment_selection_validation": True,
            },
            resource_refs=tuple(refs),
        )


class CreateFindingVersionCapability:
    spec = ToolSpec(
        name="create_finding_version",
        description=(
            "Return the Finding aggregated from fixed experiment Selection IDs and "
            "optional ComparisonGroup IDs in the published analysis. This write "
            "requires explicit approval and never accepts Evidence IDs or a hand-written conclusion."
        ),
        risk=ToolRisk.WRITE,
        input_model=CreateFindingVersionToolRequest,
    )

    def __init__(
        self,
        *,
        finding_authoring_service: FindingAuthoringService,
    ) -> None:
        self.finding_authoring_service = finding_authoring_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: CreateFindingVersionToolRequest,
    ) -> ChatToolResult:
        result = await self.finding_authoring_service.create_selection_version(
            collection_id=context.collection_id,
            objective_id=arguments.objective_id,
            source_analysis_version=arguments.source_analysis_version,
            created_by_user_id=context.user_id,
            selection_ids=tuple(arguments.selection_ids),
            comparison_group_ids=tuple(arguments.comparison_group_ids),
            parent_finding_id=arguments.parent_finding_id,
        )
        finding = result.finding
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
        if finding is not None:
            refs.append(
                ChatResourceRef(
                    resource_type="finding",
                    resource_id=(
                        f"{arguments.objective_id}:"
                        f"{result.analysis.analysis_version}:{finding.finding_id}"
                    ),
                    href=(
                        f"/collections/{context.collection_id}/objectives/"
                        f"{arguments.objective_id}?finding_id={finding.finding_id}"
                    ),
                )
            )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "analysis": {
                    "collection_id": result.analysis.collection_id,
                    "objective_id": result.analysis.objective_id,
                    "analysis_version": result.analysis.analysis_version,
                    "document_inputs": [
                        {
                            "document_id": document_input.document_id,
                            "preparation_fingerprint": document_input.preparation_fingerprint,
                        }
                        for document_input in result.analysis.document_inputs
                    ],
                    "pipeline_version": result.analysis.pipeline_version,
                    "model_name": result.analysis.model_name,
                    "prompt_versions": dict(result.analysis.prompt_versions),
                    "stats": {
                        "duration_ms": result.analysis.stats.duration_ms,
                        "token_usage": (
                            asdict(result.analysis.stats.token_usage)
                            if result.analysis.stats.token_usage is not None
                            else None
                        ),
                        "model_usage": [
                            asdict(item) for item in result.analysis.stats.model_usage
                        ],
                        "unreported_request_count": result.analysis.stats.unreported_request_count,
                        "prompt_versions": dict(result.analysis.stats.prompt_versions),
                    },
                    "status": result.analysis.status,
                    "phase": result.analysis.phase,
                    "processed_document_count": result.analysis.processed_document_count,
                    "total_document_count": result.analysis.total_document_count,
                    "current_document_id": result.analysis.current_document_id,
                    "progress_message": result.analysis.progress_message,
                    "error_code": result.analysis.error_code,
                    "error_message": result.analysis.error_message,
                    "created_at": (
                        result.analysis.created_at.isoformat()
                        if result.analysis.created_at is not None
                        else None
                    ),
                    "started_at": (
                        result.analysis.started_at.isoformat()
                        if result.analysis.started_at is not None
                        else None
                    ),
                    "completed_at": (
                        result.analysis.completed_at.isoformat()
                        if result.analysis.completed_at is not None
                        else None
                    ),
                    "origin": result.analysis.origin,
                    "scientific_record_source": result.analysis.scientific_record_source,
                    "source_analysis_version": result.analysis.source_analysis_version,
                    "created_by_user_id": result.analysis.created_by_user_id,
                    "created_by_tool_call_id": result.analysis.created_by_tool_call_id,
                    "abstention_reason": result.analysis.abstention_reason,
                    "abstention_note": result.analysis.abstention_note,
                },
                "finding": (
                    {
                        "collection_id": finding.collection_id,
                        "objective_id": finding.objective_id,
                        "analysis_version": finding.analysis_version,
                        "finding_id": finding.finding_id,
                        "statement": finding.statement,
                        "factors": list(finding.factors),
                        "outcome": finding.outcome,
                        "direction": finding.direction,
                        "assertion_strength": finding.assertion_strength,
                        "attribution_scope": finding.attribution_scope,
                        "synthesis_status": finding.synthesis_status,
                        "certainty": finding.certainty,
                        "display_rank": finding.display_rank,
                        "mechanisms": [
                            {
                                "source_term": mechanism.source_term,
                                "relation_type": mechanism.relation_type,
                                "target_term": mechanism.target_term,
                                "direction": mechanism.direction,
                                "assertion_strength": mechanism.assertion_strength,
                                "supporting_evidence_ids": list(
                                    mechanism.supporting_evidence_ids
                                ),
                            }
                            for mechanism in finding.mechanisms
                        ],
                        "scientific_context": {
                            "material": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in finding.scientific_context.material
                            ],
                            "sample": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in finding.scientific_context.sample
                            ],
                            "process": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in finding.scientific_context.process
                            ],
                            "test": [
                                {
                                    "name": attribute.name,
                                    "value": attribute.value,
                                    "unit": attribute.unit,
                                    **(
                                        {"context_scope": attribute.context_scope}
                                        if attribute.context_scope != "unknown"
                                        else {}
                                    ),
                                    **(
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
                                        if attribute.applies_to_outcomes
                                        else {}
                                    ),
                                }
                                for attribute in finding.scientific_context.test
                            ],
                        },
                        "limitations": list(finding.limitations),
                        "paper_contributions": [
                            {
                                "document_id": contribution.document_id,
                                "analysis_status": contribution.analysis_status,
                                "supporting_evidence_ids": list(
                                    contribution.supporting_evidence_ids
                                ),
                                "contradicting_evidence_ids": list(
                                    contribution.contradicting_evidence_ids
                                ),
                                "context_evidence_ids": list(
                                    contribution.context_evidence_ids
                                ),
                                "condition_boundary_evidence_ids": list(
                                    contribution.condition_boundary_evidence_ids
                                ),
                            }
                            for contribution in finding.paper_contributions
                        ],
                        "origin": finding.origin,
                        "source_analysis_version": finding.source_analysis_version,
                        "parent_finding_id": finding.parent_finding_id,
                        "created_by_user_id": finding.created_by_user_id,
                        "created_by_tool_call_id": finding.created_by_tool_call_id,
                        "created_at": (
                            finding.created_at.isoformat()
                            if finding.created_at
                            else None
                        ),
                        **(
                            {"selection_ids": list(finding.selection_ids)}
                            if finding.selection_ids
                            else {}
                        ),
                        **(
                            {"comparison_group_ids": list(finding.comparison_group_ids)}
                            if finding.comparison_group_ids
                            else {}
                        ),
                        **(
                            {"warnings": list(finding.warnings)}
                            if finding.warnings
                            else {}
                        ),
                    }
                    if finding is not None
                    else None
                ),
                "abstention_reason": result.analysis.abstention_reason,
            },
            resource_refs=tuple(refs),
            warnings=tuple(finding.warnings) if finding is not None else (),
        )


__all__ = [
    "CreateFindingDraftToolRequest",
    "CreateFindingDraftCapability",
    "CreateFindingVersionToolRequest",
    "CreateFindingVersionCapability",
]
