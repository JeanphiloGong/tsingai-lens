"""User-approved handoff to the canonical collection research process."""

from __future__ import annotations

from dataclasses import asdict

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.source import collection_service
from application.source.document_preparation_service import DocumentPreparationService
from application.pipeline.pipeline_run_service import document_preparation_error_message
from domain.chat import ChatResourceRef, ChatToolResult, ToolResultStatus, ToolRisk
from pydantic import BaseModel, ConfigDict, Field


class StartResearchProcessToolRequest(BaseModel):
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
        input_model=StartResearchProcessToolRequest,
    )

    def __init__(
        self,
        *,
        document_preparation_service: DocumentPreparationService,
    ) -> None:
        self.document_preparation_service = document_preparation_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: StartResearchProcessToolRequest,
    ) -> ChatToolResult:
        collection = await collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        documents = tuple(collection.get("documents") or ())
        if not documents:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status=ToolResultStatus.FAILED,
                error_code="collection_has_no_papers",
                error_message=(
                    "Upload at least one paper before starting literature analysis."
                ),
            )
        available_ids = {
            str(document.get("document_id") or "") for document in documents
        }
        requested_ids = tuple(
            dict.fromkeys(
                str(document_id).strip()
                for document_id in arguments.document_ids
                if str(document_id).strip()
            )
        )
        selected_ids = requested_ids or tuple(
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
                status=ToolResultStatus.FAILED,
                error_code="document_not_found",
                error_message=(
                    "The selected document is not part of this collection: "
                    + ", ".join(missing_ids)
                ),
            )
        queued_runs = []
        for document_id in selected_ids:
            queued_runs.append(
                await self.document_preparation_service.queue_document_preparation(
                    context.collection_id,
                    document_id,
                    user_id=context.user_id,
                )
            )
        runs = tuple(queued_runs)
        observations = []
        for run in runs:
            observation = asdict(run)
            observation.update(observation.pop("timestamps"))
            observation["status"] = run.status.value
            observation["errors"] = (
                [document_preparation_error_message(run.current_node)]
                if run.pipeline_name == "document_preparation" and run.errors
                else list(run.errors)
            )
            observation["warnings"] = list(run.warnings)
            observation["stats"].update(
                token_usage=(asdict(run.stats.token_usage) if run.stats.token_usage else None),
                model_usage=[asdict(item) for item in run.stats.model_usage],
                unreported_request_count=run.stats.unreported_request_count,
            )
            nodes = {}
            for node, record in zip(run.nodes, observation["nodes"]):
                record["dependencies"] = list(node.dependencies)
                record["status"] = node.status.value
                record["errors"] = (
                    [document_preparation_error_message(node.name)]
                    if run.pipeline_name == "document_preparation" and node.errors
                    else list(node.errors)
                )
                record["warnings"] = list(node.warnings)
                record["stats"].update(
                    token_usage=(asdict(node.stats.token_usage) if node.stats.token_usage else None),
                    model_usage=[asdict(item) for item in node.stats.model_usage],
                    unreported_request_count=node.stats.unreported_request_count,
                )
                record["timestamps"] = {
                    key: value for key, value in record["timestamps"].items()
                    if value is not None or key in ("started_at", "finished_at")
                }
                nodes[node.name] = record
            observation["nodes"] = nodes
            observations.append(observation)
        scope_is_collection = not requested_ids
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.QUEUED,
            data={
                "collection_id": context.collection_id,
                "document_ids": list(selected_ids),
                "runs": tuple(observations),
                "research_scope": "document_preparation",
                "objective_discovery_started": False,
                "objective_analysis_started": False,
            },
            resource_refs=tuple(
                ChatResourceRef(
                    resource_type="pipeline_run",
                    resource_id=run.run_id,
                    href=f"/collections/{context.collection_id}",
                )
                for run in runs
            ),
            warnings=(
                (
                    f"No document scope was supplied; all {len(selected_ids)} paper(s) "
                    "in the collection were queued for preparation.",
                )
                if scope_is_collection
                else ()
            ),
        )


__all__ = [
    "StartResearchProcessToolRequest",
    "StartResearchProcessCapability",
]
