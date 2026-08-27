from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
import json
from zipfile import ZipFile

from pypdf import PdfWriter
import pytest

import application.source.collection_service as collection_service_module
from application.source.collection_service import (
    CollectionService,
    CollectionSourceArchiveError,
    DocumentSourceUnavailableError,
)
from domain.source import Document
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


def _valid_pdf_bytes(title: str = "Test paper") -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": title})
    payload = BytesIO()
    writer.write(payload)
    return payload.getvalue()


async def test_collection_service_requires_explicit_dependencies() -> None:
    with pytest.raises(TypeError, match="repository"):
        CollectionService()
    with pytest.raises(TypeError, match="workspace"):
        CollectionService(repository=MemoryCollectionRepository())


async def test_collection_contains_its_uploaded_documents(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Current papers")
    first = await service.add_document(
        collection["collection_id"],
        "first.pdf",
        _valid_pdf_bytes("First paper"),
        "application/pdf",
    )
    second = await service.add_document(
        collection["collection_id"],
        "second.pdf",
        _valid_pdf_bytes("Second paper"),
        "application/pdf",
    )

    current = await service.get_collection(collection["collection_id"])

    assert current["documents"] == [first, second]
    assert current["paper_count"] == 2
    assert current["status"] == "ready"


async def test_collection_update_preserves_documents(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Before")
    document = await service.add_document(
        collection["collection_id"],
        "paper.pdf",
        _valid_pdf_bytes(),
        "application/pdf",
    )

    updated = await service.update_collection(
        collection["collection_id"], name="After", status="running"
    )

    assert updated["name"] == "After"
    assert updated["status"] == "running"
    assert updated["documents"] == [document]


async def test_missing_collection_is_not_inferred_from_workspace(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    service.workspace.create_collection_dirs("col_orphaned_workspace")

    with pytest.raises(FileNotFoundError, match="collection not found"):
        await service.get_collection("col_orphaned_workspace")


async def test_normalized_batch_becomes_documents_directly(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Imported Collection")
    batch = NormalizedImportBatch(
        documents=(
            NormalizedImportDocument(
                source_document_id="srcdoc_1",
                origin_channel="upload",
                original_filename="paper.txt",
                stored_filename="normalized_paper.txt",
                media_type="text/plain",
            ),
        ),
        text_units=(
            NormalizedImportTextUnit(
                text_unit_id="tu_1",
                source_document_id="srcdoc_1",
                sequence=1,
                text="Mix and anneal.",
                char_count=15,
            ),
            NormalizedImportTextUnit(
                text_unit_id="tu_0",
                source_document_id="srcdoc_1",
                sequence=0,
                text="Experimental Section",
                char_count=20,
            ),
        ),
        source_metadata=NormalizedImportSourceMetadata(
            channel="upload",
            adapter_name="upload",
            ingested_at="2026-08-27T00:00:00+00:00",
        ),
    )

    documents = await service.import_normalized_batch(collection["collection_id"], batch)

    assert len(documents) == 1
    assert documents[0]["document_id"].startswith("doc_")
    assert set(documents[0]) == {
        "document_id",
        "original_filename",
        "stored_filename",
        "storage_key",
        "sha256",
        "media_type",
        "status",
        "size_bytes",
        "created_at",
    }
    expected = b"Experimental Section\nMix and anneal."
    assert service.object_store.read(
        documents[0]["storage_key"], documents[0]["sha256"]
    ) == expected
    current = await service.get_collection(collection["collection_id"])
    assert current["documents"] == documents


async def test_failed_document_registration_removes_unregistered_bytes(
    monkeypatch,
    tmp_path,
) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Failed upload")
    batch = NormalizedImportBatch(
        documents=(
            NormalizedImportDocument(
                source_document_id="srcdoc_failed",
                origin_channel="upload",
                original_filename="failed.txt",
                stored_filename="failed.txt",
                media_type="text/plain",
                storage_payload_base64=base64.b64encode(b"not registered").decode("ascii"),
            ),
        ),
        text_units=(),
        source_metadata=NormalizedImportSourceMetadata(
            channel="upload",
            adapter_name="upload",
            ingested_at="2026-08-27T00:00:00+00:00",
        ),
    )

    async def fail_add_documents(*_args, **_kwargs) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service.repository, "add_documents", fail_add_documents)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.import_normalized_batch(collection["collection_id"], batch)

    key = f"{collection['collection_id']}/input/failed.txt"
    with pytest.raises(FileNotFoundError):
        service.object_store.read(key, sha256(b"not registered").hexdigest())


async def test_source_archive_uses_document_ids(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Reproduction sources")
    first_payload = _valid_pdf_bytes("First")
    second_payload = _valid_pdf_bytes("Second")
    first = await service.add_document(
        collection["collection_id"], "first.pdf", first_payload, "application/pdf"
    )
    second = await service.add_document(
        collection["collection_id"], "second.pdf", second_payload, "application/pdf"
    )

    result = await service.build_source_archive(
        collection["collection_id"],
        [second["document_id"], first["document_id"]],
    )
    try:
        with ZipFile(result["file"]) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert [item["document_id"] for item in manifest["documents"]] == [
                second["document_id"],
                first["document_id"],
            ]
            assert archive.read(manifest["documents"][0]["archive_path"]) == second_payload
            assert archive.read(manifest["documents"][1]["archive_path"]) == first_payload
    finally:
        result["file"].close()


async def test_source_archive_rejects_unknown_document(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Reproduction sources")

    with pytest.raises(CollectionSourceArchiveError) as exc_info:
        await service.build_source_archive(collection["collection_id"], ["doc_missing"])

    assert exc_info.value.code == "collection_source_document_not_found"
    assert exc_info.value.document_id == "doc_missing"


async def test_source_resolution_reads_only_current_collection_documents(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    first_collection = await service.create_collection("First")
    second_collection = await service.create_collection("Second")
    first = await service.add_document(
        first_collection["collection_id"],
        "first.pdf",
        _valid_pdf_bytes("First"),
        "application/pdf",
    )
    second = await service.add_document(
        second_collection["collection_id"],
        "second.pdf",
        _valid_pdf_bytes("Second"),
        "application/pdf",
    )

    source = await service.resolve_document_source_file(
        first_collection["collection_id"], first["document_id"]
    )
    assert source["filename"] == "first.pdf"
    with pytest.raises(FileNotFoundError, match="document not found"):
        await service.resolve_document_source_file(
            first_collection["collection_id"], second["document_id"]
        )


async def test_source_resolution_rejects_invalid_storage_key(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Unsafe")
    document = Document(
        document_id="doc_unsafe",
        original_filename="unsafe.pdf",
        stored_filename="unsafe.pdf",
        storage_key="other/input/unsafe.pdf",
        sha256="a" * 64,
        media_type="application/pdf",
        status="stored",
        size_bytes=1,
        created_at="2026-08-27T00:00:00+00:00",
    )
    await service.repository.add_documents(
        collection["collection_id"],
        (document,),
        updated_at=document.created_at,
    )

    with pytest.raises(DocumentSourceUnavailableError) as exc_info:
        await service.resolve_document_source_file(
            collection["collection_id"], document.document_id
        )
    assert exc_info.value.code == "document_source_path_invalid"


async def test_delete_collection_removes_documents_and_bytes(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Delete")
    uploaded = await service.add_document(
        collection["collection_id"], "paper.txt", b"Methods", "text/plain"
    )

    await service.delete_collection(collection["collection_id"])

    with pytest.raises(FileNotFoundError):
        await service.get_collection(collection["collection_id"])
    with pytest.raises(FileNotFoundError):
        service.object_store.read(uploaded["storage_key"], uploaded["sha256"])


async def test_import_from_adapter_adds_documents_without_manifest(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Adapter")

    class FakeAdapter:
        channel = "search"
        adapter_name = "fake_search"
        adapter_version = "1"

        def fetch(self, request: SourceAdapterRequest) -> NormalizedImportBatch:
            return NormalizedImportBatch(
                documents=(
                    NormalizedImportDocument(
                        source_document_id="srcdoc_search",
                        origin_channel="search",
                        original_filename="result.txt",
                        stored_filename="result.txt",
                        media_type="text/plain",
                    ),
                ),
                text_units=(
                    NormalizedImportTextUnit(
                        text_unit_id="tu_search",
                        source_document_id="srcdoc_search",
                        sequence=0,
                        text="Search result",
                        char_count=13,
                    ),
                ),
                source_metadata=NormalizedImportSourceMetadata(
                    channel="search",
                    adapter_name="fake_search",
                    adapter_version="1",
                    ingested_at="2026-08-27T00:00:00+00:00",
                    raw_locator=request.raw_locator,
                ),
            )

    result = await service.import_from_adapter(
        collection["collection_id"], FakeAdapter(), "doi:10.1000/test"
    )

    assert len(result) == 1
    assert (await service.get_collection(collection["collection_id"]))["documents"] == result


async def test_add_file_uses_normalized_upload(monkeypatch, tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Upload")
    captured: dict[str, object] = {}

    def fake_normalize_upload(filename: str, content: bytes, media_type: str | None = None):
        captured.update(filename=filename, content=content, media_type=media_type)
        return NormalizedImportBatch(
            documents=(
                NormalizedImportDocument(
                    source_document_id="srcdoc_upload",
                    origin_channel="upload",
                    original_filename=filename,
                    stored_filename="normalized.pdf",
                    media_type=media_type,
                    storage_payload_base64=base64.b64encode(content).decode("ascii"),
                ),
            ),
            text_units=(),
            source_metadata=NormalizedImportSourceMetadata(
                channel="upload",
                adapter_name="upload",
                ingested_at="2026-08-27T00:00:00+00:00",
            ),
        )

    monkeypatch.setattr(collection_service_module, "normalize_upload", fake_normalize_upload)
    uploaded = await service.add_document(
        collection["collection_id"], "paper.pdf", b"pdf", "application/pdf"
    )

    assert captured == {
        "filename": "paper.pdf",
        "content": b"pdf",
        "media_type": "application/pdf",
    }
    assert uploaded["stored_filename"] == "normalized.pdf"
