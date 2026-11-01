from __future__ import annotations

from dataclasses import dataclass, field, replace
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
class SourceDocument:
    document_id: str
    document_order: int
    title: str
    text: str
    creation_date: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    text_units: tuple[SourceTextUnit, ...] = ()
    blocks: tuple[SourceBlock, ...] = ()
    tables: tuple[SourceTable, ...] = ()
    table_rows: tuple[SourceTableRow, ...] = ()
    table_cells: tuple[SourceTableCell, ...] = ()
    figures: tuple[SourceFigure, ...] = ()

    @property
    def text_unit_ids(self) -> tuple[str, ...]:
        return tuple(text_unit.text_unit_id for text_unit in self.text_units)


@dataclass(frozen=True)
class SourceTextUnit:
    text_unit_id: str
    text_unit_order: int
    text: str
    n_tokens: int | None
    document_ids: tuple[str, ...]


@dataclass(frozen=True)
class SourceBlock:
    block_id: str
    document_id: str
    block_type: SourceBlockType | str
    text: str
    block_order: int
    text_unit_ids: tuple[str, ...] = ()
    page: int | None = None
    heading_path: str | None = None
    heading_level: int | None = None


@dataclass(frozen=True)
class SourceLayoutBlock:
    block_id: str | None
    text: str | None
    page: int | None
    block_order: int
    block_type: str
    heading_path: str | None


@dataclass(frozen=True)
class SourceTable:
    table_id: str
    document_id: str
    table_order: int
    caption_text: str | None
    caption_block_id: str | None
    page: int | None
    heading_path: str | None
    column_headers: tuple[str, ...]
    table_matrix: tuple[tuple[str, ...], ...]
    header_row_count: int = 1
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.table_matrix)

    @property
    def col_count(self) -> int:
        return max((len(row) for row in self.table_matrix), default=0)


@dataclass(frozen=True)
class SourceTableCell:
    cell_id: str
    document_id: str
    table_id: str
    row_index: int
    col_index: int
    cell_text: str
    row_span: int = 1
    col_span: int = 1
    column_header: bool = False
    row_header: bool = False
    row_section: bool = False
    header_path: str | None = None
    page: int | None = None
    unit_hint: str | None = None


@dataclass(frozen=True)
class SourceTableRow:
    row_id: str
    document_id: str
    table_id: str
    row_index: int
    row_text: str
    page: int | None = None
    heading_path: str | None = None


@dataclass(frozen=True)
class SourceFigure:
    figure_id: str
    document_id: str
    figure_order: int
    figure_label: str | None
    caption_text: str | None
    caption_block_id: str | None
    page: int | None
    heading_path: str | None
    image_path: str | None
    image_mime_type: str | None
    image_width: int | None
    image_height: int | None
    asset_sha256: str | None
    image_size_bytes: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


def assemble_source_documents(
    *,
    documents: Iterable[SourceDocument] = (),
    text_units: Iterable[SourceTextUnit] = (),
    blocks: Iterable[SourceBlock] = (),
    tables: Iterable[SourceTable] = (),
    table_rows: Iterable[SourceTableRow] = (),
    table_cells: Iterable[SourceTableCell] = (),
    figures: Iterable[SourceFigure] = (),
) -> tuple[SourceDocument, ...]:
    """Attach parser artifacts to the document that owns them."""

    document_items = tuple(documents)
    text_unit_items = tuple(text_units)
    block_items = tuple(blocks)
    table_items = tuple(tables)
    table_row_items = tuple(table_rows)
    table_cell_items = tuple(table_cells)
    figure_items = tuple(figures)
    document_ids = {document.document_id for document in document_items}
    if len(document_ids) != len(document_items):
        raise ValueError("source documents contain duplicate document ids")

    for text_unit in text_unit_items:
        if not text_unit.document_ids:
            raise ValueError(
                f"source text unit has no owning document: {text_unit.text_unit_id}"
            )
        unknown_ids = set(text_unit.document_ids) - document_ids
        if unknown_ids:
            raise ValueError(
                "source text unit references unknown documents: "
                f"{text_unit.text_unit_id} -> {sorted(unknown_ids)}"
            )
    for artifact_kind, artifact_items in (
        ("block", block_items),
        ("table", table_items),
        ("table row", table_row_items),
        ("table cell", table_cell_items),
        ("figure", figure_items),
    ):
        for artifact in artifact_items:
            if artifact.document_id not in document_ids:
                raise ValueError(
                    f"source {artifact_kind} references unknown document: "
                    f"{artifact.document_id}"
                )

    return tuple(
        replace(
            document,
            text_units=tuple(
                item
                for item in text_unit_items
                if document.document_id in item.document_ids
            ),
            blocks=tuple(
                item for item in block_items if item.document_id == document.document_id
            ),
            tables=tuple(
                item for item in table_items if item.document_id == document.document_id
            ),
            table_rows=tuple(
                item
                for item in table_row_items
                if item.document_id == document.document_id
            ),
            table_cells=tuple(
                item
                for item in table_cell_items
                if item.document_id == document.document_id
            ),
            figures=tuple(
                item
                for item in figure_items
                if item.document_id == document.document_id
            ),
        )
        for document in document_items
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


@dataclass(frozen=True)
class SourceReferenceMention:
    mention_id: str
    document_id: str
    reference_id: str | None
    citation_marker: str
    context_text: str
    source_block_id: str | None = None
    page: int | None = None
    confidence: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)


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
            text_unit_ids=self.text_unit_ids,
            warnings=self.warnings,
        )


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


def build_heading_blocks(
    blocks: Iterable[SourceBlock | SourceLayoutBlock],
) -> list[SourceBlock | SourceLayoutBlock]:
    return sorted(
        [block for block in blocks if block.heading_path],
        key=lambda item: (item.page is None, item.page or 0, item.block_order),
    )


def build_figure_caption_blocks(
    blocks: Iterable[SourceBlock | SourceLayoutBlock],
) -> list[SourceBlock | SourceLayoutBlock]:
    return _build_caption_blocks(blocks, "figure_caption")


def build_table_caption_blocks(
    blocks: Iterable[SourceBlock | SourceLayoutBlock],
) -> list[SourceBlock | SourceLayoutBlock]:
    return _build_caption_blocks(blocks, "table_caption")


def find_nearest_caption_block(
    *,
    page: int | None,
    caption_blocks: Iterable[SourceBlock | SourceLayoutBlock],
    used_block_ids: set[str],
) -> SourceBlock | SourceLayoutBlock | None:
    candidates = [
        block
        for block in caption_blocks
        if block.block_id
        and block.block_id not in used_block_ids
        and (page is None or block.page == page)
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: item.block_order,
    )


def resolve_heading_path_for_page(
    page: int | None,
    heading_blocks: Iterable[SourceBlock | SourceLayoutBlock],
) -> str | None:
    blocks = list(heading_blocks)
    if not blocks:
        return None
    eligible = [
        item
        for item in blocks
        if item.heading_path
        and (
            page is None or item.page is None or item.page <= page
        )
    ]
    if not eligible:
        return blocks[-1].heading_path
    return eligible[-1].heading_path


def build_source_table_rows_from_cells(
    *,
    document_id: str,
    cells: Iterable[SourceTableCell],
    heading_blocks: Iterable[SourceBlock | SourceLayoutBlock],
) -> list[SourceTableRow]:
    grouped: dict[str, list[SourceTableCell]] = {}
    for cell in cells:
        grouped.setdefault(cell.table_id, []).append(cell)

    rows: list[SourceTableRow] = []
    headings = list(heading_blocks)
    for table_id, table_cells in grouped.items():
        row_indices = sorted({cell.row_index for cell in table_cells})
        for row_index in row_indices:
            row_cells = [cell for cell in table_cells if cell.row_index == row_index]
            if all(not cell.header_path or not cell.header_path.strip() for cell in row_cells):
                continue
            ordered_cells = sorted(row_cells, key=lambda cell: cell.col_index)
            row_text = " | ".join(
                cell.cell_text.strip()
                for cell in ordered_cells
                if cell.cell_text.strip()
            )
            if not row_text:
                continue
            page = next((cell.page for cell in ordered_cells if cell.page is not None), None)
            rows.append(
                SourceTableRow(
                    row_id=f"row_{document_id}_{table_id}_{row_index}",
                    document_id=document_id,
                    table_id=table_id,
                    row_index=row_index,
                    row_text=row_text,
                    page=page,
                    heading_path=resolve_heading_path_for_page(page, headings),
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
    matrix: list[list[str]],
    column_headers: list[str],
    *,
    header_row_count: int = 1,
) -> str | None:
    if not matrix:
        return None

    col_count = max(len(column_headers), max((len(row) for row in matrix), default=0))
    if col_count <= 0:
        return None
    normalized_rows = [_normalize_table_row(row, col_count) for row in matrix]
    normalized_header_row_count = max(0, min(header_row_count, len(normalized_rows)))
    header = _normalize_table_row(column_headers, col_count)
    if not any(header) and normalized_rows:
        header = normalized_rows[0]
        normalized_header_row_count = max(1, normalized_header_row_count)
    if not any(header):
        header = [f"column_{index + 1}" for index in range(col_count)]

    body_rows = normalized_rows[normalized_header_row_count:]
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
        line = " | ".join(cell.strip() for cell in row if cell.strip())
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


def _build_caption_blocks(
    blocks: Iterable[SourceBlock | SourceLayoutBlock],
    block_type: str,
) -> list[SourceBlock | SourceLayoutBlock]:
    return [block for block in blocks if block.block_type == block_type]


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
    if value is None:
        return ()
    return tuple(part.strip() for part in value.split(">") if part.strip())


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
            parent_id = self._parent_for_non_block_source(
                heading_path=table.heading_path,
                page=table.page,
            )
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
            parent_id = self._parent_for_non_block_source(
                heading_path=figure.heading_path,
                page=figure.page,
            )
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

    def _parent_for_non_block_source(
        self,
        *,
        heading_path: str | None,
        page: int | None,
    ) -> str:
        if heading_path and heading_path in self.sections_by_heading_path:
            return self.sections_by_heading_path[heading_path]
        if page is None:
            return self.root_node_id
        preceding_sections = [
            node
            for node in self.nodes.values()
            if node.node_type == "section"
            and node.page_start is not None
            and node.page_start <= page
        ]
        if not preceding_sections:
            return self.root_node_id
        return max(
            preceding_sections,
            key=lambda node: (node.page_start or 0, node.order),
        ).node_id

    def _insert_node(self, node: SourceDocumentNode) -> None:
        self.nodes[node.node_id] = node
        if node.parent_id is not None:
            self.children_by_parent.setdefault(node.parent_id, []).append(node.node_id)


def _normalize_table_row(row: list[str], col_count: int) -> list[str]:
    values = [" ".join(value.split()) for value in row[:col_count]]
    if len(values) < col_count:
        values.extend([""] * (col_count - len(values)))
    return values


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").strip()


__all__ = [
    "SourceBlock",
    "SourceBlockType",
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
    "SourceLayoutBlock",
    "SourceTable",
    "SourceTableCell",
    "SourceTableRow",
    "SourceTextUnit",
    "assemble_source_documents",
    "build_figure_caption_blocks",
    "build_heading_blocks",
    "build_source_document_tree",
    "build_source_table_rows_from_cells",
    "build_table_caption_blocks",
    "extract_unit_hint",
    "find_nearest_caption_block",
    "make_table_id",
    "render_markdown_table",
    "render_plain_table_text",
    "resolve_heading_path_for_page",
    "update_heading_stack",
]
