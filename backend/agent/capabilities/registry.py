"""The Agent-owned registry for typed business capabilities."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from domain.chat import ChatToolResult
from pydantic import BaseModel


@dataclass(frozen=True)
class ToolExecutionContext:
    """Trusted identity and execution IDs supplied by the Agent runtime."""

    user_id: str
    workspace_id: str
    task_id: str
    operation_id: str
    tool_call_id: str | None = None
    max_result_tokens: int = 12_000


ToolHandler = Callable[
    [ToolExecutionContext, BaseModel],
    Awaitable[ChatToolResult],
]


@dataclass(frozen=True)
class ToolSpec:
    """Static model-facing metadata and the business handler for one tool."""

    name: str
    description: str
    input_model: type[BaseModel]
    handler: ToolHandler
    source: str
    parallel_safe: bool = False
    initially_available: bool = False
    requires_approval: bool = False

    def model_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_model.model_json_schema(),
            },
        }


class CapabilityRegistry:
    """Register trusted tools and resolve them by their stable name."""

    def __init__(self, specs: tuple[ToolSpec, ...] = ()) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        name = spec.name.strip()
        if not name:
            raise ValueError("tool name cannot be empty")
        if name != spec.name:
            raise ValueError("tool name must be trimmed")
        if name in self._specs:
            raise ValueError(f"duplicate tool: {name}")
        self._specs[name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name.strip())

    async def execute(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        context: ToolExecutionContext,
    ) -> ChatToolResult:
        spec = self.get(name)
        if spec is None:
            raise LookupError("unknown_tool")
        return await spec.handler(context, spec.input_model.model_validate(arguments))

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs.values())


__all__ = [
    "CapabilityRegistry",
    "ToolExecutionContext",
    "ToolHandler",
    "ToolSpec",
]
