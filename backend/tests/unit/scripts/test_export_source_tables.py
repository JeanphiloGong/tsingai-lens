from __future__ import annotations

from hashlib import sha256
import json

import pytest

from infra.persistence.file.object_store import FileObjectStore
from scripts import export_source_tables as export_script


def test_collection_input_rows_use_registered_storage_key(tmp_path):
    collections_root = tmp_path / "collections"
    collection_dir = collections_root / "col_demo"
    collection_dir.mkdir(parents=True)
    payload = b"%PDF-1.4\nregistered input\n"
    storage_key = "col_demo/input/paper.pdf"
    digest = sha256(payload).hexdigest()
    FileObjectStore(collections_root).write(storage_key, payload, digest)
    (collection_dir / "import_manifest.json").write_text(
        json.dumps(
            {
                "imports": [
                    {
                        "ingested_at": "2026-07-19T00:00:00+00:00",
                        "documents": [
                            {
                                "source_document_id": "srcdoc_1",
                                "original_filename": "paper.pdf",
                                "stored_filename": "paper.pdf",
                                "storage_key": storage_key,
                                "sha256": digest,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rows = export_script._collection_input_rows(collection_dir)

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


def test_reparse_registered_input_verifies_object_hash(monkeypatch, tmp_path):
    collections_root = tmp_path / "collections"
    collection_dir = collections_root / "col_demo"
    collection_dir.mkdir(parents=True)
    payload = b"%PDF-1.4\nregistered input\n"
    storage_key = "col_demo/input/paper.pdf"
    digest = sha256(payload).hexdigest()
    FileObjectStore(collections_root).write(storage_key, payload, digest)
    (collection_dir / "import_manifest.json").write_text(
        json.dumps(
            {
                "imports": [
                    {
                        "documents": [
                            {
                                "source_document_id": "srcdoc_1",
                                "original_filename": "paper.pdf",
                                "stored_filename": "paper.pdf",
                                "storage_key": storage_key,
                                "sha256": digest,
                            }
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (collections_root / storage_key).write_bytes(b"tampered")
    monkeypatch.setattr(export_script, "build_pdf_converter", lambda: object())

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        export_script._reparse_collection_inputs(
            backend_root=tmp_path,
            collection_dir=collection_dir,
            document_id=None,
            limit=None,
        )
