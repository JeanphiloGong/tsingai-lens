#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
from time import perf_counter
from typing import Any, Iterable

from _common import (
    DEFAULT_BACKEND_ROOT,
    ensure_backend_root_on_path,
    summarize_timings,
    write_json_output,
)


PARSER_CHOICES = ("all", "docling", "mineru")
DEFAULT_MINERU_COMMAND = "mineru"
DEFAULT_MINERU_PARSE_METHOD = "auto"
DEFAULT_MINERU_TIMEOUT_S = 900.0


@dataclass(frozen=True)
class MinerUConfig:
    command: str
    parse_method: str
    timeout_s: float
    output_dir: Path | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an offline Source parser benchmark for the active Docling path "
            "and, when installed, MinerU. This script does not change the "
            "production Source runtime or backend dependency set."
        )
    )
    parser.add_argument(
        "--backend-root",
        type=Path,
        help="Optional backend root override. Defaults to the repo-local backend root.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        help=(
            "Directory to scan for PDFs when --pdf is not provided. Defaults to "
            "<backend-root>/data/documents when it exists."
        ),
    )
    parser.add_argument(
        "--pdf",
        action="append",
        type=Path,
        default=[],
        help="PDF file to benchmark. Can be provided multiple times.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional maximum number of PDFs after sorting.",
    )
    parser.add_argument(
        "--parser",
        choices=PARSER_CHOICES,
        default="all",
        help="Parser set to run. Defaults to all.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="Optional JSON file path for the final benchmark summary.",
    )
    parser.add_argument(
        "--mineru-command",
        default=DEFAULT_MINERU_COMMAND,
        help="MinerU executable command. Defaults to `mineru`.",
    )
    parser.add_argument(
        "--mineru-parse-method",
        default=DEFAULT_MINERU_PARSE_METHOD,
        help="MinerU parse method passed with `-m`. Defaults to `auto`.",
    )
    parser.add_argument(
        "--mineru-timeout-s",
        type=float,
        default=DEFAULT_MINERU_TIMEOUT_S,
        help=f"Per-document MinerU timeout in seconds. Defaults to {DEFAULT_MINERU_TIMEOUT_S}.",
    )
    parser.add_argument(
        "--mineru-output-dir",
        type=Path,
        help=(
            "Optional directory for MinerU parser output. When omitted, a temporary "
            "directory is used and removed after summarization."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    backend_root = _resolve_backend_root(args.backend_root)
    pdf_paths = _collect_pdf_paths(
        backend_root=backend_root,
        explicit_pdfs=args.pdf,
        input_dir=args.input_dir,
        limit=args.limit,
    )

    if not pdf_paths:
        raise SystemExit(
            "No PDF inputs found. Pass --pdf or --input-dir with at least one PDF."
        )

    parser_records: list[dict[str, Any]] = []
    selected_parsers = _selected_parsers(args.parser)

    if "docling" in selected_parsers:
        parser_records.extend(
            run_docling_benchmark(
                backend_root=backend_root,
                pdf_paths=pdf_paths,
            )
        )

    if "mineru" in selected_parsers:
        parser_records.extend(
            run_mineru_benchmark(
                backend_root=backend_root,
                pdf_paths=pdf_paths,
                config=MinerUConfig(
                    command=args.mineru_command,
                    parse_method=args.mineru_parse_method,
                    timeout_s=float(args.mineru_timeout_s),
                    output_dir=args.mineru_output_dir,
                ),
            )
        )

    summary = build_summary(
        backend_root=backend_root,
        pdf_paths=pdf_paths,
        selected_parsers=selected_parsers,
        parser_records=parser_records,
        mineru_config=MinerUConfig(
            command=args.mineru_command,
            parse_method=args.mineru_parse_method,
            timeout_s=float(args.mineru_timeout_s),
            output_dir=args.mineru_output_dir,
        ),
    )

    write_json_output(args.summary_output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if any(record.get("status") == "error" for record in parser_records):
        return 1
    return 0


def run_docling_benchmark(
    *,
    backend_root: Path,
    pdf_paths: list[Path],
) -> list[dict[str, Any]]:
    ensure_backend_root_on_path(backend_root)

    try:
        import pandas as pd

        from infra.source.config.source_runtime_config import SourceRuntimeConfig
        from infra.source.runtime.workflows.create_source_artifacts import (
            _build_pdf_bundle,
            _build_pdf_converter,
        )

        config = SourceRuntimeConfig(root_dir=str(backend_root))
        converter = _build_pdf_converter()
    except Exception as exc:
        return [
            _error_record(
                parser="docling",
                pdf_path=pdf_path,
                error=f"Docling setup failed: {exc}",
            )
            for pdf_path in pdf_paths
        ]

    records: list[dict[str, Any]] = []
    for pdf_path in pdf_paths:
        started_at = perf_counter()
        try:
            payload = pdf_path.read_bytes()
            row = pd.Series(
                {
                    "id": _document_id(pdf_path),
                    "title": pdf_path.name,
                    "source_path": str(pdf_path),
                    "source_type": "pdf",
                    "metadata": {"benchmark_source": "source_parser_benchmark"},
                }
            )
            bundle = _build_pdf_bundle(
                row=row,
                payload=payload,
                config=config,
                converter=converter,
            )
            elapsed_s = perf_counter() - started_at
            metrics = summarize_source_bundle(bundle)
            records.append(
                _success_record(
                    parser="docling",
                    pdf_path=pdf_path,
                    elapsed_s=elapsed_s,
                    metrics=metrics,
                    parser_details={
                        "execution": "active_source_docling_mapping",
                        "normalized_to_source_artifacts": True,
                    },
                )
            )
        except Exception as exc:
            records.append(
                _error_record(
                    parser="docling",
                    pdf_path=pdf_path,
                    error=str(exc),
                    elapsed_s=perf_counter() - started_at,
                )
            )
    return records


def run_mineru_benchmark(
    *,
    backend_root: Path,
    pdf_paths: list[Path],
    config: MinerUConfig,
) -> list[dict[str, Any]]:
    if config.timeout_s <= 0:
        raise SystemExit("--mineru-timeout-s must be greater than 0")

    command_parts = shlex.split(config.command)
    if not command_parts:
        return [
            _skipped_record(
                parser="mineru",
                pdf_path=pdf_path,
                reason="empty MinerU command",
            )
            for pdf_path in pdf_paths
        ]

    executable = shutil.which(command_parts[0])
    if executable is None and not Path(command_parts[0]).exists():
        return [
            _skipped_record(
                parser="mineru",
                pdf_path=pdf_path,
                reason=f"MinerU command not found: {command_parts[0]}",
            )
            for pdf_path in pdf_paths
        ]

    output_context: Any
    if config.output_dir is None:
        output_context = tempfile.TemporaryDirectory(prefix="lens-mineru-benchmark-")
    else:
        config.output_dir.expanduser().resolve().mkdir(parents=True, exist_ok=True)
        output_context = nullcontext(str(config.output_dir.expanduser().resolve()))

    records: list[dict[str, Any]] = []
    with output_context as output_root_text:
        output_root = Path(output_root_text)
        for pdf_path in pdf_paths:
            records.append(
                _run_mineru_for_pdf(
                    backend_root=backend_root,
                    pdf_path=pdf_path,
                    command_parts=command_parts,
                    parse_method=config.parse_method,
                    timeout_s=config.timeout_s,
                    output_root=output_root,
                    output_is_temporary=config.output_dir is None,
                )
            )
    return records


def _run_mineru_for_pdf(
    *,
    backend_root: Path,
    pdf_path: Path,
    command_parts: list[str],
    parse_method: str,
    timeout_s: float,
    output_root: Path,
    output_is_temporary: bool,
) -> dict[str, Any]:
    output_dir = output_root / _safe_output_name(pdf_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        *command_parts,
        "-p",
        str(pdf_path),
        "-o",
        str(output_dir),
        "-m",
        parse_method,
    ]
    started_at = perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(backend_root),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return _error_record(
            parser="mineru",
            pdf_path=pdf_path,
            error=f"MinerU timed out after {timeout_s} seconds",
            elapsed_s=perf_counter() - started_at,
            parser_details={"stdout_tail": _tail(exc.stdout), "stderr_tail": _tail(exc.stderr)},
        )
    except Exception as exc:
        return _error_record(
            parser="mineru",
            pdf_path=pdf_path,
            error=str(exc),
            elapsed_s=perf_counter() - started_at,
        )

    elapsed_s = perf_counter() - started_at
    output_summary = summarize_mineru_output(output_dir)
    parser_details = {
        "execution": "mineru_cli",
        "command": _redact_command(command),
        "returncode": completed.returncode,
        "parse_method": parse_method,
        "output_dir": None if output_is_temporary else str(output_dir),
        "normalized_to_source_artifacts": False,
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
    }
    if completed.returncode != 0:
        return _error_record(
            parser="mineru",
            pdf_path=pdf_path,
            error=f"MinerU exited with status {completed.returncode}",
            elapsed_s=elapsed_s,
            metrics=output_summary,
            parser_details=parser_details,
        )

    return _success_record(
        parser="mineru",
        pdf_path=pdf_path,
        elapsed_s=elapsed_s,
        metrics=output_summary,
        parser_details=parser_details,
    )


def summarize_source_bundle(bundle: Any) -> dict[str, Any]:
    documents = bundle.documents
    text_units = bundle.text_units
    blocks = bundle.blocks
    figures = bundle.figures
    tables = getattr(bundle, "tables", None)
    table_rows = bundle.table_rows
    table_cells = bundle.table_cells

    block_count = len(blocks)
    table_count = len(tables) if tables is not None else 0
    table_cell_count = len(table_cells)
    figure_count = len(figures)
    text_chars = _frame_text_chars(documents, "text")
    warnings: list[str] = []
    if text_chars == 0:
        warnings.append("empty_document_text")
    if block_count == 0:
        warnings.append("no_blocks")
    if block_count > 0 and _non_empty_count(blocks, "page") == 0:
        warnings.append("blocks_missing_page_locators")

    return {
        "artifact_rows": {
            "documents": len(documents),
            "text_units": len(text_units),
            "blocks": block_count,
            "figures": figure_count,
            "tables": table_count,
            "table_rows": len(table_rows),
            "table_cells": table_cell_count,
        },
        "document_text_chars": text_chars,
        "text_unit_chars": _frame_text_chars(text_units, "text"),
        "block_type_counts": _value_counts(blocks, "block_type"),
        "heading_count": _equals_count(blocks, "block_type", "heading"),
        "figure_caption_count": _equals_count(blocks, "block_type", "figure_caption"),
        "table_caption_count": _equals_count(blocks, "block_type", "table_caption"),
        "table_count": table_count or _unique_count(table_cells, "table_id"),
        "table_context": {
            "tables_with_markdown": _non_empty_count(tables, "table_markdown"),
            "tables_with_text": _non_empty_count(tables, "table_text"),
            "tables_with_caption": _non_empty_count(tables, "caption_text"),
            "tables_with_column_headers": _non_empty_count(tables, "column_headers"),
        },
        "figure_asset_count": len(getattr(bundle, "figure_assets", {}) or {}),
        "locator_counts": {
            "blocks_with_page": _non_empty_count(blocks, "page"),
            "blocks_with_bbox": _non_empty_count(blocks, "bbox"),
            "blocks_with_char_range": _non_empty_count(blocks, "char_range"),
            "tables_with_page": _non_empty_count(tables, "page"),
            "tables_with_bbox": _non_empty_count(tables, "bbox"),
            "table_cells_with_page": _non_empty_count(table_cells, "page"),
            "table_cells_with_bbox": _non_empty_count(table_cells, "bbox"),
            "figures_with_page": _non_empty_count(figures, "page"),
            "figures_with_bbox": _non_empty_count(figures, "bbox"),
        },
        "locator_ratios": {
            "blocks_with_page": _ratio(_non_empty_count(blocks, "page"), block_count),
            "blocks_with_bbox": _ratio(_non_empty_count(blocks, "bbox"), block_count),
            "tables_with_page": _ratio(_non_empty_count(tables, "page"), table_count),
            "table_cells_with_page": _ratio(
                _non_empty_count(table_cells, "page"),
                table_cell_count,
            ),
            "figures_with_page": _ratio(_non_empty_count(figures, "page"), figure_count),
        },
        "warnings": warnings,
    }


def summarize_mineru_output(output_dir: Path) -> dict[str, Any]:
    files = [path for path in output_dir.rglob("*") if path.is_file()]
    files_by_suffix = Counter(path.suffix.lower() or "<none>" for path in files)
    content_list_path = _find_content_list_file(output_dir)
    content_items: list[dict[str, Any]] = []
    if content_list_path is not None:
        content_items = _load_content_items(content_list_path)
    markdown_files = [path for path in files if path.suffix.lower() in {".md", ".markdown"}]
    markdown_chars = 0
    for path in markdown_files:
        try:
            markdown_chars += len(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue

    content_summary = summarize_mineru_content_items(content_items)
    warnings: list[str] = []
    if content_list_path is None:
        warnings.append("content_list_not_found")
    if not content_items and markdown_chars == 0:
        warnings.append("no_readable_mineru_text")

    return {
        "file_count": len(files),
        "files_by_suffix": dict(sorted(files_by_suffix.items())),
        "content_list_path": str(content_list_path) if content_list_path else None,
        "markdown_file_count": len(markdown_files),
        "markdown_chars": markdown_chars,
        "content_list_summary": content_summary,
        "warnings": warnings,
    }


def summarize_mineru_content_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    text_chars = 0
    page_locator_count = 0
    bbox_locator_count = 0
    table_html_count = 0
    table_markdown_count = 0
    table_text_count = 0

    for item in items:
        kind = _classify_mineru_item(item)
        counts[kind] += 1
        if kind == "heading":
            counts["text"] += 1
        text_chars += len(_item_text(item))
        if kind == "table":
            if _first_non_empty_item_value(
                item,
                ("table_body", "table_html", "html", "table"),
            ):
                table_html_count += 1
            if _first_non_empty_item_value(
                item,
                ("table_markdown", "markdown", "md", "table_md"),
            ):
                table_markdown_count += 1
            if _item_text(item):
                table_text_count += 1
        if _has_any_key(item, ("page", "page_idx", "page_no", "page_number")):
            page_locator_count += 1
        if _has_any_key(item, ("bbox", "poly", "polygon")):
            bbox_locator_count += 1

    item_count = len(items)
    return {
        "item_count": item_count,
        "kind_counts": dict(sorted(counts.items())),
        "text_chars": text_chars,
        "heading_count": counts["heading"],
        "table_count": counts["table"],
        "table_context": {
            "tables_with_html": table_html_count,
            "tables_with_markdown": table_markdown_count,
            "tables_with_text": table_text_count,
        },
        "figure_count": counts["figure"],
        "equation_count": counts["equation"],
        "page_locator_count": page_locator_count,
        "bbox_locator_count": bbox_locator_count,
        "page_locator_ratio": _ratio(page_locator_count, item_count),
        "bbox_locator_ratio": _ratio(bbox_locator_count, item_count),
    }


def build_summary(
    *,
    backend_root: Path,
    pdf_paths: list[Path],
    selected_parsers: list[str],
    parser_records: list[dict[str, Any]],
    mineru_config: MinerUConfig,
) -> dict[str, Any]:
    records_by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in parser_records:
        records_by_document[str(record["source_path"])].append(record)

    return {
        "script": "source_parser_benchmark.py",
        "backend_root": str(backend_root),
        "selected_parsers": selected_parsers,
        "input": {
            "pdf_count": len(pdf_paths),
            "pdfs": [str(path) for path in pdf_paths],
        },
        "configuration": {
            "mineru_command": mineru_config.command,
            "mineru_parse_method": mineru_config.parse_method,
            "mineru_timeout_s": mineru_config.timeout_s,
            "mineru_output_dir": (
                str(mineru_config.output_dir.expanduser().resolve())
                if mineru_config.output_dir
                else None
            ),
        },
        "aggregate": aggregate_records(parser_records),
        "documents": [
            {
                "source_path": str(pdf_path),
                "source_sha256": _file_sha256(pdf_path),
                "runs": records_by_document.get(str(pdf_path), []),
            }
            for pdf_path in pdf_paths
        ],
    }


def aggregate_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_parser: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_parser[str(record.get("parser") or "unknown")].append(record)

    aggregate: dict[str, Any] = {}
    for parser, parser_records in sorted(by_parser.items()):
        successful = [
            record for record in parser_records if record.get("status") == "success"
        ]
        elapsed_samples = [
            float(record.get("elapsed_s") or 0.0)
            for record in successful
            if record.get("elapsed_s") is not None
        ]
        aggregate[parser] = {
            "run_count": len(parser_records),
            "success_count": len(successful),
            "skipped_count": sum(
                1 for record in parser_records if record.get("status") == "skipped"
            ),
            "error_count": sum(
                1 for record in parser_records if record.get("status") == "error"
            ),
            "elapsed_s": summarize_timings(elapsed_samples),
            "artifact_rows": _sum_artifact_rows(successful),
            "warnings": _collect_warnings(successful),
        }
    return aggregate


def _collect_pdf_paths(
    *,
    backend_root: Path,
    explicit_pdfs: list[Path],
    input_dir: Path | None,
    limit: int | None,
) -> list[Path]:
    if limit is not None and limit <= 0:
        raise SystemExit("--limit must be greater than 0")

    if explicit_pdfs:
        pdf_paths = [_resolve_pdf_path(path) for path in explicit_pdfs]
    else:
        resolved_input_dir = (
            input_dir.expanduser().resolve()
            if input_dir is not None
            else backend_root / "data" / "documents"
        )
        if not resolved_input_dir.is_dir():
            raise SystemExit(f"input directory not found: {resolved_input_dir}")
        pdf_paths = sorted(resolved_input_dir.glob("*.pdf"))

    if limit is not None:
        pdf_paths = pdf_paths[:limit]
    return pdf_paths


def _resolve_pdf_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise SystemExit(f"PDF not found: {resolved}")
    if resolved.suffix.lower() != ".pdf":
        raise SystemExit(f"not a PDF file: {resolved}")
    return resolved


def _resolve_backend_root(path: Path | None) -> Path:
    backend_root = DEFAULT_BACKEND_ROOT if path is None else path.expanduser().resolve()
    if not backend_root.is_dir():
        raise SystemExit(f"backend root not found: {backend_root}")
    return backend_root


def _selected_parsers(parser: str) -> list[str]:
    if parser == "all":
        return ["docling", "mineru"]
    return [parser]


def _success_record(
    *,
    parser: str,
    pdf_path: Path,
    elapsed_s: float,
    metrics: dict[str, Any],
    parser_details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "parser": parser,
        "status": "success",
        "source_path": str(pdf_path),
        "document_id": _document_id(pdf_path),
        "elapsed_s": round(float(elapsed_s), 6),
        "metrics": metrics,
        "parser_details": parser_details,
    }


def _error_record(
    *,
    parser: str,
    pdf_path: Path,
    error: str,
    elapsed_s: float | None = None,
    metrics: dict[str, Any] | None = None,
    parser_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "parser": parser,
        "status": "error",
        "source_path": str(pdf_path),
        "document_id": _document_id(pdf_path),
        "elapsed_s": round(float(elapsed_s), 6) if elapsed_s is not None else None,
        "error": error,
        "metrics": metrics or {},
        "parser_details": parser_details or {},
    }


def _skipped_record(*, parser: str, pdf_path: Path, reason: str) -> dict[str, Any]:
    return {
        "parser": parser,
        "status": "skipped",
        "source_path": str(pdf_path),
        "document_id": _document_id(pdf_path),
        "elapsed_s": None,
        "skip_reason": reason,
        "metrics": {},
        "parser_details": {},
    }


def _document_id(pdf_path: Path) -> str:
    return hashlib.sha256(str(pdf_path.resolve()).encode("utf-8")).hexdigest()[:16]


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_output_name(path: Path) -> str:
    digest = _document_id(path)
    safe_stem = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in path.stem
    ).strip("_")
    return f"{safe_stem[:80]}_{digest}"


def _sum_artifact_rows(records: list[dict[str, Any]]) -> dict[str, int]:
    totals: Counter[str] = Counter()
    for record in records:
        artifact_rows = (
            record.get("metrics", {}).get("artifact_rows")
            if isinstance(record.get("metrics"), dict)
            else None
        )
        if not isinstance(artifact_rows, dict):
            continue
        for name, value in artifact_rows.items():
            totals[str(name)] += int(value or 0)
    return dict(sorted(totals.items()))


def _collect_warnings(records: list[dict[str, Any]]) -> dict[str, int]:
    warnings: Counter[str] = Counter()
    for record in records:
        metrics = record.get("metrics")
        if not isinstance(metrics, dict):
            continue
        for warning in metrics.get("warnings", []) or []:
            warnings[str(warning)] += 1
    return dict(sorted(warnings.items()))


def _frame_text_chars(frame: Any, column: str) -> int:
    if frame is None or getattr(frame, "empty", True) or column not in frame:
        return 0
    return int(sum(len(str(value or "")) for value in frame[column].tolist()))


def _value_counts(frame: Any, column: str) -> dict[str, int]:
    if frame is None or getattr(frame, "empty", True) or column not in frame:
        return {}
    values = [
        str(value).strip()
        for value in frame[column].tolist()
        if str(value or "").strip()
    ]
    return dict(sorted(Counter(values).items()))


def _equals_count(frame: Any, column: str, expected: str) -> int:
    if frame is None or getattr(frame, "empty", True) or column not in frame:
        return 0
    return int(
        sum(1 for value in frame[column].tolist() if str(value or "") == expected)
    )


def _unique_count(frame: Any, column: str) -> int:
    if frame is None or getattr(frame, "empty", True) or column not in frame:
        return 0
    values = {
        str(value).strip()
        for value in frame[column].tolist()
        if str(value or "").strip()
    }
    return len(values)


def _non_empty_count(frame: Any, column: str) -> int:
    if frame is None or getattr(frame, "empty", True) or column not in frame:
        return 0
    return int(
        sum(1 for value in frame[column].tolist() if str(value or "").strip())
    )


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def _find_content_list_file(output_dir: Path) -> Path | None:
    candidates = sorted(output_dir.rglob("*content_list*.json"))
    if candidates:
        return candidates[0]
    for path in sorted(output_dir.rglob("*.json")):
        try:
            items = _extract_content_items(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
        if items:
            return path
    return None


def _load_content_items(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return _extract_content_items(payload)


def _extract_content_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("content_list", "items", "blocks", "data"):
        items = _extract_content_items(payload.get(key))
        if items:
            return items

    for value in payload.values():
        items = _extract_content_items(value)
        if items:
            return items
    return []


def _classify_mineru_item(item: dict[str, Any]) -> str:
    item_type = str(item.get("type") or item.get("category") or "").lower()
    if "table" in item_type:
        return "table"
    if "image" in item_type or "figure" in item_type or item.get("img_path"):
        return "figure"
    if "equation" in item_type or item.get("latex") or item.get("latex_text"):
        return "equation"
    if item.get("text_level") is not None or item_type in {"title", "heading"}:
        return "heading"
    if _item_text(item):
        return "text"
    return "other"


def _item_text(item: dict[str, Any]) -> str:
    parts = [
        _coerce_text(item.get(key))
        for key in (
            "text",
            "content",
            "table_body",
            "table_caption",
            "img_caption",
            "image_caption",
            "caption",
            "latex",
            "latex_text",
        )
    ]
    return "\n".join(part for part in parts if part)


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_coerce_text(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        return " ".join(
            text for text in (_coerce_text(item) for item in value.values()) if text
        ).strip()
    return str(value).strip()


def _first_non_empty_item_value(item: dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        text = _coerce_text(item.get(key))
        if text:
            return text
    return None


def _has_any_key(item: dict[str, Any], keys: Iterable[str]) -> bool:
    return any(key in item and item.get(key) is not None for key in keys)


def _tail(value: Any, limit: int = 2000) -> str | None:
    if value is None:
        return None
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    text = text.strip()
    if not text:
        return None
    return text[-limit:]


def _redact_command(command: list[str]) -> list[str]:
    return [str(part) for part in command]


if __name__ == "__main__":
    raise SystemExit(main())
