from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256

import pytest
from sqlalchemy.exc import IntegrityError

from domain.source import Collection, Document
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.collection_repository import PostgresCollectionRepository
from infra.persistence.postgres.models.document import Document as DocumentRow


pytestmark = pytest.mark.anyio


@pytest.fixture
async def collection_repository(postgres_session_factory):
    auth_repository = PostgresAuthRepository(postgres_session_factory)
    now = datetime(2026, 8, 27, tzinfo=timezone.utc)
    for user_id in ("user_a", "user_b"):
        await auth_repository.add_user(
            {
                "user_id": user_id,
                "email": f"{user_id}@example.com",
                "display_name": None,
                "password_hash": "synthetic-password-hash",
                "created_at": now.isoformat(),
            }
        )
    return PostgresCollectionRepository(postgres_session_factory)


def _collection(collection_id: str, owner_user_id: str = "user_a") -> Collection:
    return Collection.create(
        collection_id=collection_id,
        owner_user_id=owner_user_id,
        name=f"Collection {collection_id}",
        description=None,
        now_iso="2026-08-27T00:00:00+00:00",
    )


def _document(collection_id: str, suffix: str) -> Document:
    digest = sha256(suffix.encode("utf-8")).hexdigest()
    return Document(
        document_id=f"doc_{suffix}",
        original_filename=f"{suffix}.pdf",
        stored_filename=f"stored-{suffix}.pdf",
        storage_key=f"{collection_id}/input/stored-{suffix}.pdf",
        sha256=digest,
        media_type="application/pdf",
        status="stored",
        size_bytes=len(suffix),
        created_at="2026-08-27T00:01:00+00:00",
        updated_at="2026-08-27T00:01:00+00:00",
    )


async def test_collection_repository_round_trips_current_documents_by_owner(
    collection_repository,
) -> None:
    first = _collection("col_z")
    second = _collection("col_a")
    other = _collection("col_b", "user_b")
    await collection_repository.add_collection(first)
    await collection_repository.add_collection(second)
    await collection_repository.add_collection(other)
    document = _document(first.collection_id, "first")
    await collection_repository.add_documents(
        first.collection_id,
        (document,),
        updated_at=document.created_at,
    )

    stored = await collection_repository.read_collection(first.collection_id)
    assert stored == replace(
        first,
        status="uploaded",
        updated_at=document.created_at,
        documents=(document,),
    )
    assert [
        item.collection_id
        for item in await collection_repository.list_collections("user_a")
    ] == ["col_z", "col_a"]
    assert (await collection_repository.read_collection(second.collection_id)).documents == ()


async def test_collection_repository_updates_metadata_without_losing_documents(
    collection_repository,
) -> None:
    collection = _collection("col_update")
    document = _document(collection.collection_id, "paper")
    await collection_repository.add_collection(collection)
    await collection_repository.add_documents(
        collection.collection_id,
        (document,),
        updated_at=document.created_at,
    )
    stored = await collection_repository.read_collection(collection.collection_id)
    updated = replace(
        stored,
        name="Updated collection",
        status="running",
        updated_at="2026-08-27T00:02:00+00:00",
    )

    assert await collection_repository.update_collection(updated) is True
    assert await collection_repository.read_collection(collection.collection_id) == updated


async def test_collection_repository_rejects_duplicate_document_content(
    collection_repository,
) -> None:
    collection = _collection("col_duplicate_content")
    first = _document(collection.collection_id, "same")
    second = replace(
        first,
        document_id="doc_other",
        stored_filename="other.pdf",
        storage_key=f"{collection.collection_id}/input/other.pdf",
    )
    await collection_repository.add_collection(collection)
    await collection_repository.add_documents(
        collection.collection_id,
        (first,),
        updated_at=first.created_at,
    )

    with pytest.raises(
        ValueError,
        match="document content already exists in collection",
    ):
        await collection_repository.add_documents(
            collection.collection_id,
            (second,),
            updated_at=second.created_at,
        )

    assert (await collection_repository.read_collection(collection.collection_id)).documents == (
        first,
    )


async def test_collection_delete_removes_its_current_documents(
    collection_repository,
) -> None:
    collection = _collection("col_delete_documents")
    document = _document(collection.collection_id, "paper")
    await collection_repository.add_collection(collection)
    await collection_repository.add_documents(
        collection.collection_id,
        (document,),
        updated_at=document.created_at,
    )
    assert await collection_repository.delete_collection(collection.collection_id) is True
    assert await collection_repository.read_collection(collection.collection_id) is None
    async with collection_repository.session_factory() as session:
        assert await session.get(DocumentRow, document.document_id) is None


async def test_collection_repository_rejects_unknown_owner(collection_repository) -> None:
    with pytest.raises(IntegrityError):
        await collection_repository.add_collection(
            _collection("col_unknown_owner", "missing_user")
        )
