from pathlib import Path

from application.source.collection_service import CollectionService
from infra.persistence.file import FileCollectionRepository


def build_test_collection_service(root_dir: Path) -> CollectionService:
    return CollectionService(repository=FileCollectionRepository(root_dir))
