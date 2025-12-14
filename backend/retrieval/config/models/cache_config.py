from pydantic import BaseModel, Field

from retrieval.config.enums import CacheType
from retrieval.config.defaults import graphrag_config_defaults


class CacheConfig(BaseModel):
    """
    the default configuration section for cache
    """
    type: CacheType | str = Field(
            description="the cache type to use.",
            default=graphrag_config_defaults.cache.type,
            )
