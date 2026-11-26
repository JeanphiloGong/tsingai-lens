import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.source import agent_workspace_service as workspace_context
from application.source.agent_workspace_service import (
    BrowseWorkspacePapersService,
    BrowseWorkspacePapersToolRequest,
)
from agent.tools.registry import ToolExecutionContext
from agent.application.context_builder import ChatContextBuilder
from agent.application.model import ResearchWorkingNotesModelOutput
from domain.chat import ChatMessage, ChatMessageRole, ChatResourceRef, ChatToolResult


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_source_model_message_keeps_body_and_citations_without_duplicate_metadata():
    source = {"source_kind": "text_window", "source_type": "text", "block_type": "paragraph",
              "source_ref": "block-1", "source_label": "S001", "source_digest": "a" * 64,
              "page": 3, "heading_path": "Results", "content": "Elongation was measured.",
              "content_truncated": False, "canonical_length": 24, "estimated_tokens": 7}
    href = "/workspaces/col/documents/doc?view=parsed-paper&source_ref=block-1&page=3"
    result = ChatToolResult(
        tool_call_id="read", status="succeeded",
        data={"document": {"document_id": "doc", "title": "IN718"}, "sources": [source],
              "source_label_to_ref": {"S001": "block-1"}, "next_offset": None},
        resource_refs=(ChatResourceRef("source", "doc:block-1", href),),
    )
    before = asdict(result)
    message = ChatMessage(
        message_id="result", session_id="chat", role=ChatMessageRole.TOOL,
        content=json.dumps(before), tool_call_id="read", tool_result=result,
        created_at="2026-11-01T00:00:00+00:00",
    )
    content = json.loads(ChatContextBuilder.model_message(message)["content"])
    projected = content["data"]["sources"][0]
    for key in ("content", "source_ref", "source_kind", "source_digest", "source_label",
                "page", "heading_path", "content_truncated"):
        assert projected[key] == source[key]
    assert projected["href"] == href
    assert "source_label_to_ref" not in content["data"]
    assert "resource_refs" not in content
    assert "estimated_tokens" not in projected
    assert asdict(result) == before


@pytest.mark.anyio
async def test_default_browse_fits_many_identities_and_keeps_exact_continuation(monkeypatch):
    records = tuple(SimpleNamespace(
        document=SimpleNamespace(document_id=f"doc-{i}", original_filename=f"IN718 {i}.pdf", status="ready"),
        stored_filename=f"IN718 {i}.pdf",
    ) for i in range(100))
    monkeypatch.setattr(workspace_context.workspace_service, "get_workspace_for_user",
                        AsyncMock(return_value=SimpleNamespace(documents=records)))
    monkeypatch.setattr(workspace_context.DocumentProfileRepo, "list_workspace", AsyncMock(return_value=[]))
    monkeypatch.setattr(workspace_context.PaperMapRepo, "list_workspace", AsyncMock(return_value=[]))
    monkeypatch.setattr(workspace_context.SourceArtifactRepo, "read_document", AsyncMock(
        return_value=SimpleNamespace(blocks=()),
    ))
    capability = BrowseWorkspacePapersService()
    seen = []
    offset = 0
    pages = 0
    while True:
        pages += 1
        result = await capability.execute(
        user_id="user", workspace_id="col",
        tool_call_id="browse", max_result_tokens=12000,
        arguments=BrowseWorkspacePapersToolRequest(offset=offset),
    )
        message = ChatContextBuilder.tool_result_message(result)
        assert ChatContextBuilder.estimate_tokens(message) <= 12000
        seen.extend(paper["document_id"] for paper in result.data["papers"])
        next_offset = result.data["next_offset"]
        if next_offset is None:
            break
        assert next_offset > offset
        offset = next_offset
    assert seen == [f"doc-{i}" for i in range(100)]
    assert pages <= 3
