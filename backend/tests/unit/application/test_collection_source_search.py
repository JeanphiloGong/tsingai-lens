from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from application.chat.capabilities import document_sources
from application.chat.capabilities.document_sources import SearchSourcesCapability,SearchSourcesToolRequest
from application.chat.capabilities.contracts import CapabilityExecutionContext
from domain.source import SourceDocument,SourceBlock

@pytest.fixture
def anyio_backend():return 'asyncio'

@pytest.mark.anyio
async def test_collection_search_returns_ranked_papers_and_matching_window(monkeypatch):
    other=SourceDocument('other',0,'Unrelated alloy','',blocks=(SourceBlock('background','other','paragraph','elongation discussed',0),))
    target=SourceDocument('in718',1,'IN718 tensile study','',blocks=(
        SourceBlock('methods','in718','paragraph','IN718 was printed as-built.',0),
        SourceBlock('result','in718','paragraph','x '*474+'elongation measured at 17%.',1),))
    monkeypatch.setattr(document_sources.collection_service,'get_collection_for_user',AsyncMock())
    repo=SimpleNamespace(read_collection_documents=AsyncMock(return_value=(other,target)),read_documents=AsyncMock(return_value=(target,)))
    monkeypatch.setattr(document_sources,'SourceArtifactRepo',repo)
    cap=SearchSourcesCapability();context=CapabilityExecutionContext('chat','user','col','search')
    result=await cap.execute(context,SearchSourcesToolRequest(query='IN718 elongation',match_mode='all'))
    assert result.status=='succeeded'
    assert result.data['papers'][0]['document_id']=='in718'
    assert not any(m['document_id']=='other' for m in result.data['matches'])
    match=next(m for m in result.data['matches'] if m['source_ref']=='result')
    assert 'elongation' in match['content']
    assert match['content_offset']>0
    assert match['read_arguments']['source_ref']=='result'
    assert match['read_arguments']['document_id']=='in718'
    assert all(m['support_is_evidence'] is False for m in result.data['matches'])
    scoped=await cap.execute(context,SearchSourcesToolRequest(document_ids=['in718'],query='IN718'))
    repo.read_documents.assert_awaited_once_with('col',('in718',))
    assert scoped.data['papers'][0]['document_id']=='in718'


@pytest.mark.anyio
async def test_search_surfaces_other_papers_before_repeating_one_papers_passages(monkeypatch):
    documents = tuple(SourceDocument(
        f"paper-{i}", i, f"IN718 elongation study {i}", "",
        blocks=tuple(SourceBlock(f"p{i}-{j}", f"paper-{i}", "paragraph",
                                 "IN718 elongation reported.", j) for j in range(20)),
    ) for i in range(3))
    monkeypatch.setattr(document_sources.collection_service, "get_collection_for_user", AsyncMock())
    monkeypatch.setattr(document_sources, "SourceArtifactRepo", SimpleNamespace(
        read_collection_documents=AsyncMock(return_value=documents),
    ))
    capability = SearchSourcesCapability()
    context = CapabilityExecutionContext("chat", "user", "col", "search")
    result = await capability.execute(context, SearchSourcesToolRequest(query="IN718 elongation", limit=3))
    assert [hit["document_id"] for hit in result.data["matches"]] == [f"paper-{i}" for i in range(3)]
    assert result.data["matching_paper_total"] == 3
    assert result.data["match_total"] == 60
    next_page = await capability.execute(context, SearchSourcesToolRequest(
        query="IN718 elongation", limit=3, offset=result.data["next_offset"],
    ))
    assert [hit["source_ref"] for hit in next_page.data["matches"]] == [f"p{i}-1" for i in range(3)]


def test_rewording_a_search_or_returning_a_subset_is_not_new_progress():
    from application.chat.agent_runner import AgentRunLimits, _RunProgress
    from domain.chat import ChatToolCall, ChatToolResult, ToolResultStatus, ToolRisk

    progress = _RunProgress(AgentRunLimits())
    call = ChatToolCall.requested(tool_call_id="search", session_id="chat", assistant_message_id="a",
                                  name="search_sources", arguments={"query": "elongation"}, risk=ToolRisk.READ)
    hits = [{"document_id": "paper", "source_kind": "text_window", "source_ref": f"result-{i}",
             "source_digest": f"digest-{i}", "content_offset": 0, "content": "Elongation measured."}
            for i in range(2)]
    for matches, expected in ((hits, True), (hits[:1], False), ([{**hits[0], "content_offset": 800,
                                                              "content": "Another measurement."}], True)):
        result = ChatToolResult("search", ToolResultStatus.SUCCEEDED,
                                data={"query": "differently worded search", "matches": matches})
        assert progress.observe(call, result) is expected

@pytest.mark.anyio
async def test_table_pages_fit_model_budget_without_losing_rows_or_units(monkeypatch):
    from application.chat.capabilities.document_sources import InspectTableCapability,InspectTableToolRequest
    from domain.source import SourceTable
    header=('Condition','Elongation (%)')
    rows=tuple((f'condition-{i:02}',str(10+i/10)) for i in range(35))
    table=SourceTable('table','paper',0,'Reported elongation; note: as-built',None,3,'Results',header,(header,*rows))
    doc=SourceDocument('paper',0,'IN718','',tables=(table,))
    monkeypatch.setattr(document_sources.collection_service,'get_collection_for_user',AsyncMock())
    monkeypatch.setattr(document_sources,'SourceArtifactRepo',SimpleNamespace(read_document=AsyncMock(return_value=doc)))
    cap=InspectTableCapability();arguments={'document_id':'paper','table_ref':'table'};seen=[]
    for _ in range(40):
        result=await cap.execute(CapabilityExecutionContext('chat','user','col','read',max_result_tokens=700),InspectTableToolRequest(**arguments))
        assert result.status=='succeeded'
        assert document_sources.InspectDocumentSourcesCapability._result_tokens(result)<=700
        assert 'Elongation (%)' in result.data['table_markdown']
        count=result.data['returned_row_count'];assert count>0
        offset=result.data['row_offset'];seen.extend(rows[offset:offset+count])
        for row in rows[offset:offset+count]:assert row[0] in result.data['table_markdown'] and row[1] in result.data['table_markdown']
        arguments=result.data['continuation']
        if arguments is None:break
    assert seen==list(rows)
