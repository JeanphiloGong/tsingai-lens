# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Minimal Source runtime configuration models."""

from __future__ import annotations

from pathlib import Path
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class CacheType(str, Enum):
    """Supported cache types for the active Source runtime."""

    file = "file"
    memory = "memory"
    none = "none"
    blob = "blob"
    cosmosdb = "cosmosdb"


class InputFileType(str, Enum):
    """Supported input file types for the active Source runtime."""

    csv = "csv"
    document = "document"
    text = "text"
    json = "json"


class StorageType(str, Enum):
    """Supported storage types for the active Source runtime."""

    file = "file"
    memory = "memory"
    blob = "blob"
    cosmosdb = "cosmosdb"


class ChunkStrategyType(str, Enum):
    """Supported chunking strategies for the active Source runtime."""

    tokens = "tokens"
    sentence = "sentence"


class StorageConfig(BaseModel):
    """Storage configuration used by Source input/output."""

    type: StorageType | str = Field(default=StorageType.file)
    base_dir: str = Field(default="output")
    connection_string: str | None = None
    container_name: str | None = None
    storage_account_blob_url: str | None = None
    cosmosdb_account_url: str | None = None


class InputStorageConfig(StorageConfig):
    """Input storage configuration."""

    base_dir: str = Field(default="input")


class CacheConfig(BaseModel):
    """Cache configuration used by the active Source runtime."""

    type: CacheType | str = Field(default=CacheType.file)
    base_dir: str = Field(default="cache")
    connection_string: str | None = None
    container_name: str | None = None
    storage_account_blob_url: str | None = None
    cosmosdb_account_url: str | None = None


class InputConfig(BaseModel):
    """Input configuration for Source runtime normalization."""

    storage: InputStorageConfig = Field(default_factory=InputStorageConfig)
    file_type: InputFileType | str = Field(default=InputFileType.document)
    encoding: str = Field(default="utf-8")
    file_pattern: str = Field(default="")
    file_filter: dict[str, str] | None = None
    text_column: str = Field(default="text")
    title_column: str | None = None
    metadata: list[str] | None = None


class ChunkingConfig(BaseModel):
    """Chunking configuration used by the active Source runtime."""

    size: int = Field(default=1200)
    overlap: int = Field(default=100)
    group_by_columns: list[str] = Field(default_factory=lambda: ["id"])
    strategy: ChunkStrategyType | str = Field(default=ChunkStrategyType.tokens)
    encoding_model: str = Field(default="cl100k_base")
    prepend_metadata: bool = False
    chunk_size_includes_metadata: bool = False


class SourceRuntimeConfig(BaseModel):
    """Minimal config consumed by the active Source runtime."""

    root_dir: str = Field(default="")
    input: InputConfig = Field(default_factory=InputConfig)
    chunks: ChunkingConfig = Field(default_factory=ChunkingConfig)
    output: StorageConfig = Field(default_factory=StorageConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    workflows: list[str] | None = None

    def __str__(self) -> str:
        return self.model_dump_json(indent=4)

    def _resolve_root_dir(self) -> None:
        if self.root_dir.strip() == "":
            self.root_dir = str(Path.cwd())
        root_dir = Path(self.root_dir).resolve()
        if not root_dir.is_dir():
            raise FileNotFoundError(
                f"Invalid root directory: {self.root_dir} is not a directory."
            )
        self.root_dir = str(root_dir)

    def _normalize_input_pattern(self) -> None:
        if self.input.file_pattern:
            return
        file_type = str(getattr(self.input.file_type, "value", self.input.file_type))
        if file_type == InputFileType.text.value:
            self.input.file_pattern = r".*\.txt$"
        elif file_type == InputFileType.document.value:
            self.input.file_pattern = r".*\.(?:txt|pdf)$"
        else:
            self.input.file_pattern = rf".*\.{file_type}$"

    def _resolve_storage_dir(self, storage: StorageConfig) -> None:
        storage_type = str(getattr(storage.type, "value", storage.type))
        if storage_type != StorageType.file.value:
            return
        if storage.base_dir.strip() == "":
            raise ValueError("file storage requires a base_dir")
        storage.base_dir = str((Path(self.root_dir) / storage.base_dir).resolve())

    @model_validator(mode="after")
    def _validate_model(self) -> "SourceRuntimeConfig":
        self._resolve_root_dir()
        self._normalize_input_pattern()
        self._resolve_storage_dir(self.input.storage)
        self._resolve_storage_dir(self.output)
        return self
