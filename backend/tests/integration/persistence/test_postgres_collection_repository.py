from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from domain.source import Collection, Document
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.collection_repository import PostgresCollectionRepository
from infra.persistence.postgres.models.build import CollectionBuild, Task
from infra.persistence.postgres.models.collection import CollectionFile, StoredObject
from infra.persistence.postgres.models.document import CollectionDocument
from infra.persistence.postgres.models.source import SourceDocument


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
        status="ready",
        updated_at=document.created_at,
        documents=(document,),
    )
    assert [
        item.collection_id
        for item in await collection_repository.list_collections("user_a")
    ] == ["col_a", "col_z"]
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


async def test_collection_delete_removes_build_source_before_private_membership(
    collection_repository,
) -> None:
    collection = _collection("col_delete_built_source")
    document = _document(collection.collection_id, "built")
    await collection_repository.add_collection(collection)
    await collection_repository.add_documents(
        collection.collection_id,
        (document,),
        updated_at=document.created_at,
    )
    async with collection_repository.session_factory() as session:
        membership = (
            await session.execute(
                select(CollectionDocument)
                .join(
                    CollectionFile,
                    CollectionFile.collection_document_id
                    == CollectionDocument.collection_document_id,
                )
                .where(CollectionFile.file_id == document.document_id)
            )
        ).scalar_one()

    created_at = datetime(2026, 8, 27, 0, 2, tzinfo=timezone.utc)
    async with collection_repository.session_factory.begin() as session:
        session.add(
            Task(
                task_id="task_delete_built_source",
                collection_id=collection.collection_id,
                task_type="build",
                status="completed",
                current_stage="artifacts_ready",
                progress_percent=100,
                progress_detail=None,
                output_path=None,
                errors=[],
                warnings=[],
                details={},
                created_at=created_at,
                updated_at=created_at,
                started_at=created_at,
                finished_at=created_at,
            )
        )
        await session.flush()
        session.add(
            CollectionBuild(
                build_id="build_delete_built_source",
                task_id="task_delete_built_source",
                collection_id=collection.collection_id,
                mode="standard",
                build_number=1,
                status="succeeded",
                created_at=created_at,
                started_at=created_at,
                finished_at=created_at,
            )
        )
        session.add(
            SourceDocument(
                build_id="build_delete_built_source",
                source_document_id="source_delete_built_source",
                collection_id=collection.collection_id,
                collection_document_id=membership.collection_document_id,
                document_version_id=membership.document_version_id,
                document_order=0,
                title="Built source",
                text="source text",
                creation_date=None,
                metadata_json={},
            )
        )

    assert await collection_repository.delete_collection(collection.collection_id) is True
    assert await collection_repository.read_collection(collection.collection_id) is None
    async with collection_repository.session_factory() as session:
        assert await session.get(CollectionBuild, "build_delete_built_source") is None
        assert await session.get(
            SourceDocument,
            ("build_delete_built_source", "source_delete_built_source"),
        ) is None
        assert (
            await session.scalar(
                select(StoredObject).where(StoredObject.storage_key == document.storage_key)
            )
            is None
        )


async def test_collection_repository_rejects_unknown_owner(collection_repository) -> None:
    with pytest.raises(IntegrityError):
        await collection_repository.add_collection(
            _collection("col_unknown_owner", "missing_user")
        )
