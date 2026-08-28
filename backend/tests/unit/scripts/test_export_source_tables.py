from __future__ import annotations

from hashlib import sha256

import pytest

from domain.source import Collection, Document
from infra.persistence.file.object_store import FileObjectStore
from infra.persistence.memory import MemoryCollectionRepository
from scripts import export_source_tables as export_script


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _repository_with_pdf(payload: bytes) -> MemoryCollectionRepository:
    repository = MemoryCollectionRepository()
    collection = Collection.create(
        collection_id="col_demo",
        name="Demo",
        description=None,
        now_iso="2026-08-27T00:00:00+00:00",
    )
    document = Document(
        document_id="doc_1",
        original_filename="paper.pdf",
        stored_filename="paper.pdf",
        storage_key="col_demo/input/paper.pdf",
        sha256=sha256(payload).hexdigest(),
        media_type="application/pdf",
        status="stored",
        size_bytes=len(payload),
        created_at="2026-08-27T00:00:00+00:00",
    )
    await repository.add_collection(collection)
    await repository.add_documents(
        collection.collection_id,
        (document,),
        updated_at=document.created_at,
    )
    return repository


async def test_collection_input_rows_use_collection_documents(tmp_path) -> None:
    payload = b"%PDF-1.4\nregistered input\n"
    repository = await _repository_with_pdf(payload)

    rows = await export_script._collection_input_rows(repository, "col_demo")

    assert rows == [
        {
            "id": "doc_1",
            "title": "paper.pdf",
            "creation_date": "2026-08-27T00:00:00+00:00",
            "source_path": "col_demo/input/paper.pdf",
            "storage_key": "col_demo/input/paper.pdf",
            "sha256": sha256(payload).hexdigest(),
            "source_type": "pdf",
        }
    ]


async def test_collection_input_rows_do_not_scan_input_directory(tmp_path) -> None:
    input_dir = tmp_path / "collections" / "col_demo" / "input"
    input_dir.mkdir(parents=True)
    (input_dir / "unregistered.pdf").write_bytes(b"%PDF-1.4")

    assert await export_script._collection_input_rows(
        MemoryCollectionRepository(), "col_demo"
    ) == []


async def test_reparse_registered_input_verifies_object_hash(monkeypatch, tmp_path) -> None:
    collections_root = tmp_path / "collections"
    collection_dir = collections_root / "col_demo"
    collection_dir.mkdir(parents=True)
    payload = b"%PDF-1.4\nregistered input\n"
    repository = await _repository_with_pdf(payload)
    FileObjectStore(collections_root).write(
        "col_demo/input/paper.pdf", payload, sha256(payload).hexdigest()
    )
    (collections_root / "col_demo/input/paper.pdf").write_bytes(b"tampered")
    monkeypatch.setattr(export_script, "build_pdf_converter", lambda: object())

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        await export_script._reparse_collection_inputs(
            backend_root=tmp_path,
            collection_dir=collection_dir,
            collection_repository=repository,
            document_id=None,
            limit=None,
        )
