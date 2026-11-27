from __future__ import annotations

import pytest

from document.domain import Document, DocumentProfile
from document.repositories import (
    DocumentNotFound,
    DocumentRepository,
    ProfileRepository,
)
from repositories.workspace_repository import StoredDocument, StoredWorkspace, WorkspaceRepository
from workspace.domain import Workspace
from tests.integration.persistence.test_postgres_source_artifacts import NOW

pytestmark = pytest.mark.anyio


async def test_document_and_profile_repositories_share_workspace_scope_and_session(
    postgres_session_factory,
):
    workspace_repository = WorkspaceRepository()
    await workspace_repository.add_workspace(
        StoredWorkspace(
            workspace=Workspace(
                workspace_id="workspace-v2",
                owner_user_id="user-v2",
                name="V2",
                description=None,
                status="idle",
            ),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await workspace_repository.add_documents(
        "workspace-v2",
        (
            StoredDocument(
                document=Document(
                    document_id="document-v2",
                    filename="paper.pdf",
                    sha256="a" * 64,
                    media_type="application/pdf",
                    size_bytes=10,
                ),
                storage_key="workspace-v2/input/document-v2",
                created_at=NOW,
                updated_at=NOW,
            ),
        ),
        updated_at=NOW,
    )
    profile = DocumentProfile(
        document_id="document-v2",
        doc_type="experimental",
        description="A prepared experimental paper.",
        source_fingerprint="source-v2",
        profile_fingerprint="profile-v2",
        profile_version="document_profile.v2",
        generated_at="2026-11-27T00:00:00Z",
    )
    profiles = ProfileRepository()
    documents = DocumentRepository()
    async with postgres_session_factory() as db, db.begin():
        await profiles.replace("workspace-v2", profile, db=db)
        loaded_profile = await profiles.read("workspace-v2", "document-v2", db=db)
        loaded_document = await documents.read_document(
            workspace_id="workspace-v2", document_id="document-v2", db=db
        )
    assert loaded_profile == profile
    assert loaded_document.filename == "paper.pdf"
    with pytest.raises(DocumentNotFound):
        await documents.read_document(
            workspace_id="other-workspace", document_id="document-v2"
        )
