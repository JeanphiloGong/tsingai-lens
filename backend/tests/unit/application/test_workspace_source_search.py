from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from application.source import agent_source_service as document_sources
from application.source.agent_source_service import SearchSourcesService,SearchSourcesToolRequest
from agent.tools.registry import ToolExecutionContext
from domain.source import SourceDocument,SourceBlock

@pytest.fixture
def anyio_backend():return 'asyncio'

@pytest.mark.anyio
async def test_workspace_search_returns_ranked_papers_and_matching_window(monkeypatch):
    other=SourceDocument('other',0,'Unrelated alloy','',blocks=(SourceBlock('background','other','paragraph','elongation discussed',0),))
    target=SourceDocument('in718',1,'IN718 tensile study','',blocks=(
        SourceBlock('methods','in718','paragraph','IN718 was printed as-built.',0),
        SourceBlock('result','in718','paragraph','x '*474+'elongation measured at 17%.',1),))
    monkeypatch.setattr(document_sources.workspace_service,'get_workspace_for_user',AsyncMock())
    repo=SimpleNamespace(read_workspace_documents=AsyncMock(return_value=(other,target)),read_documents=AsyncMock(return_value=(target,)))
    monkeypatch.setattr(document_sources,'SourceArtifactRepo',repo)
    cap=SearchSourcesService();context=ToolExecutionContext(task_id='chat', user_id='user', workspace_id='col', tool_call_id='search', operation_id="operation")
    result=await cap.execute(user_id=context.user_id, workspace_id=context.workspace_id, tool_call_id=context.tool_call_id, max_result_tokens=context.max_result_tokens, arguments=SearchSourcesToolRequest(query='IN718 elongation',match_mode='all'))
    assert result.status=='succeeded'
    assert result.data['papers'][0]['document_id']=='in718'
    assert not any(m['document_id']=='other' for m in result.data['matches'])
    match=next(m for m in result.data['matches'] if m['source_ref']=='result')
    assert 'elongation' in match['content']
    assert match['content_offset']>0
    assert match['read_arguments']['source_ref']=='result'
    assert match['read_arguments']['document_id']=='in718'
    assert all(m['support_is_evidence'] is False for m in result.data['matches'])
    scoped=await cap.execute(user_id=context.user_id, workspace_id=context.workspace_id, tool_call_id=context.tool_call_id, max_result_tokens=context.max_result_tokens, arguments=SearchSourcesToolRequest(document_ids=['in718'],query='IN718'))
    repo.read_documents.assert_awaited_once_with('col',('in718',))
    assert scoped.data['papers'][0]['document_id']=='in718'


@pytest.mark.anyio
async def test_search_surfaces_other_papers_before_repeating_one_papers_passages(monkeypatch):
    documents = tuple(SourceDocument(
        f"paper-{i}", i, f"IN718 elongation study {i}", "",
        blocks=tuple(SourceBlock(f"p{i}-{j}", f"paper-{i}", "paragraph",
                                 "IN718 elongation reported.", j) for j in range(20)),
    ) for i in range(3))
    monkeypatch.setattr(document_sources.workspace_service, "get_workspace_for_user", AsyncMock())
    monkeypatch.setattr(document_sources, "SourceArtifactRepo", SimpleNamespace(
        read_workspace_documents=AsyncMock(return_value=documents),
    ))
    capability = SearchSourcesService()
    context = ToolExecutionContext(task_id="chat", user_id="user", workspace_id="col", tool_call_id="search", operation_id="operation")
    result = await capability.execute(user_id=context.user_id, workspace_id=context.workspace_id, tool_call_id=context.tool_call_id, max_result_tokens=context.max_result_tokens, arguments= SearchSourcesToolRequest(query="IN718 elongation", limit=3))
    assert [hit["document_id"] for hit in result.data["matches"]] == [f"paper-{i}" for i in range(3)]
    assert result.data["matching_paper_total"] == 3
    assert result.data["match_total"] == 60
    next_page = await capability.execute(user_id=context.user_id, workspace_id=context.workspace_id, tool_call_id=context.tool_call_id, max_result_tokens=context.max_result_tokens, arguments= SearchSourcesToolRequest(
        query="IN718 elongation", limit=3, offset=result.data["next_offset"],
    ))
    assert [hit["source_ref"] for hit in next_page.data["matches"]] == [f"p{i}-1" for i in range(3)]



@pytest.mark.anyio
async def test_table_pages_fit_model_budget_without_losing_rows_or_units(monkeypatch):
    from application.source.agent_source_service import InspectTableService,InspectTableToolRequest
    from domain.source import SourceTable
    header=('Condition','Elongation (%)')
    rows=tuple((f'condition-{i:02}',str(10+i/10)) for i in range(35))
    table=SourceTable('table','paper',0,'Reported elongation; note: as-built',None,3,'Results',header,(header,*rows))
    doc=SourceDocument('paper',0,'IN718','',tables=(table,))
    monkeypatch.setattr(document_sources.workspace_service,'get_workspace_for_user',AsyncMock())
    monkeypatch.setattr(document_sources,'SourceArtifactRepo',SimpleNamespace(read_document=AsyncMock(return_value=doc)))
    cap=InspectTableService();arguments={'document_id':'paper','table_ref':'table'};seen=[]
    for _ in range(40):
        result=await cap.execute(
        user_id='user', workspace_id='col',
        tool_call_id='read', max_result_tokens=700,
        arguments=InspectTableToolRequest(**arguments),
    )
        assert result.status=='succeeded'
        assert document_sources.InspectDocumentSourcesService._result_tokens(result)<=700
        assert 'Elongation (%)' in result.data['table_markdown']
        count=result.data['returned_row_count'];assert count>0
        offset=result.data['row_offset'];seen.extend(rows[offset:offset+count])
        for row in rows[offset:offset+count]:assert row[0] in result.data['table_markdown'] and row[1] in result.data['table_markdown']
        arguments=result.data['continuation']
        if arguments is None:break
    assert seen==list(rows)
