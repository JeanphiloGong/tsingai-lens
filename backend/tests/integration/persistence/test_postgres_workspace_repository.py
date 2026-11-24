from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256

import pytest
from sqlalchemy import event

from domain.source import Workspace, Document
from infra.persistence.postgres.models.workspace import (
    DocumentORM,
    DocumentPreparationORM,
)
from repositories.workspace_repository import (
    WorkspaceRepository,
    StoredWorkspace,
    StoredDocument,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
async def workspace_repository(postgres_session_factory):
    return WorkspaceRepository()


def _workspace(workspace_id: str, owner_user_id: str = "user_a") -> StoredWorkspace:
    return StoredWorkspace(
        workspace=Workspace(
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            name=f"Workspace {workspace_id}",
            description=None,
            status="idle",
        ),
        created_at="2026-08-27T00:00:00+00:00",
        updated_at="2026-08-27T00:00:00+00:00",
    )


def _document(workspace_id: str, suffix: str) -> StoredDocument:
    digest = sha256(suffix.encode("utf-8")).hexdigest()
    return StoredDocument(
        document=Document(
            document_id=f"doc_{suffix}",
            original_filename=f"{suffix}.pdf",
            sha256=digest,
            media_type="application/pdf",
            status="stored",
            size_bytes=len(suffix),
        ),
        stored_filename=f"stored-{suffix}.pdf",
        storage_key=f"{workspace_id}/input/stored-{suffix}.pdf",
        created_at="2026-08-27T00:01:00+00:00",
        updated_at="2026-08-27T00:01:00+00:00",
    )


async def test_workspace_repository_round_trips_current_documents_by_owner(
    workspace_repository,
) -> None:
    first = _workspace("col_z")
    second = _workspace("col_a")
    other = _workspace("col_b", "user_b")
    await workspace_repository.add_workspace(first)
    await workspace_repository.add_workspace(second)
    await workspace_repository.add_workspace(other)
    document = _document(first.workspace.workspace_id, "first")
    await workspace_repository.add_documents(
        first.workspace.workspace_id,
        (document,),
        updated_at=document.created_at,
    )

    stored = await workspace_repository.read_workspace(first.workspace.workspace_id)
    assert stored == replace(
        first,
        workspace=replace(first.workspace, status="uploaded"),
        updated_at=document.created_at,
        documents=(document,),
    )
    assert [
        item.workspace_id
        for item in await workspace_repository.list_workspaces("user_a")
    ] == ["col_z", "col_a"]
    assert (
        await workspace_repository.read_workspace(second.workspace.workspace_id)
    ).documents == ()


async def test_workspace_repository_updates_metadata_without_losing_documents(
    workspace_repository,
) -> None:
    workspace = _workspace("col_update")
    document = _document(workspace.workspace.workspace_id, "paper")
    await workspace_repository.add_workspace(workspace)
    await workspace_repository.add_documents(
        workspace.workspace.workspace_id,
        (document,),
        updated_at=document.created_at,
    )
    stored = await workspace_repository.read_workspace(
        workspace.workspace.workspace_id
    )
    updated = replace(
        stored,
        workspace=replace(
            stored.workspace, name="Updated workspace", status="running"
        ),
        updated_at="2026-08-27T00:02:00+00:00",
    )

    assert await workspace_repository.update_workspace(updated) is True
    assert (
        await workspace_repository.read_workspace(workspace.workspace.workspace_id)
        == updated
    )


async def test_workspace_repository_round_trips_preparation_stage_fingerprints(
    postgres_session_factory, workspace_repository,
) -> None:
    workspace = _workspace("col_stage_fingerprints")
    document = _document(workspace.workspace.workspace_id, "paper")
    await workspace_repository.add_workspace(workspace)
    await workspace_repository.add_documents(
        workspace.workspace.workspace_id,
        (document,),
        updated_at=document.created_at,
    )
    async with postgres_session_factory.begin() as session:
        session.add(
            DocumentPreparationORM(
                document_id=document.document.document_id,
                source_format="pdf",
                parser_name="test-parser",
                parser_version="source-runtime.v1",
                source_fingerprint="a" * 64,
                artifact_json={"blocks": [], "tables": [], "figures": []},
                profile_json={
                    "document_id": document.document.document_id,
                    "title": "Paper",
                    "doc_type": "uncertain",
                    "profile_warnings": [],
                    "confidence": 0.0,
                    "source_fingerprint": "a" * 64,
                    "profile_version": "document-profile.v1+paper-map.v1",
                    "profile_fingerprint": "b" * 64,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    prepared = replace(
        document,
        document=replace(
            document.document,
            status="ready",
            parser_version="source-runtime.v1",
            document_analysis_version="document-profile.v1+paper-map.v1",
            source_fingerprint="a" * 64,
            profile_fingerprint="b" * 64,
            preparation_fingerprint="b" * 64,
        ),
        updated_at="2026-08-27T00:02:00+00:00",
    )

    assert await workspace_repository.update_document(prepared) is True
    assert (
        await workspace_repository.read_document(
            workspace.workspace.workspace_id,
            document.document.document_id,
        )
        == prepared
    )


async def test_workspace_repository_rejects_duplicate_document_content(
    workspace_repository,
) -> None:
    workspace = _workspace("col_duplicate_content")
    first = _document(workspace.workspace.workspace_id, "same")
    second = replace(
        first,
        document=replace(first.document, document_id="doc_other"),
        stored_filename="other.pdf",
        storage_key=f"{workspace.workspace.workspace_id}/input/other.pdf",
    )
    await workspace_repository.add_workspace(workspace)
    await workspace_repository.add_documents(
        workspace.workspace.workspace_id,
        (first,),
        updated_at=first.created_at,
    )

    with pytest.raises(
        ValueError,
        match="document content already exists in workspace",
    ):
        await workspace_repository.add_documents(
            workspace.workspace.workspace_id,
            (second,),
            updated_at=second.created_at,
        )

    assert (
        await workspace_repository.read_workspace(workspace.workspace.workspace_id)
    ).documents == (first,)


async def test_workspace_delete_removes_its_current_documents(
    postgres_session_factory, workspace_repository,
) -> None:
    workspace = _workspace("col_delete_documents")
    document = _document(workspace.workspace.workspace_id, "paper")
    await workspace_repository.add_workspace(workspace)
    await workspace_repository.add_documents(
        workspace.workspace.workspace_id,
        (document,),
        updated_at=document.created_at,
    )
    assert (
        await workspace_repository.delete_workspace(
            workspace.workspace.workspace_id
        )
        is True
    )
    assert (
        await workspace_repository.read_workspace(workspace.workspace.workspace_id)
        is None
    )
    async with postgres_session_factory() as session:
        assert await session.get(DocumentORM, document.document.document_id) is None


async def test_workspace_repository_retains_external_owner_id(
    workspace_repository,
) -> None:
    await workspace_repository.add_workspace(
        _workspace("col_external_owner", "external_subject")
    )
    stored = await workspace_repository.read_workspace("col_external_owner")
    assert stored.workspace.owner_user_id == "external_subject"


async def test_workspace_list_reads_only_summaries_in_two_queries(
    postgres_session_factory, workspace_repository, postgres_sync_engine
) -> None:
    for number in range(4):
        workspace = replace(
            _workspace(f"col_summary_{number}"),
            created_at=f"2026-08-27T00:00:0{number}+00:00",
            updated_at=f"2026-08-27T00:00:0{number}+00:00",
        )
        await workspace_repository.add_workspace(workspace)
        if number:
            documents = tuple(
                _document(workspace.workspace.workspace_id, f"{number}_{suffix}")
                for suffix in ("z", "a")
            )
            await workspace_repository.add_documents(
                workspace.workspace.workspace_id,
                documents,
                updated_at=documents[0].created_at,
            )
    await workspace_repository.add_workspace(_workspace("col_private", "user_b"))
    statements = []
    engine = postgres_session_factory.kw["bind"].sync_engine

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        summaries = await workspace_repository.list_workspaces("user_a")
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert len(statements) == 2
    assert all("document_preparations" not in sql for sql in statements)
    assert [item.workspace_id for item in summaries] == [f"col_summary_{i}" for i in range(4)]
    assert summaries[0].documents == ()
    assert [doc.document_id for doc in summaries[1].documents] == ["doc_1_z", "doc_1_a"]
    assert not hasattr(summaries[1].documents[0], "storage_key")
