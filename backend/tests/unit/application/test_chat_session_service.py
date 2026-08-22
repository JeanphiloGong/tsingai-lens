from __future__ import annotations

from collections import deque
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from application.chat import (
    AgentContext,
    CapabilityRegistry,
    ModelToolCall,
    ModelTurn,
    ResearchAgentRunner,
    ToolSpec,
)
from application.chat.session_service import (
    ChatApprovalPendingError,
    ChatSessionNotFoundError,
    ChatSessionService,
)
from domain.chat import (
    ChatMessage,
    ChatSession,
    ChatToolCall,
    ChatToolResult,
    ToolCallStatus,
    ToolRisk,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str


class _Model:
    def __init__(self, *turns: ModelTurn) -> None:
        self.turns = deque(turns)

    def respond(self, *, messages: tuple, tool_specs: tuple) -> ModelTurn:
        return self.turns.popleft()


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


class _Repository:
    def __init__(self) -> None:
        self.sessions: dict[str, ChatSession] = {}
        self.messages: dict[str, tuple[ChatMessage, ...]] = {}
        self.calls: dict[str, ChatToolCall] = {}
        self.results: dict[str, ChatToolResult] = {}
        self.trajectory_snapshots: list[
            tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]
        ] = []

    async def add_session(self, record: ChatSession) -> None:
        self.sessions[record.session_id] = record
        self.messages[record.session_id] = ()

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


def _service(
    model: _Model,
    repository: _Repository,
    *capabilities,
) -> ChatSessionService:
    return ChatSessionService(
        collection_service=_CollectionService(),
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
                tool_call=ModelToolCall(
                    tool_call_id="call-1",
                    name="get_collection_context",
                    arguments={"question": "What is in this collection?"},
                )
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
        (("user", "assistant", "tool", "assistant"), ("succeeded",), ("succeeded",)),
    ]


async def test_chat_session_service_approves_exact_write_and_resumes() -> None:
    repository = _Repository()
    capability = _WriteCapability()
    service = _service(
        _Model(
            ModelTurn(
                content="我准备保存候选目标。",
                tool_call=ModelToolCall(
                    tool_call_id="call-1",
                    name="create_objective_candidate",
                    arguments={"question": "How does energy input affect ductility?"},
                ),
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


async def test_chat_session_service_rejection_never_executes_write() -> None:
    repository = _Repository()
    capability = _WriteCapability()
    service = _service(
        _Model(
            ModelTurn(
                tool_call=ModelToolCall(
                    tool_call_id="call-1",
                    name="create_objective_candidate",
                    arguments={"question": "How does energy input affect ductility?"},
                )
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
