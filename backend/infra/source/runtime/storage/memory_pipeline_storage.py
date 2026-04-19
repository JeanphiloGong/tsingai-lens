# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""In-memory storage used by the Source runtime."""

import re
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

from infra.source.runtime.storage.pipeline_storage import (
    PipelineStorage,
    get_timestamp_formatted_with_local_tz,
)


class MemoryPipelineStorage(PipelineStorage):
    """In-memory Source runtime storage."""

    _storage: dict[str, Any]
    _created_at: dict[str, datetime]

    def __init__(self):
        self._storage = {}
        self._created_at = {}

    def find(
        self,
        file_pattern: re.Pattern[str],
        base_dir: str | None = None,
        file_filter: dict[str, Any] | None = None,
        max_count: int = -1,
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        """Find files in storage using a regex pattern."""

        def item_filter(item: dict[str, Any]) -> bool:
            if file_filter is None:
                return True
            return all(re.search(value, item[key]) for key, value in file_filter.items())

        loaded = 0
        prefix = (base_dir or "").strip("/")
        for key in self._storage:
            if prefix and not key.startswith(prefix + "/"):
                continue
            match = file_pattern.search(key)
            if match is None:
                continue
            groups = match.groupdict()
            if not item_filter(groups):
                continue
            yield key, groups
            loaded += 1
            if max_count > 0 and loaded >= max_count:
                break

    async def get(
        self, key: str, as_bytes: bool | None = None, encoding: str | None = None
    ) -> Any:
        return self._storage.get(key)

    async def set(self, key: str, value: Any, encoding: str | None = None) -> None:
        self._storage[key] = value
        self._created_at[key] = datetime.now(timezone.utc)

    async def has(self, key: str) -> bool:
        return key in self._storage

    async def delete(self, key: str) -> None:
        del self._storage[key]
        self._created_at.pop(key, None)

    async def clear(self) -> None:
        self._storage.clear()
        self._created_at.clear()

    def child(self, name: str | None) -> "PipelineStorage":
        return MemoryPipelineStorage()

    def keys(self) -> list[str]:
        return list(self._storage.keys())

    async def get_creation_date(self, key: str) -> str:
        timestamp = self._created_at.get(key, datetime.now(timezone.utc))
        return get_timestamp_formatted_with_local_tz(timestamp)
