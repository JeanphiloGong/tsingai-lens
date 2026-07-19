from __future__ import annotations

from domain.source.collection import (
    CollectionFileRecord,
    CollectionHandoffRecord,
    CollectionImportDocumentRecord,
    CollectionImportRecord,
    CollectionRecord,
    empty_import_manifest,
)


def test_collection_record_normalizes_legacy_meta_shape() -> None:
    record = CollectionRecord.from_mapping(
        {
            "id": "default",
            "name": "default",
            "created_at": "2026-01-15T12:03:14.032160+00:00",
            "default_method": "legacy",
        },
        "default",
        now_iso="2026-01-15T12:03:14.032160+00:00",
    )

    assert record.collection_id == "default"
    assert record.name == "default"
    assert record.description is None
    assert record.status == "idle"
    assert record.paper_count == 0
    assert record.updated_at == "2026-01-15T12:03:14.032160+00:00"
    assert record.to_record() == {
        "collection_id": "default",
        "owner_user_id": "local-user",
        "name": "default",
        "description": None,
        "status": "idle",
        "paper_count": 0,
        "created_at": "2026-01-15T12:03:14.032160+00:00",
        "updated_at": "2026-01-15T12:03:14.032160+00:00",
    }


def test_collection_record_create_and_empty_manifest_are_stable() -> None:
    record = CollectionRecord.create(
        collection_id="col_123",
        name="Demo Collection",
        description="demo",
        now_iso="2026-04-19T00:00:00+00:00",
    )

    assert record.to_record()["status"] == "idle"
    assert record.to_record()["paper_count"] == 0
    assert empty_import_manifest("col_123") == {
        "schema_version": 1,
        "collection_id": "col_123",
        "handoffs": [],
        "imports": [],
    }


def test_collection_file_record_flattens_object_metadata_without_internal_identity() -> (
    None
):
    record = CollectionFileRecord(
        file_id="file_1",
        collection_id="col_123",
        object_id="obj_1",
        object_kind="source_input",
        original_filename="paper.pdf",
        stored_filename="stored-paper.pdf",
        storage_key="col_123/input/stored-paper.pdf",
        sha256="a" * 64,
        media_type="application/pdf",
        status="stored",
        size_bytes=42,
        created_at="2026-07-19T01:00:00+00:00",
        document_id="legacy-doc-1",
    )

    assert record.to_record() == {
        "file_id": "file_1",
        "collection_id": "col_123",
        "document_id": "legacy-doc-1",
        "original_filename": "paper.pdf",
        "stored_filename": "stored-paper.pdf",
        "storage_key": "col_123/input/stored-paper.pdf",
        "sha256": "a" * 64,
        "media_type": "application/pdf",
        "status": "stored",
        "size_bytes": 42,
        "created_at": "2026-07-19T01:00:00+00:00",
    }
    assert "object_id" not in record.to_record()
    assert "object_kind" not in record.to_record()


def test_collection_import_record_preserves_existing_manifest_projection() -> None:
    file_record = CollectionFileRecord(
        file_id="file_1",
        collection_id="col_123",
        object_id="obj_1",
        object_kind="source_input",
        original_filename="paper.pdf",
        stored_filename="stored-paper.pdf",
        storage_key="col_123/input/stored-paper.pdf",
        sha256="b" * 64,
        media_type="application/pdf",
        status="stored",
        size_bytes=84,
        created_at="2026-07-19T01:00:00+00:00",
    )
    import_record = CollectionImportRecord(
        import_id="imp_1",
        collection_id="col_123",
        channel="search",
        adapter_name="example",
        adapter_version="1.0",
        raw_locator="doi:10.1000/example",
        goal_context={"intent": "compare"},
        warnings=("partial_metadata",),
        ingested_at="2026-07-19T01:01:00+00:00",
        documents=(
            CollectionImportDocumentRecord(
                source_document_id="srcdoc_1",
                origin_channel="search",
                file=file_record,
                language="en",
                ingest_status="normalized",
                text_units=(
                    {
                        "text_unit_id": "tu_1",
                        "sequence": 0,
                        "page_ref": "1",
                        "char_count": 12,
                    },
                ),
            ),
        ),
    )

    assert import_record.to_record() == {
        "import_id": "imp_1",
        "channel": "search",
        "adapter_name": "example",
        "adapter_version": "1.0",
        "raw_locator": "doi:10.1000/example",
        "goal_context": {"intent": "compare"},
        "warnings": ["partial_metadata"],
        "ingested_at": "2026-07-19T01:01:00+00:00",
        "documents": [
            {
                "source_document_id": "srcdoc_1",
                "origin_channel": "search",
                "original_filename": "paper.pdf",
                "stored_filename": "stored-paper.pdf",
                "storage_key": "col_123/input/stored-paper.pdf",
                "sha256": "b" * 64,
                "media_type": "application/pdf",
                "language": "en",
                "ingest_status": "normalized",
                "text_units": [
                    {
                        "text_unit_id": "tu_1",
                        "sequence": 0,
                        "page_ref": "1",
                        "char_count": 12,
                    }
                ],
            }
        ],
    }


def test_collection_handoff_record_preserves_existing_manifest_projection() -> None:
    record = CollectionHandoffRecord(
        handoff_id="handoff_1",
        collection_id="col_123",
        kind="goal_brief",
        status="awaiting_source_material",
        created_at="2026-07-19T01:02:00+00:00",
        source_channels=("upload", "search"),
        goal_context={"research_brief": {"intent": "compare"}},
    )

    assert record.to_record() == {
        "handoff_id": "handoff_1",
        "kind": "goal_brief",
        "status": "awaiting_source_material",
        "created_at": "2026-07-19T01:02:00+00:00",
        "source_channels": ["upload", "search"],
        "goal_context": {"research_brief": {"intent": "compare"}},
    }
