"""User-approved handoff to the canonical collection research process."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.pipeline.collection_build.service import (
    CollectionBuildPreconditionError,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


class StartResearchProcessArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartResearchProcessCapability:
    spec = ToolSpec(
        name="start_research_process",
        description=(
            "Start the canonical literature-collection research process after the "
            "researcher explicitly approves it. Use this for a collection whose "
            "uploaded papers need to be prepared, classified by paper type and role, "
            "screened into a lightweight Paper Map, and synthesized into candidate "
            "research questions. This queues background work and returns immediately. "
            "It does not confirm an Objective, perform Objective-specific Evidence "
            "extraction, or publish a Finding. Use inspect_research_process afterward "
            "to read progress."
        ),
        risk=ToolRisk.WRITE,
        input_model=StartResearchProcessArguments,
    )

    def __init__(
        self,
        *,
        collection_service: Any,
        collection_build_pipeline_service: Any,
    ) -> None:
        self.collection_service = collection_service
        self.collection_build_pipeline_service = collection_build_pipeline_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        _arguments: StartResearchProcessArguments,
    ) -> ChatToolResult:
        collection = await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        if collection.get("paper_count") == 0:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="failed",
                error_code="collection_has_no_papers",
                error_message=(
                    "Upload at least one paper before starting literature analysis."
                ),
            )
        try:
            task = await self.collection_build_pipeline_service.queue_build(
                context.collection_id,
                mode="standard",
            )
        except CollectionBuildPreconditionError:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="failed",
                error_code="collection_has_no_papers",
                error_message=(
                    "Upload at least one paper before starting literature analysis."
                ),
            )
        task_id = str(task["task_id"])
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="queued",
            data={
                "collection_id": context.collection_id,
                "task_id": task_id,
                "status": str(task.get("status") or "queued"),
                "mode": str(task.get("mode") or "standard"),
                "research_scope": "paper_map_and_objective_candidates",
                "objective_analysis_started": False,
            },
            resource_refs=(
                ChatResourceRef(
                    resource_type="collection_build_task",
                    resource_id=task_id,
                    href=f"/collections/{context.collection_id}",
                ),
            ),
        )


__all__ = [
    "StartResearchProcessArguments",
    "StartResearchProcessCapability",
]
