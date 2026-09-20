from __future__ import annotations

import pytest
from pydantic import BaseModel

from application.chat import CapabilityRegistry, ModelToolCall, ModelTurn, ResearchAgentRunner
from application.chat.capability_policy import select_tool_specs
from domain.chat import ChatMessage, ChatToolRequest, ChatToolResult, ToolRisk
from tests.unit.application.test_research_agent_runner import _Capability, _Model, _context


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def discovered_messages():
    return [
        ChatMessage.user(
            message_id="user", session_id="chat-1", content="Check the paper's measurements.",
            created_at="2026-09-20T00:00:00Z",
        ),
        ChatMessage.assistant_tool_calls(
            message_id="request", session_id="chat-1", content="",
            tool_calls=(ChatToolRequest(
                tool_call_id="discovery", name="discover_research_tools",
                arguments={"tool_names": ["read_source"], "source_inspection_required": True},
                position=0,
            ),), created_at="2026-09-20T00:00:01Z",
        ),
        ChatMessage.from_tool_result(
            message_id="result", session_id="chat-1",
            result=ChatToolResult(
                tool_call_id="discovery", status="succeeded",
                data={"loaded_tool_names": ["read_source"]},
            ), created_at="2026-09-20T00:00:02Z",
        ),
    ]


@pytest.mark.parametrize("legacy_metadata", [False, True])
def test_discovered_name_resolves_current_parameters(discovered_messages, legacy_metadata):
    class CurrentReadArguments(BaseModel):
        document_id: str
        source_ref: str

    if legacy_metadata:
        discovered_messages[-1].tool_result.data["catalog_version"] = "old-catalog"
    read = _Capability("read_source", ToolRisk.READ, input_model=CurrentReadArguments)
    registry = CapabilityRegistry((read, _Capability("inspect_table", ToolRisk.READ)))

    selected = select_tool_specs(registry, discovered_messages, [])

    assert [spec.name for spec in selected] == ["read_source"]
    assert selected[0] is read.spec
    assert selected[0].input_model is CurrentReadArguments
    assert read.executed_arguments == []


def test_removed_tool_is_not_restored_from_discovery(discovered_messages):
    registry = CapabilityRegistry((_Capability("inspect_table", ToolRisk.READ),))
    assert [spec.name for spec in select_tool_specs(registry, discovered_messages, [])] == [
        "discover_research_tools",
    ]


def test_new_user_request_starts_fresh_discovery(discovered_messages):
    registry = CapabilityRegistry((_Capability("read_source", ToolRisk.READ),))
    discovered_messages.append(ChatMessage.user(
        message_id="next-user", session_id="chat-1", content="Now inspect the other paper.",
        created_at="2026-09-20T00:01:00Z",
    ))
    assert [spec.name for spec in select_tool_specs(registry, discovered_messages, [])] == [
        "discover_research_tools",
    ]


@pytest.mark.anyio
async def test_discovery_then_read_produces_identifiable_domain_result():
    from tests.integration.test_deep_path_research_flow import _tool_result

    read = _Capability("read_source", ToolRisk.READ, result_data={
        "document_id": "p1", "source_kind": "text_window", "source_ref": "results",
        "source_digest": "a" * 64, "content_truncated": False,
        "content": "Measured elongation: 8%.",
    })
    model = _Model(
        ModelTurn(tool_calls=(ModelToolCall(name="discover_research_tools", arguments={
            "tool_names": ["read_source"], "source_inspection_required": True,
        }),)),
        ModelTurn(tool_calls=(ModelToolCall(name="read_source"),)),
        ModelTurn(content="The inspected passage reports 8% elongation."),
    )
    result = await ResearchAgentRunner(model=model, capabilities=CapabilityRegistry((read,))).run_turn(
        context=_context(), previous_messages=(), user_message="Check this paper's elongation measurement.",
    )
    assert result.status == "completed"
    discovery = next(message.tool_result for message in result.messages if message.tool_result is not None)
    assert "catalog_version" not in discovery.data
    assert _tool_result({"messages": result.messages}).data["content"] == "Measured elongation: 8%."
    assert read.executed_arguments == [{}]
