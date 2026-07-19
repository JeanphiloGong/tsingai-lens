from __future__ import annotations

from hashlib import sha256

import pytest

from domain.source import (
    CollectionFileRecord,
    CollectionImportDocumentRecord,
    CollectionImportRecord,
    CollectionRecord,
)
from infra.persistence.file.object_store import FileObjectStore
from infra.persistence.memory import MemoryCollectionRepository
from scripts import export_source_tables as export_script


def test_collection_input_rows_use_registered_storage_key(tmp_path):
    collections_root = tmp_path / "collections"
    collection_dir = collections_root / "col_demo"
    collection_dir.mkdir(parents=True)
    payload = b"%PDF-1.4\nregistered input\n"
    storage_key = "col_demo/input/paper.pdf"
    digest = sha256(payload).hexdigest()
    FileObjectStore(collections_root).write(storage_key, payload, digest)
    repository = MemoryCollectionRepository()
    repository.add_collection(
        CollectionRecord.create(
            collection_id="col_demo",
            name="Demo",
            description=None,
            now_iso="2026-07-19T00:00:00+00:00",
        )
    )
    file_record = CollectionFileRecord(
        file_id="file_1",
        collection_id="col_demo",
        object_id="obj_1",
        object_kind="source_input",
        original_filename="paper.pdf",
        stored_filename="paper.pdf",
        storage_key=storage_key,
        sha256=digest,
        media_type="application/pdf",
        status="stored",
        size_bytes=len(payload),
        created_at="2026-07-19T00:00:00+00:00",
    )
    repository.add_collection_import(
        CollectionImportRecord(
            import_id="imp_1",
            collection_id="col_demo",
            channel="upload",
            adapter_name="upload",
            adapter_version=None,
            raw_locator="paper.pdf",
            goal_context=None,
            warnings=(),
            ingested_at=file_record.created_at,
            documents=(
                CollectionImportDocumentRecord(
                    source_document_id="srcdoc_1",
                    origin_channel="upload",
                    file=file_record,
                    language=None,
                    ingest_status="normalized",
                    text_units=(),
                ),
            ),
        ),
        updated_at=file_record.created_at,
    )

    rows = export_script._collection_input_rows(repository, "col_demo")

    assert rows == [
        {
            "id": "srcdoc_1",
            "title": "paper.pdf",
            "creation_date": "2026-07-19T00:00:00+00:00",
            "source_path": storage_key,
            "storage_key": storage_key,
            "sha256": digest,
            "source_type": "pdf",
        }
    ]

    repository.list_collection_imports = lambda _collection_id: ()

    assert export_script._collection_input_rows(repository, "col_demo") == [
        {
            "id": "file_1",
            "title": "paper.pdf",
            "creation_date": "2026-07-19T00:00:00+00:00",
            "source_path": storage_key,
            "storage_key": storage_key,
            "sha256": digest,
            "source_type": "pdf",
        }
    ]


def test_collection_input_rows_do_not_scan_input_directory(tmp_path):
    collection_dir = tmp_path / "collections" / "col_demo" / "input"
    collection_dir.mkdir(parents=True)
    (collection_dir / "unregistered.pdf").write_bytes(b"%PDF-1.4")
    repository = MemoryCollectionRepository()

    assert export_script._collection_input_rows(repository, "col_demo") == []


def test_reparse_registered_input_verifies_object_hash(monkeypatch, tmp_path):
    collections_root = tmp_path / "collections"
    collection_dir = collections_root / "col_demo"
    collection_dir.mkdir(parents=True)
    payload = b"%PDF-1.4\nregistered input\n"
    storage_key = "col_demo/input/paper.pdf"
    digest = sha256(payload).hexdigest()
    FileObjectStore(collections_root).write(storage_key, payload, digest)
    repository = MemoryCollectionRepository()
    repository.add_collection(
        CollectionRecord.create(
            collection_id="col_demo",
            name="Demo",
            description=None,
            now_iso="2026-07-19T00:00:00+00:00",
        )
    )
    file_record = CollectionFileRecord(
        file_id="file_1",
        collection_id="col_demo",
        object_id="obj_1",
        object_kind="source_input",
        original_filename="paper.pdf",
        stored_filename="paper.pdf",
        storage_key=storage_key,
        sha256=digest,
        media_type="application/pdf",
        status="stored",
        size_bytes=len(payload),
        created_at="2026-07-19T00:00:00+00:00",
    )
    repository.add_collection_import(
        CollectionImportRecord(
            import_id="imp_1",
            collection_id="col_demo",
            channel="upload",
            adapter_name="upload",
            adapter_version=None,
            raw_locator="paper.pdf",
            goal_context=None,
            warnings=(),
            ingested_at=file_record.created_at,
            documents=(
                CollectionImportDocumentRecord(
                    source_document_id="srcdoc_1",
                    origin_channel="upload",
                    file=file_record,
                    language=None,
                    ingest_status="normalized",
                    text_units=(),
                ),
            ),
        ),
        updated_at=file_record.created_at,
    )
    (collections_root / storage_key).write_bytes(b"tampered")
    monkeypatch.setattr(export_script, "build_pdf_converter", lambda: object())

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        export_script._reparse_collection_inputs(
            backend_root=tmp_path,
            collection_dir=collection_dir,
            collection_repository=repository,
            document_id=None,
            limit=None,
        )
