# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""In-memory cache used by the Source runtime."""

from typing import Any

from infra.source.runtime.cache.pipeline_cache import PipelineCache


class InMemoryCache(PipelineCache):
    """In-memory Source runtime cache."""

    _cache: dict[str, Any]
    _name: str

    def __init__(self, name: str | None = None):
        self._cache = {}
        self._name = name or ""

    async def get(self, key: str) -> Any:
        return self._cache.get(self._create_cache_key(key))

    async def set(self, key: str, value: Any, debug_data: dict | None = None) -> None:
        self._cache[self._create_cache_key(key)] = value

    async def has(self, key: str) -> bool:
        return self._create_cache_key(key) in self._cache

    async def delete(self, key: str) -> None:
        del self._cache[self._create_cache_key(key)]

    async def clear(self) -> None:
        self._cache.clear()

    def child(self, name: str) -> PipelineCache:
        return InMemoryCache(name)

    def _create_cache_key(self, key: str) -> str:
        return f"{self._name}{key}"
