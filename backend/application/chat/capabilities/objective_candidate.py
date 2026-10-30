"""User-approved creation of one durable Research Objective candidate."""

from __future__ import annotations

from application.core.objectives import objective_authoring_service

from domain.chat import ToolResultStatus

from pydantic import ConfigDict, Field, field_validator

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.chat.capabilities.objective_proposal import (
    ObjectiveDraftInput,
    ShortText,
)
from application.chat.capabilities.objective_derivation import (
    ObjectiveDerivationBasis,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


class CreateObjectiveCandidateToolRequest(ObjectiveDraftInput):
    model_config = ConfigDict(extra="forbid")

    seed_document_ids: list[ShortText] = Field(default_factory=list, max_length=24)
    excluded_document_ids: list[ShortText] = Field(default_factory=list, max_length=24)
    parent_objective_id: str | None = Field(default=None, max_length=240)
    parent_analysis_version: int | None = Field(default=None, ge=1)
    derivation_basis: list[ObjectiveDerivationBasis] = Field(
        default_factory=list,
        max_length=6,
    )

    @field_validator("seed_document_ids", "excluded_document_ids")
    @classmethod
    def _normalize_document_ids(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))



class CreateObjectiveCandidateCapability:
    spec = ToolSpec(
        name="create_objective_candidate",
        description=(
            "Create one durable Research Objective candidate from an already reviewed "
            "focused draft. The candidate must have exactly one outcome. Seed papers, "
            "when supplied, record where the question came from rather than its full "
            "analysis scope or Evidence. This "
            "write requires explicit backend approval and records the question as "
            "untested; it does not confirm the Objective or start analysis. When this "
            "is a follow-up question, preserve the exact parent Objective, published "
            "analysis version, and derivation basis returned by `derive_objective`."
        ),
        risk=ToolRisk.WRITE,
        input_model=CreateObjectiveCandidateToolRequest,
    )

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: CreateObjectiveCandidateToolRequest,
    ) -> ChatToolResult:
        try:
            objective = await objective_authoring_service.create_chat_assisted_candidate(
                collection_id=context.collection_id,
                user_id=context.user_id,
                tool_call_id=context.tool_call_id,
                **arguments.model_dump(),
            )
        except (ValueError, FileNotFoundError):
            return ChatToolResult(
                tool_call_id=context.tool_call_id, status=ToolResultStatus.FAILED,
                error_code="objective_candidate_rejected",
                error_message="The Objective candidate was rejected. Check its question, single outcome and current published derivation basis.",
            )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={
                "objective_id": objective.objective_id,
                "confirmation_status": objective.confirmation_status,
                "origin": objective.origin,
                "analysis_started": objective.active_analysis_version is not None,
                "research_status": "untested",
            },
            resource_refs=(
                ChatResourceRef(
                    resource_type="research_objective",
                    resource_id=objective.objective_id,
                    href=(
                        f"/collections/{context.collection_id}/objectives/"
                        f"{objective.objective_id}"
                    ),
                ),
            ),
        )


__all__ = [
    "CreateObjectiveCandidateToolRequest",
    "CreateObjectiveCandidateCapability",
]
