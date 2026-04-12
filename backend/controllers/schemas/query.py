from __future__ import annotations

from pydantic import BaseModel, Field

from retrieval.config.enums import SearchMethod


class QueryRequest(BaseModel):
    """Request payload to query an indexed knowledge graph."""

    query: str = Field(..., description="检索问题")
    method: SearchMethod | str = Field(
        default=SearchMethod.GLOBAL, description="检索方法"
    )
    collection_id: str | None = Field(default=None, description="集合 ID")
    response_type: str = Field(
        default="List of 5-7 Points", description="回答格式描述"
    )
    community_level: int | None = Field(
        default=2, description="社区层级（local/drift/global 可用）"
    )
    dynamic_community_selection: bool = Field(
        default=False, description="global 模式动态社区选择"
    )
    include_context: bool = Field(
        default=False, description="是否返回 context_data"
    )
    verbose: bool = Field(default=False, description="是否输出详细日志")


class QueryResponse(BaseModel):
    """Response payload for query results."""

    answer: object
    method: str
    collection_id: str
    output_path: str
    context_data: dict | list | None = None
