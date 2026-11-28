"""Thin Agent adapters for Document application use cases."""

from __future__ import annotations

from application.source import workspace_service
from application.source.agent_source_service import (
    InspectDocumentSourcesService, InspectDocumentSourcesToolRequest,
    InspectTableService, InspectTableToolRequest,
)
from typing import Literal

from agent.tools.registry import ToolExecutionContext, ToolSpec
from document.application.source_reading import (
    SourceReadingError,
    SourceReadingService,
    SourceSearchPage,
    SourceWindow,
)
from document.repositories.profile_repository import ProfileRepo, ProfileRepository
from domain.chat import ChatToolResult, ToolResultStatus
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReadSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str = Field(min_length=1, max_length=240)
    source_kind: Literal["text_window", "table", "figure"]
    source_ref: str = Field(min_length=1, max_length=240)
    source_version: str | None = Field(default=None, min_length=1, max_length=64)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=2_500, ge=1, le=2_500)


class SearchSourcesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_ids: list[str] | None = Field(default=None, min_length=1)
    query: str = Field(min_length=1, max_length=240)
    match_mode: Literal["any", "all", "phrase"] = "any"
    source_types: list[Literal["text", "table", "figure"]] = Field(default_factory=list, max_length=3)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=8, ge=1, le=12)

    @field_validator("document_ids")
    @classmethod
    def _unique_document_ids(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("document IDs cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("document IDs must be unique")
        return normalized

    @field_validator("query")
    @classmethod
    def _normalize_query(cls, value: str) -> str:
        return " ".join(value.split())


class ListDocumentProfilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str | None = Field(default=None, max_length=240)
    doc_type: Literal["experimental", "review", "mixed", "uncertain"] | None = None
    limit: int = Field(default=20, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def _normalize_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None


def _failed(context: ToolExecutionContext, error: SourceReadingError, document_id: str | None = None) -> ChatToolResult:
    return ChatToolResult(
        tool_call_id=context.tool_call_id,
        status=ToolResultStatus.FAILED,
        error_code=error.code,
        error_message=error.code,
        data={
            "missing_document_ids": [document_id] if error.code == "document_not_found" else [],
            "unprepared_document_ids": [document_id] if error.code == "document_sources_not_ready" else [],
        } if document_id and error.code in {"document_not_found", "document_sources_not_ready"} else {},
    )


def _source_window_data(result: SourceWindow) -> dict[str, object]:
    locator = result.locator
    return {
        "document_id": locator.document_id,
        "source_kind": locator.source_kind,
        "source_ref": locator.source_ref,
        "source_type": locator.source_type,
        "source_version": result.source_version,
        "source_digest": result.source_digest,
        "offset": result.offset,
        "limit": result.limit,
        "content": result.content,
        "next_offset": result.next_offset,
    }


def _search_page_data(result: SourceSearchPage) -> dict[str, object]:
    return {
        "offset": result.offset,
        "limit": result.limit,
        "next_offset": result.next_offset,
        "candidates": [
            {
                "document_id": item.locator.document_id,
                "source_kind": item.locator.source_kind,
                "source_ref": item.locator.source_ref,
                "source_type": item.locator.source_type,
                "source_version": item.source_version,
                "source_digest": item.source_digest,
                "excerpt": item.excerpt,
                "page": item.locator.page,
                "heading_path": item.locator.heading_path,
            }
            for item in result.candidates
        ],
    }


class ReadSourceCapability:
    def __init__(self, reading: SourceReadingService | None = None) -> None:
        self.reading = reading or SourceReadingService()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="read_source",
            description="Read one exact canonical paper Source with bounded pagination.",
            input_model=ReadSourceInput,
            handler=self.execute,
        )

    async def execute(self, context: ToolExecutionContext, arguments: ReadSourceInput) -> ChatToolResult:
        await workspace_service.get_workspace_for_user(context.workspace_id, context.user_id)
        try:
            result = await self.reading.read_source(
                workspace_id=context.workspace_id,
                document_id=arguments.document_id,
                source_kind=arguments.source_kind,
                source_ref=arguments.source_ref,
                source_version=arguments.source_version,
                offset=arguments.offset,
                limit=arguments.limit,
            )
        except SourceReadingError as error:
            return _failed(context, error)
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data=_source_window_data(result),
        )


class SearchSourcesCapability:
    def __init__(self, reading: SourceReadingService | None = None) -> None:
        self.reading = reading or SourceReadingService()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="search_sources",
            description="Search prepared paper Sources in the current Workspace.",
            input_model=SearchSourcesInput,
            handler=self.execute,
        )

    async def execute(self, context: ToolExecutionContext, arguments: SearchSourcesInput) -> ChatToolResult:
        await workspace_service.get_workspace_for_user(context.workspace_id, context.user_id)
        try:
            result = await self.reading.search_sources(
                workspace_id=context.workspace_id,
                document_ids=tuple(arguments.document_ids) if arguments.document_ids is not None else None,
                query=arguments.query,
                match_mode=arguments.match_mode,
                source_types=tuple(arguments.source_types),
                offset=arguments.offset,
                limit=arguments.limit,
            )
        except SourceReadingError as error:
            return _failed(context, error)
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data=_search_page_data(result),
        )


class ListDocumentProfilesCapability:
    def __init__(self, profiles: ProfileRepository | None = None) -> None:
        self.profiles = profiles or ProfileRepo

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="list_document_profiles",
            description="Find prepared documents by type and navigation description.",
            input_model=ListDocumentProfilesInput,
            handler=self.execute,
        )

    async def execute(self, context: ToolExecutionContext, arguments: ListDocumentProfilesInput) -> ChatToolResult:
        await workspace_service.get_workspace_for_user(context.workspace_id, context.user_id)
        profiles = await self.profiles.list_workspace(context.workspace_id)
        query = arguments.query.casefold() if arguments.query else None
        items = [
            profile
            for profile in profiles
            if (query is None or query in profile.description.casefold())
            and (arguments.doc_type is None or profile.doc_type == arguments.doc_type)
        ][: arguments.limit]
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={
                "documents": [
                    {
                        "document_id": item.document_id,
                        "doc_type": item.doc_type,
                        "description": item.description,
                        "source_fingerprint": item.source_fingerprint,
                    }
                    for item in items
                ]
            },
        )


class InspectDocumentSourcesCapability:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="inspect_document_sources",
            description="Inspect a bounded document Source outline and matching passages.",
            input_model=InspectDocumentSourcesToolRequest,
            handler=self.execute,
        )

    async def execute(self, context: ToolExecutionContext,
                      arguments: InspectDocumentSourcesToolRequest) -> ChatToolResult:
        await workspace_service.get_workspace_for_user(context.workspace_id, context.user_id)
        try:
            document, version, sections, refs = await SourceReadingService().inspect_document_sources(
                workspace_id=context.workspace_id, document_id=arguments.document_id,
                source_version=arguments.source_version, section_id=arguments.section_id,
            )
        except SourceReadingError as exc:
            return _failed(context, exc, arguments.document_id)
        return InspectDocumentSourcesService().format_outline(
            document=document, source_version=version, sections_by_id=sections,
            selected_refs=refs, arguments=arguments, workspace_id=context.workspace_id,
            tool_call_id=context.tool_call_id, max_result_tokens=context.max_result_tokens,
        )


class InspectTableCapability:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="inspect_table",
            description="Inspect a canonical table with complete-row pagination.",
            input_model=InspectTableToolRequest,
            handler=self.execute,
        )

    async def execute(self, context: ToolExecutionContext,
                      arguments: InspectTableToolRequest) -> ChatToolResult:
        await workspace_service.get_workspace_for_user(context.workspace_id, context.user_id)
        try:
            window = await SourceReadingService().inspect_table(
                workspace_id=context.workspace_id, **arguments.model_dump()
            )
        except SourceReadingError as exc:
            if exc.code in {"document_not_found", "document_sources_not_ready"}:
                return _failed(context, exc, arguments.document_id)
            code = {
                "source_not_found": "table_source_not_found",
                "source_offset_out_of_range": "table_row_offset_out_of_range",
            }.get(exc.code, exc.code)
            return ChatToolResult(tool_call_id=context.tool_call_id,
                                  status=ToolResultStatus.FAILED, error_code=code,
                                  error_message=code)
        return InspectTableService().format_table(
            window=window, arguments=arguments, workspace_id=context.workspace_id,
            tool_call_id=context.tool_call_id, max_result_tokens=context.max_result_tokens,
        )

__all__ = [
    "InspectDocumentSourcesCapability",
    "InspectTableCapability",
    "ListDocumentProfilesCapability",
    "ListDocumentProfilesInput",
    "ReadSourceCapability",
    "ReadSourceInput",
    "SearchSourcesCapability",
    "SearchSourcesInput",
]
