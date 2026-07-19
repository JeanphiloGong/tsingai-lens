from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import re
from typing import Any, Iterable, Literal, Mapping


SourceBlockType = Literal[
    "title",
    "heading",
    "paragraph",
    "list_item",
    "figure_caption",
    "table_caption",
]

SourceDocumentNodeType = Literal[
    "document",
    "section",
    "paragraph",
    "list_item",
    "table",
    "figure",
    "caption",
    "references_section",
    "reference_entry",
]

_UNIT_HINT_PATTERN = re.compile(
    r"\b(MPa|GPa|Pa|%|S/cm|mS/cm|W/mK|wt%|vol%)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceBoundingBox:
    l: float
    t: float
    r: float
    b: float
    coord_origin: str = ""

    @classmethod
    def from_value(cls, value: Any) -> "SourceBoundingBox | None":
        if _is_missing_value(value):
            return None
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            return cls.from_value(json.loads(text))
        if isinstance(value, Mapping):
            return cls(
                l=float(value.get("l", 0.0)),
                t=float(value.get("t", 0.0)),
                r=float(value.get("r", 0.0)),
                b=float(value.get("b", 0.0)),
                coord_origin=str(value.get("coord_origin") or ""),
            )
        return cls(
            l=float(getattr(value, "l", 0.0)),
            t=float(getattr(value, "t", 0.0)),
            r=float(getattr(value, "r", 0.0)),
            b=float(getattr(value, "b", 0.0)),
            coord_origin=str(
                getattr(getattr(value, "coord_origin", None), "value", None) or ""
            ),
        )

    @classmethod
    def merge(cls, values: Iterable[Any]) -> "SourceBoundingBox | None":
        boxes = [box for box in (cls.from_value(value) for value in values) if box]
        if not boxes:
            return None
        return cls(
            l=min(box.l for box in boxes),
            t=min(box.t for box in boxes),
            r=max(box.r for box in boxes),
            b=max(box.b for box in boxes),
            coord_origin=boxes[0].coord_origin,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "l": self.l,
            "t": self.t,
            "r": self.r,
            "b": self.b,
            "coord_origin": self.coord_origin,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=True, sort_keys=True)


@dataclass(frozen=True)
class SourceCharRange:
    start: int
    end: int

    @classmethod
    def from_value(cls, value: Any) -> "SourceCharRange | None":
        if _is_missing_value(value):
            return None
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            return cls.from_value(json.loads(text))
        if isinstance(value, Mapping):
            return cls(start=int(value.get("start", 0)), end=int(value.get("end", 0)))
        start, end = value
        return cls(start=int(start), end=int(end))

    def to_json(self) -> str:
        return json.dumps(
            {"start": self.start, "end": self.end},
            ensure_ascii=True,
            sort_keys=True,
        )


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    human_readable_id: int
    title: str
    text: str
    text_unit_ids: tuple[str, ...] = ()
    creation_date: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "SourceDocument":
        return cls(
            document_id=str(value.get("document_id") or value.get("id") or ""),
            human_readable_id=safe_int(value.get("human_readable_id")) or 0,
            title=str(value.get("title") or ""),
            text=str(value.get("text") or ""),
            text_unit_ids=_string_tuple(value.get("text_unit_ids")),
            creation_date=normalize_optional_text(value.get("creation_date")),
            metadata=_mapping(value.get("metadata")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.document_id,
            "human_readable_id": self.human_readable_id,
            "title": self.title,
            "text": self.text,
            "text_unit_ids": list(self.text_unit_ids),
            "creation_date": self.creation_date,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SourceTextUnit:
    text_unit_id: str
    human_readable_id: int
    text: str
    n_tokens: int | None
    document_ids: tuple[str, ...]

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "SourceTextUnit":
        return cls(
            text_unit_id=str(value.get("text_unit_id") or value.get("id") or ""),
            human_readable_id=safe_int(value.get("human_readable_id")) or 0,
            text=str(value.get("text") or ""),
            n_tokens=safe_int(value.get("n_tokens")),
            document_ids=_string_tuple(value.get("document_ids")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.text_unit_id,
            "human_readable_id": self.human_readable_id,
            "text": self.text,
            "n_tokens": self.n_tokens,
            "document_ids": list(self.document_ids),
        }


@dataclass(frozen=True)
class SourceBlock:
    block_id: str
    document_id: str
    block_type: SourceBlockType | str
    text: str
    block_order: int
    text_unit_ids: tuple[str, ...] = ()
    page: int | None = None
    bbox: SourceBoundingBox | None = None
    char_range: SourceCharRange | None = None
    heading_path: str | None = None
    heading_level: int | None = None

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "SourceBlock":
        return cls(
            block_id=str(value.get("block_id") or ""),
            document_id=str(value.get("document_id") or value.get("id") or ""),
            block_type=str(value.get("block_type") or "paragraph"),
            text=str(value.get("text") or ""),
            block_order=safe_int(value.get("block_order")) or 0,
            text_unit_ids=_string_tuple(value.get("text_unit_ids")),
            page=safe_int(value.get("page")),
            bbox=SourceBoundingBox.from_value(value.get("bbox")),
            char_range=SourceCharRange.from_value(value.get("char_range")),
            heading_path=normalize_optional_text(value.get("heading_path")),
            heading_level=safe_int(value.get("heading_level")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "document_id": self.document_id,
            "block_type": str(self.block_type),
            "text": self.text,
            "block_order": self.block_order,
            "text_unit_ids": list(self.text_unit_ids),
            "page": self.page,
            "bbox": self.bbox.to_json() if self.bbox else None,
            "char_range": self.char_range.to_json() if self.char_range else None,
            "heading_path": self.heading_path,
            "heading_level": self.heading_level,
        }


@dataclass(frozen=True)
class SourceLayoutBlock:
    block_id: str | None
    text: str | None
    page: int | None
    bbox: SourceBoundingBox | None
    block_order: int
    block_type: str
    heading_path: str | None

    @classmethod
    def from_value(
        cls, value: "SourceBlock | Mapping[str, Any]"
    ) -> "SourceLayoutBlock":
        if isinstance(value, SourceBlock):
            return cls(
                block_id=value.block_id,
                text=value.text,
                page=value.page,
                bbox=value.bbox,
                block_order=value.block_order,
                block_type=str(value.block_type),
                heading_path=value.heading_path,
            )
        return cls(
            block_id=normalize_optional_text(value.get("block_id")),
            text=normalize_optional_text(value.get("text")),
            page=safe_int(value.get("page")),
            bbox=SourceBoundingBox.from_value(value.get("bbox")),
            block_order=safe_int(value.get("block_order")) or 0,
            block_type=str(value.get("block_type") or "").strip(),
            heading_path=normalize_optional_text(value.get("heading_path")),
        )


@dataclass(frozen=True)
class SourceTable:
    table_id: str
    document_id: str
    table_order: int
    caption_text: str | None
    caption_block_id: str | None
    page: int | None
    bbox: SourceBoundingBox | None
    heading_path: str | None
    column_headers: tuple[str, ...]
    table_matrix: tuple[tuple[str, ...], ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.table_matrix)

    @property
    def col_count(self) -> int:
        return max((len(row) for row in self.table_matrix), default=0)

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "SourceTable":
        return cls(
            table_id=str(value.get("table_id") or ""),
            document_id=str(value.get("document_id") or ""),
            table_order=safe_int(value.get("table_order")) or 0,
            caption_text=normalize_optional_text(value.get("caption_text")),
            caption_block_id=normalize_optional_text(value.get("caption_block_id")),
            page=safe_int(value.get("page")),
            bbox=SourceBoundingBox.from_value(value.get("bbox")),
            heading_path=normalize_optional_text(value.get("heading_path")),
            column_headers=_string_tuple(value.get("column_headers")),
            table_matrix=_table_matrix_tuple(value.get("table_matrix")),
            metadata=_mapping(value.get("metadata")),
        )

    def to_record(self) -> dict[str, Any]:
        matrix = [list(row) for row in self.table_matrix]
        headers = list(self.column_headers)
        return {
            "table_id": self.table_id,
            "document_id": self.document_id,
            "table_order": self.table_order,
            "caption_text": self.caption_text,
            "caption_block_id": self.caption_block_id,
            "page": self.page,
            "bbox": self.bbox.to_json() if self.bbox else None,
            "heading_path": self.heading_path,
            "row_count": self.row_count,
            "col_count": self.col_count,
            "column_headers": headers,
            "table_matrix": matrix,
            "table_markdown": render_markdown_table(matrix, headers),
            "table_text": render_plain_table_text(matrix),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SourceTableCell:
    cell_id: str
    document_id: str
    table_id: str
    row_index: int
    col_index: int
    cell_text: str
    header_path: str | None = None
    page: int | None = None
    bbox: SourceBoundingBox | None = None
    char_range: SourceCharRange | None = None
    unit_hint: str | None = None

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "SourceTableCell":
        return cls(
            cell_id=str(value.get("cell_id") or ""),
            document_id=str(value.get("document_id") or value.get("id") or ""),
            table_id=str(value.get("table_id") or ""),
            row_index=safe_int(value.get("row_index")) or 0,
            col_index=safe_int(value.get("col_index")) or 0,
            cell_text=str(value.get("cell_text") or ""),
            header_path=normalize_optional_text(value.get("header_path")),
            page=safe_int(value.get("page")),
            bbox=SourceBoundingBox.from_value(value.get("bbox")),
            char_range=SourceCharRange.from_value(value.get("char_range")),
            unit_hint=normalize_optional_text(value.get("unit_hint")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "document_id": self.document_id,
            "id": self.document_id,
            "table_id": self.table_id,
            "row_index": self.row_index,
            "col_index": self.col_index,
            "cell_text": self.cell_text,
            "header_path": self.header_path,
            "page": self.page,
            "bbox": self.bbox.to_json() if self.bbox else None,
            "char_range": self.char_range.to_json() if self.char_range else None,
            "unit_hint": self.unit_hint,
        }


@dataclass(frozen=True)
class SourceTableRow:
    row_id: str
    document_id: str
    table_id: str
    row_index: int
    row_text: str
    page: int | None = None
    bbox: SourceBoundingBox | None = None
    heading_path: str | None = None

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "SourceTableRow":
        return cls(
            row_id=str(value.get("row_id") or ""),
            document_id=str(value.get("document_id") or ""),
            table_id=str(value.get("table_id") or ""),
            row_index=safe_int(value.get("row_index")) or 0,
            row_text=str(value.get("row_text") or ""),
            page=safe_int(value.get("page")),
            bbox=SourceBoundingBox.from_value(value.get("bbox")),
            heading_path=normalize_optional_text(value.get("heading_path")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "document_id": self.document_id,
            "table_id": self.table_id,
            "row_index": self.row_index,
            "row_text": self.row_text,
            "page": self.page,
            "bbox": self.bbox.to_json() if self.bbox else None,
            "heading_path": self.heading_path,
        }


@dataclass(frozen=True)
class SourceFigure:
    figure_id: str
    document_id: str
    figure_order: int
    figure_label: str | None
    caption_text: str | None
    caption_block_id: str | None
    page: int | None
    bbox: SourceBoundingBox | None
    heading_path: str | None
    image_path: str | None
    image_mime_type: str | None
    image_width: int | None
    image_height: int | None
    asset_sha256: str | None
    image_size_bytes: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "SourceFigure":
        return cls(
            figure_id=str(value.get("figure_id") or ""),
            document_id=str(value.get("document_id") or ""),
            figure_order=safe_int(value.get("figure_order")) or 0,
            figure_label=normalize_optional_text(value.get("figure_label")),
            caption_text=normalize_optional_text(value.get("caption_text")),
            caption_block_id=normalize_optional_text(value.get("caption_block_id")),
            page=safe_int(value.get("page")),
            bbox=SourceBoundingBox.from_value(value.get("bbox")),
            heading_path=normalize_optional_text(value.get("heading_path")),
            image_path=normalize_optional_text(value.get("image_path")),
            image_mime_type=normalize_optional_text(value.get("image_mime_type")),
            image_width=safe_int(value.get("image_width")),
            image_height=safe_int(value.get("image_height")),
            asset_sha256=normalize_optional_text(value.get("asset_sha256")),
            image_size_bytes=safe_int(value.get("image_size_bytes")),
            metadata=_mapping(value.get("metadata")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "figure_id": self.figure_id,
            "document_id": self.document_id,
            "figure_order": self.figure_order,
            "figure_label": self.figure_label,
            "caption_text": self.caption_text,
            "caption_block_id": self.caption_block_id,
            "page": self.page,
            "bbox": self.bbox.to_json() if self.bbox else None,
            "heading_path": self.heading_path,
            "image_path": self.image_path,
            "image_mime_type": self.image_mime_type,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "asset_sha256": self.asset_sha256,
            "image_size_bytes": self.image_size_bytes,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SourceArtifactSet:
    documents: tuple[SourceDocument, ...] = ()
    text_units: tuple[SourceTextUnit, ...] = ()
    blocks: tuple[SourceBlock, ...] = ()
    tables: tuple[SourceTable, ...] = ()
    table_rows: tuple[SourceTableRow, ...] = ()
    table_cells: tuple[SourceTableCell, ...] = ()
    figures: tuple[SourceFigure, ...] = ()

    @classmethod
    def from_records(
        cls,
        *,
        documents: Iterable[Mapping[str, Any]] = (),
        text_units: Iterable[Mapping[str, Any]] = (),
        blocks: Iterable[Mapping[str, Any]] = (),
        tables: Iterable[Mapping[str, Any]] = (),
        table_rows: Iterable[Mapping[str, Any]] = (),
        table_cells: Iterable[Mapping[str, Any]] = (),
        figures: Iterable[Mapping[str, Any]] = (),
    ) -> "SourceArtifactSet":
        return cls(
            documents=tuple(SourceDocument.from_record(item) for item in documents),
            text_units=tuple(SourceTextUnit.from_record(item) for item in text_units),
            blocks=tuple(SourceBlock.from_record(item) for item in blocks),
            tables=tuple(SourceTable.from_record(item) for item in tables),
            table_rows=tuple(SourceTableRow.from_record(item) for item in table_rows),
            table_cells=tuple(
                SourceTableCell.from_record(item) for item in table_cells
            ),
            figures=tuple(SourceFigure.from_record(item) for item in figures),
        )

    def is_empty(self) -> bool:
        return not any(
            (
                self.documents,
                self.text_units,
                self.blocks,
                self.tables,
                self.table_rows,
                self.table_cells,
                self.figures,
            )
        )


@dataclass(frozen=True)
class SourceReferenceEntry:
    reference_id: str
    document_id: str
    raw_reference: str
    reference_index: str | None = None
    title: str | None = None
    authors_text: str | None = None
    year: int | None = None
    doi: str | None = None
    source_block_id: str | None = None
    page: int | None = None
    confidence: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "SourceReferenceEntry":
        return cls(
            reference_id=str(value.get("reference_id") or ""),
            document_id=str(value.get("document_id") or ""),
            raw_reference=str(value.get("raw_reference") or ""),
            reference_index=normalize_optional_text(value.get("reference_index")),
            title=normalize_optional_text(value.get("title")),
            authors_text=normalize_optional_text(value.get("authors_text")),
            year=safe_int(value.get("year")),
            doi=normalize_optional_text(value.get("doi")),
            source_block_id=normalize_optional_text(value.get("source_block_id")),
            page=safe_int(value.get("page")),
            confidence=float(value.get("confidence") or 0.0),
            metadata=_mapping(value.get("metadata")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "document_id": self.document_id,
            "raw_reference": self.raw_reference,
            "reference_index": self.reference_index,
            "title": self.title,
            "authors_text": self.authors_text,
            "year": self.year,
            "doi": self.doi,
            "source_block_id": self.source_block_id,
            "page": self.page,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SourceReferenceMention:
    mention_id: str
    document_id: str
    reference_id: str | None
    citation_marker: str
    context_text: str
    source_block_id: str | None = None
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    confidence: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "SourceReferenceMention":
        return cls(
            mention_id=str(value.get("mention_id") or ""),
            document_id=str(value.get("document_id") or ""),
            reference_id=normalize_optional_text(value.get("reference_id")),
            citation_marker=str(value.get("citation_marker") or ""),
            context_text=str(value.get("context_text") or ""),
            source_block_id=normalize_optional_text(value.get("source_block_id")),
            page=safe_int(value.get("page")),
            char_start=safe_int(value.get("char_start")),
            char_end=safe_int(value.get("char_end")),
            confidence=float(value.get("confidence") or 0.0),
            metadata=_mapping(value.get("metadata")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "mention_id": self.mention_id,
            "document_id": self.document_id,
            "reference_id": self.reference_id,
            "citation_marker": self.citation_marker,
            "context_text": self.context_text,
            "source_block_id": self.source_block_id,
            "page": self.page,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SourceReferenceResolution:
    resolution_id: str
    reference_id: str
    provider: str
    status: str
    resolved_title: str | None = None
    resolved_authors_text: str | None = None
    resolved_year: int | None = None
    resolved_venue: str | None = None
    resolved_doi: str | None = None
    resolved_url: str | None = None
    open_access_url: str | None = None
    confidence: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "SourceReferenceResolution":
        return cls(
            resolution_id=str(value.get("resolution_id") or ""),
            reference_id=str(value.get("reference_id") or ""),
            provider=str(value.get("provider") or ""),
            status=str(value.get("status") or "unresolved"),
            resolved_title=normalize_optional_text(value.get("resolved_title")),
            resolved_authors_text=normalize_optional_text(
                value.get("resolved_authors_text")
            ),
            resolved_year=safe_int(value.get("resolved_year")),
            resolved_venue=normalize_optional_text(value.get("resolved_venue")),
            resolved_doi=normalize_optional_text(value.get("resolved_doi")),
            resolved_url=normalize_optional_text(value.get("resolved_url")),
            open_access_url=normalize_optional_text(value.get("open_access_url")),
            confidence=float(value.get("confidence") or 0.0),
            metadata=_mapping(value.get("metadata")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "resolution_id": self.resolution_id,
            "reference_id": self.reference_id,
            "provider": self.provider,
            "status": self.status,
            "resolved_title": self.resolved_title,
            "resolved_authors_text": self.resolved_authors_text,
            "resolved_year": self.resolved_year,
            "resolved_venue": self.resolved_venue,
            "resolved_doi": self.resolved_doi,
            "resolved_url": self.resolved_url,
            "open_access_url": self.open_access_url,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SourceReferenceCandidate:
    candidate_id: str
    reference_id: str
    status: str
    relevance_score: float = 0.0
    relevance_reason: str | None = None
    cited_by_document_id: str | None = None
    mention_count: int = 0
    representative_context: str | None = None
    resolved_doi: str | None = None
    resolved_url: str | None = None
    open_access_url: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "SourceReferenceCandidate":
        return cls(
            candidate_id=str(value.get("candidate_id") or ""),
            reference_id=str(value.get("reference_id") or ""),
            status=str(value.get("status") or "metadata_only"),
            relevance_score=float(value.get("relevance_score") or 0.0),
            relevance_reason=normalize_optional_text(value.get("relevance_reason")),
            cited_by_document_id=normalize_optional_text(
                value.get("cited_by_document_id")
            ),
            mention_count=safe_int(value.get("mention_count")) or 0,
            representative_context=normalize_optional_text(
                value.get("representative_context")
            ),
            resolved_doi=normalize_optional_text(value.get("resolved_doi")),
            resolved_url=normalize_optional_text(value.get("resolved_url")),
            open_access_url=normalize_optional_text(value.get("open_access_url")),
            metadata=_mapping(value.get("metadata")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "reference_id": self.reference_id,
            "status": self.status,
            "relevance_score": self.relevance_score,
            "relevance_reason": self.relevance_reason,
            "cited_by_document_id": self.cited_by_document_id,
            "mention_count": self.mention_count,
            "representative_context": self.representative_context,
            "resolved_doi": self.resolved_doi,
            "resolved_url": self.resolved_url,
            "open_access_url": self.open_access_url,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SourceReferenceSet:
    entries: tuple[SourceReferenceEntry, ...] = ()
    mentions: tuple[SourceReferenceMention, ...] = ()
    resolutions: tuple[SourceReferenceResolution, ...] = ()
    candidates: tuple[SourceReferenceCandidate, ...] = ()


@dataclass(frozen=True)
class SourceDocumentNode:
    node_id: str
    document_id: str
    parent_id: str | None
    child_ids: tuple[str, ...]
    node_type: SourceDocumentNodeType | str
    order: int
    title: str | None = None
    text: str | None = None
    semantic_role: str | None = None
    level: int | None = None
    heading_path: tuple[str, ...] = ()
    source_ref_kind: str | None = None
    source_ref_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    bbox: SourceBoundingBox | None = None
    text_unit_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def with_children(self, child_ids: Iterable[str]) -> "SourceDocumentNode":
        return SourceDocumentNode(
            node_id=self.node_id,
            document_id=self.document_id,
            parent_id=self.parent_id,
            child_ids=tuple(child_ids),
            node_type=self.node_type,
            order=self.order,
            title=self.title,
            text=self.text,
            semantic_role=self.semantic_role,
            level=self.level,
            heading_path=self.heading_path,
            source_ref_kind=self.source_ref_kind,
            source_ref_id=self.source_ref_id,
            page_start=self.page_start,
            page_end=self.page_end,
            bbox=self.bbox,
            text_unit_ids=self.text_unit_ids,
            warnings=self.warnings,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "document_id": self.document_id,
            "parent_id": self.parent_id,
            "child_ids": list(self.child_ids),
            "node_type": str(self.node_type),
            "semantic_role": self.semantic_role,
            "title": self.title,
            "text": self.text,
            "level": self.level,
            "order": self.order,
            "heading_path": list(self.heading_path),
            "source_ref_kind": self.source_ref_kind,
            "source_ref_id": self.source_ref_id,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "bbox": self.bbox.to_payload() if self.bbox else None,
            "text_unit_ids": list(self.text_unit_ids),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class SourceDocumentTree:
    document_id: str
    collection_id: str | None
    root_node_id: str
    nodes: Mapping[str, SourceDocumentNode]
    reference_records: Mapping[str, SourceReferenceEntry] = field(default_factory=dict)

    @property
    def root(self) -> SourceDocumentNode:
        return self.nodes[self.root_node_id]

    def children_of(self, node_id: str) -> tuple[SourceDocumentNode, ...]:
        node = self.nodes[node_id]
        return tuple(self.nodes[child_id] for child_id in node.child_ids)

    def node_for_source_ref(
        self,
        source_ref_kind: str,
        source_ref_id: str,
    ) -> SourceDocumentNode | None:
        for node in self.nodes.values():
            if (
                node.source_ref_kind == source_ref_kind
                and node.source_ref_id == source_ref_id
            ):
                return node
        return None

    def to_record(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "collection_id": self.collection_id,
            "root_node_id": self.root_node_id,
            "nodes": {
                node_id: node.to_record()
                for node_id, node in sorted(
                    self.nodes.items(),
                    key=lambda item: item[1].order,
                )
            },
            "reference_records": {
                reference_id: reference.to_record()
                for reference_id, reference in self.reference_records.items()
            },
        }


def build_heading_blocks(
    blocks: Iterable[SourceBlock | Mapping[str, Any]],
) -> list[SourceLayoutBlock]:
    return sorted(
        [
            block
            for block in (SourceLayoutBlock.from_value(item) for item in blocks)
            if block.heading_path
        ],
        key=lambda item: (item.page is None, item.page or 0, item.block_order),
    )


def build_figure_caption_blocks(
    blocks: Iterable[SourceBlock | Mapping[str, Any]],
) -> list[SourceLayoutBlock]:
    return _build_caption_blocks(blocks, "figure_caption")


def build_table_caption_blocks(
    blocks: Iterable[SourceBlock | Mapping[str, Any]],
) -> list[SourceLayoutBlock]:
    return _build_caption_blocks(blocks, "table_caption")


def find_nearest_caption_block(
    *,
    page: int | None,
    target_bbox: Any,
    caption_blocks: Iterable[SourceLayoutBlock | Mapping[str, Any]],
    used_block_ids: set[str],
) -> SourceLayoutBlock | None:
    normalized_page = safe_int(page)
    candidates = [
        block
        for block in _coerce_layout_blocks(caption_blocks)
        if block.block_id
        and block.block_id not in used_block_ids
        and (normalized_page is None or block.page == normalized_page)
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            _caption_distance_score(target_bbox, item.bbox),
            item.block_order,
        ),
    )


def resolve_heading_path_for_page(
    page: int | None,
    heading_blocks: Iterable[SourceLayoutBlock | Mapping[str, Any]],
) -> str | None:
    blocks = _coerce_layout_blocks(heading_blocks)
    if not blocks:
        return None
    normalized_page = safe_int(page)
    eligible = [
        item
        for item in blocks
        if item.heading_path
        and (
            normalized_page is None or item.page is None or item.page <= normalized_page
        )
    ]
    if not eligible:
        return blocks[-1].heading_path
    return eligible[-1].heading_path


def resolve_heading_path_for_target(
    *,
    page: int | None,
    target_bbox: Any,
    heading_blocks: Iterable[SourceLayoutBlock | Mapping[str, Any]],
) -> str | None:
    target = SourceBoundingBox.from_value(target_bbox)
    blocks = _coerce_layout_blocks(heading_blocks)
    normalized_page = safe_int(page)
    if target is None or normalized_page is None:
        return resolve_heading_path_for_page(page, blocks)

    candidates = []
    for item in blocks:
        if item.block_type != "heading":
            continue
        if item.page != normalized_page:
            continue
        if not item.heading_path or item.bbox is None:
            continue
        distance = _heading_above_distance(target, item.bbox)
        if distance is None:
            continue
        candidates.append((distance, -item.block_order, item))

    if not candidates:
        return resolve_heading_path_for_page(page, blocks)
    return min(candidates, key=lambda item: (item[0], item[1]))[2].heading_path


def build_source_table_rows_from_cells(
    *,
    document_id: str,
    cells: Iterable[SourceTableCell],
    heading_blocks: Iterable[SourceLayoutBlock | Mapping[str, Any]],
) -> list[SourceTableRow]:
    grouped: dict[str, list[SourceTableCell]] = {}
    for cell in cells:
        grouped.setdefault(cell.table_id, []).append(cell)

    rows: list[SourceTableRow] = []
    headings = _coerce_layout_blocks(heading_blocks)
    for table_id, table_cells in grouped.items():
        row_indices = sorted({cell.row_index for cell in table_cells})
        for row_index in row_indices:
            row_cells = [cell for cell in table_cells if cell.row_index == row_index]
            if all(not normalize_optional_text(cell.header_path) for cell in row_cells):
                continue
            ordered_cells = sorted(row_cells, key=lambda cell: cell.col_index)
            row_text = " | ".join(
                cell.cell_text.strip()
                for cell in ordered_cells
                if cell.cell_text.strip()
            )
            if not row_text:
                continue
            page = first_non_null([cell.page for cell in ordered_cells])
            bbox = SourceBoundingBox.merge(cell.bbox for cell in ordered_cells)
            rows.append(
                SourceTableRow(
                    row_id=f"row_{document_id}_{table_id}_{row_index}",
                    document_id=document_id,
                    table_id=table_id,
                    row_index=row_index,
                    row_text=row_text,
                    page=page,
                    bbox=bbox,
                    heading_path=resolve_heading_path_for_target(
                        page=page,
                        target_bbox=bbox,
                        heading_blocks=headings,
                    ),
                )
            )
    return rows


def build_source_document_tree(
    *,
    document: SourceDocument,
    blocks: Iterable[SourceBlock] = (),
    tables: Iterable[SourceTable] = (),
    figures: Iterable[SourceFigure] = (),
    references: SourceReferenceSet | None = None,
    collection_id: str | None = None,
) -> SourceDocumentTree:
    """Project flat Source artifacts into a section-oriented document tree."""

    builder = _SourceDocumentTreeBuilder(
        document=document,
        collection_id=collection_id,
        references=references or SourceReferenceSet(),
    )
    builder.add_blocks(blocks)
    builder.add_tables(tables)
    builder.add_figures(figures)
    builder.add_references()
    return builder.build()


def render_markdown_table(
    matrix: list[list[str]], column_headers: list[str]
) -> str | None:
    if not matrix:
        return None

    col_count = max(len(column_headers), max((len(row) for row in matrix), default=0))
    if col_count <= 0:
        return None
    normalized_rows = [_normalize_table_row(row, col_count) for row in matrix]
    header = _normalize_table_row(
        normalized_rows[0] if normalized_rows else column_headers,
        col_count,
    )
    if not any(header):
        header = _normalize_table_row(column_headers, col_count)
    if not any(header):
        header = [f"column_{index + 1}" for index in range(col_count)]

    body_rows = normalized_rows[1:] if normalized_rows else []
    lines = [
        "| " + " | ".join(_escape_markdown_cell(value) for value in header) + " |",
        "| " + " | ".join("---" for _ in range(col_count)) + " |",
    ]
    for row in body_rows:
        lines.append(
            "| " + " | ".join(_escape_markdown_cell(value) for value in row) + " |"
        )
    return "\n".join(lines)


def render_plain_table_text(matrix: list[list[str]]) -> str | None:
    if not matrix:
        return None
    lines = []
    for row in matrix:
        line = " | ".join(str(cell).strip() for cell in row if str(cell).strip())
        if line:
            lines.append(line)
    return "\n".join(lines) or None


def extract_unit_hint(header_path: str | None, cell_text: str) -> str | None:
    for source in (header_path or "", cell_text):
        match = _UNIT_HINT_PATTERN.search(str(source or ""))
        if match:
            return match.group(1)
    return None


def make_table_id(document_id: str, order: int, title: str | None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(title or "").lower()).strip("_")
    if not slug:
        slug = f"table_{order}"
    return f"tbl_{document_id}_{order}_{slug}"


def update_heading_stack(stack: list[str], heading: str, level: int) -> list[str]:
    normalized_heading = " ".join(str(heading or "").split())
    if not normalized_heading:
        return list(stack)

    effective_level = max(1, int(level))
    if effective_level > len(stack) + 1:
        effective_level = len(stack) + 1
    return [*stack[: effective_level - 1], normalized_heading]


def normalize_optional_text(value: Any) -> str | None:
    if _is_missing_value(value):
        return None
    text = str(value).strip()
    return text or None


def safe_int(value: Any) -> int | None:
    if _is_missing_value(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def first_non_null(values: Iterable[Any]) -> Any:
    for value in values:
        if value is None:
            continue
        if _is_missing_value(value):
            continue
        return value
    return None


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _string_tuple(value: Any) -> tuple[str, ...]:
    if _is_missing_value(value):
        return ()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return (text,)
            return _string_tuple(parsed)
        return (text,)
    if isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
        return tuple(str(item) for item in value if not _is_missing_value(item))
    return (str(value),)


def _table_matrix_tuple(value: Any) -> tuple[tuple[str, ...], ...]:
    if _is_missing_value(value):
        return ()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return ((text,),)
        return _table_matrix_tuple(parsed)
    if not isinstance(value, Iterable) or isinstance(value, (bytes, Mapping)):
        return ((str(value),),)

    rows = []
    for row in value:
        if isinstance(row, str) or not isinstance(row, Iterable):
            rows.append((str(row),))
        else:
            rows.append(tuple(str(cell) for cell in row))
    return tuple(rows)


def _mapping(value: Any) -> Mapping[str, Any]:
    if _is_missing_value(value):
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def _build_caption_blocks(
    blocks: Iterable[SourceBlock | Mapping[str, Any]],
    block_type: str,
) -> list[SourceLayoutBlock]:
    return [
        block
        for block in (SourceLayoutBlock.from_value(item) for item in blocks)
        if block.block_type == block_type
    ]


def _coerce_layout_blocks(
    blocks: Iterable[SourceLayoutBlock | Mapping[str, Any]],
) -> list[SourceLayoutBlock]:
    return [
        block
        if isinstance(block, SourceLayoutBlock)
        else SourceLayoutBlock.from_value(block)
        for block in blocks
    ]


def _caption_distance_score(figure_bbox: Any, caption_bbox: Any) -> float:
    figure = SourceBoundingBox.from_value(figure_bbox)
    caption = SourceBoundingBox.from_value(caption_bbox)
    if figure is None or caption is None:
        return float("inf")
    return _bbox_vertical_gap(figure, caption)


def _heading_above_distance(
    target: SourceBoundingBox,
    heading: SourceBoundingBox,
) -> float | None:
    if _uses_top_left_origin(target, heading):
        distance = target.t - heading.b
    else:
        distance = heading.b - target.t
    return distance if distance >= 0 else None


def _bbox_vertical_gap(first: SourceBoundingBox, second: SourceBoundingBox) -> float:
    if _uses_top_left_origin(first, second):
        first_top = min(first.t, first.b)
        first_bottom = max(first.t, first.b)
        second_top = min(second.t, second.b)
        second_bottom = max(second.t, second.b)
    else:
        first_top = max(first.t, first.b)
        first_bottom = min(first.t, first.b)
        second_top = max(second.t, second.b)
        second_bottom = min(second.t, second.b)

    if _uses_top_left_origin(first, second):
        if first_bottom < second_top:
            return second_top - first_bottom
        if second_bottom < first_top:
            return first_top - second_bottom
    else:
        if first_bottom > second_top:
            return first_bottom - second_top
        if second_bottom > first_top:
            return second_bottom - first_top
    return 0.0


def _uses_top_left_origin(*payloads: SourceBoundingBox) -> bool:
    return any("top" in payload.coord_origin.lower() for payload in payloads)


def _source_node_id(document_id: str, kind: str, source_id: str) -> str:
    safe_source = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(source_id or "")).strip("_")
    return f"node_{document_id}_{kind}_{safe_source}"


def _tree_order(kind: str, source_order: int) -> int:
    base = {
        "block": 100_000,
        "table": 200_000,
        "figure": 300_000,
        "reference_section": 800_000,
        "reference": 810_000,
    }.get(kind, 900_000)
    return base + int(source_order or 0) * 10


def _heading_path_tuple(value: str | None) -> tuple[str, ...]:
    text = normalize_optional_text(value)
    if text is None:
        return ()
    return tuple(part.strip() for part in text.split(">") if part.strip())


def _section_semantic_role(title: str | None) -> str:
    text = _semantic_text(title)
    if not text:
        return "unknown"
    if "abstract" in text:
        return "abstract"
    if "introduction" in text:
        return "introduction"
    if any(token in text for token in ("method", "material", "experimental")):
        return "methods"
    if any(token in text for token in ("result", "discussion")):
        return "results"
    if "conclusion" in text:
        return "conclusion"
    if "reference" in text:
        return "references"
    return "unknown"


def _semantic_text(value: str | None) -> str:
    return re.sub(r"[^a-z]+", " ", str(value or "").lower()).strip()


def _block_node_type(block: SourceBlock) -> str:
    if block.block_type in {"paragraph", "list_item", "caption"}:
        return str(block.block_type)
    if block.block_type in {"figure_caption", "table_caption"}:
        return "caption"
    return "paragraph"


class _SourceDocumentTreeBuilder:
    def __init__(
        self,
        *,
        document: SourceDocument,
        collection_id: str | None,
        references: SourceReferenceSet,
    ) -> None:
        self.document = document
        self.collection_id = collection_id
        self.references = references
        self.root_node_id = f"node_{document.document_id}_document"
        self.nodes: dict[str, SourceDocumentNode] = {}
        self.children_by_parent: dict[str, list[str]] = {}
        self.section_stack: list[tuple[int, str]] = []
        self.sections_by_heading_path: dict[str, str] = {}
        self.references_section_id: str | None = None
        self.nodes[self.root_node_id] = SourceDocumentNode(
            node_id=self.root_node_id,
            document_id=document.document_id,
            parent_id=None,
            child_ids=(),
            node_type="document",
            order=0,
            title=document.title,
            text=None,
            level=0,
            source_ref_kind="document",
            source_ref_id=document.document_id,
            text_unit_ids=document.text_unit_ids,
        )

    def add_blocks(self, blocks: Iterable[SourceBlock]) -> None:
        for block in sorted(blocks, key=lambda item: (item.block_order, item.block_id)):
            if block.document_id != self.document.document_id:
                continue
            if block.block_type == "title":
                continue
            if block.block_type == "heading":
                self._add_heading(block)
                continue
            self._add_block_leaf(block)

    def add_tables(self, tables: Iterable[SourceTable]) -> None:
        for table in sorted(tables, key=lambda item: (item.table_order, item.table_id)):
            if table.document_id != self.document.document_id:
                continue
            parent_id = self._parent_for_heading_path(table.heading_path)
            node_id = _source_node_id(
                self.document.document_id, "table", table.table_id
            )
            node = SourceDocumentNode(
                node_id=node_id,
                document_id=self.document.document_id,
                parent_id=parent_id,
                child_ids=(),
                node_type="table",
                order=_tree_order("table", table.table_order),
                title=table.caption_text,
                text=render_plain_table_text([list(row) for row in table.table_matrix]),
                heading_path=_heading_path_tuple(table.heading_path),
                source_ref_kind="table",
                source_ref_id=table.table_id,
                page_start=table.page,
                page_end=table.page,
                bbox=table.bbox,
            )
            self._insert_node(node)
            if table.caption_text:
                self._insert_node(
                    SourceDocumentNode(
                        node_id=_source_node_id(
                            self.document.document_id,
                            "table_caption",
                            table.table_id,
                        ),
                        document_id=self.document.document_id,
                        parent_id=node_id,
                        child_ids=(),
                        node_type="caption",
                        order=node.order + 1,
                        text=table.caption_text,
                        heading_path=node.heading_path,
                        source_ref_kind="table",
                        source_ref_id=table.table_id,
                        page_start=table.page,
                        page_end=table.page,
                    )
                )

    def add_figures(self, figures: Iterable[SourceFigure]) -> None:
        for figure in sorted(
            figures, key=lambda item: (item.figure_order, item.figure_id)
        ):
            if figure.document_id != self.document.document_id:
                continue
            parent_id = self._parent_for_heading_path(figure.heading_path)
            node_id = _source_node_id(
                self.document.document_id, "figure", figure.figure_id
            )
            node = SourceDocumentNode(
                node_id=node_id,
                document_id=self.document.document_id,
                parent_id=parent_id,
                child_ids=(),
                node_type="figure",
                order=_tree_order("figure", figure.figure_order),
                title=figure.figure_label or figure.caption_text,
                text=figure.caption_text,
                heading_path=_heading_path_tuple(figure.heading_path),
                source_ref_kind="figure",
                source_ref_id=figure.figure_id,
                page_start=figure.page,
                page_end=figure.page,
                bbox=figure.bbox,
            )
            self._insert_node(node)
            if figure.caption_text:
                self._insert_node(
                    SourceDocumentNode(
                        node_id=_source_node_id(
                            self.document.document_id,
                            "figure_caption",
                            figure.figure_id,
                        ),
                        document_id=self.document.document_id,
                        parent_id=node_id,
                        child_ids=(),
                        node_type="caption",
                        order=node.order + 1,
                        text=figure.caption_text,
                        heading_path=node.heading_path,
                        source_ref_kind="figure",
                        source_ref_id=figure.figure_id,
                        page_start=figure.page,
                        page_end=figure.page,
                    )
                )

    def add_references(self) -> None:
        for position, reference in enumerate(self.references.entries, start=1):
            if reference.document_id != self.document.document_id:
                continue
            parent_id = self._ensure_references_section()
            self._insert_node(
                SourceDocumentNode(
                    node_id=_source_node_id(
                        self.document.document_id,
                        "reference",
                        reference.reference_id,
                    ),
                    document_id=self.document.document_id,
                    parent_id=parent_id,
                    child_ids=(),
                    node_type="reference_entry",
                    semantic_role="references",
                    order=_tree_order("reference", position),
                    title=reference.title,
                    text=reference.raw_reference,
                    heading_path=("References",),
                    source_ref_kind="reference",
                    source_ref_id=reference.reference_id,
                    page_start=reference.page,
                    page_end=reference.page,
                )
            )

    def build(self) -> SourceDocumentTree:
        for node_id, node in list(self.nodes.items()):
            child_ids = sorted(
                self.children_by_parent.get(node_id, []),
                key=lambda child_id: (self.nodes[child_id].order, child_id),
            )
            self.nodes[node_id] = node.with_children(child_ids)
        return SourceDocumentTree(
            document_id=self.document.document_id,
            collection_id=self.collection_id,
            root_node_id=self.root_node_id,
            nodes=dict(self.nodes),
            reference_records={
                reference.reference_id: reference
                for reference in self.references.entries
                if reference.document_id == self.document.document_id
            },
        )

    def _add_heading(self, block: SourceBlock) -> None:
        semantic_role = _section_semantic_role(block.text)
        node_type = "references_section" if semantic_role == "references" else "section"
        level = max(1, block.heading_level or len(self.section_stack) + 1)
        while self.section_stack and self.section_stack[-1][0] >= level:
            self.section_stack.pop()
        parent_id = (
            self.section_stack[-1][1] if self.section_stack else self.root_node_id
        )
        node_id = _source_node_id(self.document.document_id, "block", block.block_id)
        node = SourceDocumentNode(
            node_id=node_id,
            document_id=self.document.document_id,
            parent_id=parent_id,
            child_ids=(),
            node_type=node_type,
            semantic_role=semantic_role,
            order=_tree_order("block", block.block_order),
            title=block.text,
            text=None,
            level=level,
            heading_path=_heading_path_tuple(block.heading_path or block.text),
            source_ref_kind="block",
            source_ref_id=block.block_id,
            page_start=block.page,
            page_end=block.page,
            bbox=block.bbox,
            text_unit_ids=block.text_unit_ids,
        )
        self._insert_node(node)
        self.section_stack.append((level, node_id))
        if block.heading_path:
            self.sections_by_heading_path[block.heading_path] = node_id
        if semantic_role == "references":
            self.references_section_id = node_id

    def _add_block_leaf(self, block: SourceBlock) -> None:
        parent_id = self._parent_for_heading_path(block.heading_path)
        node_id = _source_node_id(self.document.document_id, "block", block.block_id)
        self._insert_node(
            SourceDocumentNode(
                node_id=node_id,
                document_id=self.document.document_id,
                parent_id=parent_id,
                child_ids=(),
                node_type=_block_node_type(block),
                order=_tree_order("block", block.block_order),
                text=block.text,
                heading_path=_heading_path_tuple(block.heading_path),
                source_ref_kind="block",
                source_ref_id=block.block_id,
                page_start=block.page,
                page_end=block.page,
                bbox=block.bbox,
                text_unit_ids=block.text_unit_ids,
            )
        )

    def _ensure_references_section(self) -> str:
        if self.references_section_id is not None:
            return self.references_section_id
        node_id = _source_node_id(self.document.document_id, "section", "references")
        self.references_section_id = node_id
        self._insert_node(
            SourceDocumentNode(
                node_id=node_id,
                document_id=self.document.document_id,
                parent_id=self.root_node_id,
                child_ids=(),
                node_type="references_section",
                semantic_role="references",
                order=_tree_order("reference_section", 0),
                title="References",
                level=1,
                heading_path=("References",),
            )
        )
        return node_id

    def _parent_for_heading_path(self, heading_path: str | None) -> str:
        if heading_path and heading_path in self.sections_by_heading_path:
            return self.sections_by_heading_path[heading_path]
        return self.section_stack[-1][1] if self.section_stack else self.root_node_id

    def _insert_node(self, node: SourceDocumentNode) -> None:
        self.nodes[node.node_id] = node
        if node.parent_id is not None:
            self.children_by_parent.setdefault(node.parent_id, []).append(node.node_id)


def _normalize_table_row(row: list[str], col_count: int) -> list[str]:
    values = [" ".join(str(value or "").split()) for value in row[:col_count]]
    if len(values) < col_count:
        values.extend([""] * (col_count - len(values)))
    return values


def _escape_markdown_cell(value: str) -> str:
    return str(value or "").replace("|", "\\|").strip()


__all__ = [
    "SourceBlock",
    "SourceBlockType",
    "SourceBoundingBox",
    "SourceCharRange",
    "SourceDocument",
    "SourceDocumentNode",
    "SourceDocumentNodeType",
    "SourceDocumentTree",
    "SourceFigure",
    "SourceReferenceCandidate",
    "SourceReferenceEntry",
    "SourceReferenceMention",
    "SourceReferenceResolution",
    "SourceReferenceSet",
    "SourceArtifactSet",
    "SourceLayoutBlock",
    "SourceTable",
    "SourceTableCell",
    "SourceTableRow",
    "SourceTextUnit",
    "build_figure_caption_blocks",
    "build_heading_blocks",
    "build_source_document_tree",
    "build_source_table_rows_from_cells",
    "build_table_caption_blocks",
    "extract_unit_hint",
    "find_nearest_caption_block",
    "first_non_null",
    "make_table_id",
    "normalize_optional_text",
    "render_markdown_table",
    "render_plain_table_text",
    "resolve_heading_path_for_page",
    "resolve_heading_path_for_target",
    "safe_int",
    "update_heading_stack",
]
