"""Approved Agent access to the existing human Finding review contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk
from domain.core import Finding


ReviewStatus = Literal["correct", "incorrect", "partial", "unclear"]
IssueType = Literal[
    "none",
    "evidence_not_grounded",
    "missing_evidence",
    "insufficient_evidence",
    "wrong_factor",
    "wrong_outcome",
    "wrong_direction",
    "wrong_context",
    "wrong_mechanism",
    "wrong_attribution",
    "wrong_synthesis",
    "overclaim",
    "unclear_statement",
    "other",
]
CurationStatus = Literal["supported", "limited", "conflicted", "unsupported"]


class RecordFindingFeedbackArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=240)
    analysis_version: int = Field(ge=1)
    finding_id: str = Field(min_length=1, max_length=128)
    review_status: ReviewStatus
    issue_type: IssueType = "none"
    note: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def _validate_decision(self) -> "RecordFindingFeedbackArguments":
        if self.review_status == "correct" and self.issue_type != "none":
            raise ValueError("correct feedback cannot report an issue")
        if self.review_status in {"incorrect", "partial"} and self.issue_type == "none":
            raise ValueError(f"{self.review_status} feedback requires an issue")
        return self


class CurateFindingArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=240)
    analysis_version: int = Field(ge=1)
    finding_id: str = Field(min_length=1, max_length=128)
    curated_status: CurationStatus = "limited"
    curated_finding: dict[str, Any] = Field(
        description=(
            "The complete canonical Finding object read from the published analysis, "
            "with only the researcher-reviewed scientific fields revised. Identity, "
            "paper coverage, Evidence IDs, and Source relationships must be preserved."
        )
    )
    note: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def _validate_complete_finding(self) -> "CurateFindingArguments":
        candidate = Finding.from_mapping(self.curated_finding)
        if candidate.to_record() != self.curated_finding:
            raise ValueError(
                "curated_finding must use the complete canonical Finding contract"
            )
        if candidate.objective_id != self.objective_id:
            raise ValueError("curated Finding belongs to another Objective")
        if candidate.analysis_version != self.analysis_version:
            raise ValueError("curated Finding belongs to another analysis version")
        if candidate.finding_id != self.finding_id:
            raise ValueError("curated Finding identity differs from the target Finding")
        return self


class RecordFindingFeedbackCapability:
    spec = ToolSpec(
        name="record_finding_feedback",
        description=(
            "Record the researcher's review of one existing published Finding using "
            "the same feedback contract as the Finding workbench. Use only after the "
            "Finding and its supporting Sources have been inspected. This write "
            "requires explicit user approval and does not mutate the Finding, Evidence, "
            "or Sources."
        ),
        risk=ToolRisk.WRITE,
        input_model=RecordFindingFeedbackArguments,
    )

    def __init__(self, *, collection_service: Any, finding_feedback_service: Any) -> None:
        self.collection_service = collection_service
        self.finding_feedback_service = finding_feedback_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: RecordFindingFeedbackArguments,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        feedback = await self.finding_feedback_service.record_feedback(
            collection_id=context.collection_id,
            objective_id=arguments.objective_id,
            analysis_version=arguments.analysis_version,
            finding_id=arguments.finding_id,
            review_status=arguments.review_status,
            issue_type=arguments.issue_type,
            note=arguments.note,
            reviewer=context.user_id,
        )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data=feedback.to_record(),
            resource_refs=(
                _finding_ref(
                    context.collection_id,
                    arguments.objective_id,
                    arguments.analysis_version,
                    arguments.finding_id,
                ),
            ),
        )


class CurateFindingCapability:
    spec = ToolSpec(
        name="curate_finding",
        description=(
            "Persist one researcher-approved revision of an existing published "
            "Finding through the same curation contract as the Finding workbench. "
            "First read the exact full Finding and its Evidence, then copy the complete "
            "canonical Finding object and revise only supported scientific fields. "
            "This write requires explicit user approval. It preserves the published "
            "Finding, identity, paper coverage, Evidence IDs, Sources, and lineage."
        ),
        risk=ToolRisk.WRITE,
        input_model=CurateFindingArguments,
    )

    def __init__(self, *, collection_service: Any, finding_feedback_service: Any) -> None:
        self.collection_service = collection_service
        self.finding_feedback_service = finding_feedback_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: CurateFindingArguments,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        candidate = Finding.from_mapping(arguments.curated_finding)
        if candidate.collection_id != context.collection_id:
            raise ValueError("curated Finding belongs to another collection")
        curation = await self.finding_feedback_service.record_curation(
            collection_id=context.collection_id,
            objective_id=arguments.objective_id,
            analysis_version=arguments.analysis_version,
            finding_id=arguments.finding_id,
            curated_status=arguments.curated_status,
            curated_finding=arguments.curated_finding,
            note=arguments.note,
            reviewer=context.user_id,
        )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data=curation.to_record(),
            resource_refs=(
                _finding_ref(
                    context.collection_id,
                    arguments.objective_id,
                    arguments.analysis_version,
                    arguments.finding_id,
                ),
            ),
        )


def _finding_ref(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    finding_id: str,
) -> ChatResourceRef:
    return ChatResourceRef(
        resource_type="finding",
        resource_id=f"{objective_id}:{analysis_version}:{finding_id}",
        href=(
            f"/collections/{collection_id}/objectives/{objective_id}"
            f"?finding_id={finding_id}"
        ),
    )


__all__ = [
    "CurateFindingArguments",
    "CurateFindingCapability",
    "RecordFindingFeedbackArguments",
    "RecordFindingFeedbackCapability",
]
