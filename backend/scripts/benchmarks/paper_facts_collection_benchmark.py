#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import logging
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any

import pandas as pd

from _common import (
    add_runtime_arguments,
    display_base_url,
    ensure_backend_root_on_path,
    payload_hash,
    resolve_runtime,
    summarize_timings,
    write_json_output,
)


_PAPER_FACTS_LOGGER_NAME = "application.core.semantic_build.paper_facts_service"


class _DocumentWallClockHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self._starts: dict[str, float] = {}
        self._finishes: dict[str, float] = {}

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if "Paper facts extraction document started" in message:
            document_id = _extract_log_value(message, "document_id")
            if document_id:
                self._starts[document_id] = record.created
        elif "Paper facts extraction document finished" in message:
            document_id = _extract_log_value(message, "document_id")
            if document_id:
                self._finishes[document_id] = record.created

    def wall_time_by_document(self) -> dict[str, float]:
        metrics: dict[str, float] = {}
        for document_id, started_at in self._starts.items():
            finished_at = self._finishes.get(document_id)
            if finished_at is None:
                continue
            metrics[document_id] = round(finished_at - started_at, 6)
        return metrics


class _TimingRecordingExtractor:
    def __init__(
        self,
        inner_extractor: Any,
        *,
        payload_catalog: dict[str, list[dict[str, Any]]],
    ) -> None:
        self._inner_extractor = inner_extractor
        self._payload_catalog = {
            payload_key: list(items)
            for payload_key, items in payload_catalog.items()
        }
        self._lock = Lock()
        self.records: list[dict[str, Any]] = []

    def extract_text_window_bundle(self, payload: dict[str, Any]) -> Any:
        return self._timed_call(
            kind="text_window",
            payload=payload,
            call=self._inner_extractor.extract_text_window_bundle,
        )

    def extract_table_row_bundle(self, payload: dict[str, Any]) -> Any:
        return self._timed_call(
            kind="table_row",
            payload=payload,
            call=self._inner_extractor.extract_table_row_bundle,
        )

    def _timed_call(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        call: Any,
    ) -> Any:
        metadata = self._claim_metadata(payload)
        started_at = perf_counter()
        try:
            bundle = call(payload)
        except Exception as exc:
            elapsed_s = perf_counter() - started_at
            self._record(
                kind=kind,
                metadata=metadata,
                elapsed_s=elapsed_s,
                success=False,
                counts=None,
                error=str(exc),
            )
            raise
        elapsed_s = perf_counter() - started_at
        self._record(
            kind=kind,
            metadata=metadata,
            elapsed_s=elapsed_s,
            success=True,
            counts=_bundle_counts(bundle),
            error=None,
        )
        return bundle

    def _claim_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload_key = payload_hash(payload)
        with self._lock:
            bucket = self._payload_catalog.get(payload_key, [])
            if bucket:
                return dict(bucket.pop(0))
        return {}

    def _record(
        self,
        *,
        kind: str,
        metadata: dict[str, Any],
        elapsed_s: float,
        success: bool,
        counts: dict[str, int] | None,
        error: str | None,
    ) -> None:
        record = dict(metadata)
        record.update(
            {
                "kind": kind,
                "elapsed_s": round(elapsed_s, 6),
                "success": success,
                "counts": counts,
                "error": error,
            }
        )
        with self._lock:
            self.records.append(record)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark collection-level paper facts extraction using the real "
            "`PaperFactsService.build_paper_facts` path."
        )
    )
    parser.add_argument(
        "--collection-id",
        required=True,
        help="Target collection id.",
    )
    parser.add_argument(
        "--collections-root",
        type=Path,
        help="Optional collections root override. Defaults to <backend-root>/data/collections.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="Optional JSON file path for the final benchmark summary.",
    )
    add_runtime_arguments(
        parser,
        include_temperature=False,
        include_max_completion_tokens=False,
    )
    return parser.parse_args()


def build_services(
    collections_root: Path,
) -> tuple[Any, Any, Any, Any, Any]:
    from application.core.semantic_build.document_profile_service import DocumentProfileService
    from application.core.semantic_build.llm.extractor import CoreLLMStructuredExtractor
    from application.core.semantic_build.paper_facts_service import PaperFactsService
    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(root_dir=collections_root)
    artifact_registry_service = ArtifactRegistryService(root_dir=collections_root)
    document_profile_service = DocumentProfileService(
        collection_service=collection_service,
        artifact_registry_service=artifact_registry_service,
    )
    return (
        collection_service,
        artifact_registry_service,
        document_profile_service,
        PaperFactsService,
        CoreLLMStructuredExtractor,
    )


def load_collection_inputs_for_benchmark(
    collection_id: str,
    *,
    collections_root: Path,
) -> tuple[Path, pd.DataFrame, pd.DataFrame | None, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    from application.source.artifact_input_service import (
        load_blocks_artifact,
        load_collection_inputs,
        load_table_cells_artifact,
        load_table_rows_artifact,
    )
    from application.source.collection_service import CollectionService

    collection_service = CollectionService(root_dir=collections_root)
    output_dir = collection_service.get_paths(collection_id).output_dir
    documents, text_units = load_collection_inputs(output_dir)
    blocks = load_blocks_artifact(output_dir)
    table_rows = load_table_rows_artifact(output_dir)
    table_cells = load_table_cells_artifact(output_dir)
    profiles_path = output_dir / "document_profiles.parquet"
    if not profiles_path.is_file():
        raise SystemExit(
            "document_profiles.parquet is missing. Build document profiles first so this "
            "benchmark isolates paper-facts extraction cost."
        )
    profiles = pd.read_parquet(profiles_path)
    return output_dir, documents, text_units, blocks, table_rows, table_cells, profiles


def build_selection_plan(
    *,
    collection_id: str,
    paper_facts_service: Any,
    documents: pd.DataFrame,
    text_units: pd.DataFrame | None,
    blocks: pd.DataFrame,
    table_rows: pd.DataFrame,
    table_cells: pd.DataFrame,
    profiles: pd.DataFrame,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    from application.source.artifact_input_service import build_document_records

    document_records = build_document_records(documents, text_units)
    all_text_windows_by_doc = paper_facts_service._build_text_windows_by_document(blocks)
    table_rows_by_doc = paper_facts_service._group_table_rows_by_document(table_rows)
    table_cells_by_doc = paper_facts_service._group_table_cells_by_document(table_cells)
    profile_by_doc = {
        str(row.get("document_id") or ""): dict(row)
        for _, row in profiles.iterrows()
    }
    document_summaries: list[dict[str, Any]] = []
    payload_catalog: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for _, row in document_records.iterrows():
        document_id = str(row.get("paper_id") or "")
        profile = profile_by_doc.get(document_id)
        if not profile:
            continue

        candidate_text_windows = all_text_windows_by_doc.get(document_id, [])
        candidate_table_rows = table_rows_by_doc.get(document_id, [])
        grouped_row_cells = paper_facts_service._group_table_cells_by_row(
            table_cells_by_doc.get(document_id, [])
        )
        selected_text_windows = paper_facts_service._select_text_windows_for_extraction(
            text_windows=candidate_text_windows,
            profile=profile,
            has_table_rows=bool(candidate_table_rows),
        )
        if str(profile.get("doc_type") or "") == "review":
            selected_table_rows: list[dict[str, Any]] = []
        else:
            selected_table_rows = paper_facts_service._select_table_rows_for_extraction(
                table_rows=candidate_table_rows,
                grouped_row_cells=grouped_row_cells,
            )

        title = (
            paper_facts_service._normalize_scalar_text(profile.get("title"))
            or paper_facts_service._normalize_scalar_text(row.get("title"))
            or document_id
        )
        source_filename = paper_facts_service._normalize_scalar_text(profile.get("source_filename"))
        for position, text_window in enumerate(selected_text_windows, start=1):
            payload = paper_facts_service._build_text_window_extraction_payload(
                title=title,
                source_filename=source_filename,
                profile=profile,
                text_window=text_window,
            )
            payload_catalog[payload_hash(payload)].append(
                {
                    "collection_id": collection_id,
                    "document_id": document_id,
                    "document_title": title,
                    "kind": "text_window",
                    "unit_position": position,
                    "window_id": paper_facts_service._normalize_scalar_text(text_window.get("window_id")),
                    "heading_path": paper_facts_service._normalize_scalar_text(text_window.get("heading_path")),
                }
            )

        for position, table_row in enumerate(selected_table_rows, start=1):
            table_id = str(table_row.get("table_id") or "")
            row_index = paper_facts_service._safe_int(table_row.get("row_index"))
            row_cells = grouped_row_cells.get((table_id, row_index), [])
            payload = paper_facts_service._build_table_row_extraction_payload(
                title=title,
                source_filename=source_filename,
                profile=profile,
                table_row=table_row,
                row_cells=row_cells,
                text_windows=candidate_text_windows,
            )
            payload_catalog[payload_hash(payload)].append(
                {
                    "collection_id": collection_id,
                    "document_id": document_id,
                    "document_title": title,
                    "kind": "table_row",
                    "unit_position": position,
                    "table_id": table_id,
                    "row_index": row_index,
                    "heading_path": paper_facts_service._normalize_scalar_text(table_row.get("heading_path")),
                }
            )

        document_summaries.append(
            {
                "collection_id": collection_id,
                "document_id": document_id,
                "document_title": title,
                "doc_type": str(profile.get("doc_type") or ""),
                "raw_text_window_count": len(candidate_text_windows),
                "selected_text_window_count": len(selected_text_windows),
                "raw_table_row_count": len(candidate_table_rows),
                "selected_table_row_count": len(selected_table_rows),
                "selected_total_units": len(selected_text_windows) + len(selected_table_rows),
            }
        )

    return document_summaries, payload_catalog


def summarize_unit_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [record for record in records if record.get("success")]
    failed = [record for record in records if not record.get("success")]
    return {
        "count": len(records),
        "successful_count": len(successful),
        "failed_count": len(failed),
        "timing": summarize_timings([float(record.get("elapsed_s") or 0.0) for record in records]),
    }


def build_document_metrics(
    planned_documents: list[dict[str, Any]],
    *,
    unit_records: list[dict[str, Any]],
    wall_time_by_document: dict[str, float],
) -> list[dict[str, Any]]:
    records_by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
    records_by_document_and_kind: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in unit_records:
        document_id = str(record.get("document_id") or "")
        if not document_id:
            continue
        records_by_document[document_id].append(record)
        records_by_document_and_kind[(document_id, str(record.get("kind") or ""))].append(record)

    documents: list[dict[str, Any]] = []
    for planned in planned_documents:
        document_id = str(planned.get("document_id") or "")
        records = records_by_document.get(document_id, [])
        documents.append(
            {
                **planned,
                "document_wall_time_s": wall_time_by_document.get(document_id),
                "unit_summary": summarize_unit_records(records),
                "text_window_unit_summary": summarize_unit_records(
                    records_by_document_and_kind.get((document_id, "text_window"), [])
                ),
                "table_row_unit_summary": summarize_unit_records(
                    records_by_document_and_kind.get((document_id, "table_row"), [])
                ),
            }
        )
    return documents


def _bundle_counts(bundle: Any) -> dict[str, int]:
    return {
        "method_facts": len(getattr(bundle, "method_facts", [])),
        "sample_variants": len(getattr(bundle, "sample_variants", [])),
        "test_conditions": len(getattr(bundle, "test_conditions", [])),
        "baseline_references": len(getattr(bundle, "baseline_references", [])),
        "measurement_results": len(getattr(bundle, "measurement_results", [])),
    }


def _extract_log_value(message: str, key: str) -> str | None:
    marker = f"{key}="
    start = message.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end = message.find(" ", start)
    if end < 0:
        end = len(message)
    value = message[start:end].strip()
    return value or None


def main() -> int:
    args = parse_args()
    runtime = resolve_runtime(args)
    ensure_backend_root_on_path(runtime.backend_root)

    collections_root = (
        args.collections_root.expanduser().resolve()
        if args.collections_root is not None
        else (runtime.backend_root / "data" / "collections").resolve()
    )
    (
        collection_service,
        artifact_registry_service,
        document_profile_service,
        paper_facts_service_class,
        extractor_class,
    ) = build_services(collections_root)
    (
        output_dir,
        documents,
        text_units,
        blocks,
        table_rows,
        table_cells,
        profiles,
    ) = load_collection_inputs_for_benchmark(
        args.collection_id,
        collections_root=collections_root,
    )

    inner_extractor = extractor_class(
        model=runtime.model,
        api_key=runtime.api_key,
        base_url=runtime.base_url,
    )
    planning_service = paper_facts_service_class(
        collection_service=collection_service,
        artifact_registry_service=artifact_registry_service,
        document_profile_service=document_profile_service,
        structured_extractor=inner_extractor,
    )
    planned_documents, payload_catalog = build_selection_plan(
        collection_id=args.collection_id,
        paper_facts_service=planning_service,
        documents=documents,
        text_units=text_units,
        blocks=blocks,
        table_rows=table_rows,
        table_cells=table_cells,
        profiles=profiles,
    )

    timing_extractor = _TimingRecordingExtractor(
        inner_extractor,
        payload_catalog=payload_catalog,
    )
    benchmark_service = paper_facts_service_class(
        collection_service=collection_service,
        artifact_registry_service=artifact_registry_service,
        document_profile_service=document_profile_service,
        structured_extractor=timing_extractor,
    )

    log_handler = _DocumentWallClockHandler()
    service_logger = logging.getLogger(_PAPER_FACTS_LOGGER_NAME)
    original_level = service_logger.level
    service_logger.addHandler(log_handler)
    service_logger.setLevel(logging.INFO)

    try:
        collection_started_at = perf_counter()
        frames = benchmark_service.build_paper_facts(args.collection_id)
        collection_elapsed_s = perf_counter() - collection_started_at
    finally:
        service_logger.removeHandler(log_handler)
        service_logger.setLevel(original_level)

    wall_time_by_document = log_handler.wall_time_by_document()
    document_metrics = build_document_metrics(
        planned_documents,
        unit_records=timing_extractor.records,
        wall_time_by_document=wall_time_by_document,
    )
    all_unit_records = list(timing_extractor.records)
    text_window_records = [
        record for record in all_unit_records if str(record.get("kind") or "") == "text_window"
    ]
    table_row_records = [
        record for record in all_unit_records if str(record.get("kind") or "") == "table_row"
    ]

    summary: dict[str, Any] = {
        "script": "paper_facts_collection_benchmark.py",
        "collection_id": args.collection_id,
        "backend_root": str(runtime.backend_root),
        "collections_root": str(collections_root),
        "output_dir": str(output_dir),
        "env_file": str(runtime.env_file) if runtime.env_file else None,
        "runtime": {
            "model": runtime.model,
            "base_url": display_base_url(runtime.base_url),
            "timeout_s": runtime.timeout_s,
        },
        "planning": {
            "document_count": len(document_metrics),
            "raw_text_window_count": sum(
                int(item.get("raw_text_window_count") or 0) for item in planned_documents
            ),
            "selected_text_window_count": sum(
                int(item.get("selected_text_window_count") or 0) for item in planned_documents
            ),
            "raw_table_row_count": sum(
                int(item.get("raw_table_row_count") or 0) for item in planned_documents
            ),
            "selected_table_row_count": sum(
                int(item.get("selected_table_row_count") or 0) for item in planned_documents
            ),
            "selected_total_units": sum(
                int(item.get("selected_total_units") or 0) for item in planned_documents
            ),
        },
        "execution": {
            "collection_elapsed_s": round(collection_elapsed_s, 6),
            "all_units": summarize_unit_records(all_unit_records),
            "text_window_units": summarize_unit_records(text_window_records),
            "table_row_units": summarize_unit_records(table_row_records),
        },
        "documents": document_metrics,
        "output_frames": {
            name: len(frame)
            for name, frame in frames.items()
        },
    }

    write_json_output(args.summary_output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
