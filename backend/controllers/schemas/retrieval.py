# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

from pydantic import BaseModel, Field

from retrieval.config.enums import IndexingMethod, SearchMethod


class IndexRequest(BaseModel):
    """Request payload to start indexing."""

    collection_id: str | None = Field(default=None, description="集合 ID")
    method: IndexingMethod | str = Field(
        default=IndexingMethod.Standard, description="索引模式"
    )
    is_update_run: bool = Field(default=False, description="是否执行增量更新")
    verbose: bool = Field(default=False, description="是否输出详细日志")
    additional_context: dict | None = Field(
        default=None, description="透传到 pipeline state 的附加上下文"
    )


class IndexResponse(BaseModel):
    """Response payload summarizing pipeline execution."""

    status: str
    workflows: list[str]
    errors: list[str] | None = None
    output_path: str | None = None
    stored_input_path: str | None = None


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


class InputUploadItem(BaseModel):
    """Uploaded input file metadata."""

    original_filename: str
    stored_name: str
    stored_path: str
    converted_to_text: bool = False
    size_bytes: int


class InputUploadResponse(BaseModel):
    """Response for input file uploads without indexing."""

    count: int
    items: list[InputUploadItem]


class CollectionFileRecord(BaseModel):
    """Metadata for a collection input file."""

    key: str
    original_filename: str | None = None
    stored_path: str | None = None
    size_bytes: int | None = None
    created_at: str | None = None


class CollectionFileListResponse(BaseModel):
    """Response containing collection input files."""

    collection_id: str
    count: int
    items: list[CollectionFileRecord]


class CollectionFileDeleteResponse(BaseModel):
    """Response payload for collection file deletion."""

    collection_id: str
    key: str
    deleted_at: str | None = None
    status: str = "deleted"


class CollectionCreateRequest(BaseModel):
    """Request payload to create a collection."""

    name: str | None = Field(default=None, description="集合名称")


class CollectionRecord(BaseModel):
    """Collection metadata."""

    id: str
    name: str | None = None
    created_at: str
    updated_at: str | None = None
    status: str | None = None
    document_count: int | None = None
    entity_count: int | None = None


class CollectionListResponse(BaseModel):
    """Response containing available collections."""

    items: list[CollectionRecord]


class CollectionDeleteResponse(BaseModel):
    """Response payload for collection deletion."""

    id: str
    deleted_at: str
    status: str = "deleted"
