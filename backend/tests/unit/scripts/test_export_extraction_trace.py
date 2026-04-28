from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd


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


def test_export_trace_writes_readable_artifact_views(tmp_path):
    trace = _load_trace_module()
    backend_root = tmp_path / "backend"
    output_dir = backend_root / "data" / "collections" / "col-test" / "output"
    output_dir.mkdir(parents=True)

    pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Trace Paper",
                "text": "Table 1 Mechanical Results",
            }
        ]
    ).to_parquet(output_dir / "documents.parquet", index=False)
    pd.DataFrame(
        [
            {
                "table_id": "tbl-paper-1-1",
                "document_id": "paper-1",
                "table_order": 1,
                "caption_text": "Table 1 Mechanical Results",
                "caption_block_id": "blk-1",
                "page": 5,
                "bbox": None,
                "heading_path": "Results",
                "row_count": 2,
                "col_count": 2,
                "column_headers": ["Sample", "Strength (MPa)"],
                "table_markdown": "| Sample | Strength (MPa) |\n| --- | --- |\n| A | 560 |",
                "table_text": "Sample | Strength (MPa)\nA | 560",
                "metadata": {"source": "test"},
            }
        ]
    ).to_parquet(output_dir / "tables.parquet", index=False)
    pd.DataFrame(
        [
            {
                "row_id": "row-1",
                "document_id": "paper-1",
                "table_id": "tbl-paper-1-1",
                "row_index": 1,
                "row_text": "A | 560",
                "page": 5,
                "bbox": None,
                "heading_path": "Results",
            }
        ]
    ).to_parquet(output_dir / "table_rows.parquet", index=False)
    pd.DataFrame(
        [
            {
                "anchor_id": "anchor-1",
                "document_id": "paper-1",
                "locator_type": "table_row",
                "locator_confidence": "direct",
                "source_type": "table",
                "section_id": None,
                "char_range": None,
                "bbox": None,
                "page": 5,
                "quote": "A | 560",
                "deep_link": None,
                "block_id": None,
                "snippet_id": None,
                "figure_or_table": "tbl-paper-1-1",
                "quote_span": None,
            }
        ]
    ).to_parquet(output_dir / "evidence_anchors.parquet", index=False)
    pd.DataFrame(
        [
            {
                "evidence_id": "ev-1",
                "document_id": "paper-1",
                "claim_text": "A reached 560 MPa.",
                "claim_type": "property",
                "evidence_source_type": "table",
                "traceability_status": "direct",
                "evidence_anchors": [
                    {
                        "source_type": "table",
                        "page": 5,
                        "figure_or_table": "tbl-paper-1-1",
                        "quote": "A | 560",
                    }
                ],
            }
        ]
    ).to_parquet(output_dir / "evidence_cards.parquet", index=False)
    pd.DataFrame(
        [
            {
                "result_id": "res-1",
                "document_id": "paper-1",
                "property_normalized": "strength",
                "result_type": "scalar",
                "unit": "MPa",
                "evidence_anchor_ids": ["anchor-1"],
            }
        ]
    ).to_parquet(output_dir / "measurement_results.parquet", index=False)

    trace_dir = trace.export_trace(
        backend_root=backend_root,
        collection_id="col-test",
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
