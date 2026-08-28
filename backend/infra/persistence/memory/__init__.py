"""In-memory persistence adapters."""

from infra.persistence.memory.task_repository import MemoryTaskRepository
from infra.persistence.memory.collection_repository import MemoryCollectionRepository
from infra.persistence.memory.document_profile_repository import (
    MemoryDocumentProfileRepository,
)
from infra.persistence.memory.source_artifact_repository import (
    MemorySourceArtifactRepository,
)
from infra.persistence.memory.paper_map_repository import MemoryPaperMapRepository
from infra.persistence.memory.objective_repository import MemoryObjectiveRepository

__all__ = [
    "MemoryTaskRepository",
    "MemoryCollectionRepository",
    "MemoryDocumentProfileRepository",
    "MemorySourceArtifactRepository",
    "MemoryPaperMapRepository",
    "MemoryObjectiveRepository",
]
