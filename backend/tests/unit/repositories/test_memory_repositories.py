from __future__ import annotations

from dataclasses import replace

import pytest

from infra.persistence.memory import MemoryBuildRepository, MemoryCollectionRepository
from domain.source import (
    CollectionFileRecord,
    CollectionHandoffRecord,
    CollectionImportDocumentRecord,
    CollectionImportRecord,
    CollectionRecord,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_memory_collection_repository_round_trips_records_by_owner():
    repository = MemoryCollectionRepository()
    record = CollectionRecord(
        collection_id="col_demo",
        owner_user_id="user_demo",
        name="Demo",
        description=None,
        status="idle",
        paper_count=0,
        created_at="2026-07-19T00:00:00+00:00",
        updated_at="2026-07-19T00:00:00+00:00",
    )

    await repository.add_collection(record)

    assert await repository.read_collection(record.collection_id) == record
    assert await repository.list_collections("user_demo") == (record,)
    assert await repository.list_collections("user_other") == ()


async def test_memory_collection_repository_keeps_file_provenance_in_one_aggregate():
    repository = MemoryCollectionRepository()
    collection = CollectionRecord(
        collection_id="col_demo",
        owner_user_id="user_demo",
        name="Demo",
        description=None,
        status="idle",
        paper_count=0,
        created_at="2026-07-19T00:00:00+00:00",
        updated_at="2026-07-19T00:00:00+00:00",
    )
    file_record = CollectionFileRecord(
        file_id="file_demo",
        collection_id="col_demo",
        object_id="obj_demo",
        object_kind="source_input",
        original_filename="paper.pdf",
        stored_filename="stored-paper.pdf",
        storage_key="col_demo/input/stored-paper.pdf",
        sha256="a" * 64,
        media_type="application/pdf",
        status="stored",
        size_bytes=10,
        created_at="2026-07-19T00:01:00+00:00",
    )
    import_record = CollectionImportRecord(
        import_id="imp_demo",
        collection_id="col_demo",
        channel="upload",
        adapter_name="upload",
        adapter_version=None,
        raw_locator="paper.pdf",
        goal_context=None,
        warnings=(),
        ingested_at="2026-07-19T00:01:00+00:00",
        documents=(
            CollectionImportDocumentRecord(
                source_document_id="srcdoc_demo",
                origin_channel="upload",
                file=file_record,
                language=None,
                ingest_status="normalized",
                text_units=(),
            ),
        ),
    )
    handoff = CollectionHandoffRecord(
        handoff_id="handoff_demo",
        collection_id="col_demo",
        kind="goal_brief",
        status="awaiting_source_material",
        created_at="2026-07-19T00:02:00+00:00",
        source_channels=("upload",),
        goal_context={"research_brief": {"intent": "compare"}},
    )

    await repository.add_collection(collection)
    await repository.add_collection_import(
        import_record,
        updated_at="2026-07-19T00:01:00+00:00",
    )
    await repository.add_collection_handoff(handoff)

    assert await repository.list_collection_files("col_demo") == (file_record,)
    assert await repository.list_collection_imports("col_demo") == (import_record,)
    assert await repository.list_collection_handoffs("col_demo") == (handoff,)
    membership = (await repository.list_collection_documents("col_demo"))[0]
    assert await repository.read_document(membership.document_id) is not None
    assert (
        (await repository.read_document_version(membership.document_version_id)).sha256
        == file_record.sha256
    )
    assert (await repository.read_collection("col_demo")).paper_count == 1
    assert (await repository.read_collection("col_demo")).status == "ready"

    assert await repository.delete_collection("col_demo") is True
    assert await repository.list_collection_files("col_demo") == ()
    assert await repository.list_collection_imports("col_demo") == ()
    assert await repository.list_collection_handoffs("col_demo") == ()
    assert await repository.list_collection_documents("col_demo") == ()
    assert await repository.read_document(membership.document_id) is None
    assert await repository.read_document_version(membership.document_version_id) is None


async def test_memory_build_repository_is_directly_injected_for_isolated_tests() -> None:
    repository = MemoryBuildRepository()

    assert await repository.list_tasks() == ()
    assert await repository.read_active_build("col_demo") is None


async def test_memory_collection_import_rejects_invalid_hash_without_partial_state() -> None:
    repository = MemoryCollectionRepository()
    collection = CollectionRecord(
        collection_id="col_invalid_hash",
        owner_user_id="user_demo",
        name="Invalid hash",
        description=None,
        status="idle",
        paper_count=0,
        created_at="2026-07-19T00:00:00+00:00",
        updated_at="2026-07-19T00:00:00+00:00",
    )
    file_record = CollectionFileRecord(
        file_id="file_invalid_hash",
        collection_id=collection.collection_id,
        object_id="obj_invalid_hash",
        object_kind="source_input",
        original_filename="paper.pdf",
        stored_filename="stored-paper.pdf",
        storage_key=f"{collection.collection_id}/input/stored-paper.pdf",
        sha256="a" * 64,
        media_type="application/pdf",
        status="stored",
        size_bytes=10,
        created_at="2026-07-19T00:01:00+00:00",
    )
    import_record = CollectionImportRecord(
        import_id="imp_invalid_hash",
        collection_id=collection.collection_id,
        channel="upload",
        adapter_name="upload",
        adapter_version=None,
        raw_locator="paper.pdf",
        goal_context=None,
        warnings=(),
        ingested_at=file_record.created_at,
        documents=(
            CollectionImportDocumentRecord(
                source_document_id="srcdoc_invalid_hash",
                origin_channel="upload",
                file=replace(file_record, sha256="A" * 64),
                language=None,
                ingest_status="normalized",
                text_units=(),
            ),
        ),
    )
    await repository.add_collection(collection)

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        await repository.add_collection_import(
            import_record,
            updated_at="2026-07-19T00:02:00+00:00",
        )

    assert await repository.list_collection_files(collection.collection_id) == ()
    assert await repository.list_collection_imports(collection.collection_id) == ()
    assert await repository.list_collection_documents(collection.collection_id) == ()
    assert await repository.read_collection(collection.collection_id) == collection
