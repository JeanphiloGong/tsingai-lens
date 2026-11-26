"""Thin Agent adapters for Document Source reading use cases."""

from __future__ import annotations

from agent.tools.registry import ToolExecutionContext, ToolSpec
from application.source import agent_source_service as source_service
from domain.chat import ChatToolResult


class ReadSourceCapability:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="read_source",
            description="Read one exact canonical paper Source with bounded pagination.",
            input_model=source_service.ReadSourceToolRequest,
            handler=self.execute,
        )

    async def execute(
        self, context: ToolExecutionContext, arguments: source_service.ReadSourceToolRequest
    ) -> ChatToolResult:
        return await source_service.read_source(
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            document_id=arguments.document_id,
            source_kind=arguments.source_kind,
            source_ref=arguments.source_ref,
            source_version=arguments.source_version,
            offset=arguments.offset,
            limit=arguments.limit,
            tool_call_id=context.tool_call_id,
            max_result_tokens=context.max_result_tokens,
        )


class SearchSourcesCapability:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="search_sources",
            description="Search prepared paper Sources in the current Workspace.",
            input_model=source_service.SearchSourcesToolRequest,
            handler=self.execute,
        )

    async def execute(
        self, context: ToolExecutionContext, arguments: source_service.SearchSourcesToolRequest
    ) -> ChatToolResult:
        return await source_service.search_sources(
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            document_ids=arguments.document_ids,
            match_mode=arguments.match_mode,
            query=arguments.query,
            source_types=arguments.source_types,
            offset=arguments.offset,
            limit=arguments.limit,
            tool_call_id=context.tool_call_id,
            max_result_tokens=context.max_result_tokens,
        )


class InspectDocumentSourcesCapability:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="inspect_document_sources",
            description="Inspect a bounded document Source outline and matching passages.",
            input_model=source_service.InspectDocumentSourcesToolRequest,
            handler=self.execute,
        )

    async def execute(
        self, context: ToolExecutionContext, arguments: source_service.InspectDocumentSourcesToolRequest
    ) -> ChatToolResult:
        return await source_service.inspect_document_sources(
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            document_id=arguments.document_id,
            query=arguments.query,
            source_ref=arguments.source_ref,
            section_id=arguments.section_id,
            source_version=arguments.source_version,
            heading_path=arguments.heading_path,
            source_types=arguments.source_types,
            page=arguments.page,
            offset=arguments.offset,
            limit=arguments.limit,
            tool_call_id=context.tool_call_id,
            max_result_tokens=context.max_result_tokens,
        )


class InspectTableCapability:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="inspect_table",
            description="Inspect a canonical table with complete-row pagination.",
            input_model=source_service.InspectTableToolRequest,
            handler=self.execute,
        )

    async def execute(
        self, context: ToolExecutionContext, arguments: source_service.InspectTableToolRequest
    ) -> ChatToolResult:
        return await source_service.inspect_table(
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            document_id=arguments.document_id,
            table_ref=arguments.table_ref,
            source_version=arguments.source_version,
            row_offset=arguments.row_offset,
            row_limit=arguments.row_limit,
            tool_call_id=context.tool_call_id,
            max_result_tokens=context.max_result_tokens,
        )


__all__ = [
    "InspectDocumentSourcesCapability",
    "InspectTableCapability",
    "ReadSourceCapability",
    "SearchSourcesCapability",
]
