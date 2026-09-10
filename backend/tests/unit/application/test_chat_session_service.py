from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from hashlib import sha256
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from application.chat import (
    AgentContext,
    AgentRunLimits,
    CapabilityRegistry,
    ModelToolCall,
    ModelTurn,
    ModelUsage,
    ResearchAgentRunner,
    ToolSpec,
)
from application.chat.session_service import (
    ChatApprovalPendingError,
    ChatSessionNotFoundError,
    ChatSessionService,
    ChatSourceContextError,
)
from application.repositories.chat_repository import ChatResponseSnapshot, ChatSessionBusyError
from application.chat.capabilities.document_sources import ReadSourceCapability
from domain.chat import (
    ChatMessage,
    ChatResourceRef,
    ChatSession,
    ChatSourceContext,
    ChatToolCall,
    ChatToolResult,
    ToolCallStatus,
    ToolRisk,
)
from domain.source import SourceBlock, SourceDocument
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
    async def get_collection_for_user(
        self,
        collection_id: str,
        user_id: str,
    ) -> dict:
        if collection_id != "col-1" or user_id != "user-1":
            raise FileNotFoundError("collection not found")
        return {"collection_id": collection_id, "owner_user_id": user_id}

    async def get_document(self, collection_id: str, document_id: str) -> dict:
        if collection_id != "col-1" or document_id != "doc-1":
            raise FileNotFoundError("document not found")
        return {"collection_id": collection_id, "document_id": document_id}


class _SourceArtifactRepository:
    def __init__(self) -> None:
        self.document = SourceDocument(
            document_id="doc-1",
            document_order=0,
            title="Canonical Paper A",
            text="Conductivity improved to 12 mS/cm under EIS.",
            blocks=(
                SourceBlock(
                    block_id="results",
                    document_id="doc-1",
                    block_type="paragraph",
                    text="Conductivity improved to 12 mS/cm under EIS.",
                    block_order=0,
                    page=3,
                    heading_path="Results > Conductivity",
                ),
            ),
        )

    async def read_document(
        self,
        collection_id: str,
        document_id: str,
    ) -> SourceDocument | None:
        if collection_id == "col-1" and document_id == self.document.document_id:
            return self.document
        return None


class _Repository:
    def __init__(self) -> None:
        self.sessions: dict[str, ChatSession] = {}
        self.active_sessions: set[str] = set()
        self.response_snapshots: dict[str, ChatResponseSnapshot] = {}
        self.messages: dict[str, tuple[ChatMessage, ...]] = {}
        self.calls: dict[str, ChatToolCall] = {}
        self.results: dict[str, ChatToolResult] = {}
        self.trajectory_snapshots: list[
            tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]
        ] = []

    async def add_session(self, record: ChatSession) -> None:
        self.sessions[record.session_id] = record
        self.messages[record.session_id] = ()

    @asynccontextmanager
    async def session_execution(self, session_id: str):
        if session_id in self.active_sessions:
            raise ChatSessionBusyError()
        self.active_sessions.add(session_id)
        try:
            yield
        finally:
            self.active_sessions.remove(session_id)

    async def is_session_running(self, session_id: str) -> bool:
        return session_id in self.active_sessions

    async def read_response_snapshot(self, session_id: str) -> ChatResponseSnapshot | None:
        return self.response_snapshots.get(session_id)

    async def save_response_snapshot(self, session_id: str, snapshot: ChatResponseSnapshot) -> None:
        self.response_snapshots[session_id] = snapshot

    async def read_session_family(self, session: ChatSession) -> tuple[ChatSession, ...]:
        return (session,)

    async def read_feedback(self, session_id: str, user_id: str) -> tuple:
        return ()

    async def read_session(self, session_id: str) -> ChatSession | None:
        return self.sessions.get(session_id)

    async def read_messages(self, session_id: str) -> tuple[ChatMessage, ...]:
        return self.messages.get(session_id, ())

    async def read_tool_call(self, tool_call_id: str) -> ChatToolCall | None:
        return self.calls.get(tool_call_id)

    async def save_trajectory(
        self,
        *,
        session: ChatSession,
        messages: tuple[ChatMessage, ...],
        tool_calls: tuple[ChatToolCall, ...],
        tool_results: tuple[ChatToolResult, ...],
    ) -> None:
        self.sessions[session.session_id] = session
        self.messages[session.session_id] = messages
        self.calls.update((item.tool_call_id, item) for item in tool_calls)
        self.results.update((item.tool_call_id, item) for item in tool_results)
        self.trajectory_snapshots.append(
            (
                tuple(item.role.value for item in messages),
                tuple(item.status.value for item in tool_calls),
                tuple(item.status.value for item in tool_results),
            )
        )

    async def decide_tool_call(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        user_id: str,
        arguments_digest: str,
        decision: str,
        decided_at: str,
    ) -> ChatToolCall:
        session = self.sessions.get(session_id)
        if session is None or session.user_id != user_id:
            raise FileNotFoundError("chat session not found")
        call = self.calls[tool_call_id]
        decided = (
            call.approve(
                user_id=user_id,
                arguments_digest=arguments_digest,
                decided_at=decided_at,
            )
            if decision == "approved"
            else call.reject(
                user_id=user_id,
                arguments_digest=arguments_digest,
                decided_at=decided_at,
            )
        )
        self.calls[tool_call_id] = decided
        return decided

    async def claim_approved_tool_call(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        user_id: str,
        started_at: str,
    ) -> ChatToolCall | None:
        session = self.sessions.get(session_id)
        if session is None or session.user_id != user_id:
            raise FileNotFoundError("chat session not found")
        call = self.calls[tool_call_id]
        if call.status is ToolCallStatus.APPROVED:
            call = call.start(started_at)
            self.calls[tool_call_id] = call
            return call
        if call.status in {
            ToolCallStatus.RUNNING,
            ToolCallStatus.SUCCEEDED,
            ToolCallStatus.FAILED,
        }:
            return None
        raise ValueError(f"cannot claim tool call in status {call.status.value}")


def _service(
    model: _Model,
    repository: _Repository,
    *capabilities,
) -> ChatSessionService:
    return ChatSessionService(
        collection_service=_CollectionService(),
        source_artifact_repository=_SourceArtifactRepository(),
        repository=repository,
        runner=ResearchAgentRunner(
            model=model,
            capabilities=CapabilityRegistry(tuple(capabilities)),
        ),
    )


async def test_chat_session_service_persists_ordinary_conversation() -> None:
    repository = _Repository()
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


async def test_chat_session_service_persists_selected_source_with_user_message() -> None:
    repository = _Repository()
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
async def test_selected_blocks_are_canonicalized_together_before_a_turn(
    forged_second_block: bool,
) -> None:
    repository = _Repository()
    sources = _SourceArtifactRepository()
    methods = SourceBlock(
        block_id="methods", document_id="doc-1", block_type="paragraph",
        text="Conductivity was measured using EIS at 25 C.", block_order=1,
        page=2, heading_path="Methods > EIS",
    )
    sources.document = replace(sources.document, blocks=(*sources.document.blocks, methods))
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
        ) for block in sources.document.blocks
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


async def test_chat_session_service_rejects_source_from_another_collection() -> None:
    repository = _Repository()
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


async def test_chat_session_service_rejects_unknown_document_source() -> None:
    repository = _Repository()
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
async def test_chat_session_service_rejects_forged_source_context(
    source_kind: str,
    source_ref: str,
    quote: str,
    error: str,
) -> None:
    repository = _Repository()
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


async def test_chat_session_service_accepts_a_bounded_canonical_quote() -> None:
    repository = _Repository()
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


async def test_chat_session_service_rejects_a_stale_source_digest() -> None:
    repository = _Repository()
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


async def test_chat_session_service_streams_text_before_the_persisted_turn() -> None:
    repository = _Repository()
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


async def test_disconnected_response_restores_text_and_continues_with_the_same_message() -> None:
    repository = _Repository()
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


async def test_interrupted_response_keeps_partial_text_without_claiming_it_completed() -> None:
    repository = _Repository()
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


@pytest.mark.parametrize("transition", ["starts", "completes", "stops"])
async def test_recovery_distinguishes_snapshot_changes_from_a_stopped_worker(transition, monkeypatch) -> None:
    repository = _Repository()
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


async def test_approved_continuation_captures_text_without_repeating_the_write() -> None:
    repository = _Repository()
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


async def test_chat_session_service_checkpoints_every_agent_step() -> None:
    repository = _Repository()
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
    assert repository.trajectory_snapshots == [
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
async def test_source_comparison_preserves_inspected_paper_and_can_resume(ending: str) -> None:
    repository = _Repository()
    sources = _SourceArtifactRepository()
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
        limits=AgentRunLimits(max_elapsed_seconds=0.05, max_model_tokens=100),
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
    assert result["status"] == ("failed" if ending == "timeout" else "completed")
    if ending == "timeout":
        assert result["error_code"] == "provider_timeout"
        assert cancelled.is_set()
        assert not any(event["type"] == "text_delta" for event in events)
    else:
        assert result["completion_reason"] == "resource_budget"
        assert result["warnings"]
        assert "Paper B remains unread" in result["messages"][-1].content
    assert model.calls == (3 if ending == "timeout" else 4)
    persisted = await service.list_messages_for_user(session.session_id, "user-1")
    source_results = [message.tool_result for message in persisted
                      if message.tool_result and message.tool_result.resource_refs]
    assert len(source_results) == 1
    assert source_results[0].data["complete_source"] is True
    assert source_results[0].data["content"] == sources.document.text
    assert source_results[0].resource_refs[0].resource_type == "source"

    model.turns.clear()
    model.turns.append(ModelTurn(content="Paper B has not yet been inspected. Its Source must be read next."))
    resumed = await service.post_message_for_user(
        session.session_id, "user-1", message="Without tools, summarize what is still unread.",
    )
    assert resumed["status"] == "completed"
    assert "Paper B" in resumed["messages"][-1].content
    assert len(repository.results) == 2


async def test_chat_session_service_approves_exact_write_and_resumes() -> None:
    repository = _Repository()
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
    assert repository.calls[pending.tool_call_id].status is ToolCallStatus.SUCCEEDED
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


async def test_chat_session_service_rejection_never_executes_write() -> None:
    repository = _Repository()
    capability = _WriteCapability()
    service = _service(
        _Model(
            ModelTurn(
                tool_calls=(ModelToolCall(
                    name="create_objective_candidate",
                    arguments={"question": "How does energy input affect ductility?"},
                ),)
            )
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

    assert result["status"] == "rejected"
    assert capability.executed == []
    assert repository.results[pending.tool_call_id].error_code == "user_rejected"
    assert (
        await service.list_messages_for_user(session.session_id, "user-1")
    )[-1].role == "tool"
