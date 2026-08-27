from __future__ import annotations

from dataclasses import replace

import pytest

from domain.source import Collection, Document
from infra.persistence.memory import MemoryBuildRepository, MemoryCollectionRepository


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _collection(collection_id: str = "col_demo") -> Collection:
    return Collection.create(
        collection_id=collection_id,
        owner_user_id="user_demo",
        name="Demo",
        description=None,
        now_iso="2026-08-27T00:00:00+00:00",
    )


def _document(document_id: str = "doc_demo", sha256: str = "a" * 64) -> Document:
    return Document(
        document_id=document_id,
        original_filename="paper.pdf",
        stored_filename=f"{document_id}.pdf",
        storage_key=f"col_demo/input/{document_id}.pdf",
        sha256=sha256,
        media_type="application/pdf",
        status="stored",
        size_bytes=10,
        created_at="2026-08-27T00:01:00+00:00",
    )


async def test_memory_collection_repository_round_trips_current_aggregate() -> None:
    repository = MemoryCollectionRepository()
    collection = _collection()
    document = _document()

    await repository.add_collection(collection)
    await repository.add_documents(
        collection.collection_id,
        (document,),
        updated_at=document.created_at,
    )

    stored = await repository.read_collection(collection.collection_id)
    assert stored == replace(
        collection,
        status="ready",
        updated_at=document.created_at,
        documents=(document,),
    )
    assert await repository.list_collections("user_demo") == (stored,)
    assert await repository.list_collections("user_other") == ()


async def test_memory_collection_repository_rejects_duplicate_document_content() -> None:
    repository = MemoryCollectionRepository()
    collection = _collection()
    document = _document()
    await repository.add_collection(collection)
    await repository.add_documents(
        collection.collection_id,
        (document,),
        updated_at=document.created_at,
    )

    with pytest.raises(ValueError, match="content already exists"):
        await repository.add_documents(
            collection.collection_id,
            (_document("doc_other"),),
            updated_at=document.created_at,
        )

    assert (await repository.read_collection(collection.collection_id)).documents == (
        document,
    )


async def test_memory_collection_delete_removes_aggregate() -> None:
    repository = MemoryCollectionRepository()
    collection = _collection()
    await repository.add_collection(collection)

    assert await repository.delete_collection(collection.collection_id) is True
    assert await repository.read_collection(collection.collection_id) is None
    assert await repository.delete_collection(collection.collection_id) is False


async def test_memory_build_repository_is_directly_injected_for_isolated_tests() -> None:
    repository = MemoryBuildRepository()

    assert await repository.list_tasks() == ()
    assert await repository.read_active_build("col_demo") is None
