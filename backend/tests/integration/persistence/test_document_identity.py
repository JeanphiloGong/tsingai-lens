from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from domain.source import (
    CollectionFileRecord,
    CollectionImportDocumentRecord,
    CollectionImportRecord,
    CollectionRecord,
)
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from infra.persistence.postgres.models.collection import CollectionFile, StoredObject

pytestmark = pytest.mark.anyio


@pytest.fixture
async def document_repository(postgres_session_factory):
    sessions = postgres_session_factory
    auth = PostgresAuthRepository(sessions)
    await auth.add_user(
        {
            "user_id": "user_documents",
            "email": "documents@example.com",
            "display_name": None,
            "password_hash": "synthetic-password-hash",
            "created_at": "2026-07-19T09:00:00+00:00",
        }
    )
    return PostgresCollectionRepository(sessions)


def _collection(collection_id: str) -> CollectionRecord:
    return CollectionRecord(
        collection_id=collection_id,
        owner_user_id="user_documents",
        name=collection_id,
        description=None,
        status="idle",
        paper_count=0,
        created_at="2026-07-19T09:00:00+00:00",
        updated_at="2026-07-19T09:00:00+00:00",
    )


def _import(
    collection_id: str,
    suffix: str,
    *,
    digest: str,
) -> CollectionImportRecord:
    created_at = "2026-07-19T09:01:00+00:00"
    file_record = CollectionFileRecord(
        file_id=f"file_{suffix}",
        collection_id=collection_id,
        object_id=f"obj_{suffix}",
        object_kind="source_input",
        original_filename=f"{suffix}.pdf",
        stored_filename=f"stored-{suffix}.pdf",
        storage_key=f"{collection_id}/input/stored-{suffix}.pdf",
        sha256=digest,
        media_type="application/pdf",
        status="stored",
        size_bytes=42,
        created_at=created_at,
    )
    return CollectionImportRecord(
        import_id=f"imp_{suffix}",
        collection_id=collection_id,
        channel="upload",
        adapter_name="upload",
        adapter_version=None,
        raw_locator=file_record.original_filename,
        goal_context=None,
        warnings=(),
        ingested_at=created_at,
        documents=(
            CollectionImportDocumentRecord(
                source_document_id=f"srcdoc_{suffix}",
                origin_channel="upload",
                file=file_record,
                language=None,
                ingest_status="normalized",
                text_units=(),
            ),
        ),
    )


async def test_identical_content_reuses_version_across_collections(
    document_repository,
) -> None:
    digest = "a" * 64
    for collection_id in ("col_first", "col_second"):
        await document_repository.add_collection(_collection(collection_id))
    await document_repository.add_collection_import(
        _import("col_first", "first", digest=digest),
        updated_at="2026-07-19T09:01:00+00:00",
    )
    await document_repository.add_collection_import(
        _import("col_second", "second", digest=digest),
        updated_at="2026-07-19T09:02:00+00:00",
    )

    first = await document_repository.list_collection_documents("col_first")
    second = await document_repository.list_collection_documents("col_second")

    assert len(first) == len(second) == 1
    assert first[0].document_id == second[0].document_id
    assert first[0].document_version_id == second[0].document_version_id
    assert first[0].collection_document_id != second[0].collection_document_id
    assert await document_repository.read_document(first[0].document_id) is not None
    assert (
        (
            await document_repository.read_document_version(
                first[0].document_version_id
            )
        ).sha256
        == digest
    )
    assert (await document_repository.list_collection_files("col_first"))[
        0
    ].storage_key != (
        await document_repository.list_collection_files("col_second")
    )[0].storage_key


async def test_duplicate_content_in_one_collection_reuses_membership_and_count(
    document_repository,
) -> None:
    collection_id = "col_duplicate_content"
    digest = "b" * 64
    await document_repository.add_collection(_collection(collection_id))

    for suffix in ("duplicate_one", "duplicate_two"):
        await document_repository.add_collection_import(
            _import(collection_id, suffix, digest=digest),
            updated_at="2026-07-19T09:02:00+00:00",
        )

    assert len(await document_repository.list_collection_files(collection_id)) == 2
    assert len(await document_repository.list_collection_imports(collection_id)) == 2
    assert len(await document_repository.list_collection_documents(collection_id)) == 1
    assert (await document_repository.read_collection(collection_id)).paper_count == 1


async def test_collection_delete_preserves_shared_identity_until_last_membership(
    document_repository,
) -> None:
    digest = "c" * 64
    for collection_id in ("col_keep_first", "col_keep_second"):
        await document_repository.add_collection(_collection(collection_id))
        await document_repository.add_collection_import(
            _import(collection_id, collection_id, digest=digest),
            updated_at="2026-07-19T09:02:00+00:00",
        )
    membership = (await document_repository.list_collection_documents(
        "col_keep_first"
    ))[0]

    assert await document_repository.delete_collection("col_keep_first") is True
    assert await document_repository.read_document(membership.document_id) is not None
    assert (
        await document_repository.read_document_version(membership.document_version_id)
        is not None
    )
    assert len(
        await document_repository.list_collection_documents("col_keep_second")
    ) == 1
    assert len(await document_repository.list_collection_files("col_keep_second")) == 1

    assert await document_repository.delete_collection("col_keep_second") is True
    assert await document_repository.read_document(membership.document_id) is None
    assert (
        await document_repository.read_document_version(membership.document_version_id)
        is None
    )


async def test_postgresql_enforces_document_membership_contract(
    document_repository,
) -> None:
    repository = document_repository
    sessions = repository.session_factory
    now = datetime(2026, 7, 19, 9, tzinfo=timezone.utc).isoformat()
    for collection_id in ("col_contract_a", "col_contract_b"):
        await repository.add_collection(_collection(collection_id))
    await repository.add_collection_import(
        _import("col_contract_a", "contract", digest="d" * 64),
        updated_at=now,
    )
    membership = (await repository.list_collection_documents("col_contract_a"))[0]
    with pytest.raises(IntegrityError):
        async with sessions.begin() as session:
            session.add(
                StoredObject(
                    object_id="obj_foreign_membership",
                    object_kind="source_input",
                    storage_key="col_contract_b/input/foreign.pdf",
                    sha256="e" * 64,
                    size_bytes=1,
                    media_type="application/pdf",
                    document_version_id=membership.document_version_id,
                    created_at=datetime.fromisoformat(now),
                )
            )
            await session.flush()
            session.add(
                CollectionFile(
                    file_id="file_foreign_membership",
                    collection_id="col_contract_b",
                    object_id="obj_foreign_membership",
                    collection_document_id=membership.collection_document_id,
                    original_filename="foreign.pdf",
                    stored_filename="foreign.pdf",
                    status="stored",
                    document_id=None,
                    file_order=0,
                    created_at=datetime.fromisoformat(now),
                )
            )
