from __future__ import annotations

from dataclasses import replace

import pytest

from application.repositories.collection_repository import (
    StoredCollection,
    StoredDocument,
)
from domain.source import Collection, Document
from infra.persistence.memory import MemoryCollectionRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _collection(collection_id: str = "col_demo") -> StoredCollection:
    return StoredCollection(
        collection=Collection(
            collection_id=collection_id,
            owner_user_id="user_demo",
            name="Demo",
            description=None,
            status="idle",
        ),
        created_at="2026-08-27T00:00:00+00:00",
        updated_at="2026-08-27T00:00:00+00:00",
    )


def _document(document_id: str = "doc_demo", sha256: str = "a" * 64) -> StoredDocument:
    return StoredDocument(
        document=Document(
            document_id=document_id,
            original_filename="paper.pdf",
            sha256=sha256,
            media_type="application/pdf",
            status="stored",
            size_bytes=10,
        ),
        stored_filename=f"{document_id}.pdf",
        storage_key=f"col_demo/input/{document_id}.pdf",
        created_at="2026-08-27T00:01:00+00:00",
    )


async def test_memory_collection_repository_round_trips_current_aggregate() -> None:
    repository = MemoryCollectionRepository()
    collection = _collection()
    document = _document()

    await repository.add_collection(collection)
    await repository.add_documents(
        collection.collection.collection_id,
        (document,),
        updated_at=document.created_at,
    )

    stored = await repository.read_collection(collection.collection.collection_id)
    assert stored == replace(
        collection,
        collection=replace(collection.collection, status="uploaded"),
        updated_at=document.created_at,
        documents=(document,),
    )
    summary, = await repository.list_collections("user_demo")
    assert summary.collection_id == stored.collection.collection_id
    assert summary.documents[0].document_id == document.document.document_id
    assert not hasattr(summary.documents[0], "storage_key")
    assert await repository.list_collections("user_other") == ()


async def test_memory_collection_repository_rejects_duplicate_document_content() -> None:
    repository = MemoryCollectionRepository()
    collection = _collection()
    document = _document()
    await repository.add_collection(collection)
    await repository.add_documents(
        collection.collection.collection_id,
        (document,),
        updated_at=document.created_at,
    )

    with pytest.raises(ValueError, match="content already exists"):
        await repository.add_documents(
            collection.collection.collection_id,
            (_document("doc_other"),),
            updated_at=document.created_at,
        )

    assert (
        await repository.read_collection(collection.collection.collection_id)
    ).documents == (document,)


async def test_memory_collection_delete_removes_aggregate() -> None:
    repository = MemoryCollectionRepository()
    collection = _collection()
    await repository.add_collection(collection)

    assert (
        await repository.delete_collection(collection.collection.collection_id) is True
    )
    assert await repository.read_collection(collection.collection.collection_id) is None
    assert (
        await repository.delete_collection(collection.collection.collection_id) is False
    )
