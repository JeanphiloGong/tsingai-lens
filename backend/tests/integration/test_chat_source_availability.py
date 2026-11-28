"""Source tools use the real workspace lookup to distinguish unavailable papers."""

from application.source import agent_source_service as document_sources
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from agent.tools.document import InspectDocumentSourcesCapability, InspectTableCapability
from document.repositories.document_repository import DocumentRepo
from agent.tools.registry import ToolExecutionContext
from application.source.agent_source_service import (
    InspectDocumentSourcesToolRequest,
    InspectTableToolRequest,
    ReadSourceService,
    ReadSourceToolRequest,
    SearchSourcesService,
    SearchSourcesToolRequest,
)
from document.domain.document import Document
from repositories.workspace_repository import StoredDocument
from document.repositories.source_repository import SourceRepository


pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("state", ["missing", "unprepared", "database_failure"])
@pytest.mark.parametrize("capability,arguments", [
    (ReadSourceService, ReadSourceToolRequest(
        document_id="paper", source_kind="text_window", source_ref="methods",
    )),
    (InspectDocumentSourcesCapability, InspectDocumentSourcesToolRequest(document_id="paper")),
    (InspectTableCapability, InspectTableToolRequest(document_id="paper", table_ref="table")),
    (SearchSourcesService, SearchSourcesToolRequest(document_ids=["paper"], query="HIP")),
])
async def test_source_availability_uses_real_workspace_lookup(
    state,
    capability,
    arguments,
    workspace_service,
    monkeypatch,
    *,
    workspace_files,
):
    workspace = await workspace_service.create_workspace(
        "LPBF source inspection", owner_user_id="local-user",
    )
    workspace_id = workspace.workspace.workspace_id
    if state == "unprepared":
        await workspace_service.WorkspaceRepo.add_documents(
            workspace_id,
            (StoredDocument(
                document=Document(
                    document_id="paper", filename="lpbf.pdf", sha256="a" * 64,
                    media_type="application/pdf", size_bytes=100,
                ),
                storage_key=f"{workspace_id}/input/paper",
                created_at=workspace.created_at,
            ),),
            updated_at=workspace.updated_at,
        )
    failure = OperationalError("SELECT document", None, RuntimeError("database unavailable"))
    if state == "database_failure":
        monkeypatch.setattr(
            workspace_service.WorkspaceRepo, "read_document", AsyncMock(side_effect=failure),
        )
    context = ToolExecutionContext(
        operation_id="operation",
        task_id="chat", user_id="local-user", workspace_id=workspace_id, tool_call_id="read",
    )
    document_sources.workspace_service = workspace_service
    document_sources.SourceRepo = SourceRepository()
    handler = capability()
    if isinstance(handler, (InspectDocumentSourcesCapability, InspectTableCapability)):
        if state == "database_failure":
            monkeypatch.setattr(DocumentRepo, "read", AsyncMock(side_effect=failure))
        kwargs = dict(context=context, arguments=arguments)
    else:
        kwargs = dict(user_id=context.user_id, workspace_id=context.workspace_id,
                      tool_call_id=context.tool_call_id, max_result_tokens=context.max_result_tokens,
                      arguments=arguments)
    if state == "database_failure":
        with pytest.raises(OperationalError) as raised:
            await handler.execute(**kwargs)
        assert raised.value is failure
    else:
        result = await handler.execute(**kwargs)
        assert result.error_code == (
            "document_not_found" if state == "missing" else "document_sources_not_ready"
        )
        assert result.data["missing_document_ids"] == (["paper"] if state == "missing" else [])
        assert result.data["unprepared_document_ids"] == (["paper"] if state == "unprepared" else [])
