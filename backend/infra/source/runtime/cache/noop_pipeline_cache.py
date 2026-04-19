# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""No-op cache used by the Source runtime."""

from typing import Any

from infra.source.runtime.cache.pipeline_cache import PipelineCache


class NoopPipelineCache(PipelineCache):
    """A no-op Source runtime cache."""

    async def get(self, key: str) -> Any:
        return None

    async def set(
        self, key: str, value: str | bytes | None, debug_data: dict | None = None
    ) -> None:
        return None

    async def has(self, key: str) -> bool:
        return False

    async def delete(self, key: str) -> None:
        return None

    async def clear(self) -> None:
        return None

    def child(self, name: str) -> PipelineCache:
        return self
