"""Source tools use the real collection lookup to distinguish unavailable papers."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from application.chat import CapabilityExecutionContext
from application.chat.capabilities.document_sources import (
    InspectDocumentSourcesCapability,
    InspectDocumentSourcesToolRequest,
    InspectTableCapability,
    InspectTableToolRequest,
    ReadSourceCapability,
    ReadSourceToolRequest,
    SearchSourcesCapability,
    SearchSourcesToolRequest,
)
from domain.source import Document
from repositories.collection_repository import StoredDocument
from repositories.source_artifact_repository import SourceArtifactRepository

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("state", ["missing", "unprepared", "database_failure"])
@pytest.mark.parametrize("capability,arguments", [
    (ReadSourceCapability, ReadSourceToolRequest(
        document_id="paper", source_kind="text_window", source_ref="methods",
    )),
    (InspectDocumentSourcesCapability, InspectDocumentSourcesToolRequest(document_id="paper")),
    (InspectTableCapability, InspectTableToolRequest(document_id="paper", table_ref="table")),
    (SearchSourcesCapability, SearchSourcesToolRequest(document_ids=["paper"], query="HIP")),
])
async def test_source_availability_uses_real_collection_lookup(
    state,
    capability,
    arguments,
    collection_service,
    monkeypatch,
    *,
    collection_workspace,
):
    collection = await collection_service.create_collection(
        "LPBF source inspection", owner_user_id="local-user",
        workspace=collection_workspace,
    )
    collection_id = collection["collection_id"]
    if state == "unprepared":
        await collection_service.CollectionRepo.add_documents(
            collection_id,
            (StoredDocument(
                document=Document(
                    document_id="paper", original_filename="lpbf.pdf", sha256="a" * 64,
                    media_type="application/pdf", status="uploaded", size_bytes=100,
                ),
                stored_filename="lpbf.pdf", storage_key="lpbf.pdf",
                created_at=collection["created_at"],
            ),),
            updated_at=collection["updated_at"],
        )
    failure = OperationalError("SELECT document", None, RuntimeError("database unavailable"))
    if state == "database_failure":
        monkeypatch.setattr(
            collection_service.CollectionRepo, "read_document", AsyncMock(side_effect=failure),
        )
    context = CapabilityExecutionContext(
        session_id="chat", user_id="local-user", collection_id=collection_id, tool_call_id="read",
    )
    handler = capability(
        collection_service=collection_service, source_artifact_repository=SourceArtifactRepository(),
    )
    if state == "database_failure":
        with pytest.raises(OperationalError) as raised:
            await handler.execute(context, arguments)
        assert raised.value is failure
    else:
        result = await handler.execute(context, arguments)
        assert result.error_code == (
            "document_not_found" if state == "missing" else "document_sources_not_ready"
        )
        assert result.data["missing_document_ids"] == (["paper"] if state == "missing" else [])
        assert result.data["unprepared_document_ids"] == (["paper"] if state == "unprepared" else [])
