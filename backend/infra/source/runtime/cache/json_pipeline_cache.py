# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""JSON-backed cache used by the Source runtime."""

import json
from typing import Any

from infra.source.runtime.cache.pipeline_cache import PipelineCache
from infra.source.runtime.storage.pipeline_storage import PipelineStorage


class JsonPipelineCache(PipelineCache):
    """JSON-backed Source runtime cache."""

    _storage: PipelineStorage
    _encoding: str

    def __init__(self, storage: PipelineStorage, encoding: str = "utf-8"):
        self._storage = storage
        self._encoding = encoding

    async def get(self, key: str) -> str | None:
        if not await self.has(key):
            return None
        try:
            data = await self._storage.get(key, encoding=self._encoding)
            data = json.loads(data)
        except (UnicodeDecodeError, json.decoder.JSONDecodeError):
            await self._storage.delete(key)
            return None
        return data.get("result")

    async def set(self, key: str, value: Any, debug_data: dict | None = None) -> None:
        if value is None:
            return
        data = {"result": value, **(debug_data or {})}
        await self._storage.set(
            key, json.dumps(data, ensure_ascii=False), encoding=self._encoding
        )

    async def has(self, key: str) -> bool:
        return await self._storage.has(key)

    async def delete(self, key: str) -> None:
        if await self.has(key):
            await self._storage.delete(key)

    async def clear(self) -> None:
        await self._storage.clear()

    def child(self, name: str) -> "JsonPipelineCache":
        return JsonPipelineCache(self._storage.child(name), encoding=self._encoding)
