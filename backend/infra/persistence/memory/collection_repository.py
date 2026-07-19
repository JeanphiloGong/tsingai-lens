from __future__ import annotations

from domain.source import CollectionRecord


class MemoryCollectionRepository:
    """In-memory collection metadata for isolated tests."""

    def __init__(self) -> None:
        self._collections: dict[str, CollectionRecord] = {}

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

    def delete_collection(self, collection_id: str) -> bool:
        return self._collections.pop(collection_id, None) is not None
