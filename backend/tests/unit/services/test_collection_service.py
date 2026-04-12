from __future__ import annotations

import json

from application.collection_service import CollectionService


def test_collection_service_normalizes_legacy_meta(tmp_path):
    service = CollectionService(tmp_path / "collections")
    paths = service.get_paths("default")
    paths.collection_dir.mkdir(parents=True, exist_ok=True)
    paths.meta_path.write_text(
        json.dumps(
            {
                "id": "default",
                "name": "default",
                "created_at": "2026-01-15T12:03:14.032160+00:00",
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )

    listed = service.list_collections()
    assert listed[0]["collection_id"] == "default"
    assert listed[0]["status"] == "idle"
    assert listed[0]["default_method"] == "standard"
    assert listed[0]["updated_at"] == "2026-01-15T12:03:14.032160+00:00"

    record = service.get_collection("default")
    assert record["collection_id"] == "default"
    assert record["paper_count"] == 0

    saved = json.loads(paths.meta_path.read_text(encoding="utf-8"))
    assert saved["collection_id"] == "default"
    assert "id" not in saved


def test_delete_collection_removes_collection_directory(tmp_path):
    service = CollectionService(tmp_path / "collections")
    record = service.create_collection("Delete Me")
    collection_id = record["collection_id"]
    paths = service.get_paths(collection_id)

    service.add_file(collection_id, "paper.txt", b"Experimental Section\nMix.")

    assert paths.collection_dir.exists()
    assert paths.meta_path.exists()
    assert paths.files_path.exists()

    result = service.delete_collection(collection_id)

    assert result["collection_id"] == collection_id
    assert not paths.collection_dir.exists()


def test_delete_collection_raises_for_missing_collection(tmp_path):
    service = CollectionService(tmp_path / "collections")

    try:
        service.delete_collection("col_missing")
    except FileNotFoundError as exc:
        assert "collection not found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected FileNotFoundError")
