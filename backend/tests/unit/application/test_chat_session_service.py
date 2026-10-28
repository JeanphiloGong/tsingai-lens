from __future__ import annotations
from tests.support.postgres import seed_collection

import asyncio
from dataclasses import replace
from hashlib import sha256
from typing import Any

import pytest
from application.chat import (
    AgentContext,
    AgentRunLimits,
    CapabilityRegistry,
    ModelResponseError,
    ModelToolCall,
    ModelTurn,
    ModelUsage,
    ResearchAgentRunner,
    ToolSpec,
)
from application.chat.capabilities.document_sources import ReadSourceCapability
from application.chat.session_service import (
    ChatApprovalPendingError,
    ChatFeedbackAnalysisEnqueueError,
    ChatSessionNotFoundError,
    ChatSessionService,
    ChatSourceContextError,
    resolve_canonical_objective_source,
)
from domain.chat import (
    ChatMessage,
    ChatResourceRef,
    ChatSourceContext,
    ChatToolCall,
    ChatToolResult,
    ToolCallStatus,
    ToolResultStatus,
    ToolRisk,
)
from domain.source import SourceBlock, SourceDocument, SourceTable
from pydantic import BaseModel, ConfigDict
from repositories.chat_repository import ChatRepository, ChatResponseSnapshot
from repositories.source_artifact_repository import SourceArtifactRepository
from tests.support.postgres import read_tool_calls, read_tool_results
from tests.unit.application.test_research_agent_runner import _Model

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str


class _WriteCapability:
    spec = ToolSpec(
        name="create_objective_candidate",
        description="Create one Objective candidate.",
        risk=ToolRisk.WRITE,
        input_model=_Question,
    )

    def __init__(self) -> None:
        self.executed: list[dict[str, Any]] = []

    async def execute(
        self,
        context: AgentContext,
        arguments: BaseModel,
    ) -> ChatToolResult:
        self.executed.append(arguments.model_dump())
        return ChatToolResult(
            tool_call_id="rebound-by-runner",
            status="succeeded",
            data={"objective_id": "obj-1"},
        )


class _CollectionService:
    def __init__(self) -> None:
        self.full_reads = 0

    async def collection_belongs_to_user(
        self,
        collection_id: str,
        user_id: str,
    ) -> bool:
        return collection_id == "col-1" and user_id == "user-1"

    async def get_collection_for_user(
        self,
        collection_id: str,
        user_id: str,
    ) -> dict:
        self.full_reads += 1
        if collection_id != "col-1" or user_id != "user-1":
            raise FileNotFoundError("collection not found")
        return {"collection_id": collection_id, "owner_user_id": user_id}

    async def get_document(self, collection_id: str, document_id: str) -> dict:
        if collection_id != "col-1" or document_id != "doc-1":
            raise FileNotFoundError("document not found")
        return {"collection_id": collection_id, "document_id": document_id}


@pytest.fixture(autouse=True)
async def research_sources(postgres_session_factory):
    from tests.support.postgres import seed_collection

    await seed_collection(postgres_session_factory, "col-1", document_ids=("doc-1",))
    await SourceArtifactRepository(postgres_session_factory).replace_document(
        "col-1",
        SourceDocument(
            document_id="doc-1", document_order=0, title="Canonical Paper A",
            text="Conductivity improved to 12 mS/cm under EIS.",
            blocks=(SourceBlock(
                block_id="results", document_id="doc-1", block_type="paragraph",
                text="Conductivity improved to 12 mS/cm under EIS.", block_order=0,
                page=3, heading_path="Results > Conductivity",
            ),),
        ),
    )



def _service(
    model: _Model,
    repository: ChatRepository,
    *capabilities,
) -> ChatSessionService:
    return ChatSessionService(
        collection_service=_CollectionService(),
        source_artifact_repository=SourceArtifactRepository(repository.session_factory),
        repository=repository,
        runner=ResearchAgentRunner(
            model=model,
            capabilities=CapabilityRegistry(tuple(capabilities)),
        ),
    )


async def test_chat_session_service_persists_ordinary_conversation(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    service = _service(_Model(ModelTurn(content="你好，我可以帮助你。")), repository)
    session = await service.create_session(collection_id="col-1", user_id="user-1")

    result = await service.post_message_for_user(
        session.session_id,
        "user-1",
        message="你好",
    )

    assert result["status"] == "completed"
    assert [item.role.value for item in result["messages"]] == ["user", "assistant"]
    assert len(await service.list_messages_for_user(session.session_id, "user-1")) == 2
    with pytest.raises(ChatSessionNotFoundError):
        await service.get_session_for_user(session.session_id, "user-2")


async def test_chat_session_access_uses_collection_owner_probe(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    service = _service(_Model(ModelTurn(content="answer")), repository)
    session = await service.create_session(collection_id="col-1", user_id="user-1")

    await service.get_session_for_user(session.session_id, "user-1")
    await service.list_sessions_for_user(collection_id="col-1", user_id="user-1")

    assert service.collection_service.full_reads == 0


class _FailingAnalysisJobs:
    async def enqueue_feedback_analysis(self, **kwargs):
        raise RuntimeError("database unavailable")


async def test_feedback_is_saved_but_enqueue_failure_is_explicitly_retryable(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    service = ChatSessionService(
        collection_service=_CollectionService(),
        source_artifact_repository=SourceArtifactRepository(repository.session_factory),
        repository=repository,
        runner=ResearchAgentRunner(
            model=_Model(ModelTurn(content="answer")),
            capabilities=CapabilityRegistry(()),
        ),
        analysis_job_repository=_FailingAnalysisJobs(),
    )
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    await repository.save_trajectory(
        session=session,
        messages=(
            ChatMessage.user(
                message_id="question-1",
                session_id=session.session_id,
                content="question",
                created_at="2026-09-24T00:00:00+00:00",
            ),
            ChatMessage.assistant(
                message_id="answer-1",
                session_id=session.session_id,
                content="answer",
                created_at="2026-09-24T00:00:01+00:00",
            ),
        ),
        tool_calls=(),
        tool_results=(),
    )

    with pytest.raises(ChatFeedbackAnalysisEnqueueError):
        await service.set_message_feedback_for_user(
            session.session_id,
            "answer-1",
            "user-1",
            rating="not_helpful",
            reason="incorrect",
        )

    assert len(await repository.read_feedback(session.session_id, "user-1")) == 1


async def test_chat_session_service_persists_selected_source_with_user_message(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    service = _service(_Model(ModelTurn(content="这段原文报告了一个测量结果。")), repository)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    source_context = ChatSourceContext(
        resource_ref=ChatResourceRef(
            resource_type="source",
            resource_id="doc-1:results",
            href=(
                "/collections/col-1/documents/doc-1"
                "?view=parsed-paper&source_ref=results&page=3"
            ),
        ),
        collection_id="col-1",
        document_id="doc-1",
        document_title="Client supplied title",
        source_kind="text_window",
        source_ref="results",
        page=1,
        quote="Conductivity improved to 12 mS/cm under EIS.",
        heading_path="Client supplied heading",
    )

    await service.post_message_for_user(
        session.session_id,
        "user-1",
        message="解释这段结果。",
        source_contexts=(source_context,),
    )

    stored = await repository.read_messages(session.session_id)
    canonical_context = stored[0].source_contexts[0]
    assert canonical_context.document_title == "Canonical Paper A"
    assert canonical_context.source_kind == "text_window"
    assert canonical_context.page == 3
    assert canonical_context.heading_path == "Results > Conductivity"
    assert canonical_context.source_digest == sha256(
        b"Conductivity improved to 12 mS/cm under EIS."
    ).hexdigest()
    assert canonical_context.resource_ref.href == (
        "/collections/col-1/documents/doc-1"
        "?view=parsed-paper&source_ref=results&page=3"
    )
    assert stored[1].source_contexts == ()


@pytest.mark.parametrize("forged_second_block", [False, True])
async def test_selected_blocks_are_canonicalized_together_before_a_turn(forged_second_block: bool, *, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    sources = SourceArtifactRepository(repository.session_factory)
    methods = SourceBlock(
        block_id="methods", document_id="doc-1", block_type="paragraph",
        text="Conductivity was measured using EIS at 25 C.", block_order=1,
        page=2, heading_path="Methods > EIS",
    )
    document = await sources.read_document("col-1", "doc-1")
    document = replace(document, blocks=(*document.blocks, methods))
    await seed_collection(sources.session_factory, 'col-1', document_ids=(document.document_id,))
    await sources.replace_document("col-1", document)
    service = ChatSessionService(
        collection_service=_CollectionService(), source_artifact_repository=sources,
        repository=repository,
        runner=ResearchAgentRunner(model=_Model(ModelTurn(content="Check the measurement conditions.")), capabilities=CapabilityRegistry(())),
    )
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    contexts = tuple(
        ChatSourceContext(
            resource_ref=ChatResourceRef(resource_type="source", resource_id=f"doc-1:{block.block_id}", href=None),
            collection_id="col-1", document_id="doc-1", document_title="Untrusted client label",
            source_kind="text_window", source_ref=block.block_id, page=1,
            quote="Invented room-temperature superconductivity." if forged_second_block and block.block_id == "methods" else block.text,
        ) for block in document.blocks
    )
    if forged_second_block:
        with pytest.raises(ChatSourceContextError):
            await service.post_message_for_user(session.session_id, "user-1", message="Compare these blocks", source_contexts=contexts)
        assert not await repository.read_messages(session.session_id)
        return
    await service.post_message_for_user(session.session_id, "user-1", message="Compare these blocks", source_contexts=contexts)
    stored = await repository.read_messages(session.session_id)
    assert [item.source_ref for item in stored[0].source_contexts] == ["results", "methods"]
    assert [item.page for item in stored[0].source_contexts] == [3, 2]
    assert all(item.document_title == "Canonical Paper A" and item.source_digest for item in stored[0].source_contexts)
    assert stored[-1].role.value == "assistant"


async def test_chat_session_service_rejects_source_from_another_collection(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    service = _service(_Model(ModelTurn(content="must not run")), repository)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    foreign_source = ChatSourceContext(
        resource_ref=ChatResourceRef(
            resource_type="source",
            resource_id="doc-2:results",
            href="/collections/col-2/documents/doc-2?source_ref=results",
        ),
        collection_id="col-2",
        document_id="doc-2",
        document_title="Foreign Paper",
        source_kind="text_window",
        source_ref="results",
        page=1,
        quote="A result from another collection.",
        heading_path="Results",
    )

    with pytest.raises(ChatSourceContextError, match="does not belong"):
        await service.post_message_for_user(
            session.session_id,
            "user-1",
            message="Explain this.",
            source_contexts=(foreign_source,),
        )

    assert await repository.read_messages(session.session_id) == ()


async def test_chat_session_service_rejects_unknown_document_source(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    service = _service(_Model(ModelTurn(content="must not run")), repository)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    unknown_source = ChatSourceContext(
        resource_ref=ChatResourceRef(
            resource_type="source",
            resource_id="doc-missing:results",
            href=(
                "/collections/col-1/documents/doc-missing"
                "?view=parsed-paper&source_ref=results"
            ),
        ),
        collection_id="col-1",
        document_id="doc-missing",
        document_title="Unknown Paper",
        source_kind="text_window",
        source_ref="results",
        page=1,
        quote="A client-supplied passage without a Collection document.",
        heading_path="Results",
    )

    with pytest.raises(ChatSourceContextError, match="document does not belong"):
        await service.post_message_for_user(
            session.session_id,
            "user-1",
            message="Explain this.",
            source_contexts=(unknown_source,),
        )

    assert await repository.read_messages(session.session_id) == ()


@pytest.mark.parametrize(
    ("source_kind", "source_ref", "quote", "error"),
    (
        (
            "text_window",
            "invented-results",
            "Conductivity improved to 12 mS/cm under EIS.",
            "Source reference",
        ),
        (
            "table",
            "results",
            "Conductivity improved to 12 mS/cm under EIS.",
            "Source reference",
        ),
        (
            "text_window",
            "results",
            "The paper proved room-temperature superconductivity.",
            "quote is not contained",
        ),
    ),
)
async def test_chat_session_service_rejects_forged_source_context(source_kind: str, source_ref: str, quote: str, error: str, *, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    service = _service(_Model(ModelTurn(content="must not run")), repository)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    source_context = ChatSourceContext(
        resource_ref=ChatResourceRef(
            resource_type="source",
            resource_id=f"doc-1:{source_ref}",
            href=(
                "/collections/col-1/documents/doc-1"
                f"?view=parsed-paper&source_ref={source_ref}"
            ),
        ),
        collection_id="col-1",
        document_id="doc-1",
        document_title="Paper A",
        source_kind=source_kind,
        source_ref=source_ref,
        page=3,
        quote=quote,
        heading_path="Results",
    )

    with pytest.raises(ChatSourceContextError, match=error):
        await service.post_message_for_user(
            session.session_id,
            "user-1",
            message="Explain this.",
            source_contexts=(source_context,),
        )

    assert await repository.read_messages(session.session_id) == ()


async def test_chat_session_service_accepts_a_bounded_canonical_quote(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    service = _service(
        _Model(ModelTurn(content="This is a partial Source quote.")), repository
    )
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    source_context = ChatSourceContext(
        resource_ref=ChatResourceRef(
            resource_type="source",
            resource_id="doc-1:results",
        ),
        collection_id="col-1",
        document_id="doc-1",
        document_title="Paper A",
        source_kind="text_window",
        source_ref="results",
        page=3,
        quote="Conductivity improved to 12 mS/cm",
    )

    await service.post_message_for_user(
        session.session_id,
        "user-1",
        message="Explain this excerpt.",
        source_contexts=(source_context,),
    )

    stored = (await repository.read_messages(session.session_id))[0].source_contexts[
        0
    ]
    assert stored.quote == "Conductivity improved to 12 mS/cm"
    assert stored.quote_truncated is True
    assert stored.source_digest is not None


async def test_chat_session_service_rejects_a_stale_source_digest(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    service = _service(_Model(ModelTurn(content="must not run")), repository)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    source_context = ChatSourceContext(
        resource_ref=ChatResourceRef(
            resource_type="source",
            resource_id="doc-1:results",
        ),
        collection_id="col-1",
        document_id="doc-1",
        document_title="Paper A",
        source_kind="text_window",
        source_ref="results",
        page=3,
        quote="Conductivity improved to 12 mS/cm under EIS.",
        source_digest="0" * 64,
    )

    with pytest.raises(ChatSourceContextError, match="digest does not match"):
        await service.post_message_for_user(
            session.session_id,
            "user-1",
            message="Explain this.",
            source_contexts=(source_context,),
        )

    assert await repository.read_messages(session.session_id) == ()


async def test_chat_session_service_streams_text_before_the_persisted_turn(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    service = _service(_Model(ModelTurn(content="逐段回复")), repository)
    session = await service.create_session(collection_id="col-1", user_id="user-1")

    stream = await service.stream_message_for_user(
        session.session_id,
        "user-1",
        message="你好",
    )
    events = [event async for event in stream]

    assert events[0]["type"] == "trajectory"
    snapshot = next(event["snapshot"] for event in events if event["type"] == "snapshot")
    assert snapshot.message_id == events[-1]["turn"]["messages"][-1].message_id
    assert [event for event in events if event["type"] == "text_delta"] == [
        {"type": "text_delta", "content": "逐段"},
        {"type": "text_delta", "content": "回复"},
    ]
    assert events[-1]["type"] == "turn"
    assert any(
        event["type"] == "progress" and event["progress"]["phase"] == "model"
        for event in events
    )
    assert events[-1]["turn"]["messages"][-1].content == "逐段回复"
    assert (await repository.read_messages(session.session_id))[-1].content == "逐段回复"


class _PausedResponseModel:
    first = "Match test temperature, "
    second = "specimen orientation, and heat treatment.\n\n$\\sigma = F/A$"

    def __init__(self) -> None:
        self.continue_response = asyncio.Event()
        self.finish_response = asyncio.Event()
        self.calls = 0

    async def respond(self, *, text_delta_callback=None, **kwargs):
        self.calls += 1
        if text_delta_callback:
            text_delta_callback(self.first)
        await self.continue_response.wait()
        if text_delta_callback:
            text_delta_callback(self.second)
        await self.finish_response.wait()
        return ModelTurn(content=self.first + self.second)


async def test_disconnected_response_restores_text_and_continues_with_the_same_message(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    model = _PausedResponseModel()
    service = _service(model, repository)
    reader = _service(model, repository)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    original = await service.stream_message_for_user(
        session.session_id, "user-1", message="Explain matched LPBF tensile conditions without tools.",
    )
    try:
        async with asyncio.timeout(5):
            async for event in original:
                if event["type"] == "text_delta":
                    break
            await original.aclose()
            while True:
                saved = await reader.get_trajectory_for_user(session.session_id, "user-1")
                if saved["response"].content == model.first:
                    break
                await asyncio.sleep(0.01)
            snapshot = saved["response"]
            assert saved["running"] is True
            assert snapshot.progress["phase"] == "responding"
            assert snapshot.content.endswith(" ")
            assert len(saved["messages"]) == 1
            updates = await reader.stream_updates_for_user(
                session.session_id, "user-1", response_id=snapshot.response_id,
            )
            initial = await anext(updates)
            assert initial["trajectory"]["response"].content == model.first
            model.continue_response.set()
            next_update = await anext(updates)
            assert next_update["type"] == "snapshot"
            continued = next_update["snapshot"]
            assert continued.content == model.first + model.second
            assert continued.message_id == snapshot.message_id
            assert continued.sequence > snapshot.sequence
            model.finish_response.set()
            remaining = [event async for event in updates]
            final = remaining[-1]["trajectory"]
            assert final["response"].status == "completed"
            assert final["messages"][-1].message_id == snapshot.message_id
            assert final["messages"][-1].content == model.first + model.second
            assert model.calls == 1
    finally:
        model.continue_response.set()
        model.finish_response.set()
        await asyncio.gather(*service._active_stream_tasks, return_exceptions=True)


async def test_interrupted_response_keeps_partial_text_without_claiming_it_completed(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    model = _PausedResponseModel()
    service = _service(model, repository)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    original = await service.stream_message_for_user(session.session_id, "user-1", message="Explain matching conditions without tools.")
    async for event in original:
        if event["type"] == "text_delta":
            break
    await original.aclose()
    tasks = tuple(service._active_stream_tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    saved = await service.get_trajectory_for_user(session.session_id, "user-1")
    assert saved["running"] is False
    assert saved["response"].status == "interrupted"
    assert saved["response"].content == model.first
    assert len(saved["messages"]) == 1
    with pytest.raises(ChatSessionNotFoundError):
        await service.stream_updates_for_user(session.session_id, "user-2", response_id=saved["response"].response_id)


async def test_interrupted_tool_call_is_aborted_and_the_session_can_resume(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    started = asyncio.Event()
    release = asyncio.Event()

    class _EmptyArguments(BaseModel):
        model_config = ConfigDict(extra="forbid")

    class _BlockingReadCapability(_WriteCapability):
        spec = ToolSpec(
            name="inspect_document_sources",
            description="Inspect prepared document sources.",
            risk=ToolRisk.READ,
            input_model=_EmptyArguments,
        )

        async def execute(self, context: AgentContext, arguments: BaseModel) -> ChatToolResult:
            started.set()
            await release.wait()
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status=ToolResultStatus.SUCCEEDED,
                data={"sources": []},
            )

    capability = _BlockingReadCapability()
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(
            name=capability.spec.name,
            arguments={},
        ),)),
    )
    service = _service(model, repository, capability)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    stream = await service.stream_message_for_user(
        session.session_id,
        "user-1",
        message="Inspect the prepared paper sources.",
    )

    async def drain() -> list[dict[str, Any]]:
        return [event async for event in stream]

    consumer = asyncio.create_task(drain())
    try:
        async with asyncio.timeout(5):
            await started.wait()
        active = tuple(service._active_stream_tasks)
        assert active
        for task in active:
            task.cancel()
        await consumer
    finally:
        release.set()
        await asyncio.gather(consumer, return_exceptions=True)

    call = next(
        item for item in (await read_tool_calls(repository, session.session_id))
        if item.name == capability.spec.name
    )
    assert call.status is ToolCallStatus.FAILED
    assert call.error_code == "chat_response_interrupted"
    assert next(result for result in await read_tool_results(repository, session.session_id) if result.tool_call_id == call.tool_call_id).error_code == "chat_response_interrupted"
    saved = await service.get_trajectory_for_user(session.session_id, "user-1")
    assert saved["running"] is False
    assert saved["response"].status == "interrupted"

    model.turns.clear()
    model.turns.append(ModelTurn(content="The interrupted source inspection can be resumed."))
    resumed = await service.post_message_for_user(
        session.session_id,
        "user-1",
        message="Continue from the interrupted inspection.",
    )
    assert resumed["status"] == "completed"
    assert resumed["messages"][-1].content == "The interrupted source inspection can be resumed."


async def test_new_request_recovers_a_running_call_left_by_a_dead_worker(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    model = _Model(ModelTurn(content="The previous interruption was recovered."))
    service = _service(model, repository)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    user_message = ChatMessage.user(
        message_id="user-1-message",
        session_id=session.session_id,
        content="Inspect the prepared paper sources.",
        created_at="2026-10-10T00:00:00Z",
    )
    assistant_message = ChatMessage.assistant_tool_calls(
        message_id="assistant-1",
        session_id=session.session_id,
        content="",
        tool_calls=(ChatToolCall.requested(
            tool_call_id="call-orphaned",
            session_id=session.session_id,
            assistant_message_id="assistant-1",
            name="inspect_document_sources",
            arguments={},
            risk=ToolRisk.READ,
        ).to_request(),),
        created_at="2026-10-10T00:00:01Z",
    )
    running = ChatToolCall.requested(
        tool_call_id="call-orphaned",
        session_id=session.session_id,
        assistant_message_id="assistant-1",
        name="inspect_document_sources",
        arguments={},
        risk=ToolRisk.READ,
    ).start("2026-10-10T00:00:02Z")
    await repository.save_trajectory(
        session=session,
        messages=(user_message, assistant_message),
        tool_calls=(running,),
        tool_results=(),
    )
    await repository.save_response_snapshot(
        session.session_id,
        ChatResponseSnapshot(
            response_id="response-orphaned",
            sequence=1,
            started_at="2026-10-10T00:00:00Z",
            updated_at="2026-10-10T00:00:02Z",
            status="running",
        ),
    )

    result = await service.post_message_for_user(
        session.session_id,
        "user-1",
        message="Continue after the interruption.",
    )

    assert result["status"] == "completed"
    assert result["messages"][-1].content == "The previous interruption was recovered."
    assert (await repository.read_tool_call("call-orphaned")).status is ToolCallStatus.FAILED
    assert next(result for result in await read_tool_results(repository, session.session_id) if result.tool_call_id == "call-orphaned").error_code == "chat_response_interrupted"
    snapshot = await repository.read_response_snapshot(session.session_id)
    assert snapshot is not None
    assert snapshot.status == "completed"


@pytest.mark.parametrize("transition", ["starts", "completes", "stops"])
async def test_recovery_distinguishes_snapshot_changes_from_a_stopped_worker(transition, monkeypatch, *, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    service = _service(_Model(ModelTurn(content="unused")), repository)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    snapshot = ChatResponseSnapshot(
        response_id="response-1", sequence=1, started_at=session.created_at,
        updated_at=session.created_at, message_id="answer-1", content="Match test conditions",
    )
    if transition != "starts":
        await repository.save_response_snapshot(session.session_id, snapshot)

    async def sample_execution(_session_id):
        if transition == "starts":
            await repository.save_response_snapshot(session.session_id, snapshot)
        elif transition == "completes":
            await repository.save_response_snapshot(session.session_id, replace(snapshot, sequence=2, status="completed"))
        return False

    monkeypatch.setattr(repository, "is_session_running", sample_execution)
    saved = await service.get_trajectory_for_user(session.session_id, "user-1")
    assert saved["running"] is (transition == "starts")
    assert saved["response"].status == {"starts": "running", "completes": "completed", "stops": "interrupted"}[transition]
    assert saved["response"].content == snapshot.content


async def test_approved_continuation_captures_text_without_repeating_the_write(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    capability = _WriteCapability()
    service = _service(_Model(ModelTurn(tool_calls=(ModelToolCall(
        name="create_objective_candidate", arguments={"question": "Compare matched LPBF tensile conditions"},
    ),))), repository, capability)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    initial = await service.post_message_for_user(session.session_id, "user-1", message="Create an objective candidate for these test conditions.")
    call = initial["pending_approval"]
    assert call is not None
    original_snapshot = await repository.read_response_snapshot(session.session_id)
    model = _PausedResponseModel()
    service.runner.model = model
    decision = asyncio.create_task(service.decide_tool_call_for_user(
        session.session_id, call.tool_call_id, "user-1", arguments_digest=call.arguments_digest, decision="approved",
    ))
    try:
        async with asyncio.timeout(5):
            while True:
                snapshot = await repository.read_response_snapshot(session.session_id)
                if snapshot.content == model.first:
                    break
                await asyncio.sleep(0.01)
            assert snapshot.response_id != original_snapshot.response_id
            assert len(capability.executed) == 1
            updates = await service.stream_updates_for_user(session.session_id, "user-1", response_id=snapshot.response_id)
            assert (await anext(updates))["trajectory"]["response"].content == model.first
            await updates.aclose()
            model.continue_response.set()
            model.finish_response.set()
            result = await decision
            assert result["status"] == "completed"
            assert result["messages"][-1].message_id == snapshot.message_id
            assert len(capability.executed) == 1
    finally:
        model.continue_response.set()
        model.finish_response.set()
        await decision


async def test_approved_write_response_failure_preserves_saved_result_but_fails_turn(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    capability = _WriteCapability()
    service = _service(
        _Model(ModelTurn(tool_calls=(ModelToolCall(
            name=capability.spec.name,
            arguments={"question": "Record the reconstructed tensile experiment."},
        ),))),
        repository,
        capability,
    )
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    proposed = await service.post_message_for_user(
        session.session_id,
        "user-1",
        message="保存已重建的拉伸实验。",
    )
    pending = proposed["pending_approval"]
    assert pending is not None
    service.runner.model = _Model(ModelResponseError(
        "Model request exceeds its context window.",
        reason="context_window_exceeded",
        retryable=False,
    ))

    failed = await service.decide_tool_call_for_user(
        session.session_id,
        pending.tool_call_id,
        "user-1",
        arguments_digest=pending.arguments_digest,
        decision="approved",
    )

    assert failed["status"] == "failed"
    assert failed["completion_reason"] is None
    assert failed["error_code"] == "context_window_exceeded"
    assert failed["warnings"]
    assert failed["messages"][-1].content == (
        "已批准的操作已完成并保存。详细回复暂时无法生成；请以已保存的结果为准。"
    )
    assert len(capability.executed) == 1
    assert (await repository.read_tool_call(pending.tool_call_id)).status is ToolCallStatus.SUCCEEDED
    snapshot = await repository.read_response_snapshot(session.session_id)
    assert snapshot is not None
    assert snapshot.status == "failed"
    assert snapshot.error_code == "context_window_exceeded"
    assert snapshot.warnings == failed["warnings"]


async def test_chat_session_service_checkpoints_every_agent_step(*, postgres_session_factory, monkeypatch) -> None:
    repository = ChatRepository(postgres_session_factory)
    from unittest.mock import AsyncMock
    save_trajectory = AsyncMock(wraps=repository.save_trajectory)
    monkeypatch.setattr(repository, "save_trajectory", save_trajectory)
    capability = _WriteCapability()
    capability.spec = ToolSpec(
        name="get_collection_context",
        description="Read collection context.",
        risk=ToolRisk.READ,
        input_model=_Question,
    )
    service = _service(
        _Model(
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="get_collection_context",
                    arguments={"question": "What is in this collection?"},
                ),)
            ),
            ModelTurn(content="The collection contains relevant papers."),
        ),
        repository,
        capability,
    )
    session = await service.create_session(collection_id="col-1", user_id="user-1")

    result = await service.post_message_for_user(
        session.session_id,
        "user-1",
        message="What is in this collection?",
    )

    assert result["status"] == "completed"
    assert [
        (tuple(item.role.value for item in call.kwargs["messages"]),
         tuple(item.status.value for item in call.kwargs["tool_calls"]),
         tuple(item.status.value for item in call.kwargs["tool_results"]))
        for call in save_trajectory.call_args_list
    ] == [
        (("user",), (), ()),
        (("user", "assistant"), ("requested",), ()),
        (("user", "assistant"), ("running",), ()),
        (("user", "assistant", "tool"), ("succeeded",), ("succeeded",)),
        (("user", "assistant", "tool", "assistant"), ("succeeded", "requested"), ("succeeded",)),
        (("user", "assistant", "tool", "assistant"), ("succeeded", "running"), ("succeeded",)),
        (("user", "assistant", "tool", "assistant", "tool"), ("succeeded", "succeeded"), ("succeeded", "succeeded")),
        (("user", "assistant", "tool", "assistant", "tool", "assistant"), ("succeeded", "succeeded"), ("succeeded", "succeeded")),
    ]


@pytest.mark.parametrize("ending", ["timeout", "budget"])
async def test_source_comparison_preserves_inspected_paper_and_can_resume(ending: str, *, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    sources = SourceArtifactRepository(repository.session_factory)
    collection = _CollectionService()
    read = ReadSourceCapability(collection_service=collection, source_artifact_repository=sources)
    cancelled = asyncio.Event()

    class Model(_Model):
        calls = 0

        async def respond(self, **kwargs):
            self.calls += 1
            if ending == "timeout" and self.calls == 3:
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return await super().respond(**kwargs)

    model = Model(
        ModelTurn(tool_calls=(ModelToolCall(name="read_source", arguments={
            "document_id": "doc-1", "source_kind": "text_window", "source_ref": "results",
        }),)),
        ModelTurn(content="Paper A reports 12 mS/cm under EIS. Paper B remains unread; comparison is unresolved.",
                  usage=ModelUsage(80, 20, 100)),
    )
    runner = ResearchAgentRunner(
        model=model, capabilities=CapabilityRegistry((read,)),
        # Leave enough setup time to reach the deliberately hanging third call;
        # the whole-turn budget still cancels it promptly.
        limits=AgentRunLimits(max_elapsed_seconds=0.5, max_model_tokens=100),
    )
    service = ChatSessionService(repository=repository, collection_service=collection,
                                 source_artifact_repository=sources, runner=runner)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    stream = await service.stream_message_for_user(
        session.session_id, "user-1",
        message="Read the exact Source in paper A, then paper B, to compare their EIS conductivity measurements.",
    )
    events = [event async for event in stream]
    result = events[-1]["turn"]
    # A request deadline now preserves the completed Source read and returns a
    # resource-limited completion so the researcher can continue from evidence.
    assert result["status"] == "completed"
    if ending == "timeout":
        assert result["completion_reason"] == "resource_budget"
        assert result["error_code"] is None
        assert cancelled.is_set()
        assert not any(event["type"] == "text_delta" for event in events)
    else:
        assert result["completion_reason"] == "resource_budget"
        assert result["warnings"]
        assert "Paper B remains unread" in result["messages"][-1].content
    assert model.calls == 3  # Discovery, exact Source read, then answer or timeout.
    persisted = await service.list_messages_for_user(session.session_id, "user-1")
    source_results = [message.tool_result for message in persisted
                      if message.tool_result and message.tool_result.resource_refs]
    assert len(source_results) == 1
    assert source_results[0].data["complete_source"] is True
    assert source_results[0].data["content"] == (await sources.read_document("col-1", "doc-1")).text
    assert source_results[0].resource_refs[0].resource_type == "source"

    model.turns.clear()
    model.turns.append(ModelTurn(content="Paper B has not yet been inspected. Its Source must be read next."))
    resumed = await service.post_message_for_user(
        session.session_id, "user-1", message="Without tools, summarize what is still unread.",
    )
    assert resumed["status"] == "completed"
    assert "Paper B" in resumed["messages"][-1].content
    assert len(await read_tool_results(repository, session.session_id)) == 2


async def test_chat_session_service_approves_exact_write_and_resumes(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    capability = _WriteCapability()
    service = _service(
        _Model(
            ModelTurn(
                content="我准备保存候选目标。",
                tool_calls=(ModelToolCall(
                    name="create_objective_candidate",
                    arguments={"question": "How does energy input affect ductility?"},
                ),),
            ),
            ModelTurn(content="候选目标已创建，尚未启动分析。"),
        ),
        repository,
        capability,
    )
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    pending_turn = await service.post_message_for_user(
        session.session_id,
        "user-1",
        message="保存这个目标",
    )
    pending = pending_turn["pending_approval"]

    assert pending.status is ToolCallStatus.APPROVAL_REQUIRED
    assert (
        await service.get_pending_approval_for_user(session.session_id, "user-1")
        == pending
    )
    assert capability.executed == []
    with pytest.raises(ChatApprovalPendingError) as blocked:
        await service.post_message_for_user(
            session.session_id,
            "user-1",
            message="start another branch",
        )
    assert blocked.value.tool_call_id == pending.tool_call_id
    with pytest.raises(ValueError, match="arguments digest"):
        await service.decide_tool_call_for_user(
            session.session_id,
            pending.tool_call_id,
            "user-1",
            arguments_digest="edited",
            decision="approved",
        )

    approved_turn = await service.decide_tool_call_for_user(
        session.session_id,
        pending.tool_call_id,
        "user-1",
        arguments_digest=pending.arguments_digest,
        decision="approved",
    )

    assert approved_turn["status"] == "completed"
    assert capability.executed == [
        {"question": "How does energy input affect ductility?"}
    ]
    assert (await repository.read_tool_call(pending.tool_call_id)).status is ToolCallStatus.SUCCEEDED
    assert (
        await service.get_pending_approval_for_user(session.session_id, "user-1")
        is None
    )

    duplicate_turn = await service.decide_tool_call_for_user(
        session.session_id,
        pending.tool_call_id,
        "user-1",
        arguments_digest=pending.arguments_digest,
        decision="approved",
    )

    assert duplicate_turn["status"] == "completed"
    assert capability.executed == [
        {"question": "How does energy input affect ductility?"}
    ]


async def test_chat_session_service_rejection_never_executes_write(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    capability = _WriteCapability()
    service = _service(
        _Model(
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="create_objective_candidate",
                    arguments={"question": "How does energy input affect ductility?"},
                ),)
            ),
            ModelTurn(content="已记录你的拒绝，未创建目标。"),
        ),
        repository,
        capability,
    )
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    pending = (await service.post_message_for_user(
        session.session_id,
        "user-1",
        message="保存这个目标",
    ))["pending_approval"]

    result = await service.decide_tool_call_for_user(
        session.session_id,
        pending.tool_call_id,
        "user-1",
        arguments_digest=pending.arguments_digest,
        decision="rejected",
    )

    assert result["status"] == "completed"
    assert result["messages"][-1].content == "已记录你的拒绝，未创建目标。"
    assert capability.executed == []
    assert next(result for result in await read_tool_results(repository, session.session_id) if result.tool_call_id == pending.tool_call_id).error_code == "user_rejected"
    snapshot = await repository.read_response_snapshot(session.session_id)
    assert snapshot is not None
    assert snapshot.status == "completed"
    messages = await service.list_messages_for_user(session.session_id, "user-1")
    assert any(
        message.role == "tool" and message.tool_call_id == pending.tool_call_id
        for message in messages
    )


async def test_rename_survives_continuation_and_rejects_non_owner(*, postgres_session_factory) -> None:
    repository = ChatRepository(postgres_session_factory)
    service = _service(_Model(ModelTurn(content="Evidence retained.")), repository)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    saved = await service.set_session_title_for_user(session.session_id, "user-1", title="  IN718 comparison  ")
    assert saved.title == "IN718 comparison"
    assert saved.updated_at == session.updated_at
    with pytest.raises(ChatSessionNotFoundError):
        await service.set_session_title_for_user(session.session_id, "user-2", title="Other title")
    for invalid in (" ", "x" * 161, "line\nbreak", "nul\x00title"):
        with pytest.raises(ValueError):
            await service.set_session_title_for_user(session.session_id, "user-1", title=invalid)
    await service.post_message_for_user(session.session_id, "user-1", message="Compare the evidence")
    assert (await service.get_session_for_user(session.session_id, "user-1")).title == "IN718 comparison"
    assert (await service.list_sessions_for_user(collection_id="col-1", user_id="user-1"))[0].title == "IN718 comparison"
    assert len(await service.list_messages_for_user(session.session_id, "user-1")) == 2


@pytest.mark.parametrize("decision", ["approved", "rejected"])
async def test_approval_continuation_recovers_context_without_repeating_write(decision, *, postgres_session_factory):
    from dataclasses import replace

    from application.chat import ChatContextBuilder
    from tests.unit.application.test_chat_context_builder import _tool_pair

    class RecoveringModel(_Model):
        def __init__(self):
            super().__init__(ModelTurn(tool_calls=(ModelToolCall(
                name="create_objective_candidate", arguments={"question": "Compare matched elongation conditions."},
            ),)))
            self.continuing = False
            self.requests = []

        async def respond(self, *, context, **kwargs):
            if context.compacting:
                return ModelTurn(content='{"scope":"Match material state and test orientation.","checks":[],"next_actions":[]}')
            if not self.continuing:
                return await super().respond(context=context, **kwargs)
            self.requests.append(context)
            if len(self.requests) == 1:
                raise ModelResponseError("context rejected", reason="context_window_exceeded", retryable=False)
            return ModelTurn(content="The reviewed decision is recorded; comparable measurements remain uncertain.")

    repository = ChatRepository(postgres_session_factory)
    capability = _WriteCapability()
    model = RecoveringModel()
    service = _service(model, repository, capability)
    session = await service.create_session(collection_id="col-1", user_id="user-1")
    # Persist the preceding investigation before the approval request.
    history = tuple(replace(message, session_id=session.session_id) for i in range(10)
                    for message in _tool_pair(call_id=f"prior-{i}", payload={
                        "source_ref": f"results-{i}", "content": "Reported measurements need matched specimen orientation. " * 900,
                    }))
    calls = tuple(
        ChatToolCall.requested(
            tool_call_id=request.tool_call_id, session_id=session.session_id,
            assistant_message_id=message.message_id, name=request.name,
            arguments=request.arguments, risk=ToolRisk.READ, position=request.position,
        ).start(message.created_at).succeed(message.created_at)
        for message in history for request in message.tool_calls
    )
    await repository.save_trajectory(
        session=session, messages=history, tool_calls=calls,
        tool_results=tuple(message.tool_result for message in history if message.tool_result),
    )
    proposed = await service.post_message_for_user(session.session_id, "user-1", message="Save the reviewed objective.")
    pending = proposed["pending_approval"]
    model.continuing = True
    response = await service.decide_tool_call_for_user(
        session.session_id, pending.tool_call_id, "user-1",
        arguments_digest=pending.arguments_digest, decision=decision,
    )
    assert response["status"] == "completed"
    assert len(capability.executed) == (1 if decision == "approved" else 0)
    assert len(model.requests) == 2
    sizes = [ChatContextBuilder.estimate_tokens(context.provider_messages("system")) for context in model.requests]
    assert sizes[1] < sizes[0]
    snapshot = await repository.read_response_snapshot(session.session_id)
    assert snapshot.progress["context_recovery_attempts"] == 1
    assert snapshot.progress["retry_count"] == 1
    saved = await repository.read_messages(session.session_id)
    assert all(message in saved for message in history)


async def test_canonical_objective_table_keeps_rendered_content_and_grounding() -> None:
    table = SourceTable(
        table_id="table-1",
        document_id="paper-1",
        table_order=1,
        caption_text="Tensile results",
        caption_block_id=None,
        page=5,
        heading_path="Results",
        column_headers=("Sample", "Strength (MPa)"),
        table_matrix=(("Sample", "Strength (MPa)"), ("A", "560")),
    )
    document = SourceDocument(
        document_id="paper-1",
        document_order=1,
        title="Tensile study",
        text="Results",
        tables=(table,),
    )

    canonical = resolve_canonical_objective_source(
        document, source_kind="table", source_ref="table-1"
    )

    assert "| A | 560 |" in canonical.content
    assert canonical.page == 5
    assert canonical.heading_path == "Results"
    assert canonical.grounding_source["source_kind"] == "table"
    assert canonical.grounding_source["table_matrix"] == [
        ["Sample", "Strength (MPa)"],
        ["A", "560"],
    ]
