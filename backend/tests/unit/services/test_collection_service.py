from __future__ import annotations

import base64
from dataclasses import replace
from hashlib import sha256
import json
from zipfile import ZipFile
import pytest

import application.source.collection_service as collection_service_module
from application.source.collection_service import (
    CollectionService,
    CollectionSourceArchiveError,
)
from domain.source import (
    CollectionImportDocumentRecord,
    CollectionImportRecord,
)
from infra.persistence.memory import MemoryCollectionRepository
from infra.source.ingestion.normalized_import import (
    NormalizedImportBatch,
    NormalizedImportDocument,
    NormalizedImportSourceMetadata,
    NormalizedImportTextUnit,
)
from infra.source.ingestion.source_adapter import SourceAdapterRequest
from tests.support.collection_service import build_test_collection_service

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_collection_service_requires_explicit_repository():
    with pytest.raises(TypeError, match="repository"):
        CollectionService()

    with pytest.raises(TypeError, match="workspace"):
        CollectionService(repository=MemoryCollectionRepository())


async def test_collection_service_never_creates_collection_metadata_json(tmp_path):
    service = build_test_collection_service(tmp_path / "collections")
    record = await service.create_collection("Database metadata")
    paths = service.get_paths(record["collection_id"])

    assert await service.get_collection(record["collection_id"]) == record
    assert await service.list_collections() == [record]
    assert paths.collection_dir.exists()
    assert not (paths.collection_dir / "meta.json").exists()
    assert not (paths.collection_dir / "files.json").exists()
    assert not (paths.collection_dir / "import_manifest.json").exists()


async def test_list_files_requires_collection_metadata(tmp_path):
    service = build_test_collection_service(tmp_path / "collections")
    service.workspace.create_collection_dirs("col_orphaned_workspace")

    with pytest.raises(FileNotFoundError, match="collection not found"):
        await service.list_files("col_orphaned_workspace")


async def test_build_source_archive_preserves_requested_files_and_manifest(tmp_path):
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Reproduction sources")
    collection_id = collection["collection_id"]
    first = await service.add_file(
        collection_id,
        "paper.pdf",
        b"%PDF-1.4\nfirst paper\n",
        "application/pdf",
    )
    second = await service.add_file(
        collection_id,
        "paper.pdf",
        b"%PDF-1.4\nsecond paper\n",
        "application/pdf",
    )

    result = await service.build_source_archive(
        collection_id,
        [second["file_id"], first["file_id"]],
    )
    try:
        with ZipFile(result["file"]) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            archive_paths = [item["archive_path"] for item in manifest["files"]]

            assert archive_paths == [
                "sources/001-paper.pdf",
                "sources/002-paper.pdf",
            ]
            assert [item["file_id"] for item in manifest["files"]] == [
                second["file_id"],
                first["file_id"],
            ]
            assert archive.read(archive_paths[0]) == b"%PDF-1.4\nsecond paper\n"
            assert archive.read(archive_paths[1]) == b"%PDF-1.4\nfirst paper\n"
            assert manifest["collection_id"] == collection_id
            assert manifest["schema_version"] == 1
            assert manifest["files"][0]["sha256"] == second["sha256"]
            assert manifest["files"][0]["media_type"] == "application/pdf"
    finally:
        result["file"].close()


async def test_build_source_archive_rejects_missing_file_before_reading(
    monkeypatch,
    tmp_path,
):
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Missing source")
    uploaded = await service.add_file(
        collection["collection_id"],
        "paper.pdf",
        b"%PDF-1.4\nsource\n",
    )

    def fail_if_read(*_args, **_kwargs):
        raise AssertionError("source bytes must not be read before selection resolves")

    monkeypatch.setattr(service.object_store, "read", fail_if_read)

    with pytest.raises(CollectionSourceArchiveError) as exc_info:
        await service.build_source_archive(
            collection["collection_id"],
            [uploaded["file_id"], "file_missing"],
        )

    assert exc_info.value.code == "collection_source_file_not_found"
    assert exc_info.value.file_id == "file_missing"


async def test_build_source_archive_rejects_oversized_selection_before_reading(
    monkeypatch,
    tmp_path,
):
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Oversized source archive")
    first = await service.add_file(
        collection["collection_id"],
        "first.pdf",
        b"1234",
    )
    second = await service.add_file(
        collection["collection_id"],
        "second.pdf",
        b"5678",
    )
    monkeypatch.setattr(collection_service_module, "_SOURCE_ARCHIVE_MAX_BYTES", 7)

    def fail_if_read(*_args, **_kwargs):
        raise AssertionError("oversized archive selection must fail before byte reads")

    monkeypatch.setattr(service.object_store, "read", fail_if_read)

    with pytest.raises(CollectionSourceArchiveError) as exc_info:
        await service.build_source_archive(
            collection["collection_id"],
            [first["file_id"], second["file_id"]],
        )

    assert exc_info.value.code == "collection_source_archive_too_large"
    assert exc_info.value.file_id is None


async def test_build_source_archive_rejects_unsafe_collection_storage_key(tmp_path):
    service = build_test_collection_service(tmp_path / "collections")
    first = await service.create_collection("Requested collection")
    second = await service.create_collection("Foreign collection")
    foreign_file = await service.add_file(
        second["collection_id"],
        "foreign.pdf",
        b"%PDF-1.4\nforeign source\n",
    )
    foreign_record = (
        await service.repository.list_collection_files(second["collection_id"])
    )[0]
    unsafe_file = replace(
        foreign_record,
        file_id="file_unsafe",
        object_id="obj_unsafe",
        collection_id=first["collection_id"],
    )
    await service.repository.add_collection_import(
        CollectionImportRecord(
            import_id="imp_unsafe",
            collection_id=first["collection_id"],
            channel="upload",
            adapter_name="upload",
            adapter_version=None,
            raw_locator="foreign.pdf",
            goal_context=None,
            warnings=(),
            ingested_at=unsafe_file.created_at,
            documents=(
                CollectionImportDocumentRecord(
                    source_document_id="srcdoc_unsafe",
                    origin_channel="upload",
                    file=unsafe_file,
                    language=None,
                    ingest_status="normalized",
                    text_units=(),
                ),
            ),
        ),
        updated_at=unsafe_file.created_at,
    )

    with pytest.raises(CollectionSourceArchiveError) as exc_info:
        await service.build_source_archive(
            first["collection_id"],
            ["file_unsafe"],
        )

    assert exc_info.value.code == "collection_source_path_invalid"
    assert exc_info.value.file_id == "file_unsafe"
    assert foreign_file["storage_key"] not in str(exc_info.value)


async def test_delete_collection_removes_collection_directory(tmp_path):
    service = build_test_collection_service(tmp_path / "collections")
    record = await service.create_collection("Delete Me")
    collection_id = record["collection_id"]
    paths = service.get_paths(collection_id)

    uploaded = await service.add_file(
        collection_id,
        "paper.txt",
        b"Experimental Section\nMix.",
    )

    assert paths.collection_dir.exists()
    assert not (paths.collection_dir / "meta.json").exists()
    assert not (paths.collection_dir / "files.json").exists()
    assert not (paths.collection_dir / "import_manifest.json").exists()
    assert service.object_store.read(uploaded["storage_key"], uploaded["sha256"])

    result = await service.delete_collection(collection_id)

    assert result["collection_id"] == collection_id
    assert not paths.collection_dir.exists()
    with pytest.raises(FileNotFoundError):
        service.object_store.read(uploaded["storage_key"], uploaded["sha256"])


async def test_identical_uploads_share_identity_but_keep_collection_scoped_downloads(
    tmp_path,
):
    service = build_test_collection_service(tmp_path / "collections")
    first = await service.create_collection("First")
    second = await service.create_collection("Second")
    payload = b"%PDF-1.4\nshared content\n"

    first_file = await service.add_file(first["collection_id"], "first.pdf", payload)
    second_file = await service.add_file(second["collection_id"], "second.pdf", payload)
    first_membership = (await service.repository.list_collection_documents(
        first["collection_id"]
    ))[0]
    second_membership = (await service.repository.list_collection_documents(
        second["collection_id"]
    ))[0]
    second_source_id = (await service.get_import_manifest(second["collection_id"]))[
        "imports"
    ][0]["documents"][0]["source_document_id"]

    assert first_membership.document_id == second_membership.document_id
    assert first_membership.document_version_id == second_membership.document_version_id
    assert first_file["storage_key"] != second_file["storage_key"]
    with pytest.raises(FileNotFoundError, match="document not found"):
        await service.resolve_document_source_file(
            first["collection_id"],
            second_source_id,
        )

    await service.delete_collection(first["collection_id"])

    assert (
        service.object_store.read(second_file["storage_key"], second_file["sha256"])
        == payload
    )


async def test_delete_collection_raises_for_missing_collection(tmp_path):
    service = build_test_collection_service(tmp_path / "collections")

    try:
        await service.delete_collection("col_missing")
    except FileNotFoundError as exc:
        assert "collection not found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected FileNotFoundError")


async def test_delete_collection_rejects_another_collections_storage_key(tmp_path):
    service = build_test_collection_service(tmp_path / "collections")
    first = await service.create_collection(name="First collection")
    second = await service.create_collection(name="Second collection")
    second_file = await service.add_file(
        second["collection_id"],
        "paper.txt",
        b"Second collection bytes",
    )
    second_file_record = (await service.repository.list_collection_files(
        second["collection_id"]
    ))[0]
    invalid_file = replace(
        second_file_record,
        file_id="file_invalid_key",
        object_id="obj_invalid_key",
        collection_id=first["collection_id"],
    )
    await service.repository.add_collection_import(
        CollectionImportRecord(
            import_id="imp_invalid_key",
            collection_id=first["collection_id"],
            channel="upload",
            adapter_name="upload",
            adapter_version=None,
            raw_locator="paper.txt",
            goal_context=None,
            warnings=(),
            ingested_at=invalid_file.created_at,
            documents=(
                CollectionImportDocumentRecord(
                    source_document_id="srcdoc_invalid_key",
                    origin_channel="upload",
                    file=invalid_file,
                    language=None,
                    ingest_status="normalized",
                    text_units=(),
                ),
            ),
        ),
        updated_at=invalid_file.created_at,
    )

    with pytest.raises(ValueError, match="invalid collection object key"):
        await service.delete_collection(first["collection_id"])

    assert (
        service.object_store.read(
            second_file["storage_key"],
            second_file["sha256"],
        )
        == b"Second collection bytes"
    )


async def test_delete_collection_keeps_bytes_when_relational_delete_fails(
    monkeypatch,
    tmp_path,
):
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Delete failure")
    collection_id = collection["collection_id"]
    uploaded = await service.add_file(
        collection_id,
        "paper.txt",
        b"Registered source bytes",
    )
    collection_dir = service.get_paths(collection_id).collection_dir

    async def fail_delete(_collection_id: str) -> bool:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service.repository, "delete_collection", fail_delete)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.delete_collection(collection_id)

    current = await service.get_collection(collection_id)
    assert current == {
        **collection,
        "paper_count": 1,
        "status": "ready",
        "updated_at": current["updated_at"],
    }
    assert collection_dir.exists()
    assert (
        service.object_store.read(
            uploaded["storage_key"],
            uploaded["sha256"],
        )
        == b"Registered source bytes"
    )


async def test_collection_service_returns_empty_import_manifest_for_existing_collection(
    tmp_path,
):
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("No Manifest Yet")

    manifest = await service.get_import_manifest(collection["collection_id"])

    assert manifest == {
        "schema_version": 1,
        "collection_id": collection["collection_id"],
        "handoffs": [],
        "imports": [],
    }


async def test_collection_service_registers_goal_brief_handoff(tmp_path):
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Goal Collection")

    handoff = await service.register_goal_brief_handoff(
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
    manifest = await service.get_import_manifest(collection["collection_id"])
    assert len(manifest["handoffs"]) == 1
    assert (
        manifest["handoffs"][0]["goal_context"]["research_brief"]["material_system"]
        == "PVDF"
    )
    assert (
        manifest["handoffs"][0]["goal_context"]["coverage_assessment"]["level"]
        == "direct"
    )
    collection_dir = service.get_paths(collection["collection_id"]).collection_dir
    assert not (collection_dir / "files.json").exists()
    assert not (collection_dir / "import_manifest.json").exists()


async def test_collection_service_imports_normalized_batch_and_updates_collection(
    tmp_path,
):
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Imported Collection")
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

    records = await service.import_normalized_batch(collection_id, batch)

    assert len(records) == 1
    assert records[0]["original_filename"] == "paper.txt"
    assert records[0]["stored_filename"] == "normalized_paper.txt"
    assert records[0]["media_type"] == "text/plain"
    expected_payload = b"Experimental Section\nMix and anneal."
    expected_sha256 = sha256(expected_payload).hexdigest()
    assert records[0]["storage_key"] == (f"{collection_id}/input/normalized_paper.txt")
    assert records[0]["sha256"] == expected_sha256
    assert "stored_path" not in records[0]
    assert service.object_store.read(records[0]["storage_key"], expected_sha256) == (
        expected_payload
    )
    assert (await service.get_collection(collection_id))["paper_count"] == 1
    assert (
        (await service.list_files(collection_id))[0]["stored_filename"]
        == "normalized_paper.txt"
    )
    manifest = await service.get_import_manifest(collection_id)
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
    assert document_entry["storage_key"] == records[0]["storage_key"]
    assert document_entry["sha256"] == expected_sha256
    assert "stored_path" not in document_entry
    assert "storage_relpath" not in document_entry
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
    collection_dir = service.get_paths(collection_id).collection_dir
    assert not (collection_dir / "files.json").exists()
    assert not (collection_dir / "import_manifest.json").exists()


async def test_collection_service_cleans_only_unregistered_bytes_after_import_failure(
    monkeypatch,
    tmp_path,
):
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Failed import")
    collection_id = collection["collection_id"]
    registered = await service.add_file(
        collection_id,
        "registered.txt",
        b"Registered source bytes",
    )

    async def fail_import(*_args, **_kwargs) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service.repository, "add_collection_import", fail_import)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.add_file(
            collection_id,
            "failed.txt",
            b"Unregistered source bytes",
        )

    failed_key = f"{collection_id}/input/failed.txt"
    failed_sha256 = sha256(b"Unregistered source bytes").hexdigest()
    with pytest.raises(FileNotFoundError):
        service.object_store.read(failed_key, failed_sha256)
    assert (
        service.object_store.read(
            registered["storage_key"],
            registered["sha256"],
        )
        == b"Registered source bytes"
    )
    assert [
        record["storage_key"] for record in await service.list_files(collection_id)
    ] == [
        registered["storage_key"]
    ]


async def test_collection_service_add_file_uses_normalized_upload(
    monkeypatch,
    tmp_path,
):
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Upload Collection")
    collection_id = collection["collection_id"]
    captured: dict[str, object] = {}

    def fake_normalize_upload(
        filename: str, content: bytes, media_type: str | None = None
    ):
        captured["filename"] = filename
        captured["content"] = content
        captured["media_type"] = media_type
        return NormalizedImportBatch(
            documents=(
                NormalizedImportDocument(
                    source_document_id="srcdoc_upload",
                    origin_channel="upload",
                    original_filename=filename,
                    stored_filename="normalized_upload.pdf",
                    media_type=media_type,
                    storage_payload_base64=base64.b64encode(content).decode("ascii"),
                ),
            ),
            text_units=(),
            source_metadata=NormalizedImportSourceMetadata(
                channel="upload",
                adapter_name="upload",
                ingested_at="2026-04-13T00:00:00+00:00",
            ),
        )

    monkeypatch.setattr(
        "application.source.collection_service.normalize_upload", fake_normalize_upload
    )

    record = await service.add_file(
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
    assert record["stored_filename"] == "normalized_upload.pdf"
    assert record["storage_key"] == f"{collection_id}/input/normalized_upload.pdf"
    assert record["sha256"] == sha256(b"%PDF-1.4 fake").hexdigest()
    assert service.object_store.read(record["storage_key"], record["sha256"]) == (
        b"%PDF-1.4 fake"
    )
    manifest = await service.get_import_manifest(collection_id)
    assert manifest["handoffs"] == []
    assert len(manifest["imports"]) == 1
    assert (
        manifest["imports"][0]["documents"][0]["stored_filename"]
        == "normalized_upload.pdf"
    )
    assert manifest["imports"][0]["documents"][0]["text_units"] == []


async def test_collection_service_imports_from_source_adapter(tmp_path):
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Adapter Collection")
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

    records = await service.import_from_adapter(
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
    assert service.object_store.read(
        records[0]["storage_key"],
        records[0]["sha256"],
    ) == (b"Search adapter normalized text")

    manifest = await service.get_import_manifest(collection["collection_id"])
    assert manifest["handoffs"] == []
    assert len(manifest["imports"]) == 1
    import_entry = manifest["imports"][0]
    assert import_entry["channel"] == "search"
    assert import_entry["adapter_name"] == "fake_search"
    assert import_entry["adapter_version"] == "0.1.0"
    assert import_entry["raw_locator"] == "doi:10.1000/demo"
    assert import_entry["goal_context"] == {"intent": "compare"}
    assert import_entry["documents"][0]["source_document_id"] == "srcdoc_search_1"


async def test_collection_service_rejects_source_adapter_batch_shape_mismatch(tmp_path):
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Bad Adapter Collection")

    class BadAdapter:
        channel = "search"
        adapter_name = "bad_search"
        adapter_version = "0.0.1"

        def fetch(self, request: SourceAdapterRequest) -> dict:
            return {"raw_locator": request.raw_locator}

    with pytest.raises(TypeError) as exc_info:
        await service.import_from_adapter(
            collection["collection_id"],
            BadAdapter(),
            "doi:10.1000/bad",
        )

    assert "NormalizedImportBatch" in str(exc_info.value)
