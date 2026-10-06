# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Configuration models for Source document parsing."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class StorageConfig(BaseModel):
    """Storage configuration used by Source input/output."""

    base_dir: str = Field(default="output")


class InputStorageConfig(StorageConfig):
    """Input storage configuration."""

    base_dir: str = Field(default="input")


class InputConfig(BaseModel):
    """Input configuration for Source document normalization."""

    storage: InputStorageConfig = Field(default_factory=InputStorageConfig)
    file_type: str = Field(default="document")
    encoding: str = Field(default="utf-8")
    file_pattern: str = Field(default="")
    file_filter: dict[str, str] | None = None


class ChunkingConfig(BaseModel):
    """Token chunking configuration for document parsing."""

    size: int = Field(default=1200)
    overlap: int = Field(default=100)
    encoding_model: str = Field(default="cl100k_base")


class SourceParserConfig(BaseModel):
    """Configuration consumed by the Source parser entrypoint."""

    root_dir: str = Field(default="")
    input: InputConfig = Field(default_factory=InputConfig)
    chunks: ChunkingConfig = Field(default_factory=ChunkingConfig)
    output: StorageConfig = Field(default_factory=StorageConfig)

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
        if file_type == "document":
            self.input.file_pattern = r".*\.(?:txt|pdf)$"
        else:
            raise ValueError(f"unsupported Source input type: {file_type}")

    def _resolve_storage_dir(self, storage: StorageConfig) -> None:
        if storage.base_dir.strip() == "":
            raise ValueError("file storage requires a base_dir")
        storage.base_dir = str((Path(self.root_dir) / storage.base_dir).resolve())

    @model_validator(mode="after")
    def _validate_model(self) -> "SourceParserConfig":
        self._resolve_root_dir()
        self._normalize_input_pattern()
        self._resolve_storage_dir(self.input.storage)
        self._resolve_storage_dir(self.output)
        return self
