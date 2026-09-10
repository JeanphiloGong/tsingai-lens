from pathlib import Path

from application.source.collection_service import CollectionService
from application.source.source_import_service import SourceImportService
from infra.persistence.file import FileCollectionWorkspace
from infra.persistence.memory import MemoryCollectionRepository


def build_test_collection_service(root_dir: Path) -> CollectionService:
    return CollectionService(
        repository=MemoryCollectionRepository(),
        workspace=FileCollectionWorkspace(root_dir),
    )


def build_test_source_import_service(
    collection_service: CollectionService,
) -> SourceImportService:
    return SourceImportService(
        repository=collection_service.repository,
        object_store=collection_service.object_store,
    )
