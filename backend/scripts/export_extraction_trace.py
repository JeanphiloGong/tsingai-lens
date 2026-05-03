#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ARTIFACTS = (
    "documents",
    "text_units",
    "blocks",
    "figures",
    "tables",
    "table_rows",
    "table_cells",
)
CORE_ARTIFACTS = (
    "document_profiles",
    "evidence_anchors",
    "method_facts",
    "sample_variants",
    "test_conditions",
    "baseline_references",
    "measurement_results",
    "characterization_observations",
    "structure_features",
    "evidence_cards",
    "comparable_results",
    "collection_comparable_results",
    "comparison_rows",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Source/Core extraction artifacts into a local trace directory."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--collection-id",
        help="Collection id under <backend-root>/data/collections/<collection-id>/output.",
    )
    source.add_argument(
        "--output-dir",
        type=Path,
        help="Direct collection output directory containing parquet artifacts.",
    )
    parser.add_argument(
        "--backend-root",
        type=Path,
        default=DEFAULT_BACKEND_ROOT,
        help="Backend root. Defaults to the repo-local backend directory.",
    )
    parser.add_argument(
        "--trace-root",
        type=Path,
        help="Trace root. Defaults to <backend-root>/data/traces.",
    )
    parser.add_argument(
        "--trace-name",
        help="Optional trace directory name. Defaults to a timestamped name.",
    )
    parser.add_argument(
        "--document-id",
        help="Optional document id filter for Markdown trace views.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = export_trace(
        backend_root=args.backend_root,
        collection_id=args.collection_id,
        source_output_dir=args.output_dir,
        trace_root=args.trace_root,
        trace_name=args.trace_name,
        document_id=args.document_id,
    )
    print(output_dir)


def export_trace(
    *,
    backend_root: str | Path = DEFAULT_BACKEND_ROOT,
    collection_id: str | None = None,
    source_output_dir: str | Path | None = None,
    trace_root: str | Path | None = None,
    trace_name: str | None = None,
    document_id: str | None = None,
) -> Path:
    backend_root = Path(backend_root).expanduser().resolve()
    output_dir = _resolve_source_output_dir(
        backend_root=backend_root,
        collection_id=collection_id,
        source_output_dir=source_output_dir,
    )
    if not output_dir.is_dir():
        raise SystemExit(f"collection output directory not found: {output_dir}")

    resolved_trace_root = (
        Path(trace_root).expanduser().resolve()
        if trace_root is not None
        else backend_root / "data" / "traces"
    )
    name = trace_name or _default_trace_name(collection_id, output_dir)
    destination = resolved_trace_root / name
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "artifacts").mkdir(parents=True, exist_ok=True)

    frames = _load_artifacts(output_dir)
    _write_artifact_exports(destination / "artifacts", frames)
    summary = _build_summary(
        collection_id=collection_id,
        source_output_dir=output_dir,
        trace_dir=destination,
        frames=frames,
    )
    _write_json(destination / "summary.json", summary)
    (destination / "README.md").write_text(
        _render_readme(summary),
        encoding="utf-8",
    )
    (destination / "source_tables.md").write_text(
        _render_source_tables(frames, document_id=document_id),
        encoding="utf-8",
    )
    (destination / "extraction_trace.md").write_text(
        _render_extraction_trace(frames, document_id=document_id),
        encoding="utf-8",
    )
    return destination


def _resolve_source_output_dir(
    *,
    backend_root: Path,
    collection_id: str | None,
    source_output_dir: str | Path | None,
) -> Path:
    if source_output_dir is not None:
        return Path(source_output_dir).expanduser().resolve()
    if not collection_id:
        raise SystemExit("--collection-id or --output-dir is required")
    return backend_root / "data" / "collections" / collection_id / "output"


def _default_trace_name(collection_id: str | None, output_dir: Path) -> str:
    prefix = collection_id or output_dir.parent.name or output_dir.name
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{_safe_name(prefix)}-{timestamp}"


def _load_artifacts(output_dir: Path) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for name in (*SOURCE_ARTIFACTS, *CORE_ARTIFACTS):
        path = output_dir / f"{name}.parquet"
        if not path.is_file():
            frames[name] = pd.DataFrame()
            continue
        frames[name] = _normalize_frame(pd.read_parquet(path))
    return frames


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    normalized = frame.copy()
    for column in normalized.columns:
        normalized[column] = normalized[column].map(_normalize_value)
    return normalized


def _write_artifact_exports(destination: Path, frames: dict[str, pd.DataFrame]) -> None:
    for name, frame in frames.items():
        if frame.empty:
            continue
        records = _frame_records(frame)
        _write_json(destination / f"{name}.json", records)
        _write_csv(destination / f"{name}.csv", frame)


def _build_summary(
    *,
    collection_id: str | None,
    source_output_dir: Path,
    trace_dir: Path,
    frames: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    return {
        "collection_id": collection_id,
        "source_output_dir": str(source_output_dir),
        "trace_dir": str(trace_dir),
        "artifact_rows": {
            name: int(len(frame))
            for name, frame in frames.items()
            if not frame.empty
        },
        "generated_files": [
            "README.md",
            "summary.json",
            "source_tables.md",
            "extraction_trace.md",
            "artifacts/*.json",
            "artifacts/*.csv",
        ],
    }


def _render_readme(summary: dict[str, Any]) -> str:
    artifact_rows = summary.get("artifact_rows") or {}
    lines = [
        "# Extraction Trace",
        "",
        f"- collection_id: `{summary.get('collection_id') or 'n/a'}`",
        f"- source_output_dir: `{summary.get('source_output_dir')}`",
        "",
        "## Files",
        "",
        "- `source_tables.md`: complete Source table context for table review",
        "- `extraction_trace.md`: extracted facts with evidence anchors",
        "- `summary.json`: machine-readable artifact row counts",
        "- `artifacts/*.json`: normalized artifact records",
        "- `artifacts/*.csv`: spreadsheet-friendly artifact records",
        "",
        "## Artifact Rows",
        "",
    ]
    if not artifact_rows:
        lines.append("- no artifacts found")
    else:
        for name, count in sorted(artifact_rows.items()):
            lines.append(f"- `{name}`: {count}")
    lines.append("")
    return "\n".join(lines)


def _render_source_tables(
    frames: dict[str, pd.DataFrame],
    *,
    document_id: str | None,
) -> str:
    tables = _filter_by_document(frames.get("tables"), document_id)
    table_rows = _filter_by_document(frames.get("table_rows"), document_id)
    table_cells = frames.get("table_cells", pd.DataFrame())
    lines = ["# Source Tables", ""]
    if tables.empty:
        lines.extend(["No `tables.parquet` rows found.", ""])
        return "\n".join(lines)

    for index, table in enumerate(_frame_records(tables), start=1):
        table_id = str(table.get("table_id") or "")
        matching_rows = _records_where(table_rows, "table_id", table_id)
        matching_cells = _records_where(table_cells, "table_id", table_id)
        lines.extend(
            [
                f"## Table {index}",
                "",
                f"- document_id: `{table.get('document_id')}`",
                f"- table_id: `{table_id}`",
                f"- caption: {table.get('caption_text') or 'n/a'}",
                f"- heading_path: {table.get('heading_path') or 'n/a'}",
                f"- page: {table.get('page') or 'n/a'}",
                f"- rows: {table.get('row_count') or len(matching_rows)}",
                f"- cols: {table.get('col_count') or 'n/a'}",
                f"- table_rows: {len(matching_rows)}",
                f"- table_cells: {len(matching_cells)}",
                "",
                "### Table Markdown",
                "",
                str(table.get("table_markdown") or "_no table markdown_"),
                "",
                "### Row Anchors",
                "",
                "| row_index | row_text | page |",
                "| --- | --- | --- |",
            ]
        )
        for row in matching_rows:
            lines.append(
                "| "
                + " | ".join(
                    _md_cell(row.get(key))
                    for key in ("row_index", "row_text", "page")
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines)


def _render_extraction_trace(
    frames: dict[str, pd.DataFrame],
    *,
    document_id: str | None,
) -> str:
    documents = _filter_by_document(frames.get("documents"), document_id, id_column="id")
    evidence_cards = _filter_by_document(frames.get("evidence_cards"), document_id)
    measurement_results = _filter_by_document(frames.get("measurement_results"), document_id)
    evidence_anchors = _filter_by_document(frames.get("evidence_anchors"), document_id)
    anchor_by_id = {
        str(row.get("anchor_id") or ""): row
        for row in _frame_records(evidence_anchors)
        if str(row.get("anchor_id") or "")
    }

    document_ids = _collect_document_ids(
        documents,
        evidence_cards,
        measurement_results,
        evidence_anchors,
    )
    lines = ["# Extraction Trace", ""]
    if not document_ids:
        lines.extend(["No document-scoped extraction artifacts found.", ""])
        return "\n".join(lines)

    for current_document_id in document_ids:
        title = _document_title(documents, current_document_id)
        lines.extend(
            [
                f"## {title}",
                "",
                f"- document_id: `{current_document_id}`",
                "",
                "### Evidence Cards",
                "",
            ]
        )
        cards = _records_where(evidence_cards, "document_id", current_document_id)
        if not cards:
            lines.append("_No evidence cards._")
            lines.append("")
        else:
            for card in cards:
                lines.extend(_render_fact_block(card, anchor_by_id))

        lines.extend(["### Measurement Results", ""])
        measurements = _records_where(measurement_results, "document_id", current_document_id)
        if not measurements:
            lines.append("_No measurement results._")
            lines.append("")
        else:
            for result in measurements:
                lines.extend(_render_fact_block(result, anchor_by_id))
    return "\n".join(lines)


def _render_fact_block(
    row: dict[str, Any],
    anchor_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    title = (
        row.get("claim_text")
        or row.get("property_normalized")
        or row.get("method_name")
        or row.get("evidence_id")
        or row.get("result_id")
        or "fact"
    )
    lines = [
        f"#### {_one_line(title)}",
        "",
    ]
    for key in (
        "evidence_id",
        "claim_type",
        "evidence_source_type",
        "traceability_status",
        "result_id",
        "property_normalized",
        "result_type",
        "unit",
        "variant_id",
        "baseline_id",
        "test_condition_id",
    ):
        value = row.get(key)
        if value not in (None, "", [], {}):
            lines.append(f"- {key}: `{_one_line(value)}`")

    anchors = _anchors_for_row(row, anchor_by_id)
    if anchors:
        lines.extend(["", "Anchors:"])
        for anchor in anchors:
            quote = anchor.get("quote") or anchor.get("quote_span") or "n/a"
            lines.append(
                "- "
                + "; ".join(
                    part
                    for part in (
                        f"source={anchor.get('source_type')}",
                        f"page={anchor.get('page')}",
                        f"figure_or_table={anchor.get('figure_or_table')}",
                        f"quote={_one_line(quote)}",
                    )
                    if part and not part.endswith("=None")
                )
            )
    lines.append("")
    return lines


def _anchors_for_row(
    row: dict[str, Any],
    anchor_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    direct = row.get("evidence_anchors")
    if isinstance(direct, list):
        return [item for item in direct if isinstance(item, dict)]
    anchor_ids = row.get("evidence_anchor_ids")
    if not isinstance(anchor_ids, list):
        return []
    return [
        anchor_by_id[anchor_id]
        for anchor_id in (str(item) for item in anchor_ids)
        if anchor_id in anchor_by_id
    ]


def _filter_by_document(
    frame: pd.DataFrame | None,
    document_id: str | None,
    *,
    id_column: str = "document_id",
) -> pd.DataFrame:
    if frame is None or frame.empty or not document_id:
        return frame.copy() if frame is not None else pd.DataFrame()
    if id_column not in frame.columns:
        return frame.copy()
    return frame[frame[id_column].astype(str) == str(document_id)].copy()


def _collect_document_ids(*frames: pd.DataFrame) -> list[str]:
    values: list[str] = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        column = "document_id" if "document_id" in frame.columns else "id"
        if column not in frame.columns:
            continue
        values.extend(str(value) for value in frame[column].tolist() if str(value).strip())
    return sorted(dict.fromkeys(values))


def _document_title(documents: pd.DataFrame, document_id: str) -> str:
    if documents is None or documents.empty or "id" not in documents.columns:
        return document_id
    matched = documents[documents["id"].astype(str) == str(document_id)]
    if matched.empty:
        return document_id
    title = matched.iloc[0].get("title")
    return str(title or document_id)


def _frame_records(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _records_where(
    frame: pd.DataFrame | None,
    column: str,
    value: str,
) -> list[dict[str, Any]]:
    if frame is None or frame.empty or column not in frame.columns:
        return []
    matched = frame[frame[column].astype(str) == str(value)]
    return _frame_records(matched)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    csv_frame = frame.copy()
    for column in csv_frame.columns:
        csv_frame[column] = csv_frame[column].map(_csv_value)
    csv_frame.to_csv(path, index=False)


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
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def _json_safe(value: Any) -> Any:
    value = _normalize_value(value)
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _csv_value(value: Any) -> str:
    value = _json_safe(value)
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _safe_name(value: Any) -> str:
    text = str(value or "trace").strip()
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in text)
    return cleaned.strip("-_") or "trace"


def _one_line(value: Any, *, limit: int = 240) -> str:
    text = _csv_value(value)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _md_cell(value: Any) -> str:
    return _one_line(value, limit=160).replace("|", "\\|")


if __name__ == "__main__":
    main()
