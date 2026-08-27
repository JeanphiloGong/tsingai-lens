from __future__ import annotations

from dataclasses import replace

from domain.source import Collection, Document


class MemoryCollectionRepository:
    """In-memory persistence for collections and their current documents."""

    def __init__(self) -> None:
        self._collections: dict[str, Collection] = {}

    async def add_collection(self, collection: Collection) -> None:
        if collection.collection_id in self._collections:
            raise ValueError(
                f"collection already exists: {collection.collection_id}"
            )
        self._collections[collection.collection_id] = collection

    async def list_collections(
        self,
        owner_user_id: str | None = None,
    ) -> tuple[Collection, ...]:
        return tuple(
            collection
            for _, collection in sorted(self._collections.items())
            if owner_user_id is None
            or collection.owner_user_id == owner_user_id
        )

    async def read_collection(self, collection_id: str) -> Collection | None:
        return self._collections.get(collection_id)

    async def read_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> Document | None:
        collection = self._collections.get(collection_id)
        if collection is None:
            return None
        return next(
            (
                document
                for document in collection.documents
                if document.document_id == document_id
            ),
            None,
        )

    async def update_collection(self, collection: Collection) -> bool:
        if collection.collection_id not in self._collections:
            return False
        self._collections[collection.collection_id] = collection
        return True

    async def add_documents(
        self,
        collection_id: str,
        documents: tuple[Document, ...],
        *,
        updated_at: str,
    ) -> None:
        collection = self._collections.get(collection_id)
        if collection is None:
            raise FileNotFoundError(f"collection not found: {collection_id}")
        if not documents:
            raise ValueError("at least one document is required")

        existing_ids = {document.document_id for document in collection.documents}
        existing_hashes = {document.sha256 for document in collection.documents}
        if any(document.document_id in existing_ids for document in documents):
            raise ValueError("document already exists")
        if any(document.sha256 in existing_hashes for document in documents):
            raise ValueError("document content already exists in collection")

        self._collections[collection_id] = replace(
            collection,
            status="uploaded",
            updated_at=updated_at,
            documents=collection.documents + documents,
        )

    async def update_document(self, document: Document) -> bool:
        for collection_id, collection in self._collections.items():
            if not any(
                current.document_id == document.document_id
                for current in collection.documents
            ):
                continue
            self._collections[collection_id] = replace(
                collection,
                documents=tuple(
                    document
                    if current.document_id == document.document_id
                    else current
                    for current in collection.documents
                ),
                updated_at=document.updated_at or collection.updated_at,
            )
            return True
        return False

    async def delete_collection(self, collection_id: str) -> bool:
        return self._collections.pop(collection_id, None) is not None
