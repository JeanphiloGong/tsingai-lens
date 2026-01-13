# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

from pydantic import BaseModel, Field

from retrieval.config.enums import IndexingMethod


class IndexRequest(BaseModel):
    """Request payload to start indexing."""

    config_path: str = Field(..., description="配置文件路径（YAML/JSON/ENV）")
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


class ConfigUploadResponse(BaseModel):
    """Response after uploading a config file."""

    filename: str
    path: str


class ConfigItem(BaseModel):
    """Config metadata for listing."""

    filename: str
    path: str
    modified_at: float


class ConfigListResponse(BaseModel):
    """Response containing available configs."""

    items: list[ConfigItem]


class ConfigCreateRequest(BaseModel):
    """Create a new config file from raw content."""

    filename: str = Field(..., description="文件名，支持 .yml/.yaml/.json/.env")
    content: str = Field(..., description="文件内容")


class ConfigDetailResponse(BaseModel):
    """Config file content payload."""

    filename: str
    content: str
