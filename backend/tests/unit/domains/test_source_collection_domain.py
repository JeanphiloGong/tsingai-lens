from __future__ import annotations

from domain.source.collection import CollectionRecord, empty_import_manifest


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
