from __future__ import annotations

from pydantic import BaseModel, Field


class GraphNodeResponse(BaseModel):
    """Node payload returned by the collection graph endpoint."""

    id: str = Field(..., description="节点 ID")
    label: str = Field(..., description="节点显示名称")
    type: str | None = Field(default=None, description="节点类型")
    degree: int | None = Field(default=None, description="节点度数")


class GraphEdgeResponse(BaseModel):
    """Edge payload returned by the collection graph endpoint."""

    id: str = Field(..., description="关系 ID")
    source: str = Field(..., description="源节点 ID")
    target: str = Field(..., description="目标节点 ID")
    weight: float | None = Field(default=None, description="关系权重")
    edge_description: str | None = Field(default=None, description="关系描述")


class CollectionGraphResponse(BaseModel):
    """Collection graph response."""

    collection_id: str = Field(..., description="集合 ID")
    nodes: list[GraphNodeResponse] = Field(default_factory=list, description="图谱节点")
    edges: list[GraphEdgeResponse] = Field(default_factory=list, description="图谱边")
    truncated: bool = Field(default=False, description="是否因节点上限被截断")


class CollectionGraphNeighborhoodResponse(BaseModel):
    """Collection graph neighborhood response."""

    collection_id: str = Field(..., description="集合 ID")
    center_node_id: str = Field(..., description="中心节点 ID")
    nodes: list[GraphNodeResponse] = Field(default_factory=list, description="邻域节点")
    edges: list[GraphEdgeResponse] = Field(default_factory=list, description="邻域边")
    truncated: bool = Field(default=False, description="是否因节点上限被截断")
