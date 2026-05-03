from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_validator_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_path = (
        backend_root
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "validate_expert_gold.py"
    )
    spec = importlib.util.spec_from_file_location(
        "validate_expert_gold",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_validate_expert_gold_accepts_bom_headers_ranges_and_scoped_refs(tmp_path):
    validator = _load_validator_module()
    _write_minimal_tables(tmp_path)

    report = validator.validate_expert_gold(tmp_path)

    assert report.ok
    assert report.table_counts[validator.PAPER_TABLE] == 1
    assert report.table_counts[validator.RESULT_TABLE] == 2


def test_validate_expert_gold_reports_duplicate_and_missing_references(tmp_path):
    validator = _load_validator_module()
    _write_minimal_tables(tmp_path)
    _append_row(
        tmp_path / validator.SAMPLE_TABLE,
        "P001,S001,Duplicate,Duplicate sample,316L,process,duplicate,no,E001,",
    )
    _append_row(
        tmp_path / validator.RESULT_TABLE,
        "P001,R003,S999,T999,yield strength,980,MPa,本文实验,Table,E999,",
    )

    report = validator.validate_expert_gold(tmp_path)

    assert not report.ok
    messages = "\n".join(issue.message for issue in report.errors)
    assert "duplicate id" in messages
    assert "unknown sample S999" in messages
    assert "unknown condition T999" in messages
    assert "unknown evidence E999" in messages


def _write_minimal_tables(root: Path) -> None:
    validator = _load_validator_module()
    rows_by_table = {
        validator.PAPER_TABLE: [
            "论文编号,论文标题,DOI,文献类型,材料体系,工艺类型,研究目标,主要变量,主要性能指标,备注",
            "P001,Paper One,,实验研究,316L,LPBF,goal,temperature,strength,",
        ],
        validator.SAMPLE_TABLE: [
            "论文编号,样品编号,论文原文名称,样品说明,材料体系,主要区别类型,主要区别值,是否对照样品,证据编号或位置,备注",
            "P001,S001,Sample 1,as-built 316L,316L,post-treatment,none,yes,E001,",
            "P001,S002,Sample 2,HIP 316L,316L,post-treatment,HIP,no,E001,",
        ],
        validator.PROCESS_TABLE: [
            "论文编号,样品编号,参数类别,原文参数名,中文理解,数值,单位,适用范围,证据编号或位置,备注",
            "P001,全体样品,工艺,laser power,激光功率,280,W,全文,E001,",
        ],
        validator.CONDITION_TABLE: [
            "论文编号,测试条件编号,适用样品编号,测试类型,测试温度,应变速率或频率,构建方向,取样方向,表面状态,测试标准,其他条件,证据编号或位置,备注",
            "P001,T001,S001-S002,拉伸,room temperature,1e-3 s^-1,vertical,vertical,polished,ASTM E8,,E001,",
        ],
        validator.RESULT_TABLE: [
            "论文编号,结果编号,样品编号,测试条件编号,指标名称,数值或趋势,单位,数据属于,数据来源,证据编号或位置,备注",
            "P001,R001,S001,T001,yield strength,900,MPa,本文实验,Table,E001,",
            "P001,R002,S002,T001,yield strength,980,MPa,本文实验,Table,E001,",
        ],
        validator.COMPARISON_TABLE: [
            "论文编号,比较编号,当前样品编号,对照对象,对照类型,比较指标,当前值,对照值,单位,变化方向,证据编号或位置,备注",
            "P001,C001,S002,S001,同文对照,yield strength,980,900,MPa,提高,E001,",
        ],
        validator.OBSERVATION_TABLE: [
            "论文编号,观察编号,样品编号,表征方法,观察对象,数值或描述,单位,作者解释,证据编号或位置,备注",
            "P001,O001,\"S001,S002\",SEM,porosity,low,,supports strength,E001,",
        ],
        validator.EVIDENCE_TABLE: [
            "论文编号,证据编号,证据类型,页码,章节,表格或图号,原文短句或单元格,支持什么,备注",
            "P001,E001,表格,p.1,Results,Table 1,value,supports facts,",
        ],
        validator.UNCERTAINTY_TABLE: [
            "论文编号,问题编号,影响对象,问题类型,问题描述,影响,建议处理",
            "P001,Q001,R001,缺失,missing orientation,limited comparison,review",
        ],
    }
    for filename, rows in rows_by_table.items():
        (root / filename).write_text("\ufeff" + "\n".join(rows), encoding="utf-8")


def _append_row(path: Path, row: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n{row}")
