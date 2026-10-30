from pathlib import Path
from types import ModuleType

from application.source import collection_service, source_import_service
from infra.persistence.file import FileCollectionWorkspace
from infra.persistence.file.object_store import FileObjectStore
from repositories.collection_repository import CollectionRepository


def build_test_collection_service(root_dir: Path) -> ModuleType:
    collection_service.CollectionRepo = CollectionRepository()
    collection_service.workspace = FileCollectionWorkspace(root_dir)
    collection_service.root_dir = collection_service.workspace.root_dir
    collection_service.object_store = FileObjectStore(collection_service.root_dir)
    return collection_service


def build_test_source_import_service(
    collection_service: ModuleType,
) -> ModuleType:
    source_import_service.CollectionRepo = collection_service.CollectionRepo
    source_import_service.collection_service.object_store = (
        collection_service.object_store
    )
    return source_import_service
