from __future__ import annotations

from application.chat.capabilities import collection_context

import pytest
from application.chat import (
    CapabilityExecutionContext,
    CapabilityRegistry,
    ModelToolCall,
    ModelTurn,
    ResearchAgentRunner,
    ToolSpec,
)
from application.chat import session_service as chat_session_service
from application.chat.capabilities import GetCollectionContextCapability
from domain.chat import ChatResourceRef, ChatToolResult, ToolResultStatus, ToolRisk
from fastapi.testclient import TestClient
from main import create_app
from pydantic import BaseModel, ConfigDict
from repositories.chat_repository import ChatRepository
from repositories.source_artifact_repository import SourceArtifactRepository
from tests.unit.application.test_research_agent_runner import _Model

pytestmark = pytest.mark.anyio


class _ObjectiveRepository:
    async def list_objectives(self, collection_id: str) -> tuple:
        assert collection_id
        return ()

    async def interrupt_active_analyses(self) -> int:
        return 0


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

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: _CandidateArguments,
    ) -> ChatToolResult:
        self.executed.append(arguments.model_dump())
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
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


async def test_research_agent_http_flow_persists_tools_and_exact_write_approval(
    auth_session_service,
    collection_service,
    monkeypatch,
    *,
    postgres_session_factory,
    collection_workspace,
) -> None:
    user = await auth_session_service.create_user(
        email="agent-flow@example.com",
        password="test-password",
    )
    login = await auth_session_service.login(
        email=user["email"],
        password="test-password",
    )
    collection = await collection_service.create_collection(
        "Ti-6Al-4V energy input",
        "Literature for a traceable energy-input comparison.",
        owner_user_id=user["user_id"],
        workspace=collection_workspace,
    )
    objective_repository = _ObjectiveRepository()
    candidate_capability = _CandidateCapability()
    chat_repository = ChatRepository()
    source_artifact_repository = SourceArtifactRepository()
    model = _Model(
        ModelTurn(content="Hello. I can help inspect this literature collection."),
        ModelTurn(
            tool_calls=(
                ModelToolCall(
                    name="get_collection_context",
                    arguments={},
                ),
            )
        ),
        ModelTurn(content="This collection is ready for a focused research question."),
        ModelTurn(
            content="I prepared the exact candidate for your approval.",
            tool_calls=(
                ModelToolCall(
                    name="create_objective_candidate",
                    arguments={
                        "question": "How does energy input affect grain morphology?"
                    },
                ),
            ),
        ),
        ModelTurn(content="The candidate was created and still requires review."),
    )
    monkeypatch.setattr(chat_session_service, "collection_service", collection_service)
    monkeypatch.setattr(
        chat_session_service, "SourceArtifactRepo", source_artifact_repository
    )
    monkeypatch.setattr(chat_session_service, "ChatRepo", chat_repository)
    app = create_app()

    with TestClient(app) as client:
        collection_context.collection_service = collection_service
        collection_context.ObjectiveRepo = objective_repository
        monkeypatch.setattr(
            client.app.state.runtime.chat_session_service,
            "runner",
            ResearchAgentRunner(
                model=model,
                capabilities=CapabilityRegistry(
                    (
                        GetCollectionContextCapability(),
                        candidate_capability,
                    )
                ),
            ),
        )
        client.cookies.set("lens_session", login["session_id"])
        created = client.post(
            "/api/v1/chat-sessions",
            json={"collection_id": collection["collection_id"]},
        )
        session_id = created.json()["data"]["session_id"]

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
        pending = proposed_write.json()["data"]["pending_approval"]
        executed_before_approval = list(candidate_capability.executed)

        blocked = client.post(
            f"/api/v1/chat-sessions/{session_id}/messages",
            json={"message": "Continue without deciding"},
        )
        wrong_digest = client.post(
            f"/api/v1/chat-sessions/{session_id}/tool-calls/"
            f"{pending['tool_call_id']}/decision",
            json={"decision": "approved", "arguments_digest": "0" * 64},
        )
        approved = client.post(
            f"/api/v1/chat-sessions/{session_id}/tool-calls/"
            f"{pending['tool_call_id']}/decision",
            json={
                "decision": "approved",
                "arguments_digest": pending["arguments_digest"],
            },
        )
        trajectory = client.get(f"/api/v1/chat-sessions/{session_id}/messages")

    assert greeting.json()["code"] == 200, greeting.text
    assert context_turn.json()["code"] == 200, context_turn.text
    assert proposed_write.json()["code"] == 200, proposed_write.text
    assert approved.json()["code"] == 200, approved.text
    assert trajectory.json()["code"] == 200, trajectory.text
    assert created.status_code == 200
    assert created.json()["code"] == 200
    assert greeting.json()["data"]["status"] == "completed"
    assert all(item["role"] != "tool" for item in greeting.json()["data"]["messages"])
    assert (
        context_turn.json()["data"]["messages"][-2]["tool_result"]["data"][
            "collection"
        ]["name"]
        == "Ti-6Al-4V energy input"
    )
    assert proposed_write.status_code == 200
    assert proposed_write.json()["data"]["status"] == "approval_required"
    assert executed_before_approval == []
    assert blocked.json()["code"] == 200204
    assert wrong_digest.json()["code"] == 200204
    assert approved.status_code == 200
    assert approved.json()["data"]["status"] == "completed"
    proposed_plan = proposed_write.json()["data"]["execution_plan"]
    approved_plan = approved.json()["data"]["execution_plan"]
    assert (proposed_plan is None) == (approved_plan is None)
    if proposed_plan is not None:
        assert approved_plan["plan_id"] == proposed_plan["plan_id"]
        assert approved_plan["plan_version"] > proposed_plan["plan_version"]
    assert candidate_capability.executed == [
        {"question": "How does energy input affect grain morphology?"}
    ]
    assert trajectory.json()["data"]["pending_approval"] is None
    assert model.all_tool_spec_names[0] == ("discover_research_tools",)
    assert any(
        "create_objective_candidate" in names for names in model.all_tool_spec_names
    )
    assert model.all_tool_spec_names[-1] == (
        "create_objective_candidate",
        "discover_research_tools",
    )
    # A successful write does not hide the capability by name. The same
    # capability may be needed for a different resource in this continuation.
    assert [item["role"] for item in trajectory.json()["data"]["items"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]
