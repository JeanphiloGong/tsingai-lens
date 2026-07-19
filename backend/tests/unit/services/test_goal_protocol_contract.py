from __future__ import annotations

import pytest

from application.goal.protocol_contract import (
    proposed_design_choice_has_unsupported_detail,
    ved_design_is_scientifically_consistent,
)


@pytest.mark.parametrize(
    "content",
    [
        """Hypothesis: VED is associated with fatigue strength.
Variable matrix:
Vary laser power to create VED levels while holding scan speed, hatch spacing, and layer thickness fixed.
Measurements:
Measure fatigue strength.
Controls:
Hold scan speed, hatch spacing, and layer thickness fixed.
Risks or limits:
Treat the result as a laser-power-mediated VED path.
""",
        """假设：体积能量密度与疲劳强度相关。
变量矩阵：
改变激光功率以形成不同体积能量密度水平，同时保持扫描速度、道间距和层厚不变。
测量：
测量疲劳强度。
控制：
保持扫描速度、道间距和层厚不变。
风险或限制：
该设计只验证由激光功率实现的体积能量密度路径。
""",
    ],
)
def test_ved_design_contract_accepts_operational_designs(content):
    assert ved_design_is_scientifically_consistent(content) is True


@pytest.mark.parametrize(
    "content",
    [
        """Hypothesis: VED is associated with fatigue strength.
Variable matrix:
Compare low and moderate VED levels.
Measurements:
Measure fatigue strength.
Controls:
Hold laser power, scan speed, hatch spacing, and layer thickness fixed.
Risks or limits:
Review confounding.
""",
        """假设：体积能量密度与疲劳强度相关。
变量：
比较低、中体积能量密度水平。
测试指标：
测量疲劳强度。
对照：
保持激光功率、扫描速度、道间距和层厚不变。
限制：
检查混杂因素。
""",
    ],
)
def test_ved_design_contract_rejects_designs_without_a_changed_constituent(
    content,
):
    assert ved_design_is_scientifically_consistent(content) is False


def test_ved_design_contract_rejects_a_constituent_marked_changed_and_fixed():
    content = """Hypothesis: VED is associated with fatigue strength.
Variable matrix:
Vary laser power to create VED levels while holding scan speed, hatch spacing, and layer thickness fixed.
Measurements:
Measure fatigue strength.
Controls:
Hold laser power, scan speed, hatch spacing, and layer thickness fixed.
Risks or limits:
Review confounding.
"""

    assert ved_design_is_scientifically_consistent(content) is False


def test_ved_design_contract_rejects_an_affirmative_ved_isolation_claim():
    content = """Hypothesis: VED is associated with fatigue strength.
Variable matrix:
Vary laser power to create VED levels while holding scan speed, hatch spacing, and layer thickness fixed.
Measurements:
Measure fatigue strength.
Controls:
Hold scan speed, hatch spacing, and layer thickness fixed.
Risks or limits:
This design isolates the effect of VED from all constituent parameters.
"""

    assert ved_design_is_scientifically_consistent(content) is False


def test_ved_design_contract_allows_an_explicit_non_isolation_boundary():
    content = """Hypothesis: VED is associated with fatigue strength.
Variable matrix:
Vary laser power to create VED levels while holding scan speed, hatch spacing, and layer thickness fixed.
Measurements:
Measure fatigue strength.
Controls:
Hold scan speed, hatch spacing, and layer thickness fixed.
Risks or limits:
This estimates a laser-power-mediated path and does not isolate a universal VED-only effect.
"""

    assert ved_design_is_scientifically_consistent(content) is True


def test_ved_design_contract_rejects_ved_only_effect_as_validation_target():
    content = """Hypothesis: VED is associated with fatigue strength.
Variable matrix:
Vary laser power to create VED levels while holding scan speed, hatch spacing, and layer thickness fixed.
Measurements:
Measure fatigue strength.
Controls:
Hold scan speed, hatch spacing, and layer thickness fixed.
Risks or limits:
Additional experiments may confirm VED-only effects.
"""

    assert ved_design_is_scientifically_consistent(content) is False


@pytest.mark.parametrize(
    "item",
    [
        "Measure fatigue strength at 10^4 cycles.",
        "Measure fatigue strength at 10⁴ cycles.",
        "Measure maximum defect length by LCSM.",
        "Use the same PBF-LB machine.",
        "Use 316L stainless steel.",
    ],
)
def test_proposed_design_choice_rejects_unattributed_source_details(item):
    assert proposed_design_choice_has_unsupported_detail(item) is True


def test_proposed_design_choice_allows_source_independent_actions():
    assert (
        proposed_design_choice_has_unsupported_detail(
            "Vary laser power to create VED levels while the expert selects the levels."
        )
        is False
    )
