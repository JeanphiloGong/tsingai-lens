from __future__ import annotations

from collections import deque
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from application.chat import (
    CapabilityExecutionContext,
    CapabilityRegistry,
    ModelToolCall,
    ModelTurn,
    ResearchAgentRunner,
    ToolSpec,
)
from application.chat.capabilities import GetCollectionContextCapability
from application.chat.session_service import ChatSessionService
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk
from infra.persistence.postgres.chat_repository import PostgresChatRepository
from main import create_app


class _Model:
    def __init__(self, *turns: ModelTurn) -> None:
        self.turns = deque(turns)

    def respond(self, *, messages: tuple, tool_specs: tuple) -> ModelTurn:
        assert messages
        assert {item.name for item in tool_specs} == {
            "get_collection_context",
            "create_objective_candidate",
        }
        return self.turns.popleft()


class _ObjectiveRepository:
    def list_objectives(self, collection_id: str) -> tuple:
        assert collection_id
        return ()


class _CandidateArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str


class _CandidateCapability:
    spec = ToolSpec(
        name="create_objective_candidate",
        description="Create one unconfirmed Objective candidate.",
        risk=ToolRisk.WRITE,
        input_model=_CandidateArguments,
    )

    def __init__(self) -> None:
        self.executed: list[dict] = []

    def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: _CandidateArguments,
    ) -> ChatToolResult:
        self.executed.append(arguments.model_dump())
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "objective_id": "obj-agent-1",
                "confirmation_status": "candidate",
            },
            resource_refs=(
                ChatResourceRef(
                    resource_type="research_objective",
                    resource_id="obj-agent-1",
                    href=(
                        f"/collections/{context.collection_id}/objectives/"
                        "obj-agent-1"
                    ),
                ),
            ),
        )


def test_research_agent_http_flow_persists_tools_and_exact_write_approval(
    auth_session_service,
    collection_service,
) -> None:
    user = auth_session_service.create_user(
        email="agent-flow@example.com",
        password="test-password",
    )
    login = auth_session_service.login(
        email=user["email"],
        password="test-password",
    )
    collection = collection_service.create_collection(
        "Ti-6Al-4V energy input",
        "Literature for a traceable energy-input comparison.",
        owner_user_id=user["user_id"],
    )
    objective_repository = _ObjectiveRepository()
    candidate_capability = _CandidateCapability()
    chat_repository = PostgresChatRepository(
        auth_session_service.repository.session_factory
    )
    model = _Model(
        ModelTurn(content="Hello. I can help inspect this literature collection."),
        ModelTurn(
            tool_call=ModelToolCall(
                tool_call_id="call-context",
                name="get_collection_context",
                arguments={},
            )
        ),
        ModelTurn(content="This collection is ready for a focused research question."),
        ModelTurn(
            content="I prepared the exact candidate for your approval.",
            tool_call=ModelToolCall(
                tool_call_id="call-write",
                name="create_objective_candidate",
                arguments={
                    "question": "How does energy input affect grain morphology?"
                },
            ),
        ),
        ModelTurn(content="The candidate was created and still requires review."),
    )
    chat_service = ChatSessionService(
        collection_service=collection_service,
        repository=chat_repository,
        runner=ResearchAgentRunner(
            model=model,
            capabilities=CapabilityRegistry(
                (
                    GetCollectionContextCapability(
                        collection_service=collection_service,
                        objective_repository=objective_repository,
                    ),
                    candidate_capability,
                )
            ),
        ),
    )
    app = create_app(
        auth_session_service=auth_session_service,
        collection_service=collection_service,
        task_service=SimpleNamespace(repository=object()),
        source_artifact_repository=object(),
        paper_fact_repository=object(),
        objective_repository=objective_repository,
        comparison_repository=object(),
        finding_review_repository=object(),
        experiment_plan_repository=object(),
        chat_session_service=chat_service,
    )

    with TestClient(app) as client:
        client.cookies.set("lens_session", login["session_id"])
        created = client.post(
            "/api/v1/chat-sessions",
            json={"collection_id": collection["collection_id"]},
        )
        session_id = created.json()["session_id"]

        greeting = client.post(
            f"/api/v1/chat-sessions/{session_id}/messages",
            json={"message": "Hello"},
        )
        context_turn = client.post(
            f"/api/v1/chat-sessions/{session_id}/messages",
            json={"message": "What does this collection contain?"},
        )
        proposed_write = client.post(
            f"/api/v1/chat-sessions/{session_id}/messages",
            json={"message": "Create the focused grain-morphology objective"},
        )
        pending = proposed_write.json()["pending_approval"]
        executed_before_approval = list(candidate_capability.executed)

        blocked = client.post(
            f"/api/v1/chat-sessions/{session_id}/messages",
            json={"message": "Continue without deciding"},
        )
        wrong_digest = client.post(
            f"/api/v1/chat-sessions/{session_id}/tool-calls/call-write/decision",
            json={"decision": "approved", "arguments_digest": "0" * 64},
        )
        approved = client.post(
            f"/api/v1/chat-sessions/{session_id}/tool-calls/call-write/decision",
            json={
                "decision": "approved",
                "arguments_digest": pending["arguments_digest"],
            },
        )
        trajectory = client.get(f"/api/v1/chat-sessions/{session_id}/messages")

    assert created.status_code == 201
    assert greeting.json()["status"] == "completed"
    assert all(item["role"] != "tool" for item in greeting.json()["messages"])
    assert context_turn.json()["messages"][-2]["tool_result"]["data"][
        "collection"
    ]["name"] == "Ti-6Al-4V energy input"
    assert proposed_write.status_code == 200
    assert proposed_write.json()["status"] == "approval_required"
    assert executed_before_approval == []
    assert blocked.status_code == 409
    assert wrong_digest.status_code == 409
    assert approved.status_code == 200
    assert approved.json()["status"] == "completed"
    assert candidate_capability.executed == [
        {"question": "How does energy input affect grain morphology?"}
    ]
    assert trajectory.json()["pending_approval"] is None
    assert [item["role"] for item in trajectory.json()["items"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
