from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from domain.core import CoreFactSet, EvidenceAnchor, MeasurementResult, SampleVariant
from domain.source import SourceArtifactSet
from infra.persistence.sqlite import SqliteCoreFactRepository, SqliteSourceArtifactRepository


def _load_trace_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = backend_root / "scripts" / "export_extraction_trace.py"
    spec = importlib.util.spec_from_file_location(
        "export_extraction_trace",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_export_trace_writes_readable_artifact_views(tmp_path, monkeypatch):
    trace = _load_trace_module()
    backend_root = tmp_path / "backend"
    collection_id = "col-test"
    db_path = backend_root / "data" / "lens.sqlite"
    SqliteSourceArtifactRepository(db_path).replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=[
                {
                    "id": "paper-1",
                    "title": "Trace Paper",
                    "text": "Table 1 Mechanical Results",
                }
            ],
            tables=[
                {
                    "table_id": "tbl-paper-1-1",
                    "document_id": "paper-1",
                    "table_order": 1,
                    "caption_text": "Table 1 Mechanical Results",
                    "caption_block_id": "blk-1",
                    "page": 5,
                    "heading_path": "Results",
                    "column_headers": ["Sample", "Strength (MPa)"],
                    "table_matrix": [["Sample", "Strength (MPa)"], ["A", "560"]],
                    "metadata": {"source": "test"},
                }
            ],
            table_rows=[
                {
                    "row_id": "row-1",
                    "document_id": "paper-1",
                    "table_id": "tbl-paper-1-1",
                    "row_index": 1,
                    "row_text": "A | 560",
                    "page": 5,
                    "heading_path": "Results",
                }
            ],
        ),
    )
    SqliteCoreFactRepository(db_path).replace_collection_facts(
        collection_id,
        CoreFactSet(
            paper_facts_ready=True,
            evidence_anchors=(
                EvidenceAnchor.from_mapping(
                    {
                        "anchor_id": "anchor-1",
                        "document_id": "paper-1",
                        "locator_type": "table_row",
                        "locator_confidence": "direct",
                        "source_type": "table",
                        "page": 5,
                        "quote": "A | 560",
                        "figure_or_table": "tbl-paper-1-1",
                    }
                ),
            ),
            sample_variants=(
                SampleVariant.from_mapping(
                    {
                        "variant_id": "var-1",
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "variant_label": "A",
                        "host_material_system": {"normalized": "Trace alloy"},
                        "source_anchor_ids": ["anchor-1"],
                    }
                ),
            ),
            measurement_results=(
                MeasurementResult.from_mapping(
                    {
                        "result_id": "res-1",
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "variant_id": "var-1",
                        "property_normalized": "strength",
                        "result_type": "scalar",
                        "value_payload": {
                            "value": 560,
                            "statement": "A reached 560 MPa.",
                        },
                        "unit": "MPa",
                        "evidence_anchor_ids": ["anchor-1"],
                        "traceability_status": "direct",
                        "result_source_type": "table",
                    }
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        trace,
        "build_database_engine",
        lambda _settings: SimpleNamespace(dispose=lambda: None),
    )
    monkeypatch.setattr(trace, "build_session_factory", lambda _engine: None)
    monkeypatch.setattr(
        trace,
        "PostgresSourceArtifactRepository",
        lambda _session_factory: SqliteSourceArtifactRepository(db_path),
    )

    trace_dir = trace.export_trace(
        backend_root=backend_root,
        collection_id=collection_id,
        trace_name="trace-test",
    )

    summary = json.loads((trace_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["artifact_rows"]["tables"] == 1
    assert summary["artifact_rows"]["evidence_cards"] == 1
    assert (trace_dir / "artifacts" / "tables.json").is_file()
    assert (trace_dir / "artifacts" / "tables.csv").is_file()
    assert "Table 1 Mechanical Results" in (
        trace_dir / "source_tables.md"
    ).read_text(encoding="utf-8")
    extraction_trace = (trace_dir / "extraction_trace.md").read_text(encoding="utf-8")
    assert "A reached 560 MPa." in extraction_trace
    assert "quote=A | 560" in extraction_trace
