
from typing import Callable, ClassVar

from retrieval.storage.pipeline_storage import PipelineStorage


class StorageFactory:
    _register: ClassVar[dict[str, Callable[..., PipelineStorage]]] = {}

    @classmethod
    def register(
            cls, storage_type: str, creator: Callable[..., PipelineStorage]
            ) -> None:
        cls._register[storage_type] = creator

    @classmethod
    def create_storage(cls, storage_type: str, kwargs: dict) -> PipelineStorage:
        if storage_type not in cls._register:
            msg = f"unkonwn storage type: {storage_type}"
            raise ValueError(msg)
        
        return cls._register[storage_type](**kwargs)

