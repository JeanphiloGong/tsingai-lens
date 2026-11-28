from agent.tools.document import InspectTableCapability
from document.repositories.document_repository import DocumentRepo
from unittest.mock import AsyncMock
import pytest
from application.source import workspace_service
from agent.tools.document import SearchSourcesCapability, SearchSourcesInput
from document.application.source_reading import InspectDocumentSourcesService
from agent.tools.registry import ToolExecutionContext
from document.domain.source import SourceDocument, SourceBlock

@pytest.fixture
def anyio_backend():return 'asyncio'

@pytest.mark.anyio
async def test_workspace_search_pages_return_versioned_candidates(monkeypatch):
    documents = tuple(
        SourceDocument(
            name, order, name, "", metadata={"source_fingerprint": "v1"},
            blocks=(SourceBlock(name + "-result", name, "paragraph", "Measured IN718 elongation.", 0),),
        )
        for order, name in enumerate(("paper-a", "paper-b"))
    )
    list_sources = AsyncMock(side_effect=[documents, documents, documents[1:]])
    monkeypatch.setattr(DocumentRepo, "list", list_sources)
    monkeypatch.setattr(workspace_service, "get_workspace_for_user", AsyncMock())
    tool = SearchSourcesCapability()
    context = ToolExecutionContext("user", "col", "task", "operation", "search")
    args = SearchSourcesInput(query="IN718 elongation", limit=1, match_mode="all")
    first = await tool.execute(context, args)
    second = await tool.execute(context, args.model_copy(update={"offset": first.data["next_offset"]}))
    assert second.data["next_offset"] is None
    hits = first.data["candidates"] + second.data["candidates"]
    assert [hit["source_ref"] for hit in hits] == ["paper-a-result", "paper-b-result"]
    assert all(hit["source_version"] == "v1" and "elongation" in hit["excerpt"] for hit in hits)
    scoped = await tool.execute(context, args.model_copy(update={"document_ids": ["paper-b"]}))
    list_sources.assert_awaited_with(workspace_id="col", document_ids=("paper-b",))
    assert scoped.data["candidates"] == second.data["candidates"]


@pytest.mark.anyio
async def test_table_pages_fit_model_budget_without_losing_rows_or_units(monkeypatch):
    from document.application.source_reading import InspectTableToolRequest
    from document.domain.source import SourceTable
    header=('Condition','Elongation (%)')
    rows=tuple((f'condition-{i:02}',str(10+i/10)) for i in range(35))
    table=SourceTable('table','paper',0,'Reported elongation; note: as-built',None,3,'Results',header,(header,*rows))
    doc=SourceDocument('paper',0,'IN718','',metadata={"source_fingerprint":"v1"}, tables=(table,))
    monkeypatch.setattr(workspace_service,'get_workspace_for_user',AsyncMock())
    monkeypatch.setattr(DocumentRepo, "read", AsyncMock(return_value=doc))
    cap=InspectTableCapability();arguments={'document_id':'paper','table_ref':'table'};seen=[]
    for _ in range(40):
        result=await cap.execute(
        context=ToolExecutionContext("user","col","task","operation","call",700), arguments=InspectTableToolRequest(**arguments),
    )
        assert result.status=='succeeded'
        assert InspectDocumentSourcesService._result_tokens(result)<=700
        assert 'Elongation (%)' in result.data['table_markdown']
        count=result.data['returned_row_count'];assert count>0
        offset=result.data['row_offset'];seen.extend(rows[offset:offset+count])
        for row in rows[offset:offset+count]:assert row[0] in result.data['table_markdown'] and row[1] in result.data['table_markdown']
        arguments=result.data['continuation']
        if arguments is None:break
    assert seen==list(rows)
