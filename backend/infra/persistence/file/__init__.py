"""File-backed persistence adapters."""

from infra.persistence.file.artifact_repository import FileArtifactRepository
from infra.persistence.file.collection_repository import (
    CollectionPaths,
    FileCollectionRepository,
)
from infra.persistence.file.task_repository import FileTaskRepository

__all__ = [
    "CollectionPaths",
    "FileArtifactRepository",
    "FileCollectionRepository",
    "FileTaskRepository",
]
