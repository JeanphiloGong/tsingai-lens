from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CollectionCreateRequest(BaseModel):
    """Request payload to create a logical paper collection."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, description="Collection name")
    description: str | None = Field(default=None, description="Collection description")

    @field_validator("description")
    @classmethod
    def empty_description_is_none(cls, value: str | None) -> str | None:
        return value or None


class CollectionDocumentResponse(BaseModel):
    """A current source document in a collection."""

    document_id: str = Field(..., description="Document ID")
    original_filename: str = Field(..., description="Original filename")
    stored_filename: str = Field(..., description="Stored filename")
    storage_key: str = Field(..., description="Storage key")
    sha256: str = Field(..., description="Document content hash")
    media_type: str | None = Field(default=None, description="Media type")
    status: str = Field(..., description="Document status")
    size_bytes: int = Field(default=0, description="Document size in bytes")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last preparation-state update")
    parser_version: str | None = Field(default=None)
    document_analysis_version: str | None = Field(default=None)
    preparation_fingerprint: str | None = Field(default=None)


class CollectionResponse(BaseModel):
    """Collection metadata and its current documents."""

    collection_id: str = Field(..., description="Collection ID")
    name: str = Field(..., description="Collection name")
    description: str | None = Field(default=None, description="Collection description")
    status: str = Field(..., description="Collection status")
    paper_count: int = Field(default=0, description="Number of current documents")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    documents: list[CollectionDocumentResponse] = Field(
        default_factory=list,
        description="Current collection documents",
    )


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


class CollectionDocumentListResponse(BaseModel):
    """Collection document listing payload."""

    items: list[CollectionDocumentResponse] = Field(
        default_factory=list,
        description="Collection documents",
    )


class CollectionSourceArchiveRequest(BaseModel):
    """Selection of original collection documents to export for reproduction."""

    model_config = ConfigDict(extra="forbid")

    document_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("document_ids")
    @classmethod
    def validate_document_ids(cls, values: list[str]) -> list[str]:
        normalized = [str(value).strip() for value in values]
        if any(not value or len(value) > 128 for value in normalized):
            raise ValueError(
                "document_ids must contain non-empty values up to 128 characters"
            )
        if len(set(normalized)) != len(normalized):
            raise ValueError("document_ids must be unique")
        return normalized
