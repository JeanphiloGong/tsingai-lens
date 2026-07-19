from pathlib import Path

from application.source.collection_service import CollectionService
from infra.persistence.file import FileCollectionWorkspace
from infra.persistence.memory import MemoryCollectionRepository


def build_test_collection_service(root_dir: Path) -> CollectionService:
    return CollectionService(
        repository=MemoryCollectionRepository(),
        workspace=FileCollectionWorkspace(root_dir),
    )
