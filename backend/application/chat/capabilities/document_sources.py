"""Bounded read-only inspection of one prepared paper's Sources."""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, field_validator

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


_SOURCE_CONTENT_LIMIT = 2_500
SourceType = Literal["text", "table", "figure"]


class InspectDocumentSourcesArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=240)
    query: str | None = Field(default=None, max_length=240)
    source_ref: str | None = Field(default=None, max_length=240)
    source_types: list[SourceType] = Field(default_factory=list, max_length=3)
    page: int | None = Field(default=None, ge=1)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=8, ge=1, le=12)

    @field_validator("document_id", "query", "source_ref")
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


class InspectDocumentSourcesCapability:
    spec = ToolSpec(
        name="inspect_document_sources",
        description=(
            "Inspect a bounded page of parsed text, complete table Markdown, and figure "
            "captions from one paper in the current collection. Filter by a phrase, "
            "page, Source type, or exact Source reference. Returned content is quoted "
            "paper Source for inspection, not verified Evidence or a Finding. Continue "
            "with next_offset when more matching Sources remain."
        ),
        risk=ToolRisk.READ,
        input_model=InspectDocumentSourcesArguments,
    )

    def __init__(self, *, collection_service: Any, source_artifact_repository: Any) -> None:
        self.collection_service = collection_service
        self.source_artifact_repository = source_artifact_repository

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: InspectDocumentSourcesArguments,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        document = await self.source_artifact_repository.read_document(
            context.collection_id,
            arguments.document_id,
        )
        if document is None:
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="failed",
                error_code="document_sources_not_ready",
                error_message=(
                    "The requested paper has no prepared Source content in this "
                    "collection. Prepare the paper before inspecting it."
                ),
            )

        sources = [
            *(
                self._text_source(block)
                for block in sorted(document.blocks, key=lambda item: item.block_order)
                if str(block.text or "").strip()
            ),
            *(
                self._table_source(table)
                for table in sorted(document.tables, key=lambda item: item.table_order)
            ),
            *(
                self._figure_source(figure)
                for figure in sorted(document.figures, key=lambda item: item.figure_order)
                if str(figure.caption_text or "").strip()
            ),
        ]
        selected_types = set(arguments.source_types)
        matches = [
            item
            for item in sources
            if (not selected_types or item["source_type"] in selected_types)
            and (arguments.page is None or item["page"] == arguments.page)
            and (
                arguments.source_ref is None
                or item["source_ref"] == arguments.source_ref
            )
            and self._matches_query(item, arguments.query)
        ]
        visible = matches[arguments.offset : arguments.offset + arguments.limit]
        next_offset = arguments.offset + len(visible)
        if next_offset >= len(matches):
            next_offset = None

        refs = [self._document_ref(context.collection_id, document.document_id)]
        refs.extend(
            self._source_ref(context.collection_id, document.document_id, item)
            for item in visible
        )
        warnings: list[str] = []
        if not matches:
            warnings.append(
                "No prepared Source matched these filters; this is not evidence that "
                "the scientific result is absent from the paper."
            )
        omitted = len(matches) - len(visible) - arguments.offset
        if omitted > 0:
            warnings.append(
                f"{omitted} additional matching Source record(s) were omitted from "
                "this bounded page."
            )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "document": {
                    "document_id": document.document_id,
                    "title": str(document.title or "")[:500],
                },
                "query": arguments.query,
                "source_ref": arguments.source_ref,
                "source_types": list(arguments.source_types),
                "page": arguments.page,
                "available_counts": {
                    "text": len(document.blocks),
                    "table": len(document.tables),
                    "figure": len(document.figures),
                },
                "match_total": len(matches),
                "offset": arguments.offset,
                "limit": arguments.limit,
                "next_offset": next_offset,
                "sources": visible,
                "support_is_evidence": False,
            },
            resource_refs=tuple(refs),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _text_source(block: Any) -> dict[str, Any]:
        content, truncated = InspectDocumentSourcesCapability._bounded(block.text)
        return {
            "source_type": "text",
            "source_kind": str(block.block_type or "paragraph"),
            "source_ref": block.block_id,
            "page": block.page,
            "heading_path": block.heading_path,
            "content": content,
            "content_truncated": truncated,
        }

    @staticmethod
    def _table_source(table: Any) -> dict[str, Any]:
        record = table.to_record()
        content, truncated = InspectDocumentSourcesCapability._bounded(
            record["table_markdown"]
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
            "content_truncated": truncated,
        }

    @staticmethod
    def _figure_source(figure: Any) -> dict[str, Any]:
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
            "content_truncated": truncated,
        }

    @staticmethod
    def _bounded(value: Any) -> tuple[str, bool]:
        text = str(value or "").strip()
        return text[:_SOURCE_CONTENT_LIMIT], len(text) > _SOURCE_CONTENT_LIMIT

    @staticmethod
    def _matches_query(item: dict[str, Any], query: str | None) -> bool:
        if not query:
            return True
        searchable = " ".join(
            str(item.get(key) or "")
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
    "InspectDocumentSourcesArguments",
    "InspectDocumentSourcesCapability",
]
