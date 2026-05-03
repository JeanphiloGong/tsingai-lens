from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_converter_module():
    backend_root = Path(__file__).resolve().parents[3]
    script_dir = backend_root / "scripts" / "evaluation" / "expert_gold"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    spec = importlib.util.spec_from_file_location(
        "convert_expert_gold",
        script_dir / "convert_expert_gold.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_convert_expert_gold_writes_traceable_gold_bundle(tmp_path):
    converter = _load_converter_module()
    _write_minimal_tables(tmp_path)
    output_path = tmp_path / "generated" / "gold_bundle.json"

    result_path = converter.convert_expert_gold(
        input_dir=tmp_path,
        output_path=output_path,
    )

    assert result_path == output_path
    bundle = json.loads(output_path.read_text(encoding="utf-8"))
    assert bundle["metadata"]["schema_version"] == "expert-gold-bundle-v0.1"
    assert bundle["metadata"]["table_counts"]["05_性能结果表.csv"] == 2
    assert bundle["papers"][0]["paper_id"] == "P001"
    assert bundle["samples"][1]["is_control_sample"] == "no"
    assert bundle["process_parameters"][0]["sample_scope"] == "all_samples"
    assert bundle["test_conditions"][0]["sample_ids"] == ["S001", "S002"]
    assert bundle["measurement_results"][0]["claim_scope"] == "current_work"
    assert bundle["measurement_results"][0]["evidence_ids"] == ["E001"]
    assert bundle["comparisons"][0]["baseline_sample_ids"] == ["S001"]
    assert bundle["observations"][0]["sample_ids"] == ["S001", "S002"]
    assert bundle["evidence"][0]["quote_or_cell"] == "value"
    assert bundle["uncertainties"][0]["issue_id"] == "Q001"
    assert bundle["global_notes"][0]["scope"] == "ALL"


def _write_minimal_tables(root: Path) -> None:
    rows_by_table = {
        "01_论文信息表.csv": [
            "论文编号,论文标题,DOI,文献类型,材料体系,工艺类型,研究目标,主要变量,主要性能指标,备注",
            "P001,Paper One,,实验研究,316L,LPBF,goal,temperature,strength,",
        ],
        "02_样品实验组表.csv": [
            "论文编号,样品编号,论文原文名称,样品说明,材料体系,主要区别类型,主要区别值,是否对照样品,证据编号或位置,备注",
            "P001,S001,Sample 1,as-built 316L,316L,post-treatment,none,是,E001,",
            "P001,S002,Sample 2,HIP 316L,316L,post-treatment,HIP,否,E001,",
        ],
        "03_制备处理工艺参数表.csv": [
            "论文编号,样品编号,参数类别,原文参数名,中文理解,数值,单位,适用范围,证据编号或位置,备注",
            "P001,全体样品,工艺,laser power,激光功率,280,W,全文,E001,",
        ],
        "04_测试条件表.csv": [
            "论文编号,测试条件编号,适用样品编号,测试类型,测试温度,应变速率或频率,构建方向,取样方向,表面状态,测试标准,其他条件,证据编号或位置,备注",
            "P001,T001,S001-S002,拉伸,room temperature,1e-3 s^-1,vertical,vertical,polished,ASTM E8,,E001,",
        ],
        "05_性能结果表.csv": [
            "论文编号,结果编号,样品编号,测试条件编号,指标名称,数值或趋势,单位,数据属于,数据来源,证据编号或位置,备注",
            "P001,R001,S001,T001,yield strength,900,MPa,本文实验,Table,E001,",
            "P001,R002,S002,T001,yield strength,980,MPa,前人文献,Table,E001,",
        ],
        "06_对照比较关系表.csv": [
            "论文编号,比较编号,当前样品编号,对照对象,对照类型,比较指标,当前值,对照值,单位,变化方向,证据编号或位置,备注",
            "P001,C001,S002,S001,同文对照,yield strength,980,900,MPa,提高,E001,",
        ],
        "07_组织缺陷表征观察表.csv": [
            "论文编号,观察编号,样品编号,表征方法,观察对象,数值或描述,单位,作者解释,证据编号或位置,备注",
            "P001,O001,\"S001,S002\",SEM,porosity,low,,supports strength,E001,",
        ],
        "08_证据位置表.csv": [
            "论文编号,证据编号,证据类型,页码,章节,表格或图号,原文短句或单元格,支持什么,备注",
            "P001,E001,表格,p.1,Results,Table 1,value,supports facts,",
        ],
        "09_缺失不确定信息表.csv": [
            "论文编号,问题编号,影响对象,问题类型,问题描述,影响,建议处理",
            "P001,Q001,R001,缺失,missing orientation,limited comparison,review",
            "ALL,Q001,全体表格,跨论文可比性限制,methods differ,comparison limited,group by method",
        ],
    }
    for filename, rows in rows_by_table.items():
        (root / filename).write_text("\ufeff" + "\n".join(rows), encoding="utf-8")
