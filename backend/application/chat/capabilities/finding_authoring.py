"""Approved Agent access to canonical researcher Finding authoring."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.core.objectives.finding_authoring_service import (
    FindingAuthoringService,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


FindingAssertionStrength = Literal["causal", "associative", "descriptive"]
FindingAbstentionReason = Literal[
    "no_comparable_evidence",
    "no_grounded_evidence",
    "insufficient_evidence",
]


class CreateFindingVersionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=240)
    source_analysis_version: int = Field(ge=1, description="Inspected published analysis version supplying the Evidence; do not add analysis_version.")
    statement: str | None = Field(default=None, max_length=3_000, description="Concise proposed conclusion, not the quoted erroneous parent. Put the correction rationale and unread scope in limitations.")
    assertion_strength: FindingAssertionStrength | None = Field(
        default=None,
        description=(
            "Required for every non-abstention Finding. Choose exactly one of "
            "causal, associative, or descriptive. Omit only when abstention_reason "
            "is provided."
        ),
    )
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=100, description="Evidence supporting the proposed statement, required unless abstaining. Evidence that disproves the old parent can support its corrected statement; roles are relative to the new statement.")
    contradicting_evidence_ids: list[str] = Field(
        default_factory=list, max_length=100, description="Evidence contradicting the proposed statement, not the old disputed parent."
    )
    context_evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    condition_boundary_evidence_ids: list[str] = Field(
        default_factory=list, max_length=100
    )
    limitations: list[str] = Field(default_factory=list, max_length=20)
    parent_finding_id: str | None = Field(default=None, max_length=128)
    abstention_reason: FindingAbstentionReason | None = None

    @model_validator(mode="after")
    def validate_authoring_mode(self) -> "CreateFindingVersionArguments":
        if any(len(value.strip()) > 1_000 for value in self.limitations):
            raise ValueError("Finding limitations cannot exceed 1000 characters")
        selected = (
            self.supporting_evidence_ids
            + self.contradicting_evidence_ids
            + self.context_evidence_ids
            + self.condition_boundary_evidence_ids
        )
        if any(not value.strip() or len(value) > 128 for value in selected):
            raise ValueError("Evidence IDs must be non-empty and at most 128 characters")
        if self.abstention_reason is not None:
            if (
                (self.statement or "").strip()
                or self.assertion_strength is not None
                or selected
                or self.parent_finding_id is not None
            ):
                raise ValueError(
                    "abstention cannot contain a Finding statement or Evidence roles"
                )
            if not any(value.strip() for value in self.limitations):
                raise ValueError("abstention requires an explanation")
            return self
        if not (self.statement or "").strip():
            raise ValueError("Finding statement is required")
        if self.assertion_strength is None:
            raise ValueError("Finding assertion strength is required")
        if not self.supporting_evidence_ids:
            raise PydanticCustomError("finding_supporting_evidence_required", "Finding requires supporting Evidence")
        return self


class CreateFindingDraftArguments(CreateFindingVersionArguments):
    draft_id: str = Field(min_length=1, max_length=128)


class CreateFindingDraftCapability:
    spec = ToolSpec(
        name="create_finding_draft",
        description=(
            "Record one transient research-conclusion draft for researcher review. "
            "The draft names Evidence from one published Objective version but does "
            "not validate those bindings, publish a Finding, or change any existing "
            "record. Use the separate approved Finding write only after inspecting "
            "and validating the exact Evidence."
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
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    *arguments.supporting_evidence_ids,
                    *arguments.contradicting_evidence_ids,
                    *arguments.context_evidence_ids,
                    *arguments.condition_boundary_evidence_ids,
                )
            )
        )
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
                resource_type="evidence",
                resource_id=(
                    f"{arguments.objective_id}:"
                    f"{arguments.source_analysis_version}:{evidence_id}"
                ),
                href=(
                    f"/collections/{context.collection_id}/objectives/"
                    f"{arguments.objective_id}?evidence_id={evidence_id}"
                ),
            )
            for evidence_id in evidence_ids
        )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "draft": draft,
                "persistence": "transient_chat_result",
                "published": False,
                "requires_user_approval": True,
                "requires_evidence_validation": True,
            },
            resource_refs=tuple(refs),
        )


class CreateFindingVersionCapability:
    spec = ToolSpec(
        name="create_finding_version",
        description=(
            "Propose one new researcher-authored Finding, a hybrid Finding derived "
            "from a named parent, or an explicit evidence abstention from the current "
            "published Objective analysis. Use only Evidence IDs returned from that "
            "exact published version and only after inspecting the relevant complete "
            "Finding, Evidence, and Sources. This write requires explicit user approval "
            "and publishes a new immutable analysis version without changing the source "
            "version or parent Finding."
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
        result = await self.finding_authoring_service.create_version(
            collection_id=context.collection_id,
            objective_id=arguments.objective_id,
            source_analysis_version=arguments.source_analysis_version,
            statement=arguments.statement,
            assertion_strength=arguments.assertion_strength,
            supporting_evidence_ids=tuple(arguments.supporting_evidence_ids),
            contradicting_evidence_ids=tuple(arguments.contradicting_evidence_ids),
            context_evidence_ids=tuple(arguments.context_evidence_ids),
            condition_boundary_evidence_ids=tuple(
                arguments.condition_boundary_evidence_ids
            ),
            limitations=tuple(arguments.limitations),
            parent_finding_id=arguments.parent_finding_id,
            abstention_reason=arguments.abstention_reason,
            created_by_user_id=context.user_id,
            created_by_tool_call_id=context.tool_call_id,
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
