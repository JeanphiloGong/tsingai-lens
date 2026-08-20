"""Bounded collection and Objective context for the Research Agent."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


_OBJECTIVE_LIMIT = 12


class GetCollectionContextArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetCollectionContextCapability:
    spec = ToolSpec(
        name="get_collection_context",
        description=(
            "Read a bounded overview of the current literature collection and its "
            "Research Objective candidates. Use this before making collection-specific "
            "claims or proposing new Objective drafts."
        ),
        risk=ToolRisk.READ,
        input_model=GetCollectionContextArguments,
    )

    def __init__(self, *, collection_service: Any, objective_repository: Any) -> None:
        self.collection_service = collection_service
        self.objective_repository = objective_repository

    def execute(
        self,
        context: CapabilityExecutionContext,
        _arguments: GetCollectionContextArguments,
    ) -> ChatToolResult:
        collection = self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        objectives = self.objective_repository.list_objectives(context.collection_id)
        visible = objectives[:_OBJECTIVE_LIMIT]
        objective_records = [self._objective_summary(item) for item in visible]
        omitted = len(objectives) - len(visible)
        warnings = (
            (f"{omitted} additional Objectives were omitted from this bounded result.",)
            if omitted
            else ()
        )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "collection": {
                    "collection_id": str(collection["collection_id"]),
                    "name": str(collection.get("name") or "")[:240],
                    "description": (
                        str(collection["description"])[:1_000]
                        if collection.get("description")
                        else None
                    ),
                    "status": str(collection.get("status") or "unknown"),
                    "paper_count": int(collection.get("paper_count") or 0),
                },
                "objective_count": len(objectives),
                "objectives": objective_records,
            },
            resource_refs=(
                ChatResourceRef(
                    resource_type="collection",
                    resource_id=context.collection_id,
                    href=f"/collections/{context.collection_id}",
                ),
                *(
                    ChatResourceRef(
                        resource_type="research_objective",
                        resource_id=item.objective_id,
                        href=(
                            f"/collections/{context.collection_id}/objectives/"
                            f"{item.objective_id}"
                        ),
                    )
                    for item in visible
                ),
            ),
            warnings=warnings,
        )

    @staticmethod
    def _objective_summary(objective: Any) -> dict[str, Any]:
        return {
            "objective_id": objective.objective_id,
            "question": objective.question[:500],
            "material_scope": list(objective.material_scope[:6]),
            "variables": list(objective.variables[:6]),
            "outcomes": list(objective.outcomes[:3]),
            "confirmation_status": objective.confirmation_status,
            "published_analysis_version": objective.published_analysis_version,
            "confidence": objective.confidence,
        }


__all__ = ["GetCollectionContextArguments", "GetCollectionContextCapability"]
