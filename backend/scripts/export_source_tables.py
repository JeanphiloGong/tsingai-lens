#!/usr/bin/env python3
# ruff: noqa: E402
from __future__ import annotations

import argparse
import ast
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any

import pandas as pd


DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(DEFAULT_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(DEFAULT_BACKEND_ROOT))

from domain.ports import CollectionRepository
from infra.persistence.database import (
    DatabaseSettings,
    build_database_engine,
    build_session_factory,
)
from infra.persistence.file.object_store import FileObjectStore
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from infra.persistence.sqlite import SqliteSourceArtifactRepository
from infra.source.config.source_runtime_config import SourceRuntimeConfig
from infra.source.contracts.artifact_schemas import (
    BLOCKS_FINAL_COLUMNS,
    DOCUMENTS_FINAL_COLUMNS,
    FIGURES_FINAL_COLUMNS,
    TABLE_CELLS_FINAL_COLUMNS,
    TABLES_FINAL_COLUMNS,
    TABLE_ROWS_FINAL_COLUMNS,
    TEXT_UNITS_FINAL_COLUMNS,
)
from infra.source.runtime.parsers.docling_pdf import (
    build_pdf_bundle,
    build_pdf_converter,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export Source-split tables for review. By default the script reads "
            "existing Source artifacts; with --reparse-inputs it reparses collection "
            "input PDFs with the current Source code without writing collection data."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--collection-id",
        help="Collection id under <backend-root>/data/collections/<collection-id>.",
    )
    source.add_argument(
        "--collection-dir",
        type=Path,
        help="Direct collection directory containing input/ and output/.",
    )
    parser.add_argument(
        "--backend-root",
        type=Path,
        default=DEFAULT_BACKEND_ROOT,
        help="Backend root. Defaults to the repo-local backend directory.",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="Directory where review files should be written.",
    )
    parser.add_argument(
        "--reparse-inputs",
        action="store_true",
        help="Reparse collection input PDFs with current Source code before export.",
    )
    parser.add_argument(
        "--document-id",
        help="Optional document id filter.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional maximum number of input PDFs when reparsing.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    backend_root = args.backend_root.expanduser().resolve()
    collection_dir = _resolve_collection_dir(
        backend_root=backend_root,
        collection_id=args.collection_id,
        collection_dir=args.collection_dir,
    )
    artifact_dir = collection_dir / "output"
    if args.reparse_inputs:
        engine = build_database_engine(DatabaseSettings())
        try:
            frames = _reparse_collection_inputs(
                backend_root=backend_root,
                collection_dir=collection_dir,
                collection_repository=PostgresCollectionRepository(
                    build_session_factory(engine)
                ),
                document_id=args.document_id,
                limit=args.limit,
            )
        finally:
            engine.dispose()
        source_mode = "reparse_inputs"
    else:
        frames = _load_existing_artifacts(
            backend_root=backend_root,
            collection_dir=collection_dir,
        )
        source_mode = "existing_artifacts"

    destination = args.destination.expanduser().resolve()
    export_dir = export_source_tables(
        frames=frames,
        destination=destination,
        collection_dir=collection_dir,
        artifact_dir=artifact_dir,
        source_mode=source_mode,
        document_id=args.document_id,
    )
    print(export_dir)


def _resolve_collection_dir(
    *,
    backend_root: Path,
    collection_id: str | None,
    collection_dir: Path | None,
) -> Path:
    if collection_dir is not None:
        return collection_dir.expanduser().resolve()
    if collection_id:
        return backend_root / "data" / "collections" / collection_id
    raise SystemExit("--collection-id or --collection-dir is required")


def _load_existing_artifacts(
    *,
    backend_root: Path,
    collection_dir: Path,
) -> dict[str, pd.DataFrame]:
    collection_id = collection_dir.name
    repository = SqliteSourceArtifactRepository(backend_root / "data" / "lens.sqlite")
    artifacts = repository.read_collection_artifacts(collection_id)
    if not artifacts.documents:
        raise SystemExit(f"source artifacts not found: {collection_id}")
    return {
        "documents": _records_to_frame(artifacts.documents),
        "text_units": _records_to_frame(artifacts.text_units),
        "blocks": _records_to_frame(artifacts.blocks),
        "figures": _records_to_frame(artifacts.figures),
        "tables": _records_to_frame(artifacts.tables),
        "table_rows": _records_to_frame(artifacts.table_rows),
        "table_cells": _records_to_frame(artifacts.table_cells),
    }


def _records_to_frame(records: tuple[Any, ...]) -> pd.DataFrame:
    return _normalize_frame(pd.DataFrame([record.to_record() for record in records]))


def _reparse_collection_inputs(
    *,
    backend_root: Path,
    collection_dir: Path,
    collection_repository: CollectionRepository,
    document_id: str | None,
    limit: int | None,
) -> dict[str, pd.DataFrame]:
    inputs = _collection_input_rows(collection_repository, collection_dir.name)
    if document_id:
        inputs = [item for item in inputs if str(item.get("id") or "") == document_id]
    if limit is not None:
        inputs = inputs[: max(limit, 0)]
    if not inputs:
        raise SystemExit(f"no input PDFs found for collection: {collection_dir}")

    config = SourceRuntimeConfig(root_dir=str(backend_root))
    object_store = FileObjectStore(collection_dir.parent)
    converter = build_pdf_converter()
    bundles = []
    for index, item in enumerate(inputs, start=1):
        storage_key = str(item.get("storage_key") or "").strip()
        if storage_key:
            payload = object_store.read(
                storage_key,
                str(item.get("sha256") or "").strip(),
            )
            source_name = Path(storage_key).name
        else:
            source_path = Path(str(item["source_path"])).expanduser().resolve()
            payload = source_path.read_bytes()
            source_name = source_path.name
        print(f"[{index}/{len(inputs)}] parsing {source_name}", flush=True)
        bundles.append(
            build_pdf_bundle(
                row=pd.Series(item),
                payload=payload,
                config=config,
                converter=converter,
            )
        )

    return {
        "documents": _concat_frames(
            [bundle.documents for bundle in bundles], DOCUMENTS_FINAL_COLUMNS
        ),
        "text_units": _concat_frames(
            [bundle.text_units for bundle in bundles], TEXT_UNITS_FINAL_COLUMNS
        ),
        "blocks": _concat_frames(
            [bundle.blocks for bundle in bundles], BLOCKS_FINAL_COLUMNS
        ),
        "figures": _concat_frames(
            [bundle.figures for bundle in bundles], FIGURES_FINAL_COLUMNS
        ),
        "tables": _concat_frames(
            [bundle.tables for bundle in bundles], TABLES_FINAL_COLUMNS
        ),
        "table_rows": _concat_frames(
            [bundle.table_rows for bundle in bundles], TABLE_ROWS_FINAL_COLUMNS
        ),
        "table_cells": _concat_frames(
            [bundle.table_cells for bundle in bundles], TABLE_CELLS_FINAL_COLUMNS
        ),
    }


def _collection_input_rows(
    collection_repository: CollectionRepository,
    collection_id: str,
) -> list[dict[str, Any]]:
    rows = []
    for import_record in collection_repository.list_collection_imports(collection_id):
        for document in import_record.documents:
            file_record = document.file
            storage_key = file_record.storage_key.strip()
            if not storage_key.lower().endswith(".pdf"):
                continue
            if storage_key != f"{collection_id}/input/{file_record.stored_filename}":
                raise ValueError("invalid collection object key")
            rows.append(
                {
                    "id": document.source_document_id,
                    "title": file_record.original_filename or Path(storage_key).name,
                    "creation_date": import_record.ingested_at,
                    "source_path": storage_key,
                    "storage_key": storage_key,
                    "sha256": file_record.sha256,
                    "source_type": "pdf",
                }
            )
    if rows:
        return rows

    for file_record in collection_repository.list_collection_files(collection_id):
        storage_key = file_record.storage_key.strip()
        if not storage_key.lower().endswith(".pdf"):
            continue
        if storage_key != f"{collection_id}/input/{file_record.stored_filename}":
            raise ValueError("invalid collection object key")
        rows.append(
            {
                "id": file_record.file_id,
                "title": file_record.original_filename or Path(storage_key).name,
                "creation_date": file_record.created_at,
                "source_path": storage_key,
                "storage_key": storage_key,
                "sha256": file_record.sha256,
                "source_type": "pdf",
            }
        )
    return rows


def _concat_frames(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=columns)
    available = [frame for frame in frames if frame is not None and not frame.empty]
    if not available:
        return pd.DataFrame(columns=columns)
    concatenated = pd.concat(available, ignore_index=True)
    return _normalize_frame(concatenated.loc[:, columns])


def export_source_tables(
    *,
    frames: dict[str, pd.DataFrame],
    destination: Path,
    collection_dir: Path,
    artifact_dir: Path,
    source_mode: str,
    document_id: str | None,
) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    table_dir = destination / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)

    tables = _filter_by_document(frames.get("tables"), document_id)
    table_rows = _filter_by_document(frames.get("table_rows"), document_id)
    table_cells = _filter_by_document(frames.get("table_cells"), document_id)

    table_records = _frame_records(tables)
    summary_rows = []
    for index, table in enumerate(table_records, start=1):
        table_id = str(table.get("table_id") or "")
        rows = _records_where(table_rows, "table_id", table_id)
        cells = _records_where(table_cells, "table_id", table_id)
        prefix = (
            f"{index:03d}_{_safe_name(table.get('document_id'))}_{_safe_name(table_id)}"
        )
        prefix = prefix[:180]
        _write_table_review_files(
            table_dir=table_dir,
            prefix=prefix,
            table=table,
            rows=rows,
            cells=cells,
        )
        summary_rows.append(
            {
                "index": index,
                "document_id": table.get("document_id"),
                "table_id": table_id,
                "caption_text": table.get("caption_text"),
                "heading_path": table.get("heading_path"),
                "page": table.get("page"),
                "row_count": table.get("row_count"),
                "col_count": table.get("col_count"),
                "table_rows": len(rows),
                "table_cells": len(cells),
                "review_file": f"tables/{prefix}.md",
            }
        )

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_mode": source_mode,
        "collection_dir": str(collection_dir),
        "artifact_dir": str(artifact_dir),
        "document_id_filter": document_id,
        "table_count": len(table_records),
        "table_row_count": int(len(table_rows)),
        "table_cell_count": int(len(table_cells)),
    }
    _write_json(destination / "summary.json", summary)
    pd.DataFrame(summary_rows).to_csv(destination / "tables_summary.csv", index=False)
    (destination / "source_tables.md").write_text(
        _render_source_tables(
            summary=summary, summary_rows=summary_rows, table_dir=table_dir
        ),
        encoding="utf-8",
    )
    return destination


def _write_table_review_files(
    *,
    table_dir: Path,
    prefix: str,
    table: dict[str, Any],
    rows: list[dict[str, Any]],
    cells: list[dict[str, Any]],
) -> None:
    matrix = _normalize_matrix(table.get("table_matrix"))
    if matrix:
        pd.DataFrame(matrix).to_csv(
            table_dir / f"{prefix}_matrix.csv", index=False, header=False
        )
    pd.DataFrame(rows).to_csv(table_dir / f"{prefix}_rows.csv", index=False)
    pd.DataFrame(cells).to_csv(table_dir / f"{prefix}_cells.csv", index=False)
    (table_dir / f"{prefix}.md").write_text(
        _render_single_table(table=table, rows=rows, cells=cells, matrix=matrix),
        encoding="utf-8",
    )


def _render_source_tables(
    *,
    summary: dict[str, Any],
    summary_rows: list[dict[str, Any]],
    table_dir: Path,
) -> str:
    lines = [
        "# Source Table Split Preview",
        "",
        f"- source_mode: `{summary['source_mode']}`",
        f"- collection_dir: `{summary['collection_dir']}`",
        f"- table_count: `{summary['table_count']}`",
        f"- table_row_count: `{summary['table_row_count']}`",
        f"- table_cell_count: `{summary['table_cell_count']}`",
        "",
        "## Tables",
        "",
        "| # | document_id | table_id | page | rows | cols | caption | review |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in summary_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(item.get("index")),
                    _md_cell(item.get("document_id")),
                    _md_cell(item.get("table_id")),
                    _md_cell(item.get("page")),
                    _md_cell(item.get("row_count")),
                    _md_cell(item.get("col_count")),
                    _md_cell(item.get("caption_text")),
                    f"[open]({item.get('review_file')})",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Per-table files are under:",
            "",
            f"`{table_dir}`",
            "",
        ]
    )
    return "\n".join(lines)


def _render_single_table(
    *,
    table: dict[str, Any],
    rows: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    matrix: list[list[str]],
) -> str:
    lines = [
        f"# {table.get('table_id') or 'Table'}",
        "",
        f"- document_id: `{table.get('document_id')}`",
        f"- caption: {table.get('caption_text') or 'n/a'}",
        f"- heading_path: {table.get('heading_path') or 'n/a'}",
        f"- page: {table.get('page') or 'n/a'}",
        f"- row_count: `{table.get('row_count') or len(matrix) or len(rows)}`",
        f"- col_count: `{table.get('col_count') or _matrix_col_count(matrix)}`",
        f"- table_rows: `{len(rows)}`",
        f"- table_cells: `{len(cells)}`",
        "",
        "## Table Matrix",
        "",
        _matrix_to_markdown(matrix) if matrix else "_no table_matrix_",
        "",
        "## Table Markdown",
        "",
        str(table.get("table_markdown") or "_no table_markdown_"),
        "",
        "## Row Anchors",
        "",
        "| row_index | row_text | page | heading_path |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                _md_cell(row.get(key))
                for key in ("row_index", "row_text", "page", "heading_path")
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Cells",
            "",
            "| row | col | header_path | cell_text | unit |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for cell in cells:
        lines.append(
            "| "
            + " | ".join(
                _md_cell(cell.get(key))
                for key in (
                    "row_index",
                    "col_index",
                    "header_path",
                    "cell_text",
                    "unit_hint",
                )
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    normalized = frame.copy()
    for column in normalized.columns:
        normalized[column] = normalized[column].map(_normalize_value)
    return normalized


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_value(item) for item in value]
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, dict)):
        converted = value.tolist()
        if converted is not value:
            return _normalize_value(converted)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if (text.startswith("{") and text.endswith("}")) or (
            text.startswith("[") and text.endswith("]")
        ):
            for parser in (json.loads, ast.literal_eval):
                try:
                    return _normalize_value(parser(text))
                except (ValueError, SyntaxError, json.JSONDecodeError, TypeError):
                    continue
        return text
    return value


def _frame_records(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    return [
        {str(key): _normalize_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _filter_by_document(
    frame: pd.DataFrame | None, document_id: str | None
) -> pd.DataFrame:
    if frame is None or frame.empty or not document_id:
        return pd.DataFrame() if frame is None else frame.copy()
    column = "document_id" if "document_id" in frame.columns else "id"
    if column not in frame.columns:
        return frame.copy()
    return frame[frame[column].astype(str) == str(document_id)].copy()


def _records_where(
    frame: pd.DataFrame | None, key: str, value: str
) -> list[dict[str, Any]]:
    if frame is None or frame.empty or key not in frame.columns:
        return []
    return _frame_records(frame[frame[key].astype(str) == str(value)])


def _normalize_matrix(value: Any) -> list[list[str]]:
    normalized = _normalize_value(value)
    if not isinstance(normalized, list):
        return []
    matrix = []
    for row in normalized:
        if isinstance(row, list):
            matrix.append([str(cell or "") for cell in row])
        elif row not in (None, ""):
            matrix.append([str(row)])
    return matrix


def _matrix_to_markdown(matrix: list[list[str]]) -> str:
    if not matrix:
        return "_empty matrix_"
    col_count = _matrix_col_count(matrix)
    rows = [row + [""] * (col_count - len(row)) for row in matrix]
    header = rows[0] if rows else [f"column_{index + 1}" for index in range(col_count)]
    body = rows[1:]
    lines = [
        "| " + " | ".join(_md_cell(cell) for cell in header) + " |",
        "| " + " | ".join("---" for _ in range(col_count)) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(_md_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def _matrix_col_count(matrix: list[list[str]]) -> int:
    return max((len(row) for row in matrix), default=0)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def _safe_name(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-._")
    return text or "unknown"


if __name__ == "__main__":
    main()
