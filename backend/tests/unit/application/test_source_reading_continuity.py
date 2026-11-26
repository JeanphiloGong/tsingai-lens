from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.capabilities import document_sources
from agent.tools.registry import ToolExecutionContext
from agent.capabilities.document_sources import InspectDocumentSourcesCapability, InspectDocumentSourcesToolRequest
from domain.chat import ChatToolCall, ToolRisk, ToolResultStatus
from domain.source import SourceBlock, SourceDocument

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.mark.anyio
async def test_tree_section_continuation_survives_budget_changes_and_rejects_changed_source(monkeypatch):
    blocks = (
        SourceBlock('methods', 'paper', 'heading', 'Methods', 0, heading_path='Methods', heading_level=1),
        *(SourceBlock(f'b{i}', 'paper', 'paragraph', f'Powder and printing condition {i}. ' * 20,
                     i+1, heading_path='Methods') for i in range(12)),
        SourceBlock('results', 'paper', 'heading', 'Results', 13, heading_path='Results', heading_level=1),
    )
    doc = SourceDocument('paper', 0, 'IN718', '', blocks=blocks)
    repo = SimpleNamespace(read_document=AsyncMock(return_value=doc))
    monkeypatch.setattr(document_sources, 'SourceArtifactRepo', repo)
    monkeypatch.setattr(document_sources.workspace_service, 'get_workspace_for_user', AsyncMock())
    cap = InspectDocumentSourcesCapability()
    context = ToolExecutionContext(task_id='chat', user_id='user', workspace_id='col', tool_call_id='read', operation_id="operation", max_result_tokens=2000)
    overview = await cap.execute(replace(context,max_result_tokens=12000), InspectDocumentSourcesToolRequest(document_id='paper'))
    section = next(s for s in overview.data['document_outline'] if s['heading_path']=='Methods')
    args = {'document_id':'paper','section_id':section['section_id']}
    seen=[]; records=[]
    for i in range(20):
        result=await cap.execute(replace(context,max_result_tokens=2000 if i%2==0 else 5000),InspectDocumentSourcesToolRequest(**args))
        assert result.status=='succeeded'
        seen.extend(s['source_ref'] for s in result.data['sources'])
        records.append(result.data)
        args=result.data['continuation']
        if args is None:break
    assert seen==['methods',*(f'b{i}' for i in range(12))]
    args={**records[0]['continuation']}
    repo.read_document.return_value=replace(doc,blocks=(*blocks,SourceBlock('new','paper','paragraph','new',14)))
    stale=await cap.execute(context,InspectDocumentSourcesToolRequest(**args))
    assert stale.error_code=='source_version_changed'

@pytest.mark.anyio
async def test_full_document_read_exposes_exact_pending_arguments(monkeypatch):
    doc=SourceDocument('paper',0,'IN718','',blocks=tuple(SourceBlock(f'b{i}','paper','paragraph','Measured condition '*20,i) for i in range(10)))
    monkeypatch.setattr(document_sources,'SourceArtifactRepo',SimpleNamespace(read_document=AsyncMock(return_value=doc)))
    monkeypatch.setattr(document_sources.workspace_service,'get_workspace_for_user',AsyncMock())
    r=await InspectDocumentSourcesCapability().execute(ToolExecutionContext(task_id='chat', user_id='user', workspace_id='col', tool_call_id='read', operation_id="operation", max_result_tokens=2000),InspectDocumentSourcesToolRequest(document_id='paper'))
    assert r.data['continuation']['document_id'] == 'paper'



@pytest.mark.anyio
async def test_exact_read_budget_includes_version_and_continuation_arguments(monkeypatch):
    from agent.capabilities.document_sources import ReadSourceCapability, ReadSourceToolRequest
    from agent.application.context_builder import ChatContextBuilder

    text = "Measured IN718 elongation and test conditions. " * 100
    document = SourceDocument("paper", 0, "IN718", "", blocks=(
        SourceBlock("results", "paper", "paragraph", text, 0),
    ))
    monkeypatch.setattr(document_sources, "SourceArtifactRepo", SimpleNamespace(
        read_document=AsyncMock(return_value=document),
    ))
    monkeypatch.setattr(document_sources.workspace_service, "get_workspace_for_user", AsyncMock())
    arguments = {"document_id": "paper", "source_kind": "text_window", "source_ref": "results"}
    parts = []
    for _ in range(30):
        result = await ReadSourceCapability().execute(
            ToolExecutionContext(task_id="chat", user_id="user", workspace_id="col", tool_call_id="read", operation_id="operation", max_result_tokens=800),
            ReadSourceToolRequest(**arguments),
        )
        assert result.status is ToolResultStatus.SUCCEEDED
        assert ChatContextBuilder.estimate_tokens(ChatContextBuilder.tool_result_message(result)) <= 800
        parts.append(result.data["content"])
        arguments = result.data["continuation"]
        if arguments is None:
            break
    assert "".join(parts) == text
