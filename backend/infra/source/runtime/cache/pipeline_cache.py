# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Cache interface used by the Source runtime."""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import Any


class PipelineCache(metaclass=ABCMeta):
    """Provide a cache interface for the pipeline."""

    @abstractmethod
    async def get(self, key: str) -> Any:
        """Get the value for the given key."""

    @abstractmethod
    async def set(self, key: str, value: Any, debug_data: dict | None = None) -> None:
        """Set the value for the given key."""

    @abstractmethod
    async def has(self, key: str) -> bool:
        """Return True if the given key exists in the cache."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete the given key from the cache."""

    @abstractmethod
    async def clear(self) -> None:
        """Clear the cache."""

    @abstractmethod
    def child(self, name: str) -> "PipelineCache":
        """Create a child cache with the given name."""
