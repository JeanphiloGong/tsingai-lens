"""User-approved creation of one durable Research Objective candidate."""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field, field_validator

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.chat.capabilities.objective_proposal import (
    ObjectiveDraftInput,
    ShortText,
    normalize_terms,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


class CreateObjectiveCandidateArguments(ObjectiveDraftInput):
    model_config = ConfigDict(extra="forbid")

    seed_document_ids: list[ShortText] = Field(default_factory=list, max_length=24)
    excluded_document_ids: list[ShortText] = Field(default_factory=list, max_length=24)

    @field_validator("seed_document_ids", "excluded_document_ids")
    @classmethod
    def _normalize_document_ids(cls, values: list[str]) -> list[str]:
        return normalize_terms(values)


class CreateObjectiveCandidateCapability:
    spec = ToolSpec(
        name="create_objective_candidate",
        description=(
            "Create one durable Research Objective candidate from an already reviewed "
            "focused draft. The candidate must have exactly one outcome. Seed papers, "
            "when supplied, are a proposed inspection scope rather than Evidence. This "
            "write requires explicit backend approval and records the question as "
            "untested; it does not confirm the Objective or start analysis."
        ),
        risk=ToolRisk.WRITE,
        input_model=CreateObjectiveCandidateArguments,
    )

    def __init__(self, *, research_objective_service: Any) -> None:
        self.research_objective_service = research_objective_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: CreateObjectiveCandidateArguments,
    ) -> ChatToolResult:
        objective = await self.research_objective_service.create_chat_assisted_candidate(
            collection_id=context.collection_id,
            user_id=context.user_id,
            tool_call_id=context.tool_call_id,
            **arguments.model_dump(),
        )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
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
    "CreateObjectiveCandidateArguments",
    "CreateObjectiveCandidateCapability",
]
