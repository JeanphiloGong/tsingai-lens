#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(DEFAULT_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(DEFAULT_BACKEND_ROOT))

from infra.source.artifact_bundle import (
    source_block_payload,
    source_document_payload,
    source_figure_payload,
    source_table_cell_payload,
    source_table_payload,
    source_table_row_payload,
    source_text_unit_payload,
)

from infra.persistence.database import (  # noqa: E402
    DatabaseSettings,
    build_database_engine,
    build_session_factory,
)
from repositories.document_profile_repository import (  # noqa: E402
    DocumentProfileRepository,
)
from repositories.objective_repository import (  # noqa: E402
    ObjectiveRepository,
)

from repositories.paper_map_repository import PaperMapRepository
from repositories.source_artifact_repository import (  # noqa: E402
    SourceArtifactRepository,
)
from application.core.objectives.analysis.experiment_query_service import (
    finding_response,
    objective_evidence_response,
)

ARTIFACT_NAMES = (
    "documents",
    "text_units",
    "blocks",
    "figures",
    "tables",
    "table_rows",
    "table_cells",
    "document_profiles",
    "paper_maps",
    "objective_evidence",
    "objective_findings",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export current document and published Objective trace artifacts."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--collection-id")
    source.add_argument("--output-dir", type=Path)
    parser.add_argument("--backend-root", type=Path, default=DEFAULT_BACKEND_ROOT)
    parser.add_argument("--trace-root", type=Path)
    parser.add_argument("--trace-name")
    parser.add_argument("--document-id")
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    output = await export_trace(
        backend_root=args.backend_root,
        collection_id=args.collection_id,
        source_output_dir=args.output_dir,
        trace_root=args.trace_root,
        trace_name=args.trace_name,
        document_id=args.document_id,
    )
    print(output)


async def export_trace(
    *,
    backend_root: str | Path = DEFAULT_BACKEND_ROOT,
    collection_id: str | None = None,
    source_output_dir: str | Path | None = None,
    trace_root: str | Path | None = None,
    trace_name: str | None = None,
    document_id: str | None = None,
) -> Path:
    root = Path(backend_root).expanduser().resolve()
    source_dir = _resolve_source_output_dir(root, collection_id, source_output_dir)
    resolved_collection_id = collection_id or source_dir.parent.name
    destination_root = (
        Path(trace_root).expanduser().resolve()
        if trace_root is not None
        else root / "data" / "traces"
    )
    destination = destination_root / (
        trace_name
        or f"{resolved_collection_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    artifacts_dir = destination / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    frames = await _load_artifacts(resolved_collection_id)
    for name, frame in frames.items():
        if frame.empty:
            continue
        records = json.loads(frame.to_json(orient="records", force_ascii=False))
        (artifacts_dir / f"{name}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        frame.to_csv(artifacts_dir / f"{name}.csv", index=False)

    summary = {
        "collection_id": resolved_collection_id,
        "source_output_dir": str(source_dir),
        "trace_dir": str(destination),
        "artifact_rows": {name: len(frame) for name, frame in frames.items()},
    }
    (destination / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (destination / "README.md").write_text(
        _render_readme(summary),
        encoding="utf-8",
    )
    (destination / "source_tables.md").write_text(
        _render_source_tables(frames["tables"], document_id),
        encoding="utf-8",
    )
    (destination / "extraction_trace.md").write_text(
        _render_objective_trace(frames, document_id),
        encoding="utf-8",
    )
    return destination


async def _load_artifacts(collection_id: str) -> dict[str, pd.DataFrame]:
    engine = build_database_engine(DatabaseSettings())
    try:
        sessions = build_session_factory(engine)
        documents = await SourceArtifactRepository(
            sessions
        ).read_collection_documents(collection_id)
        profiles = await DocumentProfileRepository(sessions).list_collection(
            collection_id
        )
        paper_maps = await PaperMapRepository(sessions).list_collection(
            collection_id
        )
        objective_repository = ObjectiveRepository(sessions)
        evidence: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        for objective in await objective_repository.list_objectives(collection_id):
            version = objective.published_analysis_version
            if version is None:
                continue
            objective_evidence, _ = await objective_repository.list_evidence(
                collection_id,
                objective.objective_id,
                version,
                offset=0,
                limit=10_000,
            )
            objective_findings, _ = await objective_repository.list_findings(
                collection_id,
                objective.objective_id,
                version,
                offset=0,
                limit=10_000,
            )
            evidence.extend(
                objective_evidence_response(item) for item in objective_evidence
            )
            findings.extend(finding_response(item) for item in objective_findings)
    finally:
        await engine.dispose()

    records: dict[str, list[dict[str, Any]]] = {
        "documents": [source_document_payload(item) for item in documents],
        "text_units": [
            source_text_unit_payload(item)
            for document in documents
            for item in document.text_units
        ],
        "blocks": [
            source_block_payload(item)
            for document in documents
            for item in document.blocks
        ],
        "figures": [
            source_figure_payload(item)
            for document in documents
            for item in document.figures
        ],
        "tables": [
            source_table_payload(item)
            for document in documents
            for item in document.tables
        ],
        "table_rows": [
            source_table_row_payload(item)
            for document in documents
            for item in document.table_rows
        ],
        "table_cells": [
            source_table_cell_payload(item)
            for document in documents
            for item in document.table_cells
        ],
        "document_profiles": [
            {
                "document_id": item.document_id,
                "title": item.title,
                "doc_type": item.doc_type,
                "profile_warnings": list(item.profile_warnings),
                "confidence": round(float(item.confidence), 2),
                "profile_status": item.profile_status,
                "source_fingerprint": item.source_fingerprint,
                "profile_version": item.profile_version,
                "profile_fingerprint": item.profile_fingerprint,
                "generated_at": item.generated_at,
            }
            for item in profiles
        ],
        "paper_maps": [
            {
                "document_id": item.document_id,
                "doc_role": item.doc_role,
                "studies": [
                    {
                        "study_id": study.study_id,
                        "document_id": study.document_id,
                        "design_type": study.design_type,
                        "claim_scope": study.claim_scope,
                        "experiment_label": study.experiment_label,
                        "material_scope": list(study.material_scope),
                        "process_context": list(study.process_context),
                        "relationships": [
                            {
                                "relationship_id": item.relationship_id,
                                "varied_factors": list(item.varied_factors),
                                "outcome": item.outcome,
                                "source_refs": [
                                    {
                                        "source_kind": item.source_kind,
                                        "source_ref": item.source_ref,
                                    }
                                    for item in item.source_refs
                                ],
                                "confidence": item.confidence,
                            }
                            for item in study.relationships
                        ],
                        "confidence": study.confidence,
                    }
                    for study in item.studies
                ],
                "evidence_density": item.evidence_density,
                "confidence": item.confidence,
                "warnings": list(item.warnings),
                "unresolved_signals": [
                    {
                        "signal_id": signal.signal_id,
                        "signal_type": signal.signal_type,
                        "label": signal.label,
                        "variable_role": signal.variable_role,
                        "design_type": signal.design_type,
                        "claim_scope": signal.claim_scope,
                        "experiment_label": signal.experiment_label,
                        "material_scope": list(signal.material_scope),
                        "process_context": list(signal.process_context),
                        "source_refs": [
                            {
                                "source_kind": item.source_kind,
                                "source_ref": item.source_ref,
                            }
                            for item in signal.source_refs
                        ],
                        "confidence": signal.confidence,
                        "reason": signal.reason,
                    }
                    for signal in item.unresolved_signals
                ],
                "source_unit_coverage": [
                    {
                        "source_unit_id": item.source_unit_id,
                        "window_id": item.window_id,
                        "source_kind": item.source_kind,
                        "source_ref": item.source_ref,
                        "status": item.status.value,
                        "reason": item.reason,
                    }
                    for item in item.source_unit_coverage
                ],
                "map_status": item.map_status,
                "map_limitations": list(item.map_limitations),
                "review_synthesis": {
                    field_name: [
                        {
                            "content": item.content,
                            "material_scope": list(item.material_scope),
                            "variables": list(item.variables),
                            "outcomes": list(item.outcomes),
                            "conditions": list(item.conditions),
                            "source_refs": [
                                {
                                    "source_kind": item.source_kind,
                                    "source_ref": item.source_ref,
                                }
                                for item in item.source_refs
                            ],
                            "confidence": item.confidence,
                        }
                        for item in getattr(item.review_synthesis, field_name)
                    ]
                    for field_name in (
                        "synthesis_claims",
                        "disputes",
                        "evidence_gaps",
                        "citation_leads",
                    )
                },
                "input_fingerprint": item.input_fingerprint,
                "map_version": item.map_version,
                "generated_at": item.generated_at,
            }
            for item in paper_maps
        ],
        "objective_evidence": evidence,
        "objective_findings": findings,
    }
    return {
        name: pd.DataFrame(records.get(name, [])) for name in ARTIFACT_NAMES
    }


def _render_readme(summary: dict[str, Any]) -> str:
    rows = "\n".join(
        f"- `{name}`: {count} row(s)"
        for name, count in summary["artifact_rows"].items()
    )
    return (
        f"# Extraction Trace: {summary['collection_id']}\n\n"
        "Current per-Document preparation artifacts and published Objective results.\n\n"
        f"{rows}\n"
    )


def _render_source_tables(frame: pd.DataFrame, document_id: str | None) -> str:
    rows = _filtered_records(frame, document_id)
    lines = ["# Source Tables", ""]
    for row in rows:
        title = row.get("caption_text") or row.get("table_id") or "Untitled table"
        lines.extend(
            [
                f"## {title}",
                "",
                f"- Document: `{row.get('document_id', '')}`",
                f"- Source: `{row.get('table_id', '')}`",
                "",
                "```json",
                json.dumps(row.get("table_matrix") or [], ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _render_objective_trace(
    frames: dict[str, pd.DataFrame],
    document_id: str | None,
) -> str:
    lines = ["# Objective Evidence Trace", ""]
    for row in _filtered_records(frames["objective_findings"], document_id):
        lines.extend(
            [
                f"## Finding {row.get('finding_id', '')}",
                "",
                str(row.get("statement") or ""),
                "",
            ]
        )
    for row in _filtered_records(frames["objective_evidence"], document_id):
        lines.extend(
            [
                f"### Evidence {row.get('evidence_id', '')}",
                "",
                f"- Document: `{row.get('document_id', '')}`",
                f"- Source: `{row.get('source_kind', '')}:{row.get('source_ref', '')}`",
                "",
                str(row.get("source_excerpt") or ""),
                "",
            ]
        )
    return "\n".join(lines)


def _filtered_records(
    frame: pd.DataFrame,
    document_id: str | None,
) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    records = json.loads(frame.to_json(orient="records", force_ascii=False))
    if document_id is None:
        return records
    return [row for row in records if row.get("document_id") == document_id]


def _resolve_source_output_dir(
    backend_root: Path,
    collection_id: str | None,
    source_output_dir: str | Path | None,
) -> Path:
    if source_output_dir is not None:
        return Path(source_output_dir).expanduser().resolve()
    if not collection_id:
        raise SystemExit("--collection-id or --output-dir is required")
    return backend_root / "data" / "collections" / collection_id / "output"


if __name__ == "__main__":
    asyncio.run(main_async())
