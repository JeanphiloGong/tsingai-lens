from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from agent.capabilities import (
    CapabilityRegistry,
    ToolExecutionContext,
    ToolSpec,
)
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
    parsed = ReadArguments.model_validate(arguments)
    return ChatToolResult(
        tool_call_id=context.tool_call_id or "internal-call",
        status=ToolResultStatus.SUCCEEDED,
        data={
            "document_id": parsed.document_id,
            "source_ref": parsed.source_ref,
        },
    )


def make_spec() -> ToolSpec:
    return ToolSpec(
        name="read_source",
        description="Read one canonical Source.",
        input_model=ReadArguments,
        handler=read_source,
        source="document",
        parallel_safe=True,
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
        CapabilityRegistry((ToolSpec("", "", ReadArguments, read_source, "document"),))

    with pytest.raises(ValueError, match="must be trimmed"):
        CapabilityRegistry((ToolSpec(" read_source", "", ReadArguments, read_source, "document"),))

    spec = make_spec()
    with pytest.raises(ValueError, match="duplicate tool: read_source"):
        CapabilityRegistry((spec, spec))


def test_unknown_tool_is_not_resolved_and_arguments_are_typed() -> None:
    registry = CapabilityRegistry((make_spec(),))
    spec = registry.get("missing_tool")
    assert spec is None

    with pytest.raises(ValidationError):
        ReadArguments.model_validate({"document_id": "paper-1"})


@pytest.mark.anyio
async def test_handler_receives_server_context_and_parsed_arguments() -> None:
    spec = make_spec()

    result = await spec.handler(
        ToolExecutionContext(
            user_id="user-1",
            workspace_id="workspace-1",
            task_id="task-1",
            operation_id="operation-1",
            tool_call_id="call-1",
        ),
        ReadArguments(document_id="paper-1", source_ref="methods"),
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.data == {
        "document_id": "paper-1",
        "source_ref": "methods",
    }
