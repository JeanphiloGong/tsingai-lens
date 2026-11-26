"""User-approved handoff to the canonical workspace research process."""

from __future__ import annotations

from dataclasses import asdict

from agent.tools.registry import (
    ToolExecutionContext,
    ToolSpec,
)
from application.source import workspace_service
from application.source.document_preparation_service import queue_document_preparation
from application.pipeline.pipeline_run_service import document_preparation_error_message
from domain.chat import ChatResourceRef, ChatToolResult, ToolResultStatus
from pydantic import BaseModel, ConfigDict, Field


class StartResearchProcessToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[str] = Field(default_factory=list)


class StartResearchProcessCapability:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="start_research_process",
            description=(
                "Start the canonical literature-workspace research process after the "
                "researcher explicitly approves it. Use this for a workspace whose "
                "uploaded papers need to be prepared, classified by paper type and role, "
                "screened into a lightweight Paper Map, and synthesized into candidate "
                "research questions. This queues background work and returns immediately. "
                "It does not confirm an Objective, perform Objective-specific Evidence "
                "extraction, or publish a Finding. Use inspect_research_process afterward "
                "to read progress."
            ),
            handler=self.execute,
            requires_approval=True,
            input_model=StartResearchProcessToolRequest,
        )


    async def execute(
        self,
        context: ToolExecutionContext,
        arguments: StartResearchProcessToolRequest,
    ) -> ChatToolResult:
        workspace = await workspace_service.get_workspace_for_user(
            context.workspace_id,
            context.user_id,
        )
        documents = workspace.documents
        if not documents:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status=ToolResultStatus.FAILED,
                error_code="workspace_has_no_papers",
                error_message=(
                    "Upload at least one paper before starting literature analysis."
                ),
            )
        available_ids = {str(document.document.document_id or "") for document in documents}
        requested_ids = tuple(
            dict.fromkeys(
                str(document_id).strip()
                for document_id in arguments.document_ids
                if str(document_id).strip()
            )
        )
        selected_ids = requested_ids or tuple(
            str(document.document.document_id or "") for document in documents
        )
        missing_ids = [
            document_id for document_id in selected_ids if document_id not in available_ids
        ]
        if missing_ids:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status=ToolResultStatus.FAILED,
                error_code="document_not_found",
                error_message=(
                    "The selected document is not part of this workspace: "
                    + ", ".join(missing_ids)
                ),
            )
        queued_runs = []
        for document_id in selected_ids:
            queued_runs.append(
                await queue_document_preparation(
                    context.workspace_id,
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
                token_usage=(
                    asdict(run.stats.token_usage) if run.stats.token_usage else None
                ),
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
                    token_usage=(
                        asdict(node.stats.token_usage) if node.stats.token_usage else None
                    ),
                    model_usage=[asdict(item) for item in node.stats.model_usage],
                    unreported_request_count=node.stats.unreported_request_count,
                )
                record["timestamps"] = {
                    key: value
                    for key, value in record["timestamps"].items()
                    if value is not None or key in ("started_at", "finished_at")
                }
                nodes[node.name] = record
            observation["nodes"] = nodes
            observations.append(observation)
        scope_is_workspace = not requested_ids
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.QUEUED,
            data={
                "workspace_id": context.workspace_id,
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
                    href=f"/workspaces/{context.workspace_id}",
                )
                for run in runs
            ),
            warnings=(
                (
                    f"No document scope was supplied; all {len(selected_ids)} paper(s) "
                    "in the workspace were queued for preparation.",
                )
                if scope_is_workspace
                else ()
            ),
        )


__all__ = [
    "StartResearchProcessToolRequest",
    "StartResearchProcessCapability",
]
