"""Thin Agent adapters for Workspace screening use cases."""

from __future__ import annotations

from agent.tools.registry import ToolExecutionContext, ToolSpec
from application.source import agent_workspace_service as workspace_service
from domain.chat import ChatToolResult


class GetWorkspaceContextCapability:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="get_workspace_context",
            description="Read bounded Workspace and Objective navigation context.",
            input_model=workspace_service.GetWorkspaceContextToolRequest,
            handler=self.execute,
        )

    async def execute(
        self, context: ToolExecutionContext, arguments: workspace_service.GetWorkspaceContextToolRequest
    ) -> ChatToolResult:
        return await workspace_service.get_workspace_context(
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            tool_call_id=context.tool_call_id,
            max_result_tokens=context.max_result_tokens,
        )


class BrowseWorkspacePapersCapability:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="browse_workspace_papers",
            description="Browse bounded paper screening signals in the current Workspace.",
            input_model=workspace_service.BrowseWorkspacePapersToolRequest,
            handler=self.execute,
        )

    async def execute(
        self, context: ToolExecutionContext, arguments: workspace_service.BrowseWorkspacePapersToolRequest
    ) -> ChatToolResult:
        return await workspace_service.browse_workspace_papers(
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            query=arguments.query,
            offset=arguments.offset,
            limit=arguments.limit,
            tool_call_id=context.tool_call_id,
            max_result_tokens=context.max_result_tokens,
        )


__all__ = ["BrowseWorkspacePapersCapability", "GetWorkspaceContextCapability"]
