"""User-approved handoff to the canonical collection research process."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


class StartResearchProcessArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[str] = Field(default_factory=list)


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
        document_preparation_service: Any,
    ) -> None:
        self.collection_service = collection_service
        self.document_preparation_service = document_preparation_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        _arguments: StartResearchProcessArguments,
    ) -> ChatToolResult:
        collection = await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        documents = tuple(collection.get("documents") or ())
        if not documents:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="failed",
                error_code="collection_has_no_papers",
                error_message=(
                    "Upload at least one paper before starting literature analysis."
                ),
            )
        available_ids = {
            str(document.get("document_id") or "") for document in documents
        }
        selected_ids = tuple(
            dict.fromkeys(
                str(document_id).strip()
                for document_id in _arguments.document_ids
                if str(document_id).strip()
            )
        ) or tuple(
            str(document.get("document_id") or "") for document in documents
        )
        missing_ids = [
            document_id
            for document_id in selected_ids
            if document_id not in available_ids
        ]
        if missing_ids:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="failed",
                error_code="document_not_found",
                error_message=(
                    "The selected document is not part of this collection: "
                    + ", ".join(missing_ids)
                ),
            )
        queued_tasks = []
        for document_id in selected_ids:
            queued_tasks.append(
                await self.document_preparation_service.queue_document(
                    context.collection_id,
                    document_id,
                    mode="standard",
                )
            )
        tasks = tuple(queued_tasks)
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="queued",
            data={
                "collection_id": context.collection_id,
                "document_ids": list(selected_ids),
                "tasks": tasks,
                "mode": "standard",
                "research_scope": "document_preparation",
                "objective_discovery_started": False,
                "objective_analysis_started": False,
            },
            resource_refs=tuple(
                ChatResourceRef(
                    resource_type="document_preparation_task",
                    resource_id=str(task["task_id"]),
                    href=f"/collections/{context.collection_id}",
                )
                for task in tasks
            ),
        )


__all__ = [
    "StartResearchProcessArguments",
    "StartResearchProcessCapability",
]
