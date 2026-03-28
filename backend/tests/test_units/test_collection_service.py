from __future__ import annotations

import json

from services.collection_service import CollectionService


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
