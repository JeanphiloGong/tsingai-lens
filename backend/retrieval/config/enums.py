"""
a module containing config enums
"""
from __future__ import annotations
from enum import Enum

class CacheType(str, Enum):
    """
    the cache configuration type for the pipeline
    """
    file = "file"
    """
    the file cahce configuration type.
    """

    memory = "momory"
    """
    the memory cahce configuration type.
    """
    none = "none"
    """the none cache configuration type."""
    blob = "blob"
    """
    the blob chache configuration type
    """

    def __repr__(self):
        """
        get a string representation.
        """
        return f'"{self.value}"'

class InputFileType(str, Enum):
    """
    the input file type for the pipeline
    """
    csv = "csv"
    text = "text"
    json = "json"

    def __repr__(self) -> str:
        """get a string representation"""
        return f'"{self.value}'

class IndexingMethod(str, Enum):
    """
    enum for the type of indexing to perform
    """

    Standard = "standard"
    """
    traditional graphrag indexing, with all graph construction and summarization performed by a language model.
    """
    Fast = "fast"
    """
    Fast indexing, using NLP for graph construction and lnaguage model for summariaation.
    """
    StandardUpdate = "standard-update"
    """
    Increment update iwth standard indexing
    """
    FastUpdate = "fast-update"
    """
    Increment update with fast indexing
    """

class StorageType(str, Enum):
    """
    the output type for the pipeline
    """
    file="file"
    """the file output type"""
    memory = "memory"
    """the momory output type"""
    blob = "blob"
    """the blob output type."""
    cosmosdb = "cosmosdb"
    """the cosmosdb output type"""

    def __repr__(self):
        """
        get a string representation
        """
        return f'"{self.value}"'
