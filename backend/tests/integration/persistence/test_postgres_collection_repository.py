from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest
from sqlalchemy.exc import IntegrityError

from domain.source import (
    CollectionFileRecord,
    CollectionHandoffRecord,
    CollectionImportDocumentRecord,
    CollectionImportRecord,
    CollectionRecord,
)
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from infra.persistence.postgres.models.collection import StoredObject
from infra.persistence.postgres.models.build import CollectionBuild, Task
from infra.persistence.postgres.models.source import SourceDocument


pytestmark = pytest.mark.anyio


@pytest.fixture
async def collection_repository(postgres_session_factory):
    sessions = postgres_session_factory
    auth_repository = PostgresAuthRepository(sessions)
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
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

    return PostgresCollectionRepository(sessions)


def _collection(
    collection_id: str,
    owner_user_id: str = "user_a",
    *,
    paper_count: int = 0,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> CollectionRecord:
    created = created_at or datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc)
    updated = updated_at or created
    return CollectionRecord(
        collection_id=collection_id,
        owner_user_id=owner_user_id,
        name=f"Collection {collection_id}",
        description=None,
        status="idle",
        paper_count=paper_count,
        created_at=created.isoformat(),
        updated_at=updated.isoformat(),
    )


def _collection_import(
    collection_id: str,
    suffix: str,
    *,
    ingested_at: str,
) -> CollectionImportRecord:
    file_record = CollectionFileRecord(
        file_id=f"file_{suffix}",
        collection_id=collection_id,
        object_id=f"obj_{suffix}",
        object_kind="source_input",
        original_filename=f"{suffix}.pdf",
        stored_filename=f"stored-{suffix}.pdf",
        storage_key=f"{collection_id}/input/stored-{suffix}.pdf",
        sha256=sha256(suffix.encode("utf-8")).hexdigest(),
        media_type="application/pdf",
        status="stored",
        size_bytes=len(suffix),
        created_at=ingested_at,
    )
    return CollectionImportRecord(
        import_id=f"imp_{suffix}",
        collection_id=collection_id,
        channel="search",
        adapter_name="fixture",
        adapter_version="1.0",
        raw_locator=f"doi:{suffix}",
        goal_context={"intent": "compare", "suffix": suffix},
        warnings=(f"warning_{suffix}",),
        ingested_at=ingested_at,
        documents=(
            CollectionImportDocumentRecord(
                source_document_id=f"srcdoc_{suffix}",
                origin_channel="search",
                file=file_record,
                language="en",
                ingest_status="normalized",
                text_units=(
                    {
                        "text_unit_id": f"tu_{suffix}",
                        "sequence": 0,
                        "page_ref": "1",
                        "char_count": len(suffix),
                    },
                ),
            ),
        ),
    )


async def test_collection_repository_round_trips_and_orders_owner_records(
    collection_repository,
) -> None:
    await collection_repository.add_collection(_collection("col_z"))
    await collection_repository.add_collection(_collection("col_a"))
    await collection_repository.add_collection(_collection("col_b", "user_b"))

    assert await collection_repository.read_collection("col_z") == _collection("col_z")
    assert [
        record.collection_id
        for record in await collection_repository.list_collections("user_a")
    ] == ["col_a", "col_z"]
    assert [
        record.collection_id for record in await collection_repository.list_collections()
    ] == ["col_a", "col_b", "col_z"]


async def test_collection_repository_updates_and_deletes_existing_record(
    collection_repository,
) -> None:
    record = _collection("col_update")
    await collection_repository.add_collection(record)
    updated = CollectionRecord(
        **{
            **record.to_record(),
            "name": "Updated collection",
            "status": "completed",
            "paper_count": 2,
            "updated_at": "2026-07-19T09:00:00+00:00",
        }
    )

    assert await collection_repository.update_collection(updated) is True
    assert await collection_repository.read_collection("col_update") == updated
    assert await collection_repository.delete_collection("col_update") is True
    assert await collection_repository.read_collection("col_update") is None
    assert await collection_repository.update_collection(updated) is False
    assert await collection_repository.delete_collection("col_update") is False


async def test_collection_delete_removes_build_source_documents_before_memberships(
    collection_repository,
) -> None:
    collection_id = "col_delete_built_source"
    await collection_repository.add_collection(_collection(collection_id))
    import_record = _collection_import(
        collection_id,
        "built-source",
        ingested_at="2026-07-19T08:01:00+00:00",
    )
    await collection_repository.add_collection_import(
        import_record,
        updated_at="2026-07-19T08:01:00+00:00",
    )
    membership = (await collection_repository.list_collection_documents(collection_id))[0]
    created_at = datetime(2026, 7, 19, 8, 2, tzinfo=timezone.utc)
    async with collection_repository.session_factory.begin() as session:
        session.add(
            Task(
                task_id="task_delete_built_source",
                collection_id=collection_id,
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
                collection_id=collection_id,
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
                collection_id=collection_id,
                collection_document_id=membership.collection_document_id,
                document_version_id=membership.document_version_id,
                document_order=0,
                title="Built source",
                text="source text",
                creation_date=None,
                metadata_json={},
            )
        )

    assert await collection_repository.delete_collection(collection_id) is True
    async with collection_repository.session_factory() as session:
        assert await session.get(CollectionBuild, "build_delete_built_source") is None
        assert await session.get(
            SourceDocument,
            ("build_delete_built_source", "source_delete_built_source"),
        ) is None


@pytest.mark.parametrize(
    "record",
    [
        _collection("col_orphan", "user_missing"),
        _collection("col_negative", paper_count=-1),
        _collection(
            "col_time",
            created_at=datetime(2026, 7, 19, 9, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc),
        ),
    ],
)
async def test_collection_repository_rejects_invalid_relational_records(
    collection_repository,
    record: CollectionRecord,
) -> None:
    with pytest.raises(IntegrityError):
        await collection_repository.add_collection(record)


async def test_collection_repository_rejects_duplicate_identity(
    collection_repository,
) -> None:
    record = _collection("col_duplicate")
    await collection_repository.add_collection(record)

    with pytest.raises(IntegrityError):
        await collection_repository.add_collection(record)


async def test_collection_repository_round_trips_ordered_file_provenance_and_handoffs(
    collection_repository,
) -> None:
    collection_id = "col_provenance"
    await collection_repository.add_collection(_collection(collection_id))
    second = _collection_import(
        collection_id,
        "second",
        ingested_at="2026-07-19T08:02:00+00:00",
    )
    first = _collection_import(
        collection_id,
        "first",
        ingested_at="2026-07-19T08:01:00+00:00",
    )
    later_handoff = CollectionHandoffRecord(
        handoff_id="handoff_z",
        collection_id=collection_id,
        kind="goal_brief",
        status="awaiting_source_material",
        created_at="2026-07-19T08:04:00+00:00",
        source_channels=("upload", "search"),
        goal_context={"research_brief": {"intent": "compare"}},
    )
    earlier_handoff = CollectionHandoffRecord(
        handoff_id="handoff_a",
        collection_id=collection_id,
        kind="goal_brief",
        status="awaiting_source_material",
        created_at="2026-07-19T08:03:00+00:00",
        source_channels=("upload",),
        goal_context={"research_brief": {"intent": "review"}},
    )

    await collection_repository.add_collection_import(
        second,
        updated_at="2026-07-19T08:02:00+00:00",
    )
    await collection_repository.add_collection_import(
        first,
        updated_at="2026-07-19T08:03:00+00:00",
    )
    await collection_repository.add_collection_handoff(later_handoff)
    await collection_repository.add_collection_handoff(earlier_handoff)

    assert await collection_repository.list_collection_files(collection_id) == (
        second.documents[0].file,
        first.documents[0].file,
    )
    assert await collection_repository.list_collection_imports(collection_id) == (
        second,
        first,
    )
    assert await collection_repository.list_collection_handoffs(collection_id) == (
        later_handoff,
        earlier_handoff,
    )
    stored_collection = await collection_repository.read_collection(collection_id)
    assert stored_collection is not None
    assert stored_collection.paper_count == 2
    assert stored_collection.status == "ready"
    assert stored_collection.updated_at == "2026-07-19T08:03:00+00:00"


async def test_collection_import_rolls_back_all_state_for_invalid_object_integrity(
    collection_repository,
) -> None:
    collection_id = "col_invalid_object"
    original_collection = _collection(collection_id)
    await collection_repository.add_collection(original_collection)
    import_record = _collection_import(
        collection_id,
        "invalid",
        ingested_at="2026-07-19T08:01:00+00:00",
    )
    invalid_file = replace(import_record.documents[0].file, sha256="A" * 64)
    invalid_import = replace(
        import_record,
        documents=(replace(import_record.documents[0], file=invalid_file),),
    )

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        await collection_repository.add_collection_import(
            invalid_import,
            updated_at="2026-07-19T08:02:00+00:00",
        )

    assert await collection_repository.list_collection_files(collection_id) == ()
    assert await collection_repository.list_collection_imports(collection_id) == ()
    assert await collection_repository.read_collection(collection_id) == original_collection


async def test_collection_delete_removes_file_provenance_and_object_metadata(
    collection_repository,
) -> None:
    collection_id = "col_delete_provenance"
    await collection_repository.add_collection(_collection(collection_id))
    import_record = _collection_import(
        collection_id,
        "delete",
        ingested_at="2026-07-19T08:01:00+00:00",
    )
    handoff = CollectionHandoffRecord(
        handoff_id="handoff_delete",
        collection_id=collection_id,
        kind="goal_brief",
        status="awaiting_source_material",
        created_at="2026-07-19T08:02:00+00:00",
        source_channels=("upload",),
        goal_context={"research_brief": {"intent": "compare"}},
    )
    await collection_repository.add_collection_import(
        import_record,
        updated_at="2026-07-19T08:01:00+00:00",
    )
    await collection_repository.add_collection_handoff(handoff)

    assert await collection_repository.delete_collection(collection_id) is True

    assert await collection_repository.read_collection(collection_id) is None
    assert await collection_repository.list_collection_files(collection_id) == ()
    assert await collection_repository.list_collection_imports(collection_id) == ()
    assert await collection_repository.list_collection_handoffs(collection_id) == ()
    async with collection_repository.session_factory() as session:
        assert (
            await session.get(StoredObject, import_record.documents[0].file.object_id)
            is None
        )


async def test_postgresql_enforces_collection_contract(
    collection_repository,
) -> None:
    sessions = collection_repository.session_factory
    auth_repository = PostgresAuthRepository(sessions)
    repository = collection_repository
    now = datetime(2026, 7, 19, 9, tzinfo=timezone.utc)
    await auth_repository.add_user(
        {
            "user_id": "user_constraints",
            "email": "collection-constraints@example.com",
            "display_name": None,
            "password_hash": "synthetic-password-hash",
            "created_at": now.isoformat(),
        }
    )
    await repository.add_collection(_collection("col_constraints", "user_constraints"))

    with pytest.raises(IntegrityError):
        await repository.add_collection(_collection("col_orphan_pg", "user_missing"))
    with pytest.raises(IntegrityError):
        await repository.add_collection(
            _collection("col_negative_pg", "user_constraints", paper_count=-1)
        )
    with pytest.raises(IntegrityError):
        await repository.add_collection(
            _collection(
                "col_time_pg",
                "user_constraints",
                created_at=now,
                updated_at=now - timedelta(seconds=1),
            )
        )

    import_record = _collection_import(
        "col_constraints",
        "postgres",
        ingested_at=now.isoformat(),
    )
    await repository.add_collection_import(
        import_record,
        updated_at=now.isoformat(),
    )
    assert await repository.list_collection_imports("col_constraints") == (
        import_record,
    )

    invalid_import = _collection_import(
        "col_constraints",
        "invalid-postgres",
        ingested_at=now.isoformat(),
    )
    invalid_file = replace(
        invalid_import.documents[0].file,
        sha256="A" * 64,
    )
    invalid_import = replace(
        invalid_import,
        documents=(replace(invalid_import.documents[0], file=invalid_file),),
    )
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        await repository.add_collection_import(
            invalid_import,
            updated_at=now.isoformat(),
        )
