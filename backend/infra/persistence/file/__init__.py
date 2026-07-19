"""File-backed persistence adapters."""

from infra.persistence.file.artifact_repository import FileArtifactRepository
from infra.persistence.file.collection_workspace import FileCollectionWorkspace
from infra.persistence.file.task_repository import FileTaskRepository

__all__ = [
    "FileArtifactRepository",
    "FileCollectionWorkspace",
    "FileTaskRepository",
]
