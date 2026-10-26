"""Test doubles for isolated application-service tests; never runtime stores."""

from tests.support.repositories.collection_repository import MemoryCollectionRepository
from tests.support.repositories.document_profile_repository import (
    MemoryDocumentProfileRepository,
)
from tests.support.repositories.objective_repository import MemoryObjectiveRepository
from tests.support.repositories.paper_map_repository import MemoryPaperMapRepository
from tests.support.repositories.pipeline_run_repository import (
    MemoryPipelineRunRepository,
)
from tests.support.repositories.source_artifact_repository import (
    MemorySourceArtifactRepository,
)

__all__ = [
    "MemoryPipelineRunRepository",
    "MemoryCollectionRepository",
    "MemoryDocumentProfileRepository",
    "MemorySourceArtifactRepository",
    "MemoryPaperMapRepository",
    "MemoryObjectiveRepository",
]
