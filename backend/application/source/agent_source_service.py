"""Bounded read-only inspection of one prepared paper's Sources."""

from __future__ import annotations

from application.source import workspace_service
from document.application.source_reading import (
    InspectDocumentSourcesService, InspectDocumentSourcesToolRequest,
    InspectTableService, InspectTableToolRequest, TableWindow,
)
from document.repositories.source_repository import SourceRepo

import hashlib
import json
from dataclasses import asdict, replace
from typing import Any, Literal
from urllib.parse import urlencode

from agent.application.context_builder import ChatContextBuilder
from domain.chat import ChatResourceRef, ChatToolResult, ToolResultStatus
from document.domain.source import (
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
    *,
    workspace_id: str,
    tool_call_id: str | None,
    document_ids: list[str],
) -> ChatToolResult:
    missing = []
    for document_id in document_ids:
        try:
            await workspace_service.get_document(workspace_id, document_id)
        except ResourceNotFoundException:
            missing.append(document_id)
    return ChatToolResult(
        tool_call_id=tool_call_id,
        status=ToolResultStatus.FAILED,
        error_code="document_not_found" if missing else "document_sources_not_ready",
        error_message=(
            "These document identifiers are not in this workspace. Use browse_workspace_papers "
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


class ReadSourceService:

    async def execute(
        self,
        *,
        user_id: str,
        workspace_id: str,
        tool_call_id: str | None,
        max_result_tokens: int,
        arguments: ReadSourceToolRequest,
    ) -> ChatToolResult:
        await workspace_service.get_workspace_for_user(
            workspace_id,
            user_id,
        )
        document = await SourceRepo.read_document(
            workspace_id,
            arguments.document_id,
        )
        if document is None:
            return await _unavailable_document_sources(
                workspace_id=workspace_id, tool_call_id=tool_call_id,
                document_ids=[arguments.document_id],
            )

        source_version = hashlib.sha256(json.dumps(asdict(document), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if arguments.source_version is not None and arguments.source_version != source_version:
            return ChatToolResult(
                tool_call_id=tool_call_id, status=ToolResultStatus.FAILED,
                error_code="source_version_changed",
                error_message="Prepared Source changed. Inspect the current outline before continuing an old position.",
                data={"document_id": document.document_id, "source_version": source_version},
            )

        source = self._source_record(document, arguments)
        if source is None:
            return ChatToolResult(
                tool_call_id=tool_call_id,
                status=ToolResultStatus.FAILED,
                error_code="source_not_found",
                error_message="The requested canonical Source was not found in this paper.",
            )
        source["source_label"] = (
            InspectDocumentSourcesService._source_label_for_document(
                document, source["source_ref"]
            )
        )

        canonical_content = source.pop("_canonical_content")
        digest = hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()
        canonical_length = len(canonical_content)
        source_ref = InspectDocumentSourcesService._source_ref(
            workspace_id,
            document.document_id,
            source,
        )
        if arguments.offset > 0 and arguments.offset >= canonical_length:
            return ChatToolResult(
                tool_call_id=tool_call_id,
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
            tool_call_id=tool_call_id,
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
                "source_version": source_version,
                "continuation": {**arguments.model_dump(exclude_none=True), "source_version": source_version,
                                 "offset": next_offset} if next_offset is not None else None,
                "support_is_evidence": False,
            },
            resource_refs=(source_ref,),
            warnings=tuple(warnings),
        )
        if (
            InspectDocumentSourcesService._result_tokens(result)
            > max_result_tokens
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
                        "continuation": {**arguments.model_dump(exclude_none=True), "source_version": source_version,
                                         "offset": candidate_end},
                        "complete_source": False,
                        "content_truncated": True,
                    },
                    warnings=(
                        "Continue at next_offset before treating this Source as completely read.",
                    ),
                )
                if (
                    InspectDocumentSourcesService._result_tokens(candidate)
                    <= max_result_tokens
                ):
                    low = candidate_end
                else:
                    high = candidate_end - 1
            if low == start:
                return ChatToolResult(
                    tool_call_id=tool_call_id,
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
                    "continuation": {**arguments.model_dump(exclude_none=True), "source_version": source_version,
                                     "offset": low},
                    "complete_source": False,
                    "content_truncated": True,
                },
                warnings=(
                    "Continue at next_offset before treating this Source as completely read.",
                ),
            )
        return result

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


class SearchSourcesService:

    async def execute(
        self,
        *,
        user_id: str,
        workspace_id: str,
        tool_call_id: str | None,
        max_result_tokens: int,
        arguments: SearchSourcesToolRequest,
    ) -> ChatToolResult:
        await workspace_service.get_workspace_for_user(
            workspace_id,
            user_id,
        )
        try:
            documents = (
                await SourceRepo.read_workspace_documents(workspace_id)
                if arguments.document_ids is None else
                await SourceRepo.read_documents(workspace_id, tuple(arguments.document_ids))
            )
        except FileNotFoundError:
            return await _unavailable_document_sources(
                workspace_id=workspace_id, tool_call_id=tool_call_id,
                document_ids=arguments.document_ids or [],
            )
        documents_by_id = {document.document_id: document for document in documents}
        missing = [
            document_id
            for document_id in arguments.document_ids or []
            if document_id not in documents_by_id
        ]
        if missing:
            return await _unavailable_document_sources(
                workspace_id=workspace_id, tool_call_id=tool_call_id,
                document_ids=missing,
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
                    (InspectDocumentSourcesService._text_source(block), block.text)
                    for block in sorted(
                        document.blocks, key=lambda item: item.block_order
                    )
                    if block.text.strip()
                ),
                *(
                    (
                        InspectDocumentSourcesService._table_source(table),
                        (source_table_payload(table)["table_markdown"] or "").strip(),
                    )
                    for table in sorted(
                        document.tables, key=lambda item: item.table_order
                    )
                ),
                *(
                    (
                        InspectDocumentSourcesService._figure_source(figure),
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
        paper_hits = []
        for document_id in sorted(paper_scores, key=paper_scores.get, reverse=True):
            hits = [item for item in matches if item["document_id"] == document_id]
            if hits:
                paper_hits.append(hits)
                papers.append({"document_id": document_id, "title": documents_by_id[document_id].title[:500],
                               "matching_source_count": len(hits),
                               "matched_terms": sorted({term for item in hits for term in item["matched_terms"]})})
        # Surface each ranked paper before returning additional passages from
        # the same paper, so a long paper cannot hide the rest of the corpus.
        matches = [hits[index] for index in range(max((len(hits) for hits in paper_hits), default=0))
                   for hits in paper_hits if index < len(hits)]

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
            tool_call_id=tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={
                "query": arguments.query,
                "document_ids": arguments.document_ids,
                "match_mode": arguments.match_mode,
                "papers": [paper for paper in papers
                           if paper["document_id"] in {item["document_id"] for item in visible}],
                "matching_paper_total": len(papers),
                "source_types": list(arguments.source_types),
                "match_total": len(matches),
                "offset": arguments.offset,
                "limit": arguments.limit,
                "next_offset": next_offset,
                "matches": visible,
                "support_is_evidence": False,
            },
            resource_refs=tuple(
                InspectDocumentSourcesService._source_ref(
                    workspace_id,
                    item["document_id"],
                    item,
                )
                for item in visible
            ),
            warnings=tuple(warnings),
        )

        while InspectDocumentSourcesService._result_tokens(result) > max_result_tokens:
            if len(visible) > 1:
                visible.pop()
            elif result.data["papers"]:
                result = replace(result, data={**result.data, "papers": result.data["papers"][:-1]})
            else:
                return ChatToolResult(tool_call_id=tool_call_id, status=ToolResultStatus.FAILED,
                                      error_code="source_batch_too_large",
                                      error_message="Narrow the search scope to fit one Source preview.")
            next_offset = arguments.offset + len(visible)
            result = replace(result, data={**result.data, "matches": list(visible),
                                          "next_offset": next_offset if next_offset < len(matches) else None},
                             resource_refs=tuple(InspectDocumentSourcesService._source_ref(
                                 workspace_id, item["document_id"], item) for item in visible))
        return result


__all__ = [
    "InspectDocumentSourcesToolRequest",
    "InspectDocumentSourcesService",
    "InspectTableToolRequest",
    "InspectTableService",
    "ReadSourceToolRequest",
    "ReadSourceService",
    "SearchSourcesToolRequest",
    "SearchSourcesService",
    "read_source",
    "search_sources",
]


async def read_source(
    *,
    user_id: str,
    workspace_id: str,
    document_id: str,
    source_kind: str,
    source_ref: str,
    source_version: str | None,
    offset: int,
    limit: int,
    tool_call_id: str | None,
    max_result_tokens: int = _READ_SOURCE_CONTENT_LIMIT,
) -> ChatToolResult:
    return await ReadSourceService().execute(
        user_id=user_id,
        workspace_id=workspace_id,
        tool_call_id=tool_call_id,
        max_result_tokens=max_result_tokens,
        arguments=ReadSourceToolRequest(
            document_id=document_id,
            source_kind=source_kind,
            source_ref=source_ref,
            source_version=source_version,
            offset=offset,
            limit=limit,
        ),
    )


async def search_sources(
    *,
    user_id: str,
    workspace_id: str,
    document_ids: list[str] | None,
    match_mode: str,
    query: str,
    source_types: list[str],
    offset: int,
    limit: int,
    tool_call_id: str | None,
    max_result_tokens: int = _SOURCE_CONTENT_LIMIT,
) -> ChatToolResult:
    return await SearchSourcesService().execute(
        user_id=user_id,
        workspace_id=workspace_id,
        tool_call_id=tool_call_id,
        max_result_tokens=max_result_tokens,
        arguments=SearchSourcesToolRequest(
            document_ids=document_ids,
            match_mode=match_mode,
            query=query,
            source_types=source_types,
            offset=offset,
            limit=limit,
        ),
    )
