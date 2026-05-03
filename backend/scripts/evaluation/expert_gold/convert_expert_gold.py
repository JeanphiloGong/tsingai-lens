#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import validate_expert_gold as validator


SCHEMA_VERSION = "expert-gold-bundle-v0.1"

CLAIM_SCOPE_MAP = {
    "本文实验": "current_work",
    "前人文献": "prior_work",
    "综述总结": "literature_summary",
    "不确定": "unclear",
}
CONTROL_FLAG_MAP = {
    "是": "yes",
    "否": "no",
    "不确定": "unclear",
}
DIRECTION_MAP = {
    "提高": "improved",
    "提升": "improved",
    "下降": "decreased",
    "降低": "decreased",
    "相当": "comparable",
    "不确定": "unclear",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert expert-filled PBF-metal CSV tables into a gold bundle."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=validator.DEFAULT_INPUT_DIR,
        help="Folder containing the nine expert CSV tables.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Output JSON path. Defaults to "
            "<input>/generated/gold_bundle.json."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = convert_expert_gold(input_dir=args.input, output_path=args.output)
    print(output_path)


def convert_expert_gold(
    *,
    input_dir: str | Path = validator.DEFAULT_INPUT_DIR,
    output_path: str | Path | None = None,
) -> Path:
    root = Path(input_dir).expanduser().resolve()
    report = validator.validate_expert_gold(root)
    if not report.ok:
        raise SystemExit(validator.render_report(report))

    destination = (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else root / "generated" / "gold_bundle.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    bundle = build_gold_bundle(root, validation_report=report)
    destination.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def build_gold_bundle(
    input_dir: str | Path,
    *,
    validation_report: validator.ValidationReport | None = None,
) -> dict[str, Any]:
    root = Path(input_dir).expanduser().resolve()
    report = validation_report or validator.validate_expert_gold(root)
    if not report.ok:
        raise ValueError("expert gold input is not valid")

    tables = _load_tables(root)
    bundle: dict[str, Any] = {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_dir": str(root),
            "table_counts": report.table_counts,
            "pdf_count": report.pdf_count,
            "pdf_files": sorted(path.name for path in root.glob("*.pdf")),
        },
        "papers": _convert_papers(tables[validator.PAPER_TABLE]),
        "samples": _convert_samples(tables[validator.SAMPLE_TABLE]),
        "process_parameters": _convert_process_parameters(
            tables[validator.PROCESS_TABLE]
        ),
        "test_conditions": _convert_test_conditions(tables[validator.CONDITION_TABLE]),
        "measurement_results": _convert_measurement_results(
            tables[validator.RESULT_TABLE]
        ),
        "comparisons": _convert_comparisons(tables[validator.COMPARISON_TABLE]),
        "observations": _convert_observations(tables[validator.OBSERVATION_TABLE]),
        "evidence": _convert_evidence(tables[validator.EVIDENCE_TABLE]),
        "uncertainties": _convert_uncertainties(tables[validator.UNCERTAINTY_TABLE]),
        "global_notes": _convert_global_notes(tables),
    }
    return bundle


def _load_tables(root: Path) -> dict[str, list[dict[str, str]]]:
    return {
        filename: _read_rows(root / filename)
        for filename in validator.TABLE_SPECS
    }


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {
                (key.strip() if key is not None else ""): validator._clean_cell(value)
                for key, value in row.items()
            }
            for row in reader
        ]


def _convert_papers(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        records.append(
            {
                "paper_id": row["论文编号"],
                "title": row["论文标题"],
                "doi": row["DOI"],
                "document_type": row["文献类型"],
                "material_system": row["材料体系"],
                "process_type": row["工艺类型"],
                "research_goal": row["研究目标"],
                "main_variables": row["主要变量"],
                "target_properties": row["主要性能指标"],
                "notes": row["备注"],
                "source": _source(validator.PAPER_TABLE, row_number),
            }
        )
    return records


def _convert_samples(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        records.append(
            {
                "paper_id": row["论文编号"],
                "sample_id": row["样品编号"],
                "label_in_paper": row["论文原文名称"],
                "sample_description": row["样品说明"],
                "material_system": row["材料体系"],
                "difference_type": row["主要区别类型"],
                "difference_value": row["主要区别值"],
                "is_control_sample": _map_value(
                    row["是否对照样品"], CONTROL_FLAG_MAP
                ),
                "is_control_sample_text": row["是否对照样品"],
                "evidence_reference": row["证据编号或位置"],
                "evidence_ids": _evidence_refs(row["证据编号或位置"]),
                "notes": row["备注"],
                "source": _source(validator.SAMPLE_TABLE, row_number),
            }
        )
    return records


def _convert_process_parameters(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        sample_ref = row["样品编号"]
        records.append(
            {
                "paper_id": row["论文编号"],
                "sample_reference": sample_ref,
                "sample_ids": _sample_refs(sample_ref),
                "sample_scope": _sample_scope(sample_ref),
                "parameter_category": row["参数类别"],
                "original_parameter_name": row["原文参数名"],
                "parameter_description": row["中文理解"],
                "value": row["数值"],
                "unit": row["单位"],
                "applies_to": row["适用范围"],
                "evidence_reference": row["证据编号或位置"],
                "evidence_ids": _evidence_refs(row["证据编号或位置"]),
                "notes": row["备注"],
                "source": _source(validator.PROCESS_TABLE, row_number),
            }
        )
    return records


def _convert_test_conditions(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        sample_ref = row["适用样品编号"]
        records.append(
            {
                "paper_id": row["论文编号"],
                "test_condition_id": row["测试条件编号"],
                "sample_reference": sample_ref,
                "sample_ids": _sample_refs(sample_ref),
                "sample_scope": _sample_scope(sample_ref),
                "test_type": row["测试类型"],
                "test_temperature": row["测试温度"],
                "strain_rate_or_frequency": row["应变速率或频率"],
                "build_orientation": row["构建方向"],
                "sampling_orientation": row["取样方向"],
                "surface_condition": row["表面状态"],
                "test_standard": row["测试标准"],
                "other_conditions": row["其他条件"],
                "evidence_reference": row["证据编号或位置"],
                "evidence_ids": _evidence_refs(row["证据编号或位置"]),
                "notes": row["备注"],
                "source": _source(validator.CONDITION_TABLE, row_number),
            }
        )
    return records


def _convert_measurement_results(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        records.append(
            {
                "paper_id": row["论文编号"],
                "result_id": row["结果编号"],
                "sample_id": row["样品编号"],
                "sample_ids": _sample_refs(row["样品编号"]),
                "test_condition_id": row["测试条件编号"],
                "metric_name": row["指标名称"],
                "value_or_trend": row["数值或趋势"],
                "unit": row["单位"],
                "claim_scope": _map_value(row["数据属于"], CLAIM_SCOPE_MAP),
                "claim_scope_text": row["数据属于"],
                "source_type": row["数据来源"],
                "evidence_reference": row["证据编号或位置"],
                "evidence_ids": _evidence_refs(row["证据编号或位置"]),
                "notes": row["备注"],
                "source": _source(validator.RESULT_TABLE, row_number),
            }
        )
    return records


def _convert_comparisons(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        baseline_ref = row["对照对象"]
        records.append(
            {
                "paper_id": row["论文编号"],
                "comparison_id": row["比较编号"],
                "current_sample_id": row["当前样品编号"],
                "baseline_reference": baseline_ref,
                "baseline_sample_ids": _sample_refs(baseline_ref),
                "baseline_type": row["对照类型"],
                "metric_name": row["比较指标"],
                "current_value": row["当前值"],
                "baseline_value": row["对照值"],
                "unit": row["单位"],
                "direction": _map_value(row["变化方向"], DIRECTION_MAP),
                "direction_text": row["变化方向"],
                "evidence_reference": row["证据编号或位置"],
                "evidence_ids": _evidence_refs(row["证据编号或位置"]),
                "notes": row["备注"],
                "source": _source(validator.COMPARISON_TABLE, row_number),
            }
        )
    return records


def _convert_observations(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        sample_ref = row["样品编号"]
        records.append(
            {
                "paper_id": row["论文编号"],
                "observation_id": row["观察编号"],
                "sample_reference": sample_ref,
                "sample_ids": _sample_refs(sample_ref),
                "sample_scope": _sample_scope(sample_ref),
                "characterization_method": row["表征方法"],
                "observed_object": row["观察对象"],
                "value_or_description": row["数值或描述"],
                "unit": row["单位"],
                "author_interpretation": row["作者解释"],
                "evidence_reference": row["证据编号或位置"],
                "evidence_ids": _evidence_refs(row["证据编号或位置"]),
                "notes": row["备注"],
                "source": _source(validator.OBSERVATION_TABLE, row_number),
            }
        )
    return records


def _convert_evidence(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        if _is_global_paper(row["论文编号"]):
            continue
        records.append(
            {
                "paper_id": row["论文编号"],
                "evidence_id": row["证据编号"],
                "evidence_type": row["证据类型"],
                "page": row["页码"],
                "section": row["章节"],
                "figure_or_table": row["表格或图号"],
                "quote_or_cell": row["原文短句或单元格"],
                "supports": row["支持什么"],
                "notes": row["备注"],
                "source": _source(validator.EVIDENCE_TABLE, row_number),
            }
        )
    return records


def _convert_uncertainties(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_number, row in _rows_with_numbers(rows):
        if _is_global_paper(row["论文编号"]):
            continue
        records.append(
            {
                "paper_id": row["论文编号"],
                "issue_id": row["问题编号"],
                "affected_object": row["影响对象"],
                "issue_type": row["问题类型"],
                "description": row["问题描述"],
                "impact": row["影响"],
                "suggested_resolution": row["建议处理"],
                "source": _source(validator.UNCERTAINTY_TABLE, row_number),
            }
        )
    return records


def _convert_global_notes(
    tables: dict[str, list[dict[str, str]]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for table_name in (validator.EVIDENCE_TABLE, validator.UNCERTAINTY_TABLE):
        for row_number, row in _rows_with_numbers(tables[table_name]):
            paper_id = row.get("论文编号", "")
            if not _is_global_paper(paper_id):
                continue
            records.append(
                {
                    "scope": paper_id,
                    "table": table_name,
                    "row": row_number,
                    "record": row,
                }
            )
    return records


def _sample_refs(value: str) -> list[str]:
    if validator._is_global_sample_marker(value):
        return []
    return validator._extract_sample_refs(value)


def _sample_scope(value: str) -> str:
    return "all_samples" if validator._is_global_sample_marker(value) else "explicit"


def _evidence_refs(value: str) -> list[str]:
    return validator._extract_evidence_refs(value)


def _map_value(value: str, mapping: dict[str, str]) -> str:
    return mapping.get(value, "unknown" if value else "")


def _source(table: str, row: int) -> dict[str, Any]:
    return {"table": table, "row": row}


def _rows_with_numbers(rows: list[dict[str, str]]):
    return enumerate(rows, start=2)


def _is_global_paper(paper_id: str) -> bool:
    return paper_id in validator.GLOBAL_PAPER_MARKERS


if __name__ == "__main__":
    main()
