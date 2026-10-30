"""Approved Agent access to the existing human Finding review contracts."""

from __future__ import annotations

from typing import Any, Literal

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.evaluation.finding_feedback_service import parse_curated_finding
from domain.chat import ChatResourceRef, ChatToolResult, ToolResultStatus, ToolRisk
from domain.core import Finding
from domain.core.scientific_fact import SCIENTIFIC_RESULT_DIRECTIONS
from exceptions import (
    RequestInvalidException,
    ResourceConflictException,
    ResourceNotFoundException,
)
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

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


class RecordFindingFeedbackToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=240)
    analysis_version: int = Field(ge=1)
    finding_id: str = Field(min_length=1, max_length=128)
    review_status: ReviewStatus
    issue_type: IssueType = "none"
    note: str | None = Field(default=None, max_length=2_000)


class CurateFindingToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=240)
    analysis_version: int = Field(ge=1)
    finding_id: str = Field(min_length=1, max_length=128)
    curated_status: CurationStatus = "limited"
    curated_finding: dict[str, Any] = Field(
        description=(
            "The complete canonical Finding object read from the published analysis, "
            "with only the researcher-reviewed scientific fields revised. Required "
            "top-level keys include collection_id, objective_id, analysis_version, "
            "finding_id, statement, factors, outcome, direction, assertion_strength, "
            "attribution_scope, synthesis_status, certainty, display_rank, mechanisms, "
            "scientific_context, limitations, paper_contributions, origin, "
            "source_analysis_version, parent_finding_id, created_by_user_id, and "
            "created_by_tool_call_id. Preserve canonical field names and value types; "
            "for example use `limitations` (plural), and keep numeric values numeric. "
            "direction must be one of "
            + ", ".join(sorted(SCIENTIFIC_RESULT_DIRECTIONS))
            + ". For a verified rise-then-fall trend, use mixed and describe the "
            "treatment levels and comparators in statement; non-monotonic is not "
            "a valid direction value. "
            "Identity, "
            "paper coverage, Evidence IDs, and Source relationships must be preserved."
        )
    )
    note: str | None = Field(default=None, max_length=2_000)
    _parsed_finding: Finding | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _validate_complete_finding(self) -> "CurateFindingToolRequest":
        direction = self.curated_finding.get("direction")
        if (
            not isinstance(direction, str)
            or direction not in SCIENTIFIC_RESULT_DIRECTIONS
        ):
            raise ValueError(
                "curated_finding.direction must be one of: "
                + ", ".join(sorted(SCIENTIFIC_RESULT_DIRECTIONS))
            )
        candidate = parse_curated_finding(self.curated_finding)
        self._parsed_finding = candidate
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
        input_model=RecordFindingFeedbackToolRequest,
    )

    def __init__(
        self, *, collection_service: Any, finding_feedback_service: Any
    ) -> None:
        self.collection_service = collection_service
        self.finding_feedback_service = finding_feedback_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: RecordFindingFeedbackToolRequest,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        try:
            feedback = await self.finding_feedback_service.record_feedback(
                collection_id=context.collection_id,
                objective_id=arguments.objective_id,
                analysis_version=arguments.analysis_version,
                finding_id=arguments.finding_id,
                review_status=arguments.review_status,
                issue_type=arguments.issue_type,
                note=arguments.note,
                reviewer=context.user_id,
                user_id=context.user_id,
            )
        except (
            RequestInvalidException,
            ResourceConflictException,
            ResourceNotFoundException,
        ):
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status=ToolResultStatus.FAILED,
                error_code="finding_feedback_rejected",
                error_message="The Finding feedback was rejected. Reopen the current published Finding and review its analysis version.",
            )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={
                "feedback_id": feedback.feedback_id,
                "collection_id": feedback.collection_id,
                "objective_id": feedback.objective_id,
                "analysis_version": feedback.analysis_version,
                "finding_id": feedback.finding_id,
                "review_status": feedback.review_status,
                "issue_type": feedback.issue_type,
                "note": feedback.note,
                "reviewer": feedback.reviewer,
                "created_at": feedback.created_at,
            },
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
        input_model=CurateFindingToolRequest,
    )

    def __init__(
        self, *, collection_service: Any, finding_feedback_service: Any
    ) -> None:
        self.collection_service = collection_service
        self.finding_feedback_service = finding_feedback_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: CurateFindingToolRequest,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        candidate = arguments._parsed_finding
        if candidate is None:  # pragma: no cover - Pydantic runs the validator.
            raise ValueError("curated Finding was not validated")
        if candidate.collection_id != context.collection_id:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status=ToolResultStatus.FAILED,
                error_code="finding_collection_mismatch",
                error_message="The curated Finding belongs to another collection. Reopen the target Finding in the current collection.",
            )
        try:
            curation = await self.finding_feedback_service.record_curation(
                collection_id=context.collection_id,
                objective_id=arguments.objective_id,
                analysis_version=arguments.analysis_version,
                finding_id=arguments.finding_id,
                curated_status=arguments.curated_status,
                curated_finding=candidate,
                note=arguments.note,
                reviewer=context.user_id,
                user_id=context.user_id,
            )
        except (
            RequestInvalidException,
            ResourceConflictException,
            ResourceNotFoundException,
        ):
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status=ToolResultStatus.FAILED,
                error_code="finding_curation_rejected",
                error_message="The Finding curation was rejected. Preserve its identity, published version and paper coverage.",
            )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={
                "curation_id": curation.curation_id,
                "collection_id": curation.collection_id,
                "objective_id": curation.objective_id,
                "analysis_version": curation.analysis_version,
                "finding_id": curation.finding_id,
                "curated_status": curation.curated_status,
                "curated_finding": {
                    "collection_id": curation.curated_finding.collection_id,
                    "objective_id": curation.curated_finding.objective_id,
                    "analysis_version": curation.curated_finding.analysis_version,
                    "finding_id": curation.curated_finding.finding_id,
                    "statement": curation.curated_finding.statement,
                    "factors": list(curation.curated_finding.factors),
                    "outcome": curation.curated_finding.outcome,
                    "direction": curation.curated_finding.direction,
                    "assertion_strength": curation.curated_finding.assertion_strength,
                    "attribution_scope": curation.curated_finding.attribution_scope,
                    "synthesis_status": curation.curated_finding.synthesis_status,
                    "certainty": curation.curated_finding.certainty,
                    "display_rank": curation.curated_finding.display_rank,
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
                        for mechanism in curation.curated_finding.mechanisms
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
                            for attribute in curation.curated_finding.scientific_context.material
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
                            for attribute in curation.curated_finding.scientific_context.sample
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
                            for attribute in curation.curated_finding.scientific_context.process
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
                            for attribute in curation.curated_finding.scientific_context.test
                        ],
                    },
                    "limitations": list(curation.curated_finding.limitations),
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
                        for contribution in curation.curated_finding.paper_contributions
                    ],
                    "origin": curation.curated_finding.origin,
                    "source_analysis_version": curation.curated_finding.source_analysis_version,
                    "parent_finding_id": curation.curated_finding.parent_finding_id,
                    "created_by_user_id": curation.curated_finding.created_by_user_id,
                    "created_by_tool_call_id": curation.curated_finding.created_by_tool_call_id,
                    "created_at": (
                        curation.curated_finding.created_at.isoformat()
                        if curation.curated_finding.created_at
                        else None
                    ),
                    **(
                        {"selection_ids": list(curation.curated_finding.selection_ids)}
                        if curation.curated_finding.selection_ids
                        else {}
                    ),
                    **(
                        {
                            "comparison_group_ids": list(
                                curation.curated_finding.comparison_group_ids
                            )
                        }
                        if curation.curated_finding.comparison_group_ids
                        else {}
                    ),
                    **(
                        {"warnings": list(curation.curated_finding.warnings)}
                        if curation.curated_finding.warnings
                        else {}
                    ),
                },
                "note": curation.note,
                "reviewer": curation.reviewer,
                "updated_at": curation.updated_at,
            },
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
    "CurateFindingToolRequest",
    "CurateFindingCapability",
    "RecordFindingFeedbackToolRequest",
    "RecordFindingFeedbackCapability",
]
