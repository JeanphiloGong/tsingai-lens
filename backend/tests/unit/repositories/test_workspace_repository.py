from __future__ import annotations

from dataclasses import replace

import pytest

from domain.source import Workspace, Document
from repositories.workspace_repository import (
    StoredWorkspace,
    StoredDocument,
)
from repositories.workspace_repository import WorkspaceRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _workspace(workspace_id: str = "col_demo") -> StoredWorkspace:
    return StoredWorkspace(
        workspace=Workspace(
            workspace_id=workspace_id,
            owner_user_id="user_demo",
            name="Demo",
            description=None,
            status="idle",
        ),
        created_at="2026-08-27T00:00:00+00:00",
        updated_at="2026-08-27T00:00:00+00:00",
    )


def _document(document_id: str = "doc_demo", sha256: str = "a" * 64) -> StoredDocument:
    return StoredDocument(
        document=Document(
            document_id=document_id,
            original_filename="paper.pdf",
            sha256=sha256,
            media_type="application/pdf",
            status="stored",
            size_bytes=10,
        ),
        stored_filename=f"{document_id}.pdf",
        storage_key=f"col_demo/input/{document_id}.pdf",
        created_at="2026-08-27T00:01:00+00:00",
        updated_at="2026-08-27T00:01:00+00:00",
    )


async def test_workspace_repository_round_trips_current_aggregate(*, postgres_session_factory) -> None:
    repository = WorkspaceRepository()
    workspace = _workspace()
    document = _document()

    await repository.add_workspace(workspace)
    await repository.add_documents(
        workspace.workspace.workspace_id,
        (document,),
        updated_at=document.created_at,
    )

    stored = await repository.read_workspace(workspace.workspace.workspace_id)
    assert stored == replace(
        workspace,
        workspace=replace(workspace.workspace, status="uploaded"),
        updated_at=document.created_at,
        documents=(document,),
    )
    summary, = await repository.list_workspaces("user_demo")
    assert summary.workspace_id == stored.workspace.workspace_id
    assert summary.documents[0].document_id == document.document.document_id
    assert not hasattr(summary.documents[0], "storage_key")
    assert await repository.list_workspaces("user_other") == ()


async def test_workspace_repository_rejects_duplicate_document_content(*, postgres_session_factory) -> None:
    repository = WorkspaceRepository()
    workspace = _workspace()
    document = _document()
    await repository.add_workspace(workspace)
    await repository.add_documents(
        workspace.workspace.workspace_id,
        (document,),
        updated_at=document.created_at,
    )

    with pytest.raises(ValueError, match="content already exists"):
        await repository.add_documents(
            workspace.workspace.workspace_id,
            (_document("doc_other"),),
            updated_at=document.created_at,
        )

    assert (
        await repository.read_workspace(workspace.workspace.workspace_id)
    ).documents == (document,)


async def test_workspace_delete_removes_aggregate(*, postgres_session_factory) -> None:
    repository = WorkspaceRepository()
    workspace = _workspace()
    await repository.add_workspace(workspace)

    assert (
        await repository.delete_workspace(workspace.workspace.workspace_id) is True
    )
    assert await repository.read_workspace(workspace.workspace.workspace_id) is None
    assert (
        await repository.delete_workspace(workspace.workspace.workspace_id) is False
    )
