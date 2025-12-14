from typing import Callable, ClassVar

from retrieval.cache.pipeline_cache import PipelineCache


class CacheFactory:
    _registery: ClassVar[dict[str, Callable[..., PipelineCache]]] = {}

    @classmethod
    def register(cls, cache_type: str, creator: Callable[..., PipelineCache]) -> None:
        """register a custom cache implementation."""
        cls._registery[cache_type] = creator

    @classmethod
    def create_cache(cls, cache_type: str, kwargs: dict) -> PipelineCache:
        if cache_type not in cls._registery:
            msg = f"unknown cache type: {cache_type}"
            raise ValueError(msg)
        return cls._registery[cache_type](**kwargs)


