from __future__ import annotations

import pytest

from application.goal.protocol_contract import (
    ved_design_is_operationally_consistent,
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
    assert ved_design_is_operationally_consistent(content) is True


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
    assert ved_design_is_operationally_consistent(content) is False


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

    assert ved_design_is_operationally_consistent(content) is False
