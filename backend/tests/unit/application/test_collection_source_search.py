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
