"""Explicit researcher, collection and document prerequisites for database tests."""

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256

from domain.source import Collection, Document
from repositories.auth_repository import AuthRepository, AuthUserRecord
from repositories.collection_repository import (
    CollectionRepository,
    StoredCollection,
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


async def seed_objective(session_factory, collection_id: str, objective_id: str):
    await seed_collection(session_factory, collection_id)
    repository = ObjectiveRepository(session_factory)
    existing = await repository.read_objective(collection_id, objective_id)
    if existing is not None:
        return existing
    objective = ResearchObjective(
        collection_id=collection_id,
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
    facts = await repository.read(collection_id)
    await repository.replace(collection_id, replace(
        facts, research_objectives=(*facts.research_objectives, objective),
    ))
    return objective


async def seed_user(session_factory, user_id: str) -> None:
    users = AuthRepository(session_factory)
    if await users.read_user(user_id) is None:
        await users.add_user(AuthUserRecord(
            user_id=user_id, email=f"{user_id}@fixture.example.com",
            display_name="Researcher", password_hash="!",
            created_at=datetime.now(timezone.utc).isoformat(),
        ))


async def seed_collection(
    session_factory,
    collection_id: str,
    *,
    user_id: str = "user-1",
    document_ids: tuple[str, ...] = (),
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await seed_user(session_factory, user_id)
    collections = CollectionRepository(session_factory)
    stored = await collections.read_collection(collection_id)
    if stored is None:
        await collections.add_collection(StoredCollection(
            collection=Collection(
                collection_id=collection_id, owner_user_id=user_id,
                name="Research papers", description=None, status="idle",
            ),
            created_at=now, updated_at=now,
        ))
        existing_ids = set()
    else:
        existing_ids = {item.document.document_id for item in stored.documents}
    documents = tuple(
        StoredDocument(
            document=Document(
                document_id=document_id, original_filename=f"{document_id}.txt",
                sha256=sha256(document_id.encode()).hexdigest(), media_type="text/plain",
                status="stored", size_bytes=1,
            ),
            stored_filename=f"{document_id}.txt",
            storage_key=f"{collection_id}/input/{document_id}.txt", created_at=now,
        )
        for document_id in document_ids if document_id not in existing_ids
    )
    if documents:
        await collections.add_documents(collection_id, documents, updated_at=now)
