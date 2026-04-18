from __future__ import annotations

import json
from pathlib import Path

import pytest

from application.collections.service import CollectionService
from infra.ingestion.normalized_import import (
    NormalizedImportBatch,
    NormalizedImportDocument,
    NormalizedImportSourceMetadata,
    NormalizedImportTextUnit,
)
from infra.ingestion.source_adapter import SourceAdapterRequest


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
    assert "default_method" not in listed[0]
    assert listed[0]["updated_at"] == "2026-01-15T12:03:14.032160+00:00"

    record = service.get_collection("default")
    assert record["collection_id"] == "default"
    assert record["paper_count"] == 0
    assert "default_method" not in record

    saved = json.loads(paths.meta_path.read_text(encoding="utf-8"))
    assert saved["collection_id"] == "default"
    assert "id" not in saved
    assert "default_method" not in saved


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


def test_collection_service_returns_empty_import_manifest_for_existing_collection(tmp_path):
    service = CollectionService(tmp_path / "collections")
    collection = service.create_collection("No Manifest Yet")

    manifest = service.get_import_manifest(collection["collection_id"])

    assert manifest == {
        "schema_version": 1,
        "collection_id": collection["collection_id"],
        "handoffs": [],
        "imports": [],
    }


def test_collection_service_registers_goal_brief_handoff(tmp_path):
    service = CollectionService(tmp_path / "collections")
    collection = service.create_collection("Goal Collection")

    handoff = service.register_goal_brief_handoff(
        collection["collection_id"],
        {
            "material_system": "PVDF",
            "target_property": "adhesion strength",
            "intent": "compare",
            "objective": "Assess adhesion strength for PVDF.",
            "constraints": {"substrate": "Al"},
            "context": None,
        },
        {
            "level": "direct",
            "rationale": "bounded",
            "direct_evidence_count": 12,
            "indirect_evidence_count": 0,
            "warnings": [],
        },
    )

    assert handoff["handoff_id"].startswith("handoff_")
    assert handoff["status"] == "awaiting_source_material"
    assert handoff["source_channels"] == ["upload"]
    manifest = service.get_import_manifest(collection["collection_id"])
    assert len(manifest["handoffs"]) == 1
    assert manifest["handoffs"][0]["goal_context"]["research_brief"]["material_system"] == "PVDF"
    assert manifest["handoffs"][0]["goal_context"]["coverage_assessment"]["level"] == "direct"


def test_collection_service_imports_normalized_batch_and_updates_collection(tmp_path):
    service = CollectionService(tmp_path / "collections")
    collection = service.create_collection("Imported Collection")
    collection_id = collection["collection_id"]

    batch = NormalizedImportBatch(
        documents=(
            NormalizedImportDocument(
                source_document_id="srcdoc_1",
                origin_channel="upload",
                original_filename="paper.txt",
                stored_filename="normalized_paper.txt",
                media_type="text/plain",
                checksum="abc123",
            ),
        ),
        text_units=(
            NormalizedImportTextUnit(
                text_unit_id="tu_1",
                source_document_id="srcdoc_1",
                sequence=1,
                text="Mix and anneal.",
                char_count=len("Mix and anneal."),
            ),
            NormalizedImportTextUnit(
                text_unit_id="tu_0",
                source_document_id="srcdoc_1",
                sequence=0,
                text="Experimental Section",
                char_count=len("Experimental Section"),
            ),
        ),
        source_metadata=NormalizedImportSourceMetadata(
            channel="upload",
            adapter_name="upload",
            ingested_at="2026-04-13T00:00:00+00:00",
        ),
    )

    records = service.import_normalized_batch(collection_id, batch)

    assert len(records) == 1
    assert records[0]["original_filename"] == "paper.txt"
    assert records[0]["stored_filename"] == "normalized_paper.txt"
    assert records[0]["media_type"] == "text/plain"
    assert Path(records[0]["stored_path"]).read_text(encoding="utf-8") == (
        "Experimental Section\nMix and anneal."
    )
    assert service.get_collection(collection_id)["paper_count"] == 1
    assert service.list_files(collection_id)[0]["stored_filename"] == "normalized_paper.txt"
    manifest = service.get_import_manifest(collection_id)
    assert manifest["schema_version"] == 1
    assert manifest["collection_id"] == collection_id
    assert manifest["handoffs"] == []
    assert len(manifest["imports"]) == 1
    import_entry = manifest["imports"][0]
    assert import_entry["channel"] == "upload"
    assert import_entry["adapter_name"] == "upload"
    assert import_entry["warnings"] == []
    document_entry = import_entry["documents"][0]
    assert document_entry["source_document_id"] == "srcdoc_1"
    assert document_entry["stored_filename"] == "normalized_paper.txt"
    assert document_entry["storage_relpath"] == "input/normalized_paper.txt"
    assert document_entry["checksum"] == "abc123"
    assert document_entry["text_units"] == [
        {
            "text_unit_id": "tu_0",
            "sequence": 0,
            "page_ref": None,
            "char_count": len("Experimental Section"),
        },
        {
            "text_unit_id": "tu_1",
            "sequence": 1,
            "page_ref": None,
            "char_count": len("Mix and anneal."),
        },
    ]
    assert "text" not in document_entry["text_units"][0]
    assert "document_profiles" not in import_entry


def test_collection_service_add_file_uses_normalized_upload(monkeypatch, tmp_path):
    service = CollectionService(tmp_path / "collections")
    collection = service.create_collection("Upload Collection")
    collection_id = collection["collection_id"]
    captured: dict[str, object] = {}

    def fake_normalize_upload(filename: str, content: bytes, media_type: str | None = None):
        captured["filename"] = filename
        captured["content"] = content
        captured["media_type"] = media_type
        return NormalizedImportBatch(
            documents=(
                NormalizedImportDocument(
                    source_document_id="srcdoc_upload",
                    origin_channel="upload",
                    original_filename=filename,
                    stored_filename="normalized_upload.txt",
                    media_type=media_type,
                ),
            ),
            text_units=(
                NormalizedImportTextUnit(
                    text_unit_id="tu_upload",
                    source_document_id="srcdoc_upload",
                    sequence=0,
                    text="Normalized upload text",
                    char_count=len("Normalized upload text"),
                ),
            ),
            source_metadata=NormalizedImportSourceMetadata(
                channel="upload",
                adapter_name="upload",
                ingested_at="2026-04-13T00:00:00+00:00",
            ),
        )

    monkeypatch.setattr("application.collections.service.normalize_upload", fake_normalize_upload)

    record = service.add_file(
        collection_id,
        "paper.pdf",
        b"%PDF-1.4 fake",
        media_type="application/pdf",
    )

    assert captured == {
        "filename": "paper.pdf",
        "content": b"%PDF-1.4 fake",
        "media_type": "application/pdf",
    }
    assert record["stored_filename"] == "normalized_upload.txt"
    assert Path(record["stored_path"]).read_text(encoding="utf-8") == "Normalized upload text"
    manifest = service.get_import_manifest(collection_id)
    assert manifest["handoffs"] == []
    assert len(manifest["imports"]) == 1
    assert manifest["imports"][0]["documents"][0]["stored_filename"] == "normalized_upload.txt"
    assert manifest["imports"][0]["documents"][0]["text_units"] == [
        {
            "text_unit_id": "tu_upload",
            "sequence": 0,
            "page_ref": None,
            "char_count": len("Normalized upload text"),
        }
    ]


def test_collection_service_imports_from_source_adapter(tmp_path):
    service = CollectionService(tmp_path / "collections")
    collection = service.create_collection("Adapter Collection")
    captured: dict[str, object] = {}

    class FakeSearchAdapter:
        channel = "search"
        adapter_name = "fake_search"
        adapter_version = "0.1.0"

        def fetch(self, request: SourceAdapterRequest) -> NormalizedImportBatch:
            captured["request"] = request
            return NormalizedImportBatch(
                documents=(
                    NormalizedImportDocument(
                        source_document_id="srcdoc_search_1",
                        origin_channel=self.channel,
                        original_filename="search-result-1.txt",
                        stored_filename="search_result_1.txt",
                        media_type="text/plain",
                        checksum="searchchecksum",
                    ),
                ),
                text_units=(
                    NormalizedImportTextUnit(
                        text_unit_id="tu_search_1",
                        source_document_id="srcdoc_search_1",
                        sequence=0,
                        text="Search adapter normalized text",
                        char_count=len("Search adapter normalized text"),
                    ),
                ),
                source_metadata=NormalizedImportSourceMetadata(
                    channel=self.channel,
                    adapter_name=self.adapter_name,
                    adapter_version=self.adapter_version,
                    ingested_at="2026-04-14T00:00:00+00:00",
                    raw_locator=request.raw_locator,
                    goal_context=request.goal_context,
                ),
            )

    records = service.import_from_adapter(
        collection["collection_id"],
        FakeSearchAdapter(),
        "doi:10.1000/demo",
        goal_context={"intent": "compare"},
        max_documents=5,
        constraints={"year": "2024"},
    )

    request = captured["request"]
    assert request.collection_id == collection["collection_id"]
    assert request.raw_locator == "doi:10.1000/demo"
    assert request.goal_context == {"intent": "compare"}
    assert request.max_documents == 5
    assert request.constraints == {"year": "2024"}

    assert len(records) == 1
    assert records[0]["stored_filename"] == "search_result_1.txt"
    assert Path(records[0]["stored_path"]).read_text(encoding="utf-8") == (
        "Search adapter normalized text"
    )

    manifest = service.get_import_manifest(collection["collection_id"])
    assert manifest["handoffs"] == []
    assert len(manifest["imports"]) == 1
    import_entry = manifest["imports"][0]
    assert import_entry["channel"] == "search"
    assert import_entry["adapter_name"] == "fake_search"
    assert import_entry["adapter_version"] == "0.1.0"
    assert import_entry["raw_locator"] == "doi:10.1000/demo"
    assert import_entry["goal_context"] == {"intent": "compare"}
    assert import_entry["documents"][0]["source_document_id"] == "srcdoc_search_1"

    artifacts = service.artifact_repository.read(collection["collection_id"])
    assert artifacts["document_profiles_generated"] is False
    assert artifacts["evidence_cards_generated"] is False
    assert artifacts["characterization_observations_generated"] is False
    assert artifacts["structure_features_generated"] is False
    assert artifacts["test_conditions_generated"] is False
    assert artifacts["baseline_references_generated"] is False
    assert artifacts["sample_variants_generated"] is False
    assert artifacts["measurement_results_generated"] is False
    assert artifacts["comparison_rows_generated"] is False
    assert artifacts["table_cells_generated"] is False


def test_collection_service_rejects_source_adapter_batch_shape_mismatch(tmp_path):
    service = CollectionService(tmp_path / "collections")
    collection = service.create_collection("Bad Adapter Collection")

    class BadAdapter:
        channel = "search"
        adapter_name = "bad_search"
        adapter_version = "0.0.1"

        def fetch(self, request: SourceAdapterRequest) -> dict:
            return {"raw_locator": request.raw_locator}

    with pytest.raises(TypeError) as exc_info:
        service.import_from_adapter(
            collection["collection_id"],
            BadAdapter(),
            "doi:10.1000/bad",
        )

    assert "NormalizedImportBatch" in str(exc_info.value)
