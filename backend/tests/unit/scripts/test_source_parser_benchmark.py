from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_benchmark_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_dir = backend_root / "scripts" / "benchmarks"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    spec = importlib.util.spec_from_file_location(
        "source_parser_benchmark",
        script_dir / "source_parser_benchmark.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_summarize_mineru_content_items_counts_common_elements() -> None:
    benchmark = _load_benchmark_module()

    summary = benchmark.summarize_mineru_content_items(
        [
            {"type": "text", "text": "plain paragraph", "page_idx": 0},
            {"type": "title", "text": "Methods", "text_level": 1, "bbox": [1, 2, 3, 4]},
            {"type": "table", "table_body": "<table><tr><td>1</td></tr></table>"},
            {"type": "image", "img_caption": ["Figure 1. Sample"]},
            {"type": "interline_equation", "latex": "E=mc^2"},
        ]
    )

    assert summary["item_count"] == 5
    assert summary["kind_counts"] == {
        "equation": 1,
        "figure": 1,
        "heading": 1,
        "table": 1,
        "text": 2,
    }
    assert summary["heading_count"] == 1
    assert summary["table_count"] == 1
    assert summary["figure_count"] == 1
    assert summary["equation_count"] == 1
    assert summary["page_locator_count"] == 1
    assert summary["bbox_locator_count"] == 1
    assert summary["page_locator_ratio"] == 0.2
    assert summary["bbox_locator_ratio"] == 0.2


def test_aggregate_records_preserves_parser_status_counts() -> None:
    benchmark = _load_benchmark_module()

    summary = benchmark.aggregate_records(
        [
            {
                "parser": "docling",
                "status": "success",
                "elapsed_s": 1.5,
                "metrics": {
                    "artifact_rows": {"documents": 1, "blocks": 2},
                    "warnings": ["blocks_missing_page_locators"],
                },
            },
            {
                "parser": "docling",
                "status": "error",
                "elapsed_s": None,
                "metrics": {},
            },
            {
                "parser": "mineru",
                "status": "skipped",
                "elapsed_s": None,
                "metrics": {},
            },
        ]
    )

    assert summary["docling"]["run_count"] == 2
    assert summary["docling"]["success_count"] == 1
    assert summary["docling"]["error_count"] == 1
    assert summary["docling"]["artifact_rows"] == {"blocks": 2, "documents": 1}
    assert summary["docling"]["warnings"] == {"blocks_missing_page_locators": 1}
    assert summary["mineru"]["run_count"] == 1
    assert summary["mineru"]["skipped_count"] == 1
