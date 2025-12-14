from dataclasses import dataclass, field
from typing import ClassVar

from pandas.core.reshape import encoding

from retrieval.config.enums import CacheType, InputFileType, StorageType

DEFAULT_OUTPUT_BASE_DIR = "output"

@dataclass
class InputStorageDefaults(StorageDefaults):
    """default values for input storage"""
    base_dir: str = "input"

@dataclass
class InputDefaults:
    """
    default values for input
    """

    storage: InputStorageDefaults = field(default_factory=InputStorageDefaults)
    file_type: ClassVar[InputFileType] = InputFileType.text
    file_pattern: str = ""
    encoding: str = "utf-8"
    metadata: None = None

@dataclass
class StorageDefaults:
    """default values for storage"""
    type: ClassVar[StorageType] = StorageType.file
    base_dir: str = DEFAULT_OUTPUT_BASE_DIR
    connection_string: None = None
    container_name: None = None
    storage_account_blob_url: None = None
    cosmosdb_account_url: None = None

@dataclass
class CacheDefaults:
    """Default values for cache."""

    type: ClassVar[CacheType] = CacheType.file
    base_dir: str = "cache"
    connection_string: None = None
    container_name: None = None
    storage_account_blob_url: None = None
    cosmosdb_account_url: None = None

@dataclass
class GraphRagConfigDefaults:
    """
    default value for graphrag
    """
    root_dir: str = ""
    input: InputDefaults = field(default_factory=InputDefaults)
    workflows: None = None
    storage: StorageDefaults = field(default_factory=StorageDefaults)
    cache: CacheDefaults = field(default_factory=CacheDefaults)


graphrag_config_defaults = GraphRagConfigDefaults()
