from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.chat.agent_runner import AgentRunLimits, _RunProgress
from application.chat.capabilities import document_sources
from application.chat.capabilities.contracts import CapabilityExecutionContext
from application.chat.capabilities.document_sources import InspectDocumentSourcesCapability, InspectDocumentSourcesToolRequest
from application.chat.capability_policy import _section_reading_progress
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
    monkeypatch.setattr(document_sources.collection_service, 'get_collection_for_user', AsyncMock())
    cap = InspectDocumentSourcesCapability()
    context = CapabilityExecutionContext('chat','user','col','read',max_result_tokens=2000)
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
    ledger=_section_reading_progress({'inspect_document_sources':records})[0]
    assert ledger['pending_section_reads']==[]
    args={**records[0]['continuation']}
    repo.read_document.return_value=replace(doc,blocks=(*blocks,SourceBlock('new','paper','paragraph','new',14)))
    stale=await cap.execute(context,InspectDocumentSourcesToolRequest(**args))
    assert stale.error_code=='source_version_changed'

@pytest.mark.anyio
async def test_full_document_read_exposes_exact_pending_arguments(monkeypatch):
    doc=SourceDocument('paper',0,'IN718','',blocks=tuple(SourceBlock(f'b{i}','paper','paragraph','Measured condition '*20,i) for i in range(10)))
    monkeypatch.setattr(document_sources,'SourceArtifactRepo',SimpleNamespace(read_document=AsyncMock(return_value=doc)))
    monkeypatch.setattr(document_sources.collection_service,'get_collection_for_user',AsyncMock())
    r=await InspectDocumentSourcesCapability().execute(CapabilityExecutionContext('chat','user','col','read',max_result_tokens=2000),InspectDocumentSourcesToolRequest(document_id='paper'))
    ledger=_section_reading_progress({'inspect_document_sources':[r.data]})[0]
    assert ledger['pending_section_reads'][0]['arguments']==r.data['continuation']


def test_changed_batch_length_is_not_new_source_coverage():
    from domain.chat import ChatToolResult,ChatResourceRef
    call=ChatToolCall.requested(tool_call_id='read',session_id='chat',assistant_message_id='a',name='inspect_document_sources',arguments={},risk=ToolRisk.READ)
    sources=[{'source_ref':f'b{i}','source_kind':'text_window','source_digest':str(i),'content':'measured','content_truncated':False} for i in range(4)]
    result=ChatToolResult('read',ToolResultStatus.SUCCEEDED,data={'document':{'document_id':'paper'},'sources':sources},resource_refs=(ChatResourceRef('source','paper:b0'),))
    progress=_RunProgress(AgentRunLimits())
    assert progress.observe(call,result)
    assert not progress.observe(call,replace(result,data={**result.data,'sources':sources[:2]}))

@pytest.mark.anyio
async def test_current_and_previous_turn_facts_survive_repeated_fallback_compaction():
    import json
    from dataclasses import asdict
    from application.chat import CapabilityRegistry, ResearchAgentRunner, ChatContextBuilder
    from domain.chat import ChatMessage, ChatMessageRole, ChatToolResult, ChatToolRequest
    def pair(name,text):
        result=ChatToolResult(name,ToolResultStatus.SUCCEEDED,data={'document':{'document_id':'paper'},'sources':[{
            'source_kind':'text_window','source_ref':name,'source_digest':name+'-digest','page':3,
            'heading_path':name,'content':text,'content_truncated':False}]})
        return [ChatMessage(name+'-a','chat',ChatMessageRole.ASSISTANT,'','2026-11-01',tool_calls=(ChatToolRequest(name,'inspect_document_sources',{'document_id':'paper'},0),)),
                ChatMessage(name+'-r','chat',ChatMessageRole.TOOL,json.dumps(asdict(result)),'2026-11-01',tool_call_id=name,tool_result=result)]
    active=ChatMessage.user(message_id='user',session_id='chat',content='Compare only the reported IN718 measurements. Orientation unknown.',created_at='2026-11-01')
    messages=[active,*pair('Methods','As-built IN718; P=250 W, V=700 mm/s; test at 650 C. Orientation not reported.'),
              *pair('Results','The matching as-built specimen elongation was 17%; density was 99.92%.')]
    from application.chat.model import ModelResponseError
    class UnavailableCompaction:
        async def respond(self, **kwargs):
            raise ModelResponseError("Compaction format unavailable", reason="invalid_response_shape", retryable=False)
    runner=ResearchAgentRunner(model=UnavailableCompaction(),capabilities=CapabilityRegistry(()),context_builder=ChatContextBuilder(max_messages=3))
    progress=_RunProgress(runner.limits,restored_elapsed_seconds=190)
    for i in range(3):
        messages.extend(pair(f'other{i}','A different measurement with no orientation value.'))
        view=await runner._prepare_model_context(tuple(messages),(),progress,active_user_message_id='user')
        text=json.dumps(view.provider_messages('test'))
        for fact in ('250 W','700 mm/s','650 C','17%','99.92%','Methods-digest','Results-digest'):
            assert fact in text
    new=ChatMessage.user(message_id='next',session_id='chat',content='Continue; what was the elongation and orientation?',created_at='2026-11-01')
    messages.append(new)
    view=await runner._prepare_model_context(tuple(messages),(),progress,active_user_message_id='next')
    text=json.dumps(view.provider_messages('test'))
    assert '17%' in text and 'Orientation not reported' in text
