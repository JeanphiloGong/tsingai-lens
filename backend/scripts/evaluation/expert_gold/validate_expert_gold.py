#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Iterable


DEFAULT_BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT_DIR = DEFAULT_BACKEND_ROOT / "tests" / "fixtures" / "local_expert_gold"

PAPER_TABLE = "01_论文信息表.csv"
SAMPLE_TABLE = "02_样品实验组表.csv"
PROCESS_TABLE = "03_制备处理工艺参数表.csv"
CONDITION_TABLE = "04_测试条件表.csv"
RESULT_TABLE = "05_性能结果表.csv"
COMPARISON_TABLE = "06_对照比较关系表.csv"
OBSERVATION_TABLE = "07_组织缺陷表征观察表.csv"
EVIDENCE_TABLE = "08_证据位置表.csv"
UNCERTAINTY_TABLE = "09_缺失不确定信息表.csv"

GLOBAL_SAMPLE_MARKERS = {
    "",
    "all",
    "all samples",
    "all_sample",
    "all_samples",
    "not applicable",
    "n/a",
    "na",
    "不适用",
    "全体",
    "全体样品",
    "全部样品",
    "所有样品",
    "全文",
    "全文/全体样品",
}
GLOBAL_PAPER_MARKERS = {"ALL", "TEMPLATE"}

SAMPLE_REF_RE = re.compile(r"S(\d{1,4})", re.IGNORECASE)
SAMPLE_RANGE_RE = re.compile(r"S(\d{1,4})\s*[-–—~至到]\s*S?(\d{1,4})", re.IGNORECASE)
EVIDENCE_REF_RE = re.compile(r"E(\d{1,4})", re.IGNORECASE)


@dataclass(frozen=True)
class TableSpec:
    filename: str
    headers: tuple[str, ...]
    key_columns: tuple[str, ...]
    required_columns: tuple[str, ...]


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    table: str
    row: int | None
    message: str


@dataclass
class ValidationReport:
    input_dir: str
    table_counts: dict[str, int] = field(default_factory=dict)
    pdf_count: int = 0
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "input_dir": self.input_dir,
            "ok": self.ok,
            "table_counts": self.table_counts,
            "pdf_count": self.pdf_count,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [asdict(issue) for issue in self.errors],
            "warnings": [asdict(issue) for issue in self.warnings],
        }


TABLE_SPECS = {
    PAPER_TABLE: TableSpec(
        filename=PAPER_TABLE,
        headers=(
            "论文编号",
            "论文标题",
            "DOI",
            "文献类型",
            "材料体系",
            "工艺类型",
            "研究目标",
            "主要变量",
            "主要性能指标",
            "备注",
        ),
        key_columns=("论文编号",),
        required_columns=("论文编号", "论文标题"),
    ),
    SAMPLE_TABLE: TableSpec(
        filename=SAMPLE_TABLE,
        headers=(
            "论文编号",
            "样品编号",
            "论文原文名称",
            "样品说明",
            "材料体系",
            "主要区别类型",
            "主要区别值",
            "是否对照样品",
            "证据编号或位置",
            "备注",
        ),
        key_columns=("论文编号", "样品编号"),
        required_columns=("论文编号", "样品编号", "样品说明"),
    ),
    PROCESS_TABLE: TableSpec(
        filename=PROCESS_TABLE,
        headers=(
            "论文编号",
            "样品编号",
            "参数类别",
            "原文参数名",
            "中文理解",
            "数值",
            "单位",
            "适用范围",
            "证据编号或位置",
            "备注",
        ),
        key_columns=(),
        required_columns=("论文编号", "参数类别", "原文参数名"),
    ),
    CONDITION_TABLE: TableSpec(
        filename=CONDITION_TABLE,
        headers=(
            "论文编号",
            "测试条件编号",
            "适用样品编号",
            "测试类型",
            "测试温度",
            "应变速率或频率",
            "构建方向",
            "取样方向",
            "表面状态",
            "测试标准",
            "其他条件",
            "证据编号或位置",
            "备注",
        ),
        key_columns=("论文编号", "测试条件编号"),
        required_columns=("论文编号", "测试条件编号", "测试类型"),
    ),
    RESULT_TABLE: TableSpec(
        filename=RESULT_TABLE,
        headers=(
            "论文编号",
            "结果编号",
            "样品编号",
            "测试条件编号",
            "指标名称",
            "数值或趋势",
            "单位",
            "数据属于",
            "数据来源",
            "证据编号或位置",
            "备注",
        ),
        key_columns=("论文编号", "结果编号"),
        required_columns=("论文编号", "结果编号", "样品编号", "指标名称"),
    ),
    COMPARISON_TABLE: TableSpec(
        filename=COMPARISON_TABLE,
        headers=(
            "论文编号",
            "比较编号",
            "当前样品编号",
            "对照对象",
            "对照类型",
            "比较指标",
            "当前值",
            "对照值",
            "单位",
            "变化方向",
            "证据编号或位置",
            "备注",
        ),
        key_columns=("论文编号", "比较编号"),
        required_columns=("论文编号", "比较编号", "当前样品编号", "比较指标"),
    ),
    OBSERVATION_TABLE: TableSpec(
        filename=OBSERVATION_TABLE,
        headers=(
            "论文编号",
            "观察编号",
            "样品编号",
            "表征方法",
            "观察对象",
            "数值或描述",
            "单位",
            "作者解释",
            "证据编号或位置",
            "备注",
        ),
        key_columns=("论文编号", "观察编号"),
        required_columns=("论文编号", "观察编号", "表征方法", "观察对象"),
    ),
    EVIDENCE_TABLE: TableSpec(
        filename=EVIDENCE_TABLE,
        headers=(
            "论文编号",
            "证据编号",
            "证据类型",
            "页码",
            "章节",
            "表格或图号",
            "原文短句或单元格",
            "支持什么",
            "备注",
        ),
        key_columns=("论文编号", "证据编号"),
        required_columns=("论文编号", "证据编号", "证据类型"),
    ),
    UNCERTAINTY_TABLE: TableSpec(
        filename=UNCERTAINTY_TABLE,
        headers=(
            "论文编号",
            "问题编号",
            "影响对象",
            "问题类型",
            "问题描述",
            "影响",
            "建议处理",
        ),
        key_columns=("论文编号", "问题编号"),
        required_columns=("论文编号", "问题编号", "问题描述"),
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate expert-filled PBF-metal gold annotation CSV files."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help="Folder containing the nine expert CSV tables.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the validation report as JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = validate_expert_gold(args.input)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_report(report))
    raise SystemExit(0 if report.ok else 1)


def validate_expert_gold(input_dir: str | Path = DEFAULT_INPUT_DIR) -> ValidationReport:
    root = Path(input_dir).expanduser().resolve()
    report = ValidationReport(input_dir=str(root))
    if not root.is_dir():
        report.errors.append(
            ValidationIssue(
                severity="error",
                table="input",
                row=None,
                message=f"input directory not found: {root}",
            )
        )
        return report

    loaded: dict[str, list[dict[str, str]]] = {}
    for filename, spec in TABLE_SPECS.items():
        rows, headers = _read_table(root / filename, spec, report)
        loaded[filename] = rows
        report.table_counts[filename] = len(rows)
        if headers is not None:
            _validate_headers(headers, spec, report)
            _validate_required_values(rows, spec, report)
            _validate_duplicate_keys(rows, spec, report)

    report.pdf_count = len(list(root.glob("*.pdf")))

    context = _build_context(loaded)
    _validate_paper_references(loaded, context, report)
    _validate_sample_references(loaded, context, report)
    _validate_condition_references(loaded, context, report)
    _validate_evidence_references(loaded, context, report)
    return report


def render_report(report: ValidationReport) -> str:
    lines = [
        "# Expert Gold Validation",
        "",
        f"Input: {report.input_dir}",
        f"Status: {'ok' if report.ok else 'failed'}",
        f"PDF files: {report.pdf_count}",
        "",
        "## Table Rows",
    ]
    for filename in TABLE_SPECS:
        lines.append(f"- {filename}: {report.table_counts.get(filename, 0)}")
    lines.extend(
        [
            "",
            f"Errors: {len(report.errors)}",
            f"Warnings: {len(report.warnings)}",
        ]
    )
    if report.errors:
        lines.extend(["", "## Errors"])
        lines.extend(_render_issues(report.errors))
    if report.warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(_render_issues(report.warnings))
    return "\n".join(lines)


def _render_issues(issues: Iterable[ValidationIssue]) -> list[str]:
    rendered: list[str] = []
    for issue in issues:
        row = f":{issue.row}" if issue.row is not None else ""
        rendered.append(f"- {issue.table}{row}: {issue.message}")
    return rendered


def _read_table(
    path: Path,
    spec: TableSpec,
    report: ValidationReport,
) -> tuple[list[dict[str, str]], list[str] | None]:
    if not path.is_file():
        report.errors.append(
            ValidationIssue(
                severity="error",
                table=spec.filename,
                row=None,
                message="required CSV file is missing",
            )
        )
        return [], None
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = [header.strip() for header in (reader.fieldnames or [])]
        rows = [
            {
                (key.strip() if key is not None else ""): _clean_cell(value)
                for key, value in row.items()
            }
            for row in reader
        ]
    return rows, headers


def _validate_headers(
    headers: list[str],
    spec: TableSpec,
    report: ValidationReport,
) -> None:
    expected = list(spec.headers)
    if headers == expected:
        return
    missing = [header for header in expected if header not in headers]
    extra = [header for header in headers if header not in expected]
    if missing:
        report.errors.append(
            ValidationIssue(
                severity="error",
                table=spec.filename,
                row=None,
                message=f"missing headers: {', '.join(missing)}",
            )
        )
    if extra:
        report.errors.append(
            ValidationIssue(
                severity="error",
                table=spec.filename,
                row=None,
                message=f"unexpected headers: {', '.join(extra)}",
            )
        )


def _validate_required_values(
    rows: list[dict[str, str]],
    spec: TableSpec,
    report: ValidationReport,
) -> None:
    for index, row in enumerate(rows, start=2):
        for column in spec.required_columns:
            if not row.get(column, "").strip():
                report.errors.append(
                    ValidationIssue(
                        severity="error",
                        table=spec.filename,
                        row=index,
                        message=f"required column is empty: {column}",
                    )
                )


def _validate_duplicate_keys(
    rows: list[dict[str, str]],
    spec: TableSpec,
    report: ValidationReport,
) -> None:
    if not spec.key_columns:
        return
    seen: dict[tuple[str, ...], int] = {}
    for index, row in enumerate(rows, start=2):
        key = tuple(row.get(column, "").strip() for column in spec.key_columns)
        if any(not part for part in key):
            continue
        if key in seen:
            report.errors.append(
                ValidationIssue(
                    severity="error",
                    table=spec.filename,
                    row=index,
                    message=f"duplicate id {key}; first seen at row {seen[key]}",
                )
            )
            continue
        seen[key] = index


def _build_context(rows_by_table: dict[str, list[dict[str, str]]]) -> dict[str, set[str]]:
    papers = {row["论文编号"] for row in rows_by_table[PAPER_TABLE] if row.get("论文编号")}
    samples = {
        _scoped_id(row["论文编号"], row["样品编号"])
        for row in rows_by_table[SAMPLE_TABLE]
        if row.get("论文编号") and row.get("样品编号")
    }
    conditions = {
        _scoped_id(row["论文编号"], row["测试条件编号"])
        for row in rows_by_table[CONDITION_TABLE]
        if row.get("论文编号") and row.get("测试条件编号")
    }
    evidence = {
        _scoped_id(row["论文编号"], row["证据编号"])
        for row in rows_by_table[EVIDENCE_TABLE]
        if row.get("论文编号") and row.get("证据编号")
    }
    return {
        "papers": papers,
        "samples": samples,
        "conditions": conditions,
        "evidence": evidence,
    }


def _validate_paper_references(
    rows_by_table: dict[str, list[dict[str, str]]],
    context: dict[str, set[str]],
    report: ValidationReport,
) -> None:
    papers = context["papers"]
    for table, rows in rows_by_table.items():
        for index, row in enumerate(rows, start=2):
            paper_id = row.get("论文编号", "")
            if paper_id in GLOBAL_PAPER_MARKERS:
                continue
            if paper_id and paper_id not in papers:
                report.errors.append(
                    ValidationIssue(
                        severity="error",
                        table=table,
                        row=index,
                        message=f"unknown paper id: {paper_id}",
                    )
                )


def _validate_sample_references(
    rows_by_table: dict[str, list[dict[str, str]]],
    context: dict[str, set[str]],
    report: ValidationReport,
) -> None:
    samples = context["samples"]
    checks = (
        (PROCESS_TABLE, "样品编号", False),
        (CONDITION_TABLE, "适用样品编号", False),
        (RESULT_TABLE, "样品编号", True),
        (COMPARISON_TABLE, "当前样品编号", True),
        (COMPARISON_TABLE, "对照对象", False),
        (OBSERVATION_TABLE, "样品编号", False),
    )
    for table, column, require_match in checks:
        for index, row in enumerate(rows_by_table[table], start=2):
            paper_id = row.get("论文编号", "")
            value = row.get(column, "")
            if _is_global_sample_marker(value):
                continue
            refs = _extract_sample_refs(value)
            if not refs and require_match:
                report.errors.append(
                    ValidationIssue(
                        severity="error",
                        table=table,
                        row=index,
                        message=f"{column} does not contain a sample id: {value}",
                    )
                )
                continue
            for sample_id in refs:
                scoped = _scoped_id(paper_id, sample_id)
                if scoped not in samples:
                    report.errors.append(
                        ValidationIssue(
                            severity="error",
                            table=table,
                            row=index,
                            message=f"{column} references unknown sample {sample_id}",
                        )
                    )


def _validate_condition_references(
    rows_by_table: dict[str, list[dict[str, str]]],
    context: dict[str, set[str]],
    report: ValidationReport,
) -> None:
    conditions = context["conditions"]
    for index, row in enumerate(rows_by_table[RESULT_TABLE], start=2):
        condition_id = row.get("测试条件编号", "")
        if not condition_id:
            continue
        scoped = _scoped_id(row.get("论文编号", ""), condition_id)
        if scoped not in conditions:
            report.errors.append(
                ValidationIssue(
                    severity="error",
                    table=RESULT_TABLE,
                    row=index,
                    message=f"测试条件编号 references unknown condition {condition_id}",
                )
            )


def _validate_evidence_references(
    rows_by_table: dict[str, list[dict[str, str]]],
    context: dict[str, set[str]],
    report: ValidationReport,
) -> None:
    evidence = context["evidence"]
    for table, rows in rows_by_table.items():
        if table == EVIDENCE_TABLE:
            continue
        evidence_columns = [column for column in rows[0].keys() if "证据" in column] if rows else []
        for index, row in enumerate(rows, start=2):
            paper_id = row.get("论文编号", "")
            for column in evidence_columns:
                for evidence_id in _extract_evidence_refs(row.get(column, "")):
                    scoped = _scoped_id(paper_id, evidence_id)
                    if scoped not in evidence:
                        report.errors.append(
                            ValidationIssue(
                                severity="error",
                                table=table,
                                row=index,
                                message=f"{column} references unknown evidence {evidence_id}",
                            )
                        )


def _extract_sample_refs(value: str) -> list[str]:
    normalized = _clean_cell(value)
    refs: list[str] = []
    for start, end in SAMPLE_RANGE_RE.findall(normalized):
        refs.extend(_expand_sample_range(start, end))
    without_ranges = SAMPLE_RANGE_RE.sub(" ", normalized)
    refs.extend(f"S{int(match):03d}" for match in SAMPLE_REF_RE.findall(without_ranges))
    return _dedupe_preserve_order(refs)


def _expand_sample_range(start: str, end: str) -> list[str]:
    start_int = int(start)
    end_int = int(end)
    if end_int < start_int:
        start_int, end_int = end_int, start_int
    width = max(len(start), len(end), 3)
    return [f"S{number:0{width}d}" for number in range(start_int, end_int + 1)]


def _extract_evidence_refs(value: str) -> list[str]:
    return _dedupe_preserve_order(
        f"E{int(match):03d}" for match in EVIDENCE_REF_RE.findall(_clean_cell(value))
    )


def _is_global_sample_marker(value: str) -> bool:
    return _clean_cell(value).lower() in GLOBAL_SAMPLE_MARKERS


def _scoped_id(paper_id: str, local_id: str) -> str:
    return f"{paper_id.strip()}::{local_id.strip().upper()}"


def _clean_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\ufeff", "").strip()


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


if __name__ == "__main__":
    main()
