"""Exercise terminal notes -> real HTTP new request -> new persisted snapshot."""

import json

import pytest
from application.chat import CapabilityRegistry, ModelTurn, ResearchAgentRunner
from domain.chat import ChatMessage
from repositories.chat_repository import ChatResponseSnapshot
from tests.integration.persistence.test_chat_branches import (
    NOW,
    branch_app,
)  # noqa: F401
from tests.support.chat_model_connections import scripted_chat_runner  # noqa: F401

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("terminal_status", ["completed", "failed", "interrupted"])
async def test_new_http_request_inherits_notes_but_not_old_runtime_budget(
    branch_app, scripted_chat_runner, terminal_status
):
    fixture = branch_app
    session = await fixture.service.create_session(
        collection_id="collection", user_id=fixture.owner
    )
    prior = ChatMessage.user(
        message_id="prior-input",
        session_id=session.session_id,
        content="The density target is 99.9%; it is not a measured density.",
        created_at=NOW,
    )
    await fixture.repository.save_trajectory(
        chat_session=session, messages=(prior,), tool_calls=(), tool_results=()
    )
    notes = {
        "scope": "old scope",
        "checks": [
            {
                "statement": "The researcher supplied a density target, not a measurement.",
                "conditions": "user constraint",
                "basis_message_ids": [prior.message_id],
                "unresolved": "density must be measured",
            }
        ],
        "next_actions": ["obsolete action"],
    }
    await fixture.repository.save_response_snapshot(
        session.session_id,
        ChatResponseSnapshot(
            response_id="previous-response",
            sequence=3,
            started_at=NOW,
            updated_at=NOW,
            status=terminal_status,
            progress={
                "elapsed_ms": 300000,
                "executed_tool_count": 96,
                "total_tokens": 1000000,
                "context_checkpoint": {
                    "user_message_id": prior.message_id,
                    "working_summary": json.dumps(notes),
                    "compacted_message_ids": [],
                },
            },
        ),
    )
    observed = []

    class Model:
        async def respond(self, *, context, **kwargs):
            observed.append(context)
            memory = json.loads(context.working_summary)
            assert memory["checks"] == notes["checks"]
            assert not memory["next_actions"]
            assert (
                next(
                    m.content
                    for m in context.messages
                    if m.message_id == context.active_user_message_id
                )
                == "Continue; exclude paper B."
            )
            return ModelTurn(
                content="Paper B excluded. Density remains an unmeasured constraint."
            )

    fixture.service.runner = ResearchAgentRunner(
        model=Model(), capabilities=CapabilityRegistry(())
    )
    response = await fixture.client.post(
        f"/api/v1/chat-sessions/{session.session_id}/messages",
        json={"message": "Continue; exclude paper B."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "completed"
    assert len(observed) == 1
    saved = await fixture.repository.read_messages(session.session_id)
    assert saved[0] == prior and saved[-2].content == "Continue; exclude paper B."
    snapshot = await fixture.repository.read_response_snapshot(session.session_id)
    assert (
        snapshot.response_id != "previous-response" and snapshot.status == "completed"
    )
    assert snapshot.progress["executed_tool_count"] == 0
    assert snapshot.progress["elapsed_ms"] < 300000
    assert snapshot.progress["execution_plan"] is None
