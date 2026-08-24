from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CollectionCreateRequest(BaseModel):
    """Request payload to create a logical paper collection."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="Collection name")
    description: str | None = Field(default=None, description="Collection description")


class CollectionResponse(BaseModel):
    """Collection metadata returned to clients."""

    collection_id: str = Field(..., description="Collection ID")
    name: str = Field(..., description="Collection name")
    description: str | None = Field(default=None, description="Collection description")
    status: str = Field(..., description="Collection status")
    paper_count: int = Field(default=0, description="Number of papers")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")


class CollectionListResponse(BaseModel):
    """Collection listing payload."""

    items: list[CollectionResponse] = Field(
        default_factory=list,
        description="Collections",
    )


class CollectionDeleteResponse(BaseModel):
    """Collection deletion result."""

    collection_id: str = Field(..., description="Deleted collection ID")
    deleted_at: str = Field(..., description="Deletion timestamp")


class CollectionFileResponse(BaseModel):
    """Stored collection file metadata."""

    file_id: str = Field(..., description="File ID")
    collection_id: str = Field(..., description="Collection ID")
    original_filename: str = Field(..., description="Original filename")
    stored_filename: str = Field(..., description="Stored filename")
    stored_path: str = Field(..., description="Storage path")
    media_type: str | None = Field(default=None, description="Media type")
    status: str = Field(..., description="File status")
    size_bytes: int = Field(default=0, description="File size in bytes")
    created_at: str = Field(..., description="Creation timestamp")


class CollectionFileListResponse(BaseModel):
    """Collection file listing payload."""

    items: list[CollectionFileResponse] = Field(
        default_factory=list,
        description="Collection files",
    )


class CollectionSourceArchiveRequest(BaseModel):
    """Selection of original collection files to export for reproduction."""

    model_config = ConfigDict(extra="forbid")

    file_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("file_ids")
    @classmethod
    def validate_file_ids(cls, values: list[str]) -> list[str]:
        normalized = [str(value).strip() for value in values]
        if any(not value or len(value) > 128 for value in normalized):
            raise ValueError(
                "file_ids must contain non-empty values up to 128 characters"
            )
        if len(set(normalized)) != len(normalized):
            raise ValueError("file_ids must be unique")
        return normalized
