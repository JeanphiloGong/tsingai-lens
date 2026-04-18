from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ComparabilityStatus = Literal["comparable", "limited", "not_comparable", "insufficient"]


class ComparisonRowItemResponse(BaseModel):
    """Single collection-facing comparison row."""

    row_id: str = Field(..., description="comparison row ID")
    collection_id: str = Field(..., description="集合 ID")
    source_document_id: str = Field(..., description="来源文档 ID")
    variant_id: str | None = Field(default=None, description="样品变体 ID")
    variant_label: str | None = Field(default=None, description="样品变体标签")
    variable_axis: str | None = Field(default=None, description="变量轴名称")
    variable_value: str | float | int | None = Field(default=None, description="变量轴取值")
    baseline_reference: str | None = Field(default=None, description="baseline 参考对象")
    result_source_type: str | None = Field(default=None, description="结果来源类型")
    supporting_evidence_ids: list[str] = Field(default_factory=list, description="支撑 evidence IDs")
    material_system_normalized: str = Field(..., description="标准化材料体系")
    process_normalized: str = Field(..., description="标准化工艺")
    property_normalized: str = Field(..., description="标准化性质指标")
    baseline_normalized: str = Field(..., description="标准化 baseline")
    test_condition_normalized: str = Field(..., description="标准化测试条件")
    comparability_status: ComparabilityStatus = Field(..., description="可比性状态")
    comparability_warnings: list[str] = Field(default_factory=list, description="可比性警告")
    value: float | None = Field(default=None, description="归一化后的数值")
    unit: str | None = Field(default=None, description="单位")


class ComparisonRowListResponse(BaseModel):
    """Collection-scoped comparison row listing."""

    collection_id: str = Field(..., description="集合 ID")
    total: int = Field(..., description="总条数")
    count: int = Field(..., description="返回条数")
    items: list[ComparisonRowItemResponse] = Field(default_factory=list, description="comparison row 列表")
