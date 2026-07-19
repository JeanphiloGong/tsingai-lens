from __future__ import annotations

from dataclasses import replace

from domain.source import (
    CollectionFileRecord,
    CollectionHandoffRecord,
    CollectionImportRecord,
    CollectionRecord,
)


class MemoryCollectionRepository:
    """In-memory collection metadata for isolated tests."""

    def __init__(self) -> None:
        self._collections: dict[str, CollectionRecord] = {}
        self._files: dict[str, list[CollectionFileRecord]] = {}
        self._imports: dict[str, list[CollectionImportRecord]] = {}
        self._handoffs: dict[str, list[CollectionHandoffRecord]] = {}

    def add_collection(self, record: CollectionRecord) -> None:
        if record.collection_id in self._collections:
            raise ValueError(f"collection already exists: {record.collection_id}")
        self._collections[record.collection_id] = record

    def list_collections(
        self,
        owner_user_id: str | None = None,
    ) -> tuple[CollectionRecord, ...]:
        return tuple(
            record
            for _, record in sorted(self._collections.items())
            if owner_user_id is None or record.owner_user_id == owner_user_id
        )

    def read_collection(self, collection_id: str) -> CollectionRecord | None:
        return self._collections.get(collection_id)

    def update_collection(self, record: CollectionRecord) -> bool:
        if record.collection_id not in self._collections:
            return False
        self._collections[record.collection_id] = record
        return True

    def add_collection_import(
        self,
        record: CollectionImportRecord,
        *,
        updated_at: str,
    ) -> None:
        collection = self._collections.get(record.collection_id)
        if collection is None:
            raise FileNotFoundError(f"collection not found: {record.collection_id}")
        if not record.documents:
            raise ValueError("collection import must include at least one document")
        if any(
            document.file.collection_id != record.collection_id
            for document in record.documents
        ):
            raise ValueError("collection import file belongs to another collection")

        files = self._files.setdefault(record.collection_id, [])
        imports = self._imports.setdefault(record.collection_id, [])
        incoming_files = [document.file for document in record.documents]
        existing_file_ids = {item.file_id for item in files}
        existing_object_ids = {item.object_id for item in files}
        existing_storage_keys = {item.storage_key for item in files}
        if any(item.file_id in existing_file_ids for item in incoming_files):
            raise ValueError("collection file already exists")
        if any(item.object_id in existing_object_ids for item in incoming_files):
            raise ValueError("stored object already exists")
        if any(item.storage_key in existing_storage_keys for item in incoming_files):
            raise ValueError("storage key already exists")
        if any(item.import_id == record.import_id for item in imports):
            raise ValueError("collection import already exists")

        files.extend(incoming_files)
        imports.append(record)
        self._collections[record.collection_id] = replace(
            collection,
            status="ready",
            paper_count=len(files),
            updated_at=updated_at,
        )

    def list_collection_files(
        self,
        collection_id: str,
    ) -> tuple[CollectionFileRecord, ...]:
        return tuple(self._files.get(collection_id, ()))

    def list_collection_imports(
        self,
        collection_id: str,
    ) -> tuple[CollectionImportRecord, ...]:
        return tuple(self._imports.get(collection_id, ()))

    def add_collection_handoff(self, record: CollectionHandoffRecord) -> None:
        if record.collection_id not in self._collections:
            raise FileNotFoundError(f"collection not found: {record.collection_id}")
        handoffs = self._handoffs.setdefault(record.collection_id, [])
        if any(item.handoff_id == record.handoff_id for item in handoffs):
            raise ValueError("collection handoff already exists")
        handoffs.append(record)

    def list_collection_handoffs(
        self,
        collection_id: str,
    ) -> tuple[CollectionHandoffRecord, ...]:
        return tuple(self._handoffs.get(collection_id, ()))

    def delete_collection(self, collection_id: str) -> bool:
        if self._collections.pop(collection_id, None) is None:
            return False
        self._files.pop(collection_id, None)
        self._imports.pop(collection_id, None)
        self._handoffs.pop(collection_id, None)
        return True
