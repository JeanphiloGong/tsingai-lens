"""Document-owned Source reading use cases."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, Protocol

from domain.source import SourceDocument, render_markdown_table

ReadableSourceKind = Literal["text_window", "table", "figure"]
SourceType = Literal["text", "table", "figure"]


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
            from repositories.source_artifact_repository import SourceArtifactRepo

            repository = SourceArtifactRepo
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
            raise SourceReadingError("document_not_found") from exc
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


__all__ = [
    "DocumentSourceRepository",
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
