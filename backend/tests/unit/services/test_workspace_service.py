from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from zipfile import ZipFile

import pytest
from application.source import (
    workspace_service,
    source_archive_service,
    source_import_service,
)
from application.source.source_archive_service import (
    WorkspaceSourceArchiveError,
    DocumentSourceUnavailableError,
)
from domain.source import Document
from exceptions import (
    RequestInvalidException,
    ResourceConflictException,
    ResourceNotFoundException,
)
from infra.persistence.file.object_store import FileObjectStore
from infra.persistence.file import FileWorkspace
from pypdf import PdfWriter
from repositories.workspace_repository import StoredDocument

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


def test_source_archive_operations_have_a_direct_owner() -> None:
    assert "build_source_archive" not in workspace_service.__dict__
    assert "resolve_document_source_file" not in workspace_service.__dict__
    assert "build_source_archive" in source_archive_service.__dict__
    assert "resolve_document_source_file" in source_archive_service.__dict__
    assert "add_document" not in workspace_service.__dict__
    assert "add_document" in source_import_service.__dict__


async def test_workspace_contains_its_uploaded_documents(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
    object_store,
) -> None:
    service = workspace_service
    workspace = await service.create_workspace("Current papers")
    first = await source_import_service.add_document(
        workspace.workspace.workspace_id,
        "first.pdf",
        _valid_pdf_bytes("First paper"),
        "application/pdf",
        user_id="local-user",
    )
    second = await source_import_service.add_document(
        workspace.workspace.workspace_id,
        "second.pdf",
        _valid_pdf_bytes("Second paper"),
        "application/pdf",
        user_id="local-user",
    )

    current = await service.get_workspace(workspace.workspace.workspace_id)

    assert current.documents == (first, second)
    assert len(current.documents) == 2
    assert current.workspace.status == "uploaded"


async def test_shared_workspace_files_preserve_workspace_isolation(
    tmp_path, monkeypatch, *, postgres_session_factory
) -> None:
    first_workspace = FileWorkspace(tmp_path / "first-app")
    second_workspace = FileWorkspace(tmp_path / "second-app")
    first_store = FileObjectStore(first_workspace.root_dir)
    second_store = FileObjectStore(second_workspace.root_dir)
    from infra.persistence.file import workspace_files as workspace_module, object_store as store_module

    monkeypatch.setattr(workspace_module, "Workspace", first_workspace, raising=False)
    monkeypatch.setattr(store_module, "Store", first_store, raising=False)
    first = await workspace_service.create_workspace(
        "LPBF porosity",
    )
    second = await workspace_service.create_workspace(
        "Tensile comparison",
    )
    first_content = _valid_pdf_bytes("Porosity")
    second_content = _valid_pdf_bytes("Tensile")
    first_document = await source_import_service.add_document(
        first.workspace.workspace_id, "porosity.pdf", first_content,
        user_id="local-user",
    )
    second_document = await source_import_service.add_document(
        second.workspace.workspace_id, "tensile.pdf", second_content,
        user_id="local-user",
    )
    monkeypatch.setattr(store_module, "Store", second_store)
    with pytest.raises(DocumentSourceUnavailableError):
        await source_archive_service.resolve_document_source_file(
            first.workspace.workspace_id, first_document.document.document_id,
            user_id="local-user",
        )
    monkeypatch.setattr(store_module, "Store", first_store)
    await workspace_service.delete_workspace_for_user(
        first.workspace.workspace_id, "local-user",
    )
    assert not first_workspace.get_paths(first.workspace.workspace_id).workspace_dir.exists()
    assert first_store.read(
        second_document.storage_key, second_document.document.sha256
    ) == second_content
    surviving = await workspace_service.get_workspace(second.workspace.workspace_id)
    assert surviving.documents == (second_document,)


async def test_upload_retry_reuses_content_identity_and_preserves_preparation(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
    object_store,
) -> None:
    service = workspace_service
    workspace_id = (await service.create_workspace('LPBF papers')).workspace.workspace_id
    importer = source_import_service
    content = _valid_pdf_bytes("LPBF heat treatment")
    original = await importer.add_document(
        workspace_id, "study.pdf", content, "application/pdf", user_id="local-user",
    )
    await service.update_document_preparation(
        workspace_id,
        original.document.document_id,
        status="ready",
        preparation_fingerprint="prepared",
        parser_version="parser-1",
        document_analysis_version="profile-1",
    )
    prepared = (await service.get_workspace(workspace_id)).documents[0]

    recovered = await importer.add_document(
        workspace_id,
        "renamed.pdf",
        content,
        "application/pdf",
        reuse_existing=True,
        user_id="local-user",
    )
    assert recovered == prepared
    input_dir = workspace_files.get_paths(workspace_id).input_dir
    assert [path.name for path in input_dir.iterdir()] == [Path(original.storage_key).name]
    with pytest.raises(
        ResourceConflictException, match="Document content already exists"
    ):
        await importer.add_document(
            workspace_id, "again.pdf", content, "application/pdf", user_id="local-user",
        )
    assert [path.name for path in input_dir.iterdir()] == [Path(original.storage_key).name]
    different = await importer.add_document(
        workspace_id,
        "study.pdf",
        _valid_pdf_bytes("Different experiment"),
        "application/pdf",
        reuse_existing=True,
        user_id="local-user",
    )
    assert different.document.document_id != original.document.document_id
    assert len((await service.get_workspace(workspace_id)).documents) == 2
    assert len(list(input_dir.iterdir())) == 2


async def test_workspace_update_preserves_documents(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
    object_store,
) -> None:
    service = workspace_service
    workspace = await service.create_workspace("Before")
    document = await source_import_service.add_document(
        workspace.workspace.workspace_id,
        "paper.pdf",
        _valid_pdf_bytes(),
        "application/pdf",
        user_id="local-user",
    )

    updated = await service.update_workspace(
        workspace.workspace.workspace_id, name="After", status="running"
    )

    assert updated.workspace.name == "After"
    assert updated.workspace.status == "running"
    assert updated.documents == (document,)


async def test_missing_workspace_is_not_inferred_from_workspace(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
) -> None:
    service = workspace_service
    workspace_files.create_workspace_dirs("col_orphaned_workspace")

    with pytest.raises(ResourceNotFoundException, match="workspace not found"):
        await service.get_workspace("col_orphaned_workspace")


async def test_upload_registers_document_and_preserves_original_bytes(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
    object_store,
) -> None:
    service = workspace_service
    workspace = await service.create_workspace("Uploaded Workspace")
    content = b"  Experimental Section\r\nMix and anneal.\r\n"
    document = await source_import_service.add_document(
        workspace.workspace.workspace_id,
        "../paper.TXT",
        content,
        " text/plain ",
        user_id="local-user",
    )

    assert document.document.document_id.startswith("doc_")
    assert document.document.filename == "paper.TXT"
    assert Path(document.storage_key).name == document.document.document_id
    assert document.document.media_type == "text/plain"
    assert document.status == "stored"
    assert document.document.size_bytes == len(content)
    assert document.document.sha256 == sha256(content).hexdigest()

    assert (
        object_store.read(document.storage_key, document.document.sha256)
        == content
    )
    current = await service.get_workspace(workspace.workspace.workspace_id)
    assert current.documents == (document,)


async def test_failed_document_registration_removes_unregistered_bytes(
    monkeypatch,
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
    object_store,
) -> None:
    service = workspace_service
    workspace = await service.create_workspace("Failed upload")
    written_keys: list[str] = []
    write = object_store.write

    def capture_write(storage_key, payload, sha256) -> None:
        write(storage_key, payload, sha256)
        written_keys.append(storage_key)

    async def fail_add_documents(*_args, **_kwargs) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service.WorkspaceRepo, "add_documents", fail_add_documents)
    monkeypatch.setattr(object_store, "write", capture_write)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await source_import_service.add_document(
            workspace.workspace.workspace_id,
            "failed.txt",
            b"not registered",
            "text/plain",
            user_id="local-user",
        )

    assert len(written_keys) == 1
    with pytest.raises(FileNotFoundError):
        object_store.read(
            written_keys[0], sha256(b"not registered").hexdigest()
        )
    assert (await service.get_workspace(workspace.workspace.workspace_id)).documents == ()


async def test_registration_error_preserves_bytes_already_registered(
    monkeypatch,
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
    object_store,
) -> None:
    service = workspace_service
    workspace_id = (await service.create_workspace('Committed upload')).workspace.workspace_id
    add_documents = service.WorkspaceRepo.add_documents
    content = b"Experimental Section\nMix and anneal."

    async def commit_then_fail(*args, **kwargs) -> None:
        await add_documents(*args, **kwargs)
        raise RuntimeError("connection lost after commit")

    monkeypatch.setattr(service.WorkspaceRepo, "add_documents", commit_then_fail)
    with pytest.raises(RuntimeError, match="connection lost after commit"):
        await source_import_service.add_document(
            workspace_id, "paper.txt", content, "text/plain", user_id="local-user",
        )

    documents = (await service.get_workspace(workspace_id)).documents
    assert len(documents) == 1
    assert (
        object_store.read(documents[0].storage_key, documents[0].document.sha256)
        == content
    )


async def test_source_archive_uses_document_ids(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
    object_store,
) -> None:
    service = workspace_service
    workspace = await service.create_workspace("Reproduction sources")
    first_payload = _valid_pdf_bytes("First")
    second_payload = _valid_pdf_bytes("Second")
    first = await source_import_service.add_document(
        workspace.workspace.workspace_id,
        "first.pdf",
        first_payload,
        "application/pdf",
        user_id="local-user",
    )
    second = await source_import_service.add_document(
        workspace.workspace.workspace_id,
        "second.pdf",
        second_payload,
        "application/pdf",
        user_id="local-user",
    )

    result = await source_archive_service.build_source_archive(
        workspace.workspace.workspace_id,
        [second.document.document_id, first.document.document_id],
        user_id="local-user",
    )
    try:
        with ZipFile(result["file"]) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert [item["document_id"] for item in manifest["documents"]] == [
                second.document.document_id,
                first.document.document_id,
            ]
            assert (
                archive.read(manifest["documents"][0]["archive_path"]) == second_payload
            )
            assert (
                archive.read(manifest["documents"][1]["archive_path"]) == first_payload
            )
    finally:
        result["file"].close()


async def test_source_archive_rejects_unknown_document(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
    object_store,
) -> None:
    service = workspace_service
    workspace = await service.create_workspace("Reproduction sources")

    with pytest.raises(ResourceNotFoundException) as exc_info:
        await source_archive_service.build_source_archive(
            workspace.workspace.workspace_id, ["doc_missing"], user_id="local-user",
        )

    assert exc_info.value.data["code"] == "workspace_source_document_not_found"
    assert exc_info.value.data["document_id"] == "doc_missing"


async def test_source_resolution_reads_only_current_workspace_documents(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
    object_store,
) -> None:
    service = workspace_service
    first_workspace = await service.create_workspace("First")
    second_workspace = await service.create_workspace("Second")
    first = await source_import_service.add_document(
        first_workspace.workspace.workspace_id,
        "first.pdf",
        _valid_pdf_bytes("First"),
        "application/pdf",
        user_id="local-user",
    )
    second = await source_import_service.add_document(
        second_workspace.workspace.workspace_id,
        "second.pdf",
        _valid_pdf_bytes("Second"),
        "application/pdf",
        user_id="local-user",
    )

    source = await source_archive_service.resolve_document_source_file(
        first_workspace.workspace.workspace_id, first.document.document_id, user_id="local-user",
    )
    assert source["filename"] == "first.pdf"
    with pytest.raises(ResourceNotFoundException, match="Document not found"):
        await source_archive_service.resolve_document_source_file(
            first_workspace.workspace.workspace_id,
            second.document.document_id,
            user_id="local-user",
        )


async def test_source_resolution_rejects_invalid_storage_key(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
    object_store,
) -> None:
    service = workspace_service
    workspace = await service.create_workspace("Unsafe")
    document = StoredDocument(
        document=Document(
            document_id="doc_unsafe",
            filename="unsafe.pdf",
            sha256="a" * 64,
            media_type="application/pdf",
            size_bytes=1,
        ),
        storage_key="other/input/unsafe.pdf",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    await service.WorkspaceRepo.add_documents(
        workspace.workspace.workspace_id,
        (document,),
        updated_at=document.created_at,
    )

    with pytest.raises(DocumentSourceUnavailableError) as exc_info:
        await source_archive_service.resolve_document_source_file(
            workspace.workspace.workspace_id,
            document.document.document_id,
            user_id="local-user",
        )
    assert exc_info.value.data["code"] == "document_source_path_invalid"


async def test_delete_workspace_removes_documents_and_bytes(
    tmp_path,
    *,
    postgres_session_factory,
    workspace_files,
    object_store,
) -> None:
    service = workspace_service
    workspace = await service.create_workspace("Delete")
    uploaded = await source_import_service.add_document(
        workspace.workspace.workspace_id,
        "paper.txt",
        b"Methods",
        "text/plain",
        user_id="local-user",
    )

    await service.delete_workspace(workspace.workspace.workspace_id)

    with pytest.raises(ResourceNotFoundException):
        await service.get_workspace(workspace.workspace.workspace_id)
    with pytest.raises(FileNotFoundError):
        object_store.read(uploaded.storage_key, uploaded.document.sha256)


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
    tmp_path,
    filename,
    content,
    media_type,
    message,
    *,
    postgres_session_factory,
    workspace_files,
    object_store,
) -> None:
    service = workspace_service
    workspace = await service.create_workspace("Upload")
    workspace_id = workspace.workspace.workspace_id

    with pytest.raises(RequestInvalidException, match=message):
        await source_import_service.add_document(
            workspace_id, filename, content, media_type, user_id="local-user",
        )

    assert (await service.get_workspace(workspace_id)).documents == ()
    assert list(workspace_files.get_paths(workspace_id).input_dir.iterdir()) == []
