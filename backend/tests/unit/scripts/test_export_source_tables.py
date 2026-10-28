from __future__ import annotations

from hashlib import sha256

import pytest

from infra.persistence.file.object_store import FileObjectStore
from repositories.collection_repository import (
    StoredCollection,
    StoredDocument,
)
from scripts import export_source_tables as export_script
from domain.source import (
    Collection,
    Document,
    SourceDocument,
    SourceTable,
)
from types import SimpleNamespace
from unittest.mock import AsyncMock
from repositories.collection_repository import CollectionRepository
from repositories.source_artifact_repository import SourceArtifactRepository
from tests.support.postgres import seed_collection

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _repository_with_pdf(payload: bytes, *, postgres_session_factory) -> CollectionRepository:
    repository = CollectionRepository()
    collection = StoredCollection(
        collection=Collection(
            collection_id="col_demo",
            name="Demo",
            description=None,
            owner_user_id="local-user",
            status="idle",
        ),
        created_at="2026-08-27T00:00:00+00:00",
        updated_at="2026-08-27T00:00:00+00:00",
    )
    document = StoredDocument(
        document=Document(
            document_id="doc_1",
            original_filename="paper.pdf",
            sha256=sha256(payload).hexdigest(),
            media_type="application/pdf",
            status="stored",
            size_bytes=len(payload),
        ),
        stored_filename="paper.pdf",
        storage_key="col_demo/input/paper.pdf",
        created_at="2026-08-27T00:00:00+00:00",
    )
    await repository.add_collection(collection)
    await repository.add_documents(
        collection.collection.collection_id,
        (document,),
        updated_at=document.created_at,
    )
    return repository


async def test_collection_input_rows_use_collection_documents(tmp_path, *, postgres_session_factory) -> None:
    payload = b"%PDF-1.4\nregistered input\n"
    repository = await _repository_with_pdf(payload, postgres_session_factory=postgres_session_factory)

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


async def test_collection_input_rows_do_not_scan_input_directory(tmp_path, *, postgres_session_factory) -> None:
    input_dir = tmp_path / "collections" / "col_demo" / "input"
    input_dir.mkdir(parents=True)
    (input_dir / "unregistered.pdf").write_bytes(b"%PDF-1.4")

    assert await export_script._collection_input_rows(
        CollectionRepository(), "col_demo"
    ) == []


async def test_reparse_registered_input_verifies_object_hash(monkeypatch, tmp_path, *, postgres_session_factory) -> None:
    collections_root = tmp_path / "collections"
    collection_dir = collections_root / "col_demo"
    collection_dir.mkdir(parents=True)
    payload = b"%PDF-1.4\nregistered input\n"
    repository = await _repository_with_pdf(payload, postgres_session_factory=postgres_session_factory)
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


async def test_existing_source_table_export_keeps_table_rows(
    monkeypatch, tmp_path, *, postgres_session_factory
) -> None:
    document = SourceDocument(
        document_id="paper-1",
        document_order=1,
        title="Tensile study",
        text="Results",
        tables=(
            SourceTable(
                table_id="table-1",
                document_id="paper-1",
                table_order=1,
                caption_text="Tensile results",
                caption_block_id=None,
                page=5,
                heading_path="Results",
                column_headers=("Sample", "Strength (MPa)"),
                table_matrix=(("Sample", "Strength (MPa)"), ("A", "560")),
            ),
        ),
    )
    repository = SourceArtifactRepository()
    await seed_collection(postgres_session_factory, "col_demo", document_ids=("paper-1",))
    await repository.replace_document("col_demo", document)
    monkeypatch.setattr(
        export_script,
        "build_database_engine",
        lambda _settings: SimpleNamespace(dispose=AsyncMock()),
    )
    monkeypatch.setattr(export_script, "build_session_factory", lambda _engine: None)
    monkeypatch.setattr(
        export_script, "SourceArtifactRepository", lambda _sessions: repository
    )

    frames = await export_script._load_existing_artifacts(
        backend_root=tmp_path, collection_dir=tmp_path / "col_demo"
    )

    assert frames["documents"].iloc[0]["id"] == "paper-1"
    assert frames["tables"].iloc[0]["table_id"] == "table-1"
    assert "560" in frames["tables"].iloc[0]["table_markdown"]
    assert frames["table_rows"].empty
