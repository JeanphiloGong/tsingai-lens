"""Approved Agent access to canonical researcher Finding authoring."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.core.objectives.finding_authoring_service import (
    FindingAuthoringService,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


class CreateFindingVersionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=240)
    source_analysis_version: int = Field(ge=1)
    selection_ids: list[str] = Field(default_factory=list, max_length=100)
    comparison_group_ids: list[str] = Field(default_factory=list, max_length=20)
    parent_finding_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_authoring_mode(self) -> "CreateFindingVersionArguments":
        selected = self.selection_ids + self.comparison_group_ids
        if any(not value.strip() or len(value) > 128 for value in selected):
            raise ValueError("experiment reference IDs must be non-empty and at most 128 characters")
        if not self.selection_ids:
            raise ValueError("Finding requires experiment selections")
        return self


class CreateFindingDraftArguments(CreateFindingVersionArguments):
    draft_id: str = Field(min_length=1, max_length=128)


class CreateFindingDraftCapability:
    spec = ToolSpec(
        name="create_finding_draft",
        description=(
            "Record one transient Finding draft that selects experiment results and "
            "optional ComparisonGroups for researcher review."
        ),
        risk=ToolRisk.DRAFT,
        input_model=CreateFindingDraftArguments,
    )

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: CreateFindingDraftArguments,
    ) -> ChatToolResult:
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
        input_model=CreateFindingVersionArguments,
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
        arguments: CreateFindingVersionArguments,
    ) -> ChatToolResult:
        result = await self.finding_authoring_service.create_selection_version(
            collection_id=context.collection_id,
            objective_id=arguments.objective_id,
            source_analysis_version=arguments.source_analysis_version,
            created_by_user_id=context.user_id,
            selection_ids=tuple(arguments.selection_ids),
            comparison_group_ids=tuple(arguments.comparison_group_ids),
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
                "analysis": result.analysis.to_record(),
                "finding": finding.to_record() if finding is not None else None,
                "abstention_reason": result.analysis.abstention_reason,
            },
            resource_refs=tuple(refs),
            warnings=tuple(finding.warnings) if finding is not None else (),
        )


__all__ = [
    "CreateFindingDraftArguments",
    "CreateFindingDraftCapability",
    "CreateFindingVersionArguments",
    "CreateFindingVersionCapability",
]
