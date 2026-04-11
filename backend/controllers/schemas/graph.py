from __future__ import annotations

from pydantic import BaseModel, Field


class GraphNodeResponse(BaseModel):
    """Node payload returned by the collection graph endpoint."""

    id: str = Field(..., description="节点 ID")
    label: str = Field(..., description="节点显示名称")
    type: str | None = Field(default=None, description="节点类型")
    description: str | None = Field(default=None, description="节点描述")
    degree: int | None = Field(default=None, description="节点度数")
    frequency: int | None = Field(default=None, description="节点频次")
    x: float | None = Field(default=None, description="布局 X 坐标")
    y: float | None = Field(default=None, description="布局 Y 坐标")
    community: int | None = Field(default=None, description="所属社区")
    node_text_unit_ids: str | None = Field(default=None, description="关联文本单元 ID 列表")
    node_text_unit_count: int | None = Field(default=None, description="关联文本单元数量")
    node_document_ids: str | None = Field(default=None, description="关联文档 ID 列表")
    node_document_titles: str | None = Field(default=None, description="关联文档标题列表")
    node_document_count: int | None = Field(default=None, description="关联文档数量")


class GraphEdgeResponse(BaseModel):
    """Edge payload returned by the collection graph endpoint."""

    id: str = Field(..., description="关系 ID")
    source: str = Field(..., description="源节点 ID")
    target: str = Field(..., description="目标节点 ID")
    weight: float | None = Field(default=None, description="关系权重")
    edge_description: str | None = Field(default=None, description="关系描述")
    edge_text_unit_ids: str | None = Field(default=None, description="关联文本单元 ID 列表")
    edge_text_unit_count: int | None = Field(default=None, description="关联文本单元数量")
    edge_document_ids: str | None = Field(default=None, description="关联文档 ID 列表")
    edge_document_titles: str | None = Field(default=None, description="关联文档标题列表")
    edge_document_count: int | None = Field(default=None, description="关联文档数量")


class CollectionGraphResponse(BaseModel):
    """Collection graph response."""

    collection_id: str = Field(..., description="集合 ID")
    output_path: str = Field(..., description="图谱输出目录")
    nodes: list[GraphNodeResponse] = Field(default_factory=list, description="图谱节点")
    edges: list[GraphEdgeResponse] = Field(default_factory=list, description="图谱边")
    truncated: bool = Field(default=False, description="是否因节点上限被截断")
    community: str | None = Field(default=None, description="当前社区筛选标签")
