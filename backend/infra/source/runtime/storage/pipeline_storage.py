# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Storage interface used by the Source runtime."""

import re
from abc import ABCMeta, abstractmethod
from collections.abc import Iterator
from datetime import datetime
from typing import Any


class PipelineStorage(metaclass=ABCMeta):
    """Provide a storage interface for the pipeline."""

    @abstractmethod
    def find(
        self,
        file_pattern: re.Pattern[str],
        base_dir: str | None = None,
        file_filter: dict[str, Any] | None = None,
        max_count: int = -1,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """Find files in storage."""

    @abstractmethod
    async def get(
        self, key: str, as_bytes: bool | None = None, encoding: str | None = None
    ) -> Any:
        """Get the value for the given key."""

    @abstractmethod
    async def set(self, key: str, value: Any, encoding: str | None = None) -> None:
        """Set the value for the given key."""

    @abstractmethod
    async def has(self, key: str) -> bool:
        """Return True if the given key exists in storage."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete the given key from storage."""

    @abstractmethod
    async def clear(self) -> None:
        """Clear the storage."""

    @abstractmethod
    def child(self, name: str | None) -> "PipelineStorage":
        """Create a child storage instance."""

    @abstractmethod
    def keys(self) -> list[str]:
        """List all keys in storage."""

    @abstractmethod
    async def get_creation_date(self, key: str) -> str:
        """Get the creation date for the given key."""


def get_timestamp_formatted_with_local_tz(timestamp: datetime) -> str:
    """Get the formatted timestamp with the local time zone."""
    creation_time_local = timestamp.astimezone()
    return creation_time_local.strftime("%Y-%m-%d %H:%M:%S %z")
