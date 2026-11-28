"""Document-owned Source reading use cases."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any, Literal, Protocol

from agent.application.context_builder import ChatContextBuilder
from domain.chat import ChatResourceRef, ChatToolResult, ToolResultStatus
from document.domain.source import SourceBlock, SourceFigure, SourceTable, build_source_document_tree, SourceDocument, render_markdown_table
from infra.source.artifact_bundle import source_table_payload
from pydantic import BaseModel, ConfigDict, Field, field_validator
from urllib.parse import urlencode

ReadableSourceKind = Literal["text_window", "table", "figure"]
SourceType = Literal["text", "table", "figure"]

_SOURCE_CONTENT_LIMIT = 2_500
_TABLE_CONTENT_LIMIT = 12_000


class DocumentSourceRepository(Protocol):
    async def read(
        self,
        *,
        workspace_id: str,
        document_id: str,
        source_version: str | None,
    ) -> SourceDocument: ...

    async def list(
        self,
        *,
        workspace_id: str,
        document_ids: tuple[str, ...] | None,
    ) -> tuple[SourceDocument, ...]: ...


class SourceReadingError(ValueError):
    """Stable application error for a Source reading request."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SourceLocator:
    document_id: str
    source_kind: ReadableSourceKind
    source_ref: str
    source_type: SourceType
    page: int | None
    heading_path: str | None


@dataclass(frozen=True)
class SourceWindow:
    locator: SourceLocator
    source_version: str
    source_digest: str
    offset: int
    limit: int
    content: str
    next_offset: int | None


@dataclass(frozen=True)
class SourceCandidate:
    locator: SourceLocator
    source_version: str
    source_digest: str
    excerpt: str


@dataclass(frozen=True)
class SourceSearchPage:
    candidates: tuple[SourceCandidate, ...]
    offset: int
    limit: int
    next_offset: int | None


@dataclass(frozen=True)
class TableWindow:
    locator: SourceLocator
    source_version: str
    source_digest: str
    caption: str | None
    column_headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    row_offset: int
    row_limit: int
    document_title: str
    table: SourceTable
    next_row_offset: int | None


@dataclass(frozen=True)
class _ResolvedSource:
    locator: SourceLocator
    content: str
    rows: tuple[tuple[str, ...], ...] | None
    caption: str | None
    column_headers: tuple[str, ...]


class SourceReadingService:
    def __init__(self, repository: DocumentSourceRepository | None = None) -> None:
        if repository is None:
            from document.repositories.document_repository import DocumentRepo

            repository = DocumentRepo
        self.repository = repository

    async def _read_current(
        self,
        *,
        workspace_id: str,
        document_id: str,
        source_version: str | None,
    ) -> tuple[SourceDocument, str]:
        try:
            source = await self.repository.read(
                workspace_id=workspace_id,
                document_id=document_id,
                source_version=source_version,
            )
        except FileNotFoundError as exc:
            raise SourceReadingError("document_sources_not_ready" if exc.args == ("document_sources_not_ready",) else "document_not_found") from exc
        except LookupError as exc:
            raise SourceReadingError("document_sources_not_ready") from exc
        except ValueError as exc:
            if str(exc) == "source_version_changed":
                raise SourceReadingError("source_version_changed") from exc
            raise
        version = str(source.metadata.get("source_fingerprint") or "")
        if not version:
            raise SourceReadingError("document_sources_not_ready")
        if source_version is not None and source_version != version:
            raise SourceReadingError("source_version_changed")
        return source, version

    @staticmethod
    def _resolve(
        source: SourceDocument,
        *,
        source_kind: ReadableSourceKind,
        source_ref: str,
    ) -> _ResolvedSource:
        if source_kind == "text_window":
            item = next(
                (block for block in source.blocks if block.block_id == source_ref),
                None,
            )
            if item is None:
                raise SourceReadingError("source_not_found")
            return _ResolvedSource(
                locator=SourceLocator(
                    source.document_id,
                    source_kind,
                    item.block_id,
                    "text",
                    item.page,
                    item.heading_path,
                ),
                content=item.text,
                rows=None,
                caption=None,
                column_headers=(),
            )
        if source_kind == "table":
            item = next(
                (table for table in source.tables if table.table_id == source_ref),
                None,
            )
            if item is None:
                raise SourceReadingError("source_not_found")
            content = render_markdown_table(
                [list(row) for row in item.table_matrix],
                list(item.column_headers),
                header_row_count=item.header_row_count,
            ) or ""
            return _ResolvedSource(
                locator=SourceLocator(
                    source.document_id,
                    source_kind,
                    item.table_id,
                    "table",
                    item.page,
                    item.heading_path,
                ),
                content=content,
                rows=tuple(item.table_matrix[item.header_row_count :]),
                caption=item.caption_text,
                column_headers=item.column_headers,
            )
        item = next(
            (figure for figure in source.figures if figure.figure_id == source_ref),
            None,
        )
        if item is None:
            raise SourceReadingError("source_not_found")
        return _ResolvedSource(
            locator=SourceLocator(
                source.document_id,
                source_kind,
                item.figure_id,
                "figure",
                item.page,
                item.heading_path,
            ),
            content=item.caption_text or "",
            rows=None,
            caption=item.caption_text,
            column_headers=(),
        )

    async def read_source(
        self,
        *,
        workspace_id: str,
        document_id: str,
        source_kind: ReadableSourceKind,
        source_ref: str,
        source_version: str | None = None,
        offset: int = 0,
        limit: int = 2_500,
    ) -> SourceWindow:
        if offset < 0 or limit < 1:
            raise SourceReadingError("source_offset_out_of_range")
        source, version = await self._read_current(
            workspace_id=workspace_id,
            document_id=document_id,
            source_version=source_version,
        )
        resolved = self._resolve(
            source,
            source_kind=source_kind,
            source_ref=source_ref,
        )
        if offset > len(resolved.content):
            raise SourceReadingError("source_offset_out_of_range")
        content = resolved.content[offset : offset + limit]
        end = offset + len(content)
        return SourceWindow(
            locator=resolved.locator,
            source_version=version,
            source_digest=sha256(resolved.content.encode("utf-8")).hexdigest(),
            offset=offset,
            limit=limit,
            content=content,
            next_offset=end if end < len(resolved.content) else None,
        )

    async def search_sources(
        self,
        *,
        workspace_id: str,
        document_ids: tuple[str, ...] | None,
        query: str,
        match_mode: Literal["any", "all", "phrase"] = "any",
        source_types: tuple[SourceType, ...] = (),
        offset: int = 0,
        limit: int = 8,
    ) -> SourceSearchPage:
        if not query.strip():
            raise SourceReadingError("source_query_required")
        if offset < 0 or limit < 1:
            raise SourceReadingError("source_offset_out_of_range")
        documents = await self.repository.list(
            workspace_id=workspace_id,
            document_ids=document_ids,
        )
        terms = tuple(part.casefold() for part in query.split() if part)
        candidates: list[SourceCandidate] = []
        for document in documents:
            version = str(document.metadata.get("source_fingerprint") or "")
            if not version:
                continue
            items = [
                ("text", block.block_id, block.text, block.page, block.heading_path)
                for block in document.blocks
            ]
            items.extend(
                (
                    "table",
                    table.table_id,
                    render_markdown_table(
                        [list(row) for row in table.table_matrix],
                        list(table.column_headers),
                        header_row_count=table.header_row_count,
                    )
                    or table.caption_text
                    or "",
                    table.page,
                    table.heading_path,
                )
                for table in document.tables
            )
            items.extend(
                ("figure", figure.figure_id, figure.caption_text or "", figure.page, figure.heading_path)
                for figure in document.figures
            )
            for source_type, source_ref, text, page, heading_path in items:
                if source_types and source_type not in source_types:
                    continue
                folded = text.casefold()
                matches = (
                    query.casefold() in folded
                    if match_mode == "phrase"
                    else all(term in folded for term in terms)
                    if match_mode == "all"
                    else any(term in folded for term in terms)
                )
                if not matches:
                    continue
                source_kind: ReadableSourceKind = {
                    "text": "text_window",
                    "table": "table",
                    "figure": "figure",
                }[source_type]
                locator = SourceLocator(
                    document.document_id,
                    source_kind,
                    source_ref,
                    source_type,
                    page,
                    heading_path,
                )
                candidates.append(
                    SourceCandidate(
                        locator=locator,
                        source_version=version,
                        source_digest=sha256(text.encode("utf-8")).hexdigest(),
                        excerpt=text[:240],
                    )
                )
        page = tuple(candidates[offset : offset + limit])
        next_offset = offset + len(page) if offset + len(page) < len(candidates) else None
        return SourceSearchPage(page, offset, limit, next_offset)

    async def inspect_document_sources(
        self, *, workspace_id: str, document_id: str,
        source_version: str | None = None, section_id: str | None = None,
    ) -> tuple[SourceDocument, str, dict[str, str], set[str] | None]:
        document, version = await self._read_current(
            workspace_id=workspace_id, document_id=document_id,
            source_version=source_version,
        )
        tree = build_source_document_tree(
            document=document, blocks=document.blocks, tables=document.tables,
            figures=document.figures, workspace_id=workspace_id,
        )
        sections = {}
        for node in tree.nodes.values():
            if node.node_type in {"section", "references_section"}:
                sections[node.node_id] = " > ".join(node.heading_path)
        if section_id is None:
            return document, version, sections, None
        if section_id not in sections:
            raise SourceReadingError("section_not_found")
        refs = set()
        pending = [section_id]
        while pending:
            node = tree.nodes[pending.pop()]
            if node.source_ref_id is not None:
                refs.add(node.source_ref_id)
            pending.extend(node.child_ids)
        return document, version, sections, refs

    async def inspect_table(
        self,
        *,
        workspace_id: str,
        document_id: str,
        table_ref: str,
        source_version: str | None = None,
        row_offset: int = 0,
        row_limit: int = 20,
    ) -> TableWindow:
        if row_offset < 0 or row_limit < 1:
            raise SourceReadingError("source_offset_out_of_range")
        source, version = await self._read_current(
            workspace_id=workspace_id,
            document_id=document_id,
            source_version=source_version,
        )
        resolved = self._resolve(
            source,
            source_kind="table",
            source_ref=table_ref,
        )
        if resolved.rows is None:
            raise SourceReadingError("source_not_found")
        if row_offset > len(resolved.rows):
            raise SourceReadingError("source_offset_out_of_range")
        rows = resolved.rows[row_offset : row_offset + row_limit]
        next_offset = row_offset + len(rows)
        return TableWindow(
            document_title=source.title, table=next(t for t in source.tables if t.table_id == table_ref),
            locator=resolved.locator,
            source_version=version,
            source_digest=sha256(resolved.content.encode("utf-8")).hexdigest(),
            caption=resolved.caption,
            column_headers=resolved.column_headers,
            rows=rows,
            row_offset=row_offset,
            row_limit=row_limit,
            next_row_offset=next_offset if next_offset < len(resolved.rows) else None,
        )


class InspectDocumentSourcesToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str = Field(min_length=1, max_length=240)
    query: str | None = Field(default=None, max_length=240)
    source_ref: str | None = Field(default=None, min_length=1, max_length=240)
    section_id: str | None = Field(default=None, min_length=1, max_length=500, description="Copy the section_id from the outline; reads its complete subtree.")
    source_version: str | None = Field(default=None, min_length=1, max_length=64)
    heading_path: str | None = Field(
        default=None,
        max_length=1000,
        description="Exact heading_path from the document outline. Reads that section and its subsections; omit to inspect the whole prepared document.",
    )
    source_types: list[SourceType] = Field(default_factory=list, max_length=3)
    page: int | None = Field(default=None, ge=1)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(
        default=200,
        ge=1,
        le=200,
        description="Optional record cap. Omit to read a batch of complete passages fitted to the available context.",
    )

    @field_validator("query", "heading_path")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @field_validator("source_types")
    @classmethod
    def _unique_source_types(cls, values: list[SourceType]) -> list[SourceType]:
        return list(dict.fromkeys(values))


class SearchSourcesToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[str] | None = Field(default=None, min_length=1, description="Omit to search the current workspace; supply IDs to narrow it.")
    match_mode: Literal["any", "all", "phrase"] = Field(default="any", description="Case-insensitive terms; all requires every term somewhere in the same paper, phrase requires an exact phrase.")
    query: str = Field(min_length=1, max_length=240)
    source_types: list[SourceType] = Field(default_factory=list, max_length=3)
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

    @field_validator("source_types")
    @classmethod
    def _unique_source_types(cls, values: list[SourceType]) -> list[SourceType]:
        return list(dict.fromkeys(values))


class InspectTableToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str = Field(min_length=1, max_length=240)
    table_ref: str = Field(min_length=1, max_length=240)
    source_version: str | None = Field(default=None, min_length=1, max_length=64)
    row_offset: int = Field(default=0, ge=0)
    row_limit: int = Field(default=20, ge=1, le=50)



class InspectTableService:

    def format_table(self, *, window: TableWindow, arguments: InspectTableToolRequest,
                     workspace_id: str, tool_call_id: str | None,
                     max_result_tokens: int) -> ChatToolResult:
        table = window.table
        source_version = window.source_version
        record = source_table_payload(table)
        canonical_markdown = (record["table_markdown"] or "").strip()
        digest = window.source_digest
        data_rows = table.table_matrix[table.header_row_count :]
        if arguments.row_offset > 0 and arguments.row_offset >= len(data_rows):
            return ChatToolResult(
                tool_call_id=tool_call_id,
                status=ToolResultStatus.FAILED,
                data={
                    "document_id": window.locator.document_id,
                    "table_ref": table.table_id,
                    "caption": table.caption_text,
                    "page": table.page,
                    "heading_path": table.heading_path,
                    "data_row_count": len(data_rows),
                    "row_offset": arguments.row_offset,
                    "source_digest": digest,
                    "support_is_evidence": False,
                },
                resource_refs=(
                    InspectDocumentSourcesService._source_ref(
                        workspace_id,
                        window.locator.document_id,
                        {"source_ref": table.table_id, "page": table.page},
                    ),
                ),
                error_code="table_row_offset_out_of_range",
                error_message=(
                    "The requested table row offset is outside the data rows. "
                    "Start at row 0 and follow next_row_offset values returned by "
                    "inspect_table."
                ),
            )
        complete_table = (
            arguments.row_offset == 0
            and len(canonical_markdown.encode("utf-8")) <= _TABLE_CONTENT_LIMIT
        )
        if complete_table:
            markdown = canonical_markdown
            returned_row_count = len(data_rows)
            next_row_offset = None
            content_truncated = False
            oversized_row_offset = None
        else:
            headers = list(table.column_headers) or [
                f"column_{index + 1}" for index in range(table.col_count)
            ]
            # Select complete rows only. Rendering a full window and truncating
            # its string can hide the boundary inside a row while the old code
            # advanced past every selected row, making later rows unreachable.
            selected_rows: list[tuple[str, ...]] = []
            oversized_row_offset: int | None = None
            remaining_rows = window.rows
            for relative_index, row in enumerate(remaining_rows[: arguments.row_limit]):
                candidate = (
                    render_markdown_table(
                        [list(item) for item in (*selected_rows, row)],
                        headers,
                        header_row_count=0,
                    )
                    or ""
                )
                if len(candidate.encode("utf-8")) > _TABLE_CONTENT_LIMIT:
                    oversized_row_offset = arguments.row_offset + relative_index
                    break
                selected_rows.append(row)

            # A single pathological row cannot fit the bounded response. Return
            # a preview but keep the continuation at that row; callers can use
            # read_source's character pagination for the complete table content.
            if not selected_rows and oversized_row_offset is not None:
                oversized_markdown = (
                    render_markdown_table(
                        [list(remaining_rows[0])],
                        headers,
                        header_row_count=0,
                    )
                    or ""
                )
                markdown, _ = self._bounded_utf8(
                    oversized_markdown,
                    limit=_TABLE_CONTENT_LIMIT,
                )
                returned_row_count = 0
                next_row_offset = oversized_row_offset
                content_truncated = True
            else:
                markdown = (
                    render_markdown_table(
                        [list(row) for row in selected_rows],
                        headers,
                        header_row_count=0,
                    )
                    or ""
                )
                returned_row_count = len(selected_rows)
                next_row_offset = arguments.row_offset + returned_row_count
                content_truncated = (
                    oversized_row_offset is not None or next_row_offset < len(data_rows)
                )
            if next_row_offset >= len(data_rows):
                next_row_offset = None

        result = ChatToolResult(
            tool_call_id=tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={
                "document_id": window.locator.document_id,
                "document_title": window.document_title,
                "table_ref": table.table_id,
                "source_version": source_version,
                "continuation": {**arguments.model_dump(exclude_none=True), "source_version": source_version, "row_offset": next_row_offset} if next_row_offset is not None else None,
                "caption": table.caption_text,
                "page": table.page,
                "heading_path": table.heading_path,
                "column_headers": list(table.column_headers),
                "data_row_count": len(data_rows),
                "column_count": table.col_count,
                "row_offset": arguments.row_offset,
                "returned_row_count": returned_row_count,
                "next_row_offset": next_row_offset,
                "complete_table": complete_table,
                "content_truncated": content_truncated,
                "oversized_row_offset": oversized_row_offset,
                "table_markdown": markdown,
                "source_digest": digest,
                "support_is_evidence": False,
            },
            resource_refs=(
                InspectDocumentSourcesService._source_ref(
                    workspace_id,
                    window.locator.document_id,
                    {
                        "source_ref": table.table_id,
                        "page": table.page,
                    },
                ),
            ),
            warnings=(
                (
                    "The table window stopped before a row that exceeds the bounded "
                    "response. Continue from next_row_offset; if that offset repeats, "
                    "use read_source character pagination.",
                )
                if oversized_row_offset is not None
                else ()
            ),
        )

        while InspectDocumentSourcesService._result_tokens(result) > max_result_tokens:
            count = result.data["returned_row_count"]
            if count <= 1:
                return ChatToolResult(
                    tool_call_id=tool_call_id, status=ToolResultStatus.FAILED,
                    error_code="table_row_exceeds_budget",
                    error_message="A complete table row and its headers do not fit. Read the canonical table with read_source.",
                    data={"read_arguments": {"document_id": window.locator.document_id, "source_kind": "table",
                                             "source_ref": table.table_id, "source_version": source_version}},
                )
            count -= 1
            next_row_offset = arguments.row_offset + count
            headers = list(table.column_headers) or [f"column_{i+1}" for i in range(table.col_count)]
            markdown = render_markdown_table(
                [list(row) for row in data_rows[arguments.row_offset:next_row_offset]], headers, header_row_count=0,
            ) or ""
            result = replace(result, data={**result.data,
                "returned_row_count": count, "table_markdown": markdown,
                "next_row_offset": next_row_offset, "complete_table": False, "content_truncated": True,
                "continuation": {**arguments.model_dump(exclude_none=True), "source_version": source_version,
                                 "row_offset": next_row_offset},
            })
        return result

    @staticmethod
    def _bounded_utf8(
        value: str,
        *,
        limit: int,
    ) -> tuple[str, bool]:
        text = value
        encoded = text.encode("utf-8")
        if len(encoded) <= limit:
            return text, False
        return encoded[:limit].decode("utf-8", errors="ignore"), True


class InspectDocumentSourcesService:

    def format_outline(self, *, document: SourceDocument, source_version: str,
                       sections_by_id: dict[str, str], selected_refs: set[str] | None,
                       arguments: InspectDocumentSourcesToolRequest, workspace_id: str,
                       tool_call_id: str | None, max_result_tokens: int) -> ChatToolResult:
        sources = [
            *(
                self._text_source(block)
                for block in sorted(document.blocks, key=lambda item: item.block_order)
                if block.text.strip()
            ),
            *(
                self._table_source(table)
                for table in sorted(document.tables, key=lambda item: item.table_order)
            ),
            *(
                self._figure_source(figure)
                for figure in sorted(
                    document.figures, key=lambda item: item.figure_order
                )
                if (figure.caption_text or "").strip()
            ),
        ]
        for source in sources:
            content = source.pop("_canonical_content")
            source.update(
                content=content,
                content_truncated=False,
                canonical_length=len(content),
                estimated_tokens=ChatContextBuilder.estimate_tokens(content),
            )
        for index, source in enumerate(sources, start=1):
            source["source_label"] = f"S{index:03d}"
        sections: dict[str, dict[str, Any]] = {}
        for source in sources:
            heading = " ".join((source["heading_path"] or "").split())
            section = sections.setdefault(
                heading,
                {
                    "heading_path": heading,
                    "pages": [],
                    "source_count": 0,
                    "source_types": [],
                    "first_source_ref": source["source_ref"],
                    "canonical_length": 0,
                    "estimated_tokens": 0,
                },
            )
            section["source_count"] += 1
            section["canonical_length"] += source["canonical_length"]
            section["estimated_tokens"] += source["estimated_tokens"]
            if source["page"] is not None and source["page"] not in section["pages"]:
                section["pages"].append(source["page"])
            if source["source_type"] not in section["source_types"]:
                section["source_types"].append(source["source_type"])
        for heading, section in sections.items():
            section["section_id"] = next(
                (key for key, path in sections_by_id.items() if path == heading), None
            )
        selected_types = set(arguments.source_types)
        matches = [
            item
            for item in sources
            if (selected_refs is None or item["source_ref"] in selected_refs)
            and (not selected_types or item["source_type"] in selected_types)
            and (arguments.page is None or item["page"] == arguments.page)
            and (
                arguments.heading_path is None
                or " ".join((item["heading_path"] or "").split())
                == arguments.heading_path
                or " ".join((item["heading_path"] or "").split()).startswith(arguments.heading_path + " > ")
            )
            and (
                arguments.source_ref is None
                or item["source_ref"] == arguments.source_ref
            )
            and self._matches_query(item, arguments.query)
        ]
        # Keep complete passages together. Reserve space for the outline,
        # Size the complete tool envelope once, including locators and warnings.
        outline = list(sections.values())[:80]
        if arguments.heading_path is not None:
            outline = [section for heading, section in sections.items()
                       if heading == arguments.heading_path
                       or heading.startswith(arguments.heading_path + " > ")][:80]
        if arguments.section_id is not None:
            outline = [section for section in outline if section["first_source_ref"] in selected_refs]
        continuation_args = arguments.model_dump(exclude_none=True, exclude={"offset", "limit"})
        continuation_args["source_version"] = source_version
        visible = list(matches[arguments.offset : arguments.offset + arguments.limit])
        next_offset = arguments.offset + len(visible)
        if next_offset >= len(matches):
            next_offset = None

        refs = [self._document_ref(workspace_id, document.document_id)]
        refs.extend(
            self._source_ref(workspace_id, document.document_id, item)
            for item in visible
        )
        result = ChatToolResult(
            tool_call_id=tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={
                "document": {
                    "document_id": document.document_id,
                    "title": document.title[:500],
                },
                "query": arguments.query,
                "section_id": arguments.section_id,
                "source_version": source_version,
                "continuation": {**continuation_args, "offset": next_offset} if next_offset is not None else None,
                "source_ref": arguments.source_ref,
                "heading_path": arguments.heading_path,
                "source_types": list(arguments.source_types),
                "page": arguments.page,
                "available_counts": {
                    "text": len(document.blocks),
                    "table": len(document.tables),
                    "figure": len(document.figures),
                },
                "prepared_source_pages": sorted(
                    {item["page"] for item in sources if item["page"] is not None},
                    key=str,
                ),
                "document_outline": outline,
                "outline_section_total": len(sections),
                "outline_truncated": len(sections) > len(outline),
                "coverage_note": (
                    "This outline describes prepared Sources, not the original PDF's total pages "
                    "or a completed scientific review. When outline_truncated is false, it lists "
                    "all prepared sections: searching this document cannot retrieve unprepared body sections. "
                    "No keyword matches does not mean no body text. "
                    "Use heading_path and next_offset to inspect relevant sections; verify conditions, "
                    "comparators, measurements and results before completing the requested review."
                ),
                "match_total": len(matches),
                "offset": arguments.offset,
                "limit": arguments.limit,
                "next_offset": next_offset,
                "sources": visible,
                "source_label_to_ref": {
                    source["source_label"]: source["source_ref"] for source in visible
                },
                "batch_token_budget": max_result_tokens,
                "returned_source_count": len(visible),
                "support_is_evidence": False,
            },
            resource_refs=tuple(refs),
        )

        while True:
            result = replace(result, warnings=tuple([
                *(["No prepared Source matched these filters; this is not evidence of scientific absence."]
                  if not matches else []),
                *(["Continue with next_offset for additional matching Sources."]
                  if result.data["next_offset"] is not None else []),
                *(["An oversized Source is listed without its content; read it separately."]
                  if any(source["content_truncated"] for source in visible) else []),
            ]))
            if self._result_tokens(result) <= max_result_tokens:
                return result
            if len(visible) > 1:
                visible.pop()
            elif outline:
                outline.pop()
            elif visible and visible[0]["content"]:
                visible[0] = {
                    **visible[0],
                    "content": "",
                    "content_truncated": True,
                    "reading_note": "Read this oversized Source with read_source or inspect_table.",
                }
            else:
                return ChatToolResult(
                    tool_call_id=tool_call_id,
                    status=ToolResultStatus.FAILED,
                    error_code="source_batch_too_large",
                    error_message="Request this paper individually with an exact Source or narrower section.",
                )
            next_offset = arguments.offset + len(visible)
            result = replace(
                result,
                data={
                    **result.data,
                    "sources": list(visible),
                    "document_outline": list(outline),
                    "source_label_to_ref": {
                        source["source_label"]: source["source_ref"]
                        for source in visible
                    },
                    "outline_truncated": len(sections) > len(outline),
                    "returned_source_count": len(visible),
                    "next_offset": next_offset if next_offset < len(matches) else None,
                    "continuation": {**continuation_args, "offset": next_offset} if next_offset < len(matches) else None,
                },
                resource_refs=(
                    self._document_ref(workspace_id, document.document_id),
                    *(
                        self._source_ref(
                            workspace_id, document.document_id, source
                        )
                        for source in visible
                    ),
                ),
            )
    @staticmethod
    def _result_tokens(result: ChatToolResult) -> int:
        return ChatContextBuilder.estimate_tokens(
            ChatContextBuilder.tool_result_message(result)
        )

    @staticmethod
    def _source_label_for_document(document: SourceDocument, source_ref: str) -> str:
        refs = [
            block.block_id
            for block in sorted(document.blocks, key=lambda item: item.block_order)
            if block.text.strip()
        ]
        refs.extend(
            table.table_id
            for table in sorted(document.tables, key=lambda item: item.table_order)
        )
        refs.extend(
            figure.figure_id
            for figure in sorted(document.figures, key=lambda item: item.figure_order)
            if (figure.caption_text or "").strip()
        )
        try:
            return f"S{refs.index(source_ref) + 1:03d}"
        except ValueError:
            return ""

    @staticmethod
    def _text_source(block: SourceBlock) -> dict[str, Any]:
        content, truncated = InspectDocumentSourcesService._bounded(block.text)
        return {
            "source_type": "text",
            # `source_kind` is the stable Evidence locator kind. Keep the
            # parser-specific block type as separate display metadata.
            "source_kind": "text_window",
            "block_type": block.block_type,
            "source_ref": block.block_id,
            "page": block.page,
            "heading_path": block.heading_path,
            "content": content,
            "_canonical_content": block.text,
            "content_truncated": truncated,
            "source_digest": hashlib.sha256(block.text.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def _table_source(table: SourceTable) -> dict[str, Any]:
        record = source_table_payload(table)
        # Empty parser tables are still valid navigation records. Keep their
        # canonical content representation stable instead of letting the
        # digest path call ``encode`` on ``None``.
        canonical_markdown = (record["table_markdown"] or "").strip()
        content, truncated = InspectDocumentSourcesService._bounded(
            canonical_markdown
        )
        return {
            "source_type": "table",
            "source_kind": "table",
            "source_ref": table.table_id,
            "page": table.page,
            "heading_path": table.heading_path,
            "caption": table.caption_text,
            "row_count": table.row_count,
            "column_count": table.col_count,
            "content": content,
            "_canonical_content": canonical_markdown,
            "content_truncated": truncated,
            "source_digest": hashlib.sha256(
                canonical_markdown.encode("utf-8")
            ).hexdigest(),
        }

    @staticmethod
    def _figure_source(figure: SourceFigure) -> dict[str, Any]:
        content, truncated = InspectDocumentSourcesService._bounded(
            figure.caption_text
        )
        return {
            "source_type": "figure",
            "source_kind": "figure",
            "source_ref": figure.figure_id,
            "page": figure.page,
            "heading_path": figure.heading_path,
            "figure_label": figure.figure_label,
            "content": content,
            "_canonical_content": (figure.caption_text or ""),
            "content_truncated": truncated,
            "source_digest": hashlib.sha256(
                (figure.caption_text or "").encode("utf-8")
            ).hexdigest(),
        }

    @staticmethod
    def _bounded(
        value: str | None,
        *,
        limit: int = _SOURCE_CONTENT_LIMIT,
    ) -> tuple[str, bool]:
        text = (value or "").strip()
        return text[:limit], len(text) > limit

    @staticmethod
    def _matches_query(item: dict[str, Any], query: str | None) -> bool:
        if not query:
            return True
        searchable = " ".join(
            (item.get(key) or "")
            for key in ("heading_path", "caption", "figure_label", "content")
        ).casefold()
        normalized = query.casefold()
        return normalized in searchable or all(
            term in searchable for term in normalized.split()
        )

    @staticmethod
    def _document_ref(workspace_id: str, document_id: str) -> ChatResourceRef:
        return ChatResourceRef(
            resource_type="document",
            resource_id=document_id,
            href=f"/workspaces/{workspace_id}/documents/{document_id}",
        )

    @staticmethod
    def _source_ref(
        workspace_id: str,
        document_id: str,
        source: dict[str, Any],
    ) -> ChatResourceRef:
        query = {
            "view": "parsed-paper",
            "source_ref": source["source_ref"],
        }
        if source.get("page") is not None:
            query["page"] = str(source["page"])
        return ChatResourceRef(
            resource_type="source",
            resource_id=f"{document_id}:{source['source_ref']}",
            href=(
                f"/workspaces/{workspace_id}/documents/{document_id}?"
                f"{urlencode(query)}"
            ),
        )




__all__ = [
    "DocumentSourceRepository",
    "InspectDocumentSourcesToolRequest",
    "InspectDocumentSourcesService",
    "InspectTableToolRequest",
    "InspectTableService",
    "ReadableSourceKind",
    "SourceCandidate",
    "SourceLocator",
    "SourceReadingError",
    "SourceReadingService",
    "SourceSearchPage",
    "SourceType",
    "SourceWindow",
    "TableWindow",
]
