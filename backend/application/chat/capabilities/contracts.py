"""Explicit contracts for Lens capabilities visible to the Research Agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from domain.chat import ChatToolResult, ToolRisk


@dataclass(frozen=True)
class AgentContext:
    session_id: str
    user_id: str
    collection_id: str


@dataclass(frozen=True)
class CapabilityExecutionContext:
    session_id: str
    user_id: str
    collection_id: str
    tool_call_id: str

    @classmethod
    def for_call(
        cls,
        context: AgentContext,
        tool_call_id: str,
    ) -> "CapabilityExecutionContext":
        return cls(
            session_id=context.session_id,
            user_id=context.user_id,
            collection_id=context.collection_id,
            tool_call_id=tool_call_id,
        )


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk: ToolRisk
    input_model: type[BaseModel]

    def model_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_model.model_json_schema(),
            },
        }


class CapabilityHandler(Protocol):
    spec: ToolSpec

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: BaseModel,
    ) -> ChatToolResult: ...


__all__ = [
    "AgentContext",
    "CapabilityExecutionContext",
    "CapabilityHandler",
    "ToolSpec",
]
