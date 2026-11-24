"""Explicit researcher, workspace and document prerequisites for database tests."""

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256

from domain.source import Workspace, Document
from repositories.workspace_repository import (
    WorkspaceRepository,
    StoredWorkspace,
    StoredDocument,
)
from domain.core import ResearchObjective
from repositories.objective_repository import ObjectiveRepository


async def read_tool_calls(repository, session_id: str):
    messages = await repository.read_messages(session_id)
    return tuple([
        await repository.read_tool_call(request.tool_call_id)
        for message in messages for request in message.tool_calls
    ])


async def read_tool_results(repository, session_id: str):
    return tuple(
        message.tool_result for message in await repository.read_messages(session_id)
        if message.tool_result is not None
    )


async def seed_objective(session_factory, workspace_id: str, objective_id: str):
    await seed_workspace(session_factory, workspace_id)
    repository = ObjectiveRepository()
    existing = await repository.read_objective(workspace_id, objective_id)
    if existing is not None:
        return existing
    objective = ResearchObjective(
        workspace_id=workspace_id,
        objective_id=objective_id,
        question="How does laser power affect measured porosity?",
        material_scope=(),
        variables=("laser power",),
        outcomes=("porosity",),
        mechanisms=(),
        constraints=(),
        requested_comparator=None,
        seed_document_ids=(),
        excluded_document_ids=(),
        confidence=0.0,
        reason=None,
    )
    facts = await repository.read(workspace_id)
    await repository.replace(workspace_id, replace(
        facts, research_objectives=(*facts.research_objectives, objective),
    ))
    return objective


async def seed_workspace(
    session_factory,
    workspace_id: str,
    *,
    user_id: str = "user-1",
    document_ids: tuple[str, ...] = (),
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    workspaces = WorkspaceRepository()
    stored = await workspaces.read_workspace(workspace_id)
    if stored is None:
        await workspaces.add_workspace(
            StoredWorkspace(
                workspace=Workspace(
                    workspace_id=workspace_id,
                    owner_user_id=user_id,
                    name="Research papers",
                    description=None,
                    status="idle",
                ),
                created_at=now,
                updated_at=now,
            )
        )
        existing_ids = set()
    else:
        existing_ids = {item.document.document_id for item in stored.documents}
    documents = tuple(
        StoredDocument(
            document=Document(
                document_id=document_id,
                original_filename=f"{document_id}.txt",
                sha256=sha256(document_id.encode()).hexdigest(),
                media_type="text/plain",
                status="stored",
                size_bytes=1,
            ),
            stored_filename=f"{document_id}.txt",
            storage_key=f"{workspace_id}/input/{document_id}.txt",
            created_at=now,
        )
        for document_id in document_ids
        if document_id not in existing_ids
    )
    if documents:
        await workspaces.add_documents(workspace_id, documents, updated_at=now)
