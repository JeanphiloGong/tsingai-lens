from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import BaseModel, ValidationError

from agent.tools.registry import CapabilityRegistry, ToolExecutionContext, ToolSpec
from domain.chat import ChatToolResult, ToolResultStatus


class ReadArguments(BaseModel):
    document_id: str
    source_ref: str


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def read_source(
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ChatToolResult:
    assert isinstance(arguments, ReadArguments)
    return ChatToolResult(
        tool_call_id=context.tool_call_id or "internal-call",
        status=ToolResultStatus.SUCCEEDED,
        data={
            "document_id": arguments.document_id,
            "source_ref": arguments.source_ref,
        },
    )


def make_spec() -> ToolSpec:
    return ToolSpec(
        name="read_source",
        description="Read one canonical Source.",
        input_model=ReadArguments,
        handler=read_source,
    )


def test_registry_exports_schema_and_resolves_registered_tool() -> None:
    registry = CapabilityRegistry((make_spec(),))

    spec = registry.get("read_source")

    assert spec is not None
    assert spec.model_schema()["function"]["parameters"]["required"] == [
        "document_id",
        "source_ref",
    ]
    assert registry.specs == (spec,)


def test_registry_rejects_empty_trimmed_or_duplicate_names() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        CapabilityRegistry((ToolSpec("", "", ReadArguments, read_source),))

    with pytest.raises(ValueError, match="must be trimmed"):
        CapabilityRegistry((ToolSpec(" read_source", "", ReadArguments, read_source),))

    spec = make_spec()
    with pytest.raises(ValueError, match="duplicate tool: read_source"):
        CapabilityRegistry((spec, spec))


@pytest.mark.anyio
async def test_execute_rejects_unknown_tool_and_invalid_arguments_before_calling_handler() -> None:
    async def unexpected_handler(context: ToolExecutionContext, arguments: BaseModel) -> ChatToolResult:
        pytest.fail("invalid tool call reached the handler")

    registry = CapabilityRegistry((replace(make_spec(), handler=unexpected_handler),))
    context = ToolExecutionContext(task_id="user-1", user_id="workspace-1", workspace_id="task-1", tool_call_id="operation-1", operation_id="operation")

    with pytest.raises(LookupError, match="^unknown_tool$"):
        await registry.execute("missing_tool", {}, context=context)

    with pytest.raises(ValidationError):
        await registry.execute("read_source", {"document_id": "paper-1"}, context=context)


@pytest.mark.anyio
async def test_execute_passes_server_context_and_parsed_arguments_to_handler() -> None:
    registry = CapabilityRegistry((make_spec(),))

    result = await registry.execute(
        "read_source",
        {"document_id": "paper-1", "source_ref": "methods"},
        context=ToolExecutionContext(
            user_id="user-1",
            workspace_id="workspace-1",
            task_id="task-1",
            operation_id="operation-1",
            tool_call_id="call-1",
        ),
    )

    assert result.tool_call_id == "call-1"
    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.data == {
        "document_id": "paper-1",
        "source_ref": "methods",
    }
