"""Approved Agent access to canonical researcher Finding authoring."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    source_analysis_version: int = Field(ge=1)
    statement: str | None = Field(default=None, max_length=3_000)
    assertion_strength: FindingAssertionStrength | None = None
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    contradicting_evidence_ids: list[str] = Field(
        default_factory=list, max_length=100
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
            raise ValueError("Finding requires supporting Evidence")
        return self


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
        )


__all__ = [
    "CreateFindingVersionArguments",
    "CreateFindingVersionCapability",
]
