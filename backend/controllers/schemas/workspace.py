from __future__ import annotations

from pydantic import BaseModel, Field

from .collection import CollectionResponse
from .task import TaskResponse


class WorkspaceArtifactStatusResponse(BaseModel):
    """Collection-scoped artifact readiness summary."""

    output_path: str = Field(..., description="集合输出目录")
    documents_ready: bool = Field(default=False, description="documents.parquet 是否存在")
    graph_ready: bool = Field(default=False, description="图谱 parquet 是否就绪")
    sections_ready: bool = Field(default=False, description="sections.parquet 是否存在")
    procedure_blocks_ready: bool = Field(
        default=False,
        description="procedure_blocks.parquet 是否存在",
    )
    protocol_steps_ready: bool = Field(
        default=False,
        description="protocol_steps.parquet 是否存在",
    )
    graphml_ready: bool = Field(default=False, description="graph.graphml 是否存在")
    updated_at: str = Field(..., description="更新时间")


class WorkspaceCapabilitiesResponse(BaseModel):
    """Feature gates exposed to the frontend workspace."""

    can_view_graph: bool = Field(default=False, description="是否可查看图谱")
    can_download_graphml: bool = Field(default=False, description="是否可导出 GraphML")
    can_view_protocol_steps: bool = Field(default=False, description="是否可查看 protocol steps")
    can_search_protocol: bool = Field(default=False, description="是否可检索 protocol steps")
    can_generate_sop: bool = Field(default=False, description="是否可生成 SOP 草案")


class WorkspaceOverviewResponse(BaseModel):
    """Top-level collection workspace payload."""

    collection: CollectionResponse = Field(..., description="集合元数据")
    file_count: int = Field(default=0, description="集合文件数")
    status_summary: str = Field(..., description="工作区摘要状态")
    artifacts: WorkspaceArtifactStatusResponse = Field(..., description="产物状态")
    latest_task: TaskResponse | None = Field(default=None, description="最近一次任务")
    recent_tasks: list[TaskResponse] = Field(default_factory=list, description="最近任务列表")
    capabilities: WorkspaceCapabilitiesResponse = Field(..., description="工作区能力开关")
