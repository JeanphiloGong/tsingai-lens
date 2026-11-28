from agent.tools.document import InspectDocumentSourcesCapability
from document.repositories.document_repository import DocumentRepo
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.source import workspace_service
from agent.tools.registry import ToolExecutionContext
from document.application.source_reading import InspectDocumentSourcesToolRequest
from domain.chat import ToolResultStatus
from document.domain.source import SourceBlock, SourceDocument

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
    doc = SourceDocument('paper', 0, 'IN718', '', metadata={"source_fingerprint":"v1"}, blocks=blocks)
    repo = SimpleNamespace(read_document=AsyncMock(return_value=doc))
    monkeypatch.setattr(DocumentRepo, 'read', repo.read_document)
    monkeypatch.setattr(workspace_service, 'get_workspace_for_user', AsyncMock())
    cap = InspectDocumentSourcesCapability()
    context = ToolExecutionContext(task_id='chat', user_id='user', workspace_id='col', tool_call_id='read', operation_id="operation", max_result_tokens=2000)
    overview = await cap.execute(context=replace(context, max_result_tokens=12000), arguments=InspectDocumentSourcesToolRequest(document_id='paper'))
    section = next(s for s in overview.data['document_outline'] if s['heading_path']=='Methods')
    args = {'document_id':'paper','section_id':section['section_id']}
    seen=[]; records=[]
    for i in range(20):
        result=await cap.execute(context=replace(context, max_result_tokens=2000 if i%2==0 else 5000), arguments=InspectDocumentSourcesToolRequest(**args))
        assert result.status=='succeeded'
        seen.extend(s['source_ref'] for s in result.data['sources'])
        records.append(result.data)
        args=result.data['continuation']
        if args is None:break
    assert seen==['methods',*(f'b{i}' for i in range(12))]
    args={**records[0]['continuation']}
    repo.read_document.return_value=replace(doc,metadata={"source_fingerprint":"changed"},blocks=(*blocks,SourceBlock('new','paper','paragraph','new',14)))
    stale=await cap.execute(context=context, arguments=InspectDocumentSourcesToolRequest(**args))
    assert stale.error_code=='source_version_changed'

@pytest.mark.anyio
async def test_full_document_read_exposes_exact_pending_arguments(monkeypatch):
    doc=SourceDocument('paper',0,'IN718','',metadata={"source_fingerprint":"v1"}, blocks=tuple(SourceBlock(f'b{i}','paper','paragraph','Measured condition '*20,i) for i in range(10)))
    monkeypatch.setattr(DocumentRepo, "read", AsyncMock(return_value=doc))
    monkeypatch.setattr(workspace_service,'get_workspace_for_user',AsyncMock())
    r=await InspectDocumentSourcesCapability().execute(
        context=ToolExecutionContext("user","col","task","operation","call",2000), arguments=InspectDocumentSourcesToolRequest(document_id='paper'),
    )
    assert r.data['continuation']['document_id'] == 'paper'



@pytest.mark.anyio
async def test_exact_read_continues_on_the_same_version(monkeypatch):
    from agent.tools.document import ReadSourceCapability, ReadSourceInput

    text = "Measured IN718 elongation and test conditions. " * 100
    document = SourceDocument("paper", 0, "IN718", "", metadata={"source_fingerprint": "v1"}, blocks=(
        SourceBlock("results", "paper", "paragraph", text, 0),
    ))
    monkeypatch.setattr(DocumentRepo, "read", AsyncMock(return_value=document))
    monkeypatch.setattr(workspace_service, "get_workspace_for_user", AsyncMock())
    tool = ReadSourceCapability()
    context = ToolExecutionContext("user", "col", "task", "operation", "read")
    args = ReadSourceInput(document_id="paper", source_kind="text_window", source_ref="results", limit=800)
    parts = []
    for offset in range(0, len(text), args.limit):
        result = await tool.execute(context, args)
        assert result.status is ToolResultStatus.SUCCEEDED
        assert result.data["offset"] == offset
        assert result.data["source_version"] == "v1"
        parts.append(result.data["content"])
        if result.data["next_offset"] is None:
            break
        args = args.model_copy(update={"offset": result.data["next_offset"], "source_version": "v1"})
    assert "".join(parts) == text
    assert result.data["next_offset"] is None
