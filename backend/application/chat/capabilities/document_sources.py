"""Bounded read-only inspection of one prepared paper's Sources."""

from __future__ import annotations

from application.source import collection_service
from repositories.source_artifact_repository import SourceArtifactRepo

import hashlib
import json
from dataclasses import asdict, replace
from typing import Any, Literal
from urllib.parse import urlencode

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.chat.context_builder import ChatContextBuilder
from domain.chat import ChatResourceRef, ChatToolResult, ToolResultStatus, ToolRisk
from domain.source import (
    SourceBlock,
    SourceDocument,
    SourceFigure,
    SourceTable,
    render_markdown_table,
    build_source_document_tree,
)
from exceptions import ResourceNotFoundException
from infra.source.artifact_bundle import source_table_payload
from pydantic import BaseModel, ConfigDict, Field, field_validator

_SOURCE_CONTENT_LIMIT = 2_500
_SEARCH_CONTENT_LIMIT = 800
_TABLE_CONTENT_LIMIT = 12_000
_READ_SOURCE_CONTENT_LIMIT = 12_000
SourceType = Literal["text", "table", "figure"]
ReadableSourceKind = Literal["text_window", "table", "figure"]


async def _unavailable_document_sources(
    context: CapabilityExecutionContext,
    document_ids: list[str],
) -> ChatToolResult:
    missing = []
    for document_id in document_ids:
        try:
            await collection_service.get_document(context.collection_id, document_id)
        except ResourceNotFoundException:
            missing.append(document_id)
    return ChatToolResult(
        tool_call_id=context.tool_call_id,
        status=ToolResultStatus.FAILED,
        error_code="document_not_found" if missing else "document_sources_not_ready",
        error_message=(
            "These document identifiers are not in this collection. Use browse_collection_papers "
            "to locate the papers and copy their exact document_id; this does not establish "
            "that the papers lack Source content."
            if missing
            else "These papers exist, but their canonical Source content is not prepared."
        ),
        data={
            "missing_document_ids": missing,
            "unprepared_document_ids": [
                item for item in document_ids if item not in missing
            ],
        },
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

    document_ids: list[str] | None = Field(default=None, min_length=1, description="Omit to search the current collection; supply IDs to narrow it.")
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


class ReadSourceToolRequest(BaseModel):
    """Identify one canonical Source and request a bounded exact excerpt."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str = Field(min_length=1, max_length=240)
    source_kind: ReadableSourceKind
    source_ref: str = Field(min_length=1, max_length=240)
    source_version: str | None = Field(default=None, min_length=1, max_length=64)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(
        default=_READ_SOURCE_CONTENT_LIMIT, ge=1, le=_READ_SOURCE_CONTENT_LIMIT
    )


class ReadSourceCapability:
    spec = ToolSpec(
        name="read_source",
        description=(
            "Read one exact canonical paper Source by document, Source kind, and "
            "Source reference. The returned content is the complete Source when it "
            "fits the bounded result, with its stable authoring source_label (S001, "
            "S002, ...) and source_ref, a stable digest, and continuation offset "
            "for oversized text. Use the source_label, not source_ref, when citing "
            "PaperExperiment evidence. This is the source-reading step for Evidence; "
            "it does not itself create Evidence or a Finding. Use inspect_table for "
            "row-aware inspection of an oversized table."
        ),
        risk=ToolRisk.READ,
        input_model=ReadSourceToolRequest,
        parallel_safe=True,
    )

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: ReadSourceToolRequest,
    ) -> ChatToolResult:
        await collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        document = await SourceArtifactRepo.read_document(
            context.collection_id,
            arguments.document_id,
        )
        if document is None:
            return await _unavailable_document_sources(
                context, [arguments.document_id]
            )

        source_version = hashlib.sha256(json.dumps(asdict(document), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if arguments.source_version is not None and arguments.source_version != source_version:
            return ChatToolResult(
                tool_call_id=context.tool_call_id, status=ToolResultStatus.FAILED,
                error_code="source_version_changed",
                error_message="Prepared Source changed. Inspect the current outline before continuing an old position.",
                data={"document_id": document.document_id, "source_version": source_version},
            )

        source = self._source_record(document, arguments)
        if source is None:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status=ToolResultStatus.FAILED,
                error_code="source_not_found",
                error_message="The requested canonical Source was not found in this paper.",
            )
        source["source_label"] = (
            InspectDocumentSourcesCapability._source_label_for_document(
                document, source["source_ref"]
            )
        )

        canonical_content = source.pop("_canonical_content")
        digest = hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()
        canonical_length = len(canonical_content)
        source_ref = InspectDocumentSourcesCapability._source_ref(
            context.collection_id,
            document.document_id,
            source,
        )
        if arguments.offset > 0 and arguments.offset >= canonical_length:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status=ToolResultStatus.FAILED,
                data={
                    **source,
                    "document_id": document.document_id,
                    "requested_offset": arguments.offset,
                    "canonical_length": canonical_length,
                    "source_digest": digest,
                    "support_is_evidence": False,
                },
                resource_refs=(source_ref,),
                error_code="source_offset_out_of_range",
                error_message=(
                    "The requested offset is outside the canonical Source content. "
                    "Start at offset 0 and follow the next_offset values returned by "
                    "read_source."
                ),
            )

        start = arguments.offset
        end = min(start + arguments.limit, canonical_length)
        content = canonical_content[start:end]
        next_offset = end if end < canonical_length else None
        complete_source = start == 0 and next_offset is None
        warnings: list[str] = []
        if not complete_source:
            warnings.append(
                "The Source content is paginated; use next_offset to read the "
                "remaining canonical content before drafting Evidence."
            )
        result = ChatToolResult(
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={
                **source,
                "document_id": document.document_id,
                "document_title": document.title[:500],
                "content": content,
                "content_offset": start,
                "canonical_length": canonical_length,
                "next_offset": next_offset,
                "complete_source": complete_source,
                "content_truncated": not complete_source,
                "source_digest": digest,
                "support_is_evidence": False,
            },
            resource_refs=(source_ref,),
            warnings=tuple(warnings),
        )
        if (
            InspectDocumentSourcesCapability._result_tokens(result)
            > context.max_result_tokens
        ):
            low, high = start, end
            while low < high:
                candidate_end = (low + high + 1) // 2
                candidate = replace(
                    result,
                    data={
                        **result.data,
                        "content": canonical_content[start:candidate_end],
                        "next_offset": candidate_end,
                        "complete_source": False,
                        "content_truncated": True,
                    },
                    warnings=(
                        "Continue at next_offset before treating this Source as completely read.",
                    ),
                )
                if (
                    InspectDocumentSourcesCapability._result_tokens(candidate)
                    <= context.max_result_tokens
                ):
                    low = candidate_end
                else:
                    high = candidate_end - 1
            if low == start:
                return ChatToolResult(
                    tool_call_id=context.tool_call_id,
                    status=ToolResultStatus.FAILED,
                    error_code="source_batch_too_large",
                    error_message="Read this Source individually to leave room for its content and locator.",
                )
            result = replace(
                result,
                data={
                    **result.data,
                    "content": canonical_content[start:low],
                    "next_offset": low,
                    "complete_source": False,
                    "content_truncated": True,
                },
                warnings=(
                    "Continue at next_offset before treating this Source as completely read.",
                ),
            )
        return replace(result, data={**result.data, "source_version": source_version,
            "continuation": {**arguments.model_dump(exclude_none=True), "source_version": source_version,
                             "offset": result.data["next_offset"]} if result.data["next_offset"] is not None else None})

    @staticmethod
    def _source_record(
        document: SourceDocument, arguments: ReadSourceToolRequest
    ) -> dict[str, Any] | None:
        if arguments.source_kind == "text_window":
            item = next(
                (
                    block
                    for block in document.blocks
                    if block.block_id == arguments.source_ref
                ),
                None,
            )
            if item is None:
                return None
            return {
                "source_type": "text",
                "source_kind": "text_window",
                "source_ref": item.block_id,
                "page": item.page,
                "heading_path": item.heading_path,
                "block_type": item.block_type,
                "_canonical_content": item.text,
            }
        if arguments.source_kind == "table":
            item = next(
                (
                    table
                    for table in document.tables
                    if table.table_id == arguments.source_ref
                ),
                None,
            )
            if item is None:
                return None
            record = source_table_payload(item)
            return {
                "source_type": "table",
                "source_kind": "table",
                "source_ref": item.table_id,
                "page": item.page,
                "heading_path": item.heading_path,
                "caption": item.caption_text,
                "row_count": item.row_count,
                "column_count": item.col_count,
                "_canonical_content": (record["table_markdown"] or "").strip(),
            }
        item = next(
            (
                figure
                for figure in document.figures
                if figure.figure_id == arguments.source_ref
            ),
            None,
        )
        if item is None:
            return None
        return {
            "source_type": "figure",
            "source_kind": "figure",
            "source_ref": item.figure_id,
            "page": item.page,
            "heading_path": item.heading_path,
            "figure_label": item.figure_label,
            "_canonical_content": (item.caption_text or ""),
        }


class SearchSourcesCapability:
    spec = ToolSpec(
        name="search_sources",
        description=(
            "Search the current collection for paper content; omit document_ids for the whole collection. "
            "Use match_mode to match any terms, all terms across a paper, or an exact phrase. "
            "Returns ranked papers and passages around actual hits with exact reading arguments. "
            "Results are bounded, paginated navigation candidates with "
            "canonical Source digests. A match is not Evidence and does not prove "
            "relevance; inspect the exact Source before making a scientific judgment."
        ),
        risk=ToolRisk.READ,
        input_model=SearchSourcesToolRequest,
        parallel_safe=True,
    )

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: SearchSourcesToolRequest,
    ) -> ChatToolResult:
        await collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        try:
            documents = (
                await SourceArtifactRepo.read_collection_documents(context.collection_id)
                if arguments.document_ids is None else
                await SourceArtifactRepo.read_documents(context.collection_id, tuple(arguments.document_ids))
            )
        except FileNotFoundError:
            return await _unavailable_document_sources(
                context, arguments.document_ids or []
            )
        documents_by_id = {document.document_id: document for document in documents}
        missing = [
            document_id
            for document_id in arguments.document_ids or []
            if document_id not in documents_by_id
        ]
        if missing:
            return await _unavailable_document_sources(
                context, missing
            )

        selected_types = set(arguments.source_types)
        matches: list[dict[str, Any]] = []
        terms = list(dict.fromkeys(arguments.query.casefold().split()))
        paper_scores: dict[str, tuple[int, int]] = {}
        for document in documents:
            document_id = document.document_id
            source_version = hashlib.sha256(json.dumps(asdict(document), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            tree = build_source_document_tree(document=document, blocks=document.blocks, tables=document.tables, figures=document.figures)
            sections = {" > ".join(node.heading_path): node.node_id for node in tree.nodes.values()
                        if node.node_type in {"section", "references_section"}}
            paper_terms = {term for term in terms if term in document.title.casefold()}
            title_terms = len(paper_terms)
            paper_start = len(matches)
            candidates = (
                *(
                    (InspectDocumentSourcesCapability._text_source(block), block.text)
                    for block in sorted(
                        document.blocks, key=lambda item: item.block_order
                    )
                    if block.text.strip()
                ),
                *(
                    (
                        InspectDocumentSourcesCapability._table_source(table),
                        (source_table_payload(table)["table_markdown"] or "").strip(),
                    )
                    for table in sorted(
                        document.tables, key=lambda item: item.table_order
                    )
                ),
                *(
                    (
                        InspectDocumentSourcesCapability._figure_source(figure),
                        (figure.caption_text or ""),
                    )
                    for figure in sorted(
                        document.figures, key=lambda item: item.figure_order
                    )
                    if (figure.caption_text or "").strip()
                ),
            )
            for item, canonical_content in candidates:
                item.pop("_canonical_content", None)
                searchable_item = {**item, "content": canonical_content}
                if selected_types and item["source_type"] not in selected_types:
                    continue
                searchable = " ".join(str(searchable_item.get(key) or "") for key in ("heading_path", "caption", "figure_label", "content")).casefold()
                matched = [term for term in terms if term in searchable]
                paper_terms.update(matched)
                if not matched or (arguments.match_mode == "phrase" and arguments.query.casefold() not in searchable):
                    continue
                positions = [canonical_content.casefold().find(term) for term in matched]
                positions = [position for position in positions if position >= 0]
                offset = max(0, min(positions) - 160) if positions else 0
                content = canonical_content[offset:offset + _SEARCH_CONTENT_LIMIT]
                matches.append({
                    **item, "document_id": document_id, "document_title": document.title[:500],
                    "content": content, "content_offset": offset,
                    "content_truncated": offset > 0 or offset + len(content) < len(canonical_content),
                    "matched_terms": matched, "section_id": sections.get(item.get("heading_path")),
                    "source_version": source_version, "support_is_evidence": False,
                    "read_arguments": {"document_id": document_id, "source_kind": item["source_kind"],
                                       "source_ref": item["source_ref"], "source_version": source_version},
                })
            if arguments.match_mode == "all" and len(paper_terms) != len(terms):
                del matches[paper_start:]
                continue
            paper_scores[document_id] = (len(paper_terms), title_terms)
        matches.sort(key=lambda item: (*paper_scores[item["document_id"]], len(item["matched_terms"])), reverse=True)
        papers = []
        for document_id in sorted(paper_scores, key=paper_scores.get, reverse=True):
            hits = [item for item in matches if item["document_id"] == document_id]
            if hits:
                papers.append({"document_id": document_id, "title": documents_by_id[document_id].title[:500],
                               "matching_source_count": len(hits),
                               "matched_terms": sorted({term for item in hits for term in item["matched_terms"]})})

        visible = matches[arguments.offset : arguments.offset + arguments.limit]
        next_offset = arguments.offset + len(visible)
        if next_offset >= len(matches):
            next_offset = None
        warnings: list[str] = []
        if not matches:
            warnings.append(
                "No prepared Source matched this query; this does not establish "
                "scientific absence."
            )
        if next_offset is not None:
            warnings.append(
                f"{len(matches) - next_offset} additional matching Source record(s) "
                "remain on later pages."
            )
        result = ChatToolResult(
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={
                "query": arguments.query,
                "document_ids": arguments.document_ids,
                "match_mode": arguments.match_mode,
                "papers": papers[:100],
                "source_types": list(arguments.source_types),
                "match_total": len(matches),
                "offset": arguments.offset,
                "limit": arguments.limit,
                "next_offset": next_offset,
                "matches": visible,
                "support_is_evidence": False,
            },
            resource_refs=tuple(
                InspectDocumentSourcesCapability._source_ref(
                    context.collection_id,
                    item["document_id"],
                    item,
                )
                for item in visible
            ),
            warnings=tuple(warnings),
        )

        while InspectDocumentSourcesCapability._result_tokens(result) > context.max_result_tokens:
            if len(visible) > 1:
                visible.pop()
            elif result.data["papers"]:
                result = replace(result, data={**result.data, "papers": result.data["papers"][:-1]})
            else:
                return ChatToolResult(tool_call_id=context.tool_call_id, status=ToolResultStatus.FAILED,
                                      error_code="source_batch_too_large",
                                      error_message="Narrow the search scope to fit one Source preview.")
            next_offset = arguments.offset + len(visible)
            result = replace(result, data={**result.data, "matches": list(visible),
                                          "next_offset": next_offset if next_offset < len(matches) else None},
                             resource_refs=tuple(InspectDocumentSourcesCapability._source_ref(
                                 context.collection_id, item["document_id"], item) for item in visible))
        return result


class InspectTableCapability:
    spec = ToolSpec(
        name="inspect_table",
        description=(
            "Read one exact canonical paper table as Markdown. Lens returns the whole "
            "table when it fits the bounded result; only oversized tables are split "
            "into header-preserving row windows. The complete-table digest remains "
            "stable across windows. A table read is Source inspection, not Evidence."
        ),
        risk=ToolRisk.READ,
        input_model=InspectTableToolRequest,
        parallel_safe=True,
    )

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: InspectTableToolRequest,
    ) -> ChatToolResult:
        await collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        document = await SourceArtifactRepo.read_document(
            context.collection_id,
            arguments.document_id,
        )
        if document is None:
            return await _unavailable_document_sources(
                context, [arguments.document_id]
            )
        source_version = hashlib.sha256(json.dumps(asdict(document), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if arguments.source_version is not None and arguments.source_version != source_version:
            return ChatToolResult(
                tool_call_id=context.tool_call_id, status=ToolResultStatus.FAILED,
                error_code="source_version_changed",
                error_message="Prepared Source changed. Inspect the current outline before continuing an old position.",
                data={"document_id": document.document_id, "source_version": source_version},
            )

        table = next(
            (item for item in document.tables if item.table_id == arguments.table_ref),
            None,
        )
        if table is None:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status=ToolResultStatus.FAILED,
                error_code="table_source_not_found",
                error_message="The requested table Source was not found in this paper.",
            )

        record = source_table_payload(table)
        canonical_markdown = (record["table_markdown"] or "").strip()
        digest = hashlib.sha256(canonical_markdown.encode("utf-8")).hexdigest()
        data_rows = table.table_matrix[table.header_row_count :]
        if arguments.row_offset > 0 and arguments.row_offset >= len(data_rows):
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status=ToolResultStatus.FAILED,
                data={
                    "document_id": document.document_id,
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
                    InspectDocumentSourcesCapability._source_ref(
                        context.collection_id,
                        document.document_id,
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
            remaining_rows = data_rows[arguments.row_offset :]
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
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={
                "document_id": document.document_id,
                "document_title": document.title,
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
                InspectDocumentSourcesCapability._source_ref(
                    context.collection_id,
                    document.document_id,
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

        while InspectDocumentSourcesCapability._result_tokens(result) > context.max_result_tokens:
            count = result.data["returned_row_count"]
            if count <= 1:
                return ChatToolResult(
                    tool_call_id=context.tool_call_id, status=ToolResultStatus.FAILED,
                    error_code="table_row_exceeds_budget",
                    error_message="A complete table row and its headers do not fit. Read the canonical table with read_source.",
                    data={"read_arguments": {"document_id": document.document_id, "source_kind": "table",
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


class InspectDocumentSourcesCapability:
    spec = ToolSpec(
        name="inspect_document_sources",
        description=(
            "Read a context-sized batch of complete paper passages, tables and captions, with a section outline and length estimates. "
            "Each returned Source includes its stable authoring label (S001, S002, ...); "
            "copy that source_label exactly into PaperExperiment source_labels and binding "
            "fields, never combine it with source_ref. The response also includes a "
            "source_label_to_ref map for the returned batch. Select a heading or page and omit "
            "limit for automatic batching; continue with next_offset, and use read_source "
            "for any oversized truncated Source."
        ),
        risk=ToolRisk.READ,
        input_model=InspectDocumentSourcesToolRequest,
        parallel_safe=True,
    )

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: InspectDocumentSourcesToolRequest,
    ) -> ChatToolResult:
        await collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        document = await SourceArtifactRepo.read_document(
            context.collection_id,
            arguments.document_id,
        )
        if document is None:
            return await _unavailable_document_sources(
                context, [arguments.document_id]
            )

        source_version = hashlib.sha256(json.dumps(asdict(document), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if arguments.source_version is not None and arguments.source_version != source_version:
            return ChatToolResult(
                tool_call_id=context.tool_call_id, status=ToolResultStatus.FAILED,
                error_code="source_version_changed",
                error_message="Prepared Source changed. Inspect the current outline before continuing an old position.",
                data={"document_id": document.document_id, "source_version": source_version},
            )

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
        tree = build_source_document_tree(document=document, blocks=document.blocks, tables=document.tables,
                                          figures=document.figures, collection_id=context.collection_id)
        section_nodes = {node.node_id: node for node in tree.nodes.values()
                         if node.node_type in {"section", "references_section"}}
        for heading, section in sections.items():
            node = next((node for node in section_nodes.values() if " > ".join(node.heading_path) == heading), None)
            section["section_id"] = node.node_id if node else None
        selected_refs = None
        if arguments.section_id is not None:
            if arguments.section_id not in section_nodes:
                return ChatToolResult(
                    tool_call_id=context.tool_call_id, status=ToolResultStatus.FAILED,
                    error_code="section_not_found", error_message="Copy an exact section_id from the current outline.",
                    data={"document_id": document.document_id, "source_version": source_version,
                          "document_outline": list(sections.values())[:80]},
                )
            selected_refs = set()
            pending = [arguments.section_id]
            while pending:
                node = tree.nodes[pending.pop()]
                if node.source_ref_id is not None:
                    selected_refs.add(node.source_ref_id)
                pending.extend(node.child_ids)
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

        refs = [self._document_ref(context.collection_id, document.document_id)]
        refs.extend(
            self._source_ref(context.collection_id, document.document_id, item)
            for item in visible
        )
        result = ChatToolResult(
            tool_call_id=context.tool_call_id,
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
                "batch_token_budget": context.max_result_tokens,
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
            if self._result_tokens(result) <= context.max_result_tokens:
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
                    tool_call_id=context.tool_call_id,
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
                    self._document_ref(context.collection_id, document.document_id),
                    *(
                        self._source_ref(
                            context.collection_id, document.document_id, source
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
        content, truncated = InspectDocumentSourcesCapability._bounded(block.text)
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
        content, truncated = InspectDocumentSourcesCapability._bounded(
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
        content, truncated = InspectDocumentSourcesCapability._bounded(
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
    def _document_ref(collection_id: str, document_id: str) -> ChatResourceRef:
        return ChatResourceRef(
            resource_type="document",
            resource_id=document_id,
            href=f"/collections/{collection_id}/documents/{document_id}",
        )

    @staticmethod
    def _source_ref(
        collection_id: str,
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
                f"/collections/{collection_id}/documents/{document_id}?"
                f"{urlencode(query)}"
            ),
        )


__all__ = [
    "InspectDocumentSourcesToolRequest",
    "InspectDocumentSourcesCapability",
    "InspectTableToolRequest",
    "InspectTableCapability",
    "ReadSourceToolRequest",
    "ReadSourceCapability",
    "SearchSourcesToolRequest",
    "SearchSourcesCapability",
]
