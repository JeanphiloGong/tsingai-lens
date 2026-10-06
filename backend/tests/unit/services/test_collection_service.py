from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

import pytest
from pypdf import PdfWriter

from application.repositories.collection_repository import StoredDocument
from application.source.collection_service import CollectionService
from application.source.source_archive_service import (
    CollectionSourceArchiveError,
    DocumentSourceUnavailableError,
    SourceArchiveService,
)
from application.source.source_import_service import SourceImportService
from domain.chat.permissions import AUTO_ACTIONS
from domain.source import Document
from infra.persistence.memory import MemoryCollectionRepository
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


def test_source_archive_operations_have_a_direct_owner() -> None:
    assert "build_source_archive" not in CollectionService.__dict__
    assert "resolve_document_source_file" not in CollectionService.__dict__
    assert "build_source_archive" in SourceArchiveService.__dict__
    assert "resolve_document_source_file" in SourceArchiveService.__dict__
    assert "add_document" not in CollectionService.__dict__
    assert "add_document" in SourceImportService.__dict__


async def test_collection_contains_its_uploaded_documents(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Current papers")
    first = await _import_service(service).add_document(
        collection["collection_id"],
        "first.pdf",
        _valid_pdf_bytes("First paper"),
        "application/pdf",
    )
    second = await _import_service(service).add_document(
        collection["collection_id"],
        "second.pdf",
        _valid_pdf_bytes("Second paper"),
        "application/pdf",
    )

    current = await service.get_collection(collection["collection_id"])

    assert current["documents"] == [first, second]
    assert current["paper_count"] == 2
    assert current["status"] == "uploaded"


def _archive_service(collection_service: CollectionService) -> SourceArchiveService:
    return SourceArchiveService(
        repository=collection_service.repository,
        object_store=collection_service.object_store,
    )


def _import_service(collection_service: CollectionService) -> SourceImportService:
    return SourceImportService(
        repository=collection_service.repository,
        object_store=collection_service.object_store,
    )


async def test_upload_retry_reuses_content_identity_and_preserves_preparation(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection_id = (await service.create_collection("LPBF papers"))["collection_id"]
    importer = _import_service(service)
    content = _valid_pdf_bytes("LPBF heat treatment")
    original = await importer.add_document(collection_id, "study.pdf", content, "application/pdf")
    await service.update_document_preparation(
        collection_id, original["document_id"], status="ready",
        preparation_fingerprint="prepared", parser_version="parser-1",
        document_analysis_version="profile-1",
    )
    prepared = (await service.get_collection(collection_id))["documents"][0]

    recovered = await importer.add_document(
        collection_id, "renamed.pdf", content, "application/pdf", reuse_existing=True,
    )
    assert recovered == prepared
    input_dir = service.workspace.get_paths(collection_id).input_dir
    assert [path.name for path in input_dir.iterdir()] == [original["stored_filename"]]
    with pytest.raises(ValueError, match="document content already exists"):
        await importer.add_document(collection_id, "again.pdf", content, "application/pdf")
    assert [path.name for path in input_dir.iterdir()] == [original["stored_filename"]]
    different = await importer.add_document(
        collection_id, "study.pdf", _valid_pdf_bytes("Different experiment"),
        "application/pdf", reuse_existing=True,
    )
    assert different["document_id"] != original["document_id"]
    assert len((await service.get_collection(collection_id))["documents"]) == 2
    assert len(list(input_dir.iterdir())) == 2


async def test_collection_update_preserves_documents(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Before")
    document = await _import_service(service).add_document(
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


async def test_collection_agent_default_permission_is_owner_scoped(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Permission defaults", owner_user_id="user-1")
    expiry = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    saved = await service.set_agent_default_permission_for_user(
        collection["collection_id"],
        "user-1",
        mode="auto",
        actions=[],
        all_actions=True,
        expires_at=expiry,
        expected_revision=0,
    )

    assert saved["actions"] == sorted(AUTO_ACTIONS)
    assert (
        await service.get_agent_default_permission_for_user(
            collection["collection_id"], "user-1"
        )
    ) == saved
    with pytest.raises(FileNotFoundError):
        await service.get_agent_default_permission_for_user(
            collection["collection_id"], "other-user"
        )


async def test_missing_collection_is_not_inferred_from_workspace(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    service.workspace.create_collection_dirs("col_orphaned_workspace")

    with pytest.raises(FileNotFoundError, match="collection not found"):
        await service.get_collection("col_orphaned_workspace")


async def test_upload_registers_document_and_preserves_original_bytes(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Uploaded Collection")
    content = b"  Experimental Section\r\nMix and anneal.\r\n"
    document = await _import_service(service).add_document(
        collection["collection_id"], "../paper.TXT", content, " text/plain "
    )

    assert document["document_id"].startswith("doc_")
    assert document["original_filename"] == "paper.TXT"
    assert document["stored_filename"].endswith("_paper.txt")
    assert document["media_type"] == "text/plain"
    assert document["status"] == "stored"
    assert document["size_bytes"] == len(content)
    assert document["sha256"] == sha256(content).hexdigest()
    assert set(document) == {
        "document_id",
        "original_filename",
        "stored_filename",
        "storage_key",
        "sha256",
        "media_type",
        "status",
        "size_bytes",
        "created_at",
        "updated_at",
        "parser_version",
        "document_analysis_version",
        "source_fingerprint",
        "profile_fingerprint",
        "preparation_fingerprint",
    }
    assert service.object_store.read(
        document["storage_key"], document["sha256"]
    ) == content
    current = await service.get_collection(collection["collection_id"])
    assert current["documents"] == [document]


async def test_failed_document_registration_removes_unregistered_bytes(
    monkeypatch,
    tmp_path,
) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Failed upload")
    written_keys: list[str] = []
    write = service.object_store.write

    def capture_write(storage_key, payload, sha256) -> None:
        write(storage_key, payload, sha256)
        written_keys.append(storage_key)

    async def fail_add_documents(*_args, **_kwargs) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service.repository, "add_documents", fail_add_documents)
    monkeypatch.setattr(service.object_store, "write", capture_write)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await _import_service(service).add_document(
            collection["collection_id"], "failed.txt", b"not registered", "text/plain"
        )

    assert len(written_keys) == 1
    with pytest.raises(FileNotFoundError):
        service.object_store.read(written_keys[0], sha256(b"not registered").hexdigest())
    assert (await service.get_collection(collection["collection_id"]))["documents"] == []


async def test_registration_error_preserves_bytes_already_registered(monkeypatch, tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection_id = (await service.create_collection("Committed upload"))["collection_id"]
    add_documents = service.repository.add_documents
    content = b"Experimental Section\nMix and anneal."

    async def commit_then_fail(*args, **kwargs) -> None:
        await add_documents(*args, **kwargs)
        raise RuntimeError("connection lost after commit")

    monkeypatch.setattr(service.repository, "add_documents", commit_then_fail)
    with pytest.raises(RuntimeError, match="connection lost after commit"):
        await _import_service(service).add_document(
            collection_id, "paper.txt", content, "text/plain"
        )

    documents = (await service.get_collection(collection_id))["documents"]
    assert len(documents) == 1
    assert service.object_store.read(
        documents[0]["storage_key"], documents[0]["sha256"]
    ) == content


async def test_source_archive_uses_document_ids(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Reproduction sources")
    first_payload = _valid_pdf_bytes("First")
    second_payload = _valid_pdf_bytes("Second")
    first = await _import_service(service).add_document(
        collection["collection_id"], "first.pdf", first_payload, "application/pdf"
    )
    second = await _import_service(service).add_document(
        collection["collection_id"], "second.pdf", second_payload, "application/pdf"
    )

    result = await _archive_service(service).build_source_archive(
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
        await _archive_service(service).build_source_archive(
            collection["collection_id"], ["doc_missing"]
        )

    assert exc_info.value.code == "collection_source_document_not_found"
    assert exc_info.value.document_id == "doc_missing"


async def test_source_resolution_reads_only_current_collection_documents(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    first_collection = await service.create_collection("First")
    second_collection = await service.create_collection("Second")
    first = await _import_service(service).add_document(
        first_collection["collection_id"],
        "first.pdf",
        _valid_pdf_bytes("First"),
        "application/pdf",
    )
    second = await _import_service(service).add_document(
        second_collection["collection_id"],
        "second.pdf",
        _valid_pdf_bytes("Second"),
        "application/pdf",
    )

    source = await _archive_service(service).resolve_document_source_file(
        first_collection["collection_id"], first["document_id"]
    )
    assert source["filename"] == "first.pdf"
    with pytest.raises(FileNotFoundError, match="document not found"):
        await _archive_service(service).resolve_document_source_file(
            first_collection["collection_id"], second["document_id"]
        )


async def test_source_resolution_rejects_invalid_storage_key(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Unsafe")
    document = StoredDocument(
        document=Document(
            document_id="doc_unsafe",
            original_filename="unsafe.pdf",
            sha256="a" * 64,
            media_type="application/pdf",
            status="stored",
            size_bytes=1,
        ),
        stored_filename="unsafe.pdf",
        storage_key="other/input/unsafe.pdf",
        created_at="2026-08-27T00:00:00+00:00",
    )
    await service.repository.add_documents(
        collection["collection_id"],
        (document,),
        updated_at=document.created_at,
    )

    with pytest.raises(DocumentSourceUnavailableError) as exc_info:
        await _archive_service(service).resolve_document_source_file(
            collection["collection_id"], document.document.document_id
        )
    assert exc_info.value.code == "document_source_path_invalid"


async def test_delete_collection_removes_documents_and_bytes(tmp_path) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Delete")
    uploaded = await _import_service(service).add_document(
        collection["collection_id"], "paper.txt", b"Methods", "text/plain"
    )

    await service.delete_collection(collection["collection_id"])

    with pytest.raises(FileNotFoundError):
        await service.get_collection(collection["collection_id"])
    with pytest.raises(FileNotFoundError):
        service.object_store.read(uploaded["storage_key"], uploaded["sha256"])


@pytest.mark.parametrize(
    ("filename", "content", "media_type", "message"),
    [
        ("paper.pdf", _valid_pdf_bytes()[:100], "application/pdf", "PDF is damaged"),
        ("paper.txt", b"\xff", "text/plain", "text upload must be valid UTF-8"),
        ("paper.txt", b"", "text/plain", "uploaded file is empty"),
        ("paper.bin", b"\xff", "application/octet-stream", "unsupported upload type"),
    ],
)
async def test_invalid_upload_leaves_no_document_or_bytes(
    tmp_path, filename, content, media_type, message,
) -> None:
    service = build_test_collection_service(tmp_path / "collections")
    collection = await service.create_collection("Upload")
    collection_id = collection["collection_id"]

    with pytest.raises(ValueError, match=message):
        await _import_service(service).add_document(
            collection_id, filename, content, media_type
        )

    assert (await service.get_collection(collection_id))["documents"] == []
    assert list(service.workspace.get_paths(collection_id).input_dir.iterdir()) == []
