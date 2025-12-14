from retrieval.cache.factory import CacheFactory
from retrieval.cache.pipeline_cache import PipelineCache
from retrieval.config.models import cache_config
from retrieval.config.models.storage_config import StorageConfig
from retrieval.storage.factory import StorageFactory
from retrieval.storage.pipeline_storage import PipelineStorage


def create_storage_from_config(output: StorageConfig) -> PipelineStorage:
    """create a storage object from the config."""
    storage_config = output.model_dump()
    return StorageFactory.create_storage(
            storage_type=storage_config["type"],
            kwargs=storage_config,
            )

def create_cache_from_config(cache: CacheConfig, root_dir: str) -> PipelineCache:
    cache_config = cache.model_dump()
    kwargs = {**cache_config, "root_dir": root_dir}
    return CacheFactory().create_cache(
            cache_type=cache_config["type"],
            kwargs=kwargs
            )
