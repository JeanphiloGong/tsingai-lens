from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy import func, select

from agent.application.task_execution import task_execution
from agent.tools.registry import CapabilityRegistry, ToolSpec
from domain.chat import ChatToolResult, ToolResultStatus
from infra.identity.client import SESSION_COOKIE_NAME
from infra.persistence.postgres.models.chat import (
    AgentOperationORM,
    ChatModelCallORM,
)
from infra.persistence.postgres.models.model_connection import ModelConnectionORM
from infra.persistence.postgres.models.workspace import WorkspaceORM
from main import app

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_module_cutover_uses_one_task_and_final_tables(
    postgres_session_factory, identity_subjects, monkeypatch
):
    owner = await identity_subjects.create_subject(email="cutover-owner@example.test")
    session = await identity_subjects.issue_session(email="cutover-owner@example.test")
    other = await identity_subjects.create_subject(email="cutover-other@example.test")
    other_session = await identity_subjects.issue_session(email="cutover-other@example.test")
    assert other["user_id"] != owner["user_id"]
    assert not any(
        path.startswith("/api/v1/chat-sessions")
        or path.endswith(("/permissions", "/agent-permissions"))
        or any(segment in path for segment in ("/feedback-cases", "/feedback-datasets", "/model-calls"))
        for path in app.openapi()["paths"]
    )
    now = datetime.now(UTC)
    async with postgres_session_factory.begin() as db:
        db.add(WorkspaceORM(
            workspace_id="cutover-workspace", owner_user_id=owner["user_id"],
            name="316L papers", status="idle", created_at=now, updated_at=now,
        ))
        db.add(ModelConnectionORM(
            connection_id="cutover-model", display_name="Cutover model", kind="chat",
            base_url="http://model.test/v1", model="research", enabled=True,
            created_at=now, updated_at=now,
        ))

    class ReadSource(BaseModel):
        source_ref: str

    reads = []

    async def read_source(context, request):
        assert context.workspace_id == "cutover-workspace"
        assert context.user_id == owner["user_id"]
        reads.append(context.task_id)
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data={"source_ref": request.source_ref, "hold_minutes": 30},
        )

    monkeypatch.setattr(task_execution, "registry", CapabilityRegistry((
        ToolSpec("read_source", "Read a paper Source.", ReadSource, read_source),
        ToolSpec(
            "review_source", "Save a Source review.", ReadSource, read_source,
            requires_approval=True,
        ),
    )))

    fail_once = True

    class FakeProvider:
        def __init__(self, **arguments):
            self.chat = SimpleNamespace(completions=self)

        async def create(self, *, messages, tools, **options):
            nonlocal fail_once
            assert {item["function"]["name"] for item in tools} == {"read_source", "review_source"}
            if messages[-1]["role"] == "tool" and fail_once:
                fail_once = False
                from agent.application.model import ModelResponseError
                raise ModelResponseError("Connection lost.", reason="transport_error")
            if messages[-1]["role"] == "tool":
                assert '"hold_minutes": 30' in messages[-1]["content"]
                message = SimpleNamespace(content="The Methods report a 30-minute hold.", tool_calls=[])
                finish = "stop"
            else:
                name = "review_source" if "review" in messages[-1]["content"] else "read_source"
                function = SimpleNamespace(name=name, arguments='{"source_ref":"methods"}')
                message = SimpleNamespace(
                    content=None, tool_calls=[SimpleNamespace(id="provider-call", function=function)]
                )
                finish = "tool_calls"
            return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)], usage=None)

        async def close(self):
            pass

    monkeypatch.setattr("infra.llm.chat_model.AsyncOpenAI", FakeProvider)
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://lens.test",
                    cookies={SESSION_COOKIE_NAME: session["session_id"]}) as client,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://lens.test",
                    cookies={SESSION_COOKIE_NAME: other_session["session_id"]}) as outsider,
    ):
        created = await client.post(
            "/api/v1/conversations", json={"workspace_id": "cutover-workspace"}
        )
        conversation_id = created.json()["data"]["conversation_id"]
        path = f"/api/v1/conversations/{conversation_id}"
        sent = await client.post(f"{path}/messages", json={"message": "Inspect Methods"})
        assert sent.status_code == 200
        task_id = sent.json()["data"]["task_id"]
        task_path = f"{path}/tasks/{task_id}"
        task = (await client.get(task_path)).json()["data"]
        assert task["status"] == "interrupted"
        assert task["error_code"] == "transport_error"
        assert reads == [task_id]
        assert (await outsider.get(task_path)).status_code == 404
        assert (await outsider.get(f"{path}/messages")).status_code == 404

        resumed = await client.post(f"{task_path}/resume", json={
            "request_id": str(uuid4()),
            "expected_checkpoint_revision": task["checkpoint_revision"],
        })
        assert resumed.status_code == 200
        completed = (await client.get(task_path)).json()["data"]
        assert completed["status"] == "completed"
        assert reads == [task_id]
        events = await client.get(f"{task_path}/events")
        assert events.status_code == 200
        assert f'"task_id": "{task_id}"' in events.text
        assert '"status": "completed"' in events.text
        assert not (await client.get(
            f"{task_path}/events", params={"after_revision": completed["checkpoint_revision"]}
        )).text
        messages = (await client.get(f"{path}/messages")).json()["data"]["items"]
        assert messages[-1]["message_id"] == completed["final_message_id"]
        assert messages[-1]["content"] == "The Methods report a 30-minute hold."
        assert messages[-1]["can_rate"] is True
        assert messages[-2]["can_rate"] is False

        approved_send = await client.post(f"{path}/messages", json={
            "message": "Please review the Methods", "parent_message_id": completed["final_message_id"],
        })
        approval_id = approved_send.json()["data"]["task_id"]
        approval_path = f"{path}/tasks/{approval_id}"
        waiting = (await client.get(approval_path)).json()["data"]
        assert waiting["status"] == "approval_required"
        operation = waiting["active_operation"]
        decision_path = f"{approval_path}/operations/{operation['operation_id']}/decision"
        wrong = await client.post(decision_path, json={
            "request_id": str(uuid4()), "decision": "approved", "arguments_digest": "0" * 64,
        })
        assert wrong.status_code == 409
        assert reads == [task_id]
        approved = await client.post(decision_path, json={
            "request_id": str(uuid4()), "decision": "approved",
            "arguments_digest": operation["arguments_digest"],
        })
        assert approved.status_code == 200
        assert (await client.get(approval_path)).json()["data"]["status"] == "completed"
        assert reads == [task_id, approval_id]
        assert (await client.get(f"{path}/tree")).status_code == 200
        assert not any("/model-calls" in route for route in app.openapi()["paths"])
        for suffix in ("", "/one"):
            retired = await client.get(
                f"/api/v1/chat-sessions/{conversation_id}/model-calls{suffix}"
            )
            assert retired.json()["code"] == 200201

    async with postgres_session_factory() as db:
        operations = (await db.scalars(select(AgentOperationORM))).all()
        assert {(item.task_id, item.status) for item in operations} == {
            (task_id, "succeeded"), (approval_id, "succeeded"),
        }
        assert all(item.assistant_message_id for item in operations)
        sequence = (await db.scalars(select(ChatModelCallORM.sequence)
            .where(ChatModelCallORM.task_id == task_id)
            .order_by(ChatModelCallORM.sequence))).all()
        assert sequence == [0, 1, 2]
