from __future__ import annotations

from pydantic import BaseModel, Field


class CollectionCreateRequest(BaseModel):
    """Request payload to create a logical paper collection."""

    name: str = Field(..., description="集合名称")
    description: str | None = Field(default=None, description="集合描述")
    default_method: str = Field(default="standard", description="默认索引模式")


class CollectionResponse(BaseModel):
    """Collection metadata returned to clients."""

    collection_id: str = Field(..., description="集合 ID")
    name: str = Field(..., description="集合名称")
    description: str | None = Field(default=None, description="集合描述")
    status: str = Field(..., description="集合状态")
    default_method: str = Field(..., description="默认索引模式")
    paper_count: int = Field(default=0, description="论文数量")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")


class CollectionListResponse(BaseModel):
    """Collection listing payload."""

    items: list[CollectionResponse] = Field(default_factory=list, description="集合列表")


class CollectionFileResponse(BaseModel):
    """Stored collection file metadata."""

    file_id: str = Field(..., description="文件 ID")
    collection_id: str = Field(..., description="集合 ID")
    original_filename: str = Field(..., description="原始文件名")
    stored_filename: str = Field(..., description="存储文件名")
    stored_path: str = Field(..., description="存储路径")
    media_type: str | None = Field(default=None, description="媒体类型")
    status: str = Field(..., description="文件状态")
    size_bytes: int = Field(default=0, description="字节大小")
    created_at: str = Field(..., description="创建时间")


class CollectionFileListResponse(BaseModel):
    """Collection file listing payload."""

    items: list[CollectionFileResponse] = Field(default_factory=list, description="文件列表")
