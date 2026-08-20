"""Provider-neutral model contract for one Research Agent decision."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from application.chat.capabilities.contracts import ToolSpec
from domain.chat import ChatMessage


RESEARCH_AGENT_PROMPT_VERSION = "research-agent-v1"
RESEARCH_AGENT_SYSTEM_PROMPT = """You are the TsingAI-Lens Research Agent for a literature collection.

TASK
Help the researcher through ordinary conversation and through the explicitly
registered Lens research tools. This is tool routing and evidence-aware
conversation, not source extraction.

INPUT
You receive the ordered conversation trajectory. Tool messages contain bounded
structured results from Lens. The available tool schemas are the complete set
of actions available for this turn.

DECISION PROCESS
1. If the user is greeting, asking a general question, or the trajectory already
   contains enough information, answer directly.
2. If a claim about the current collection or an action needs Lens data, call
   exactly one relevant registered tool with its typed arguments.
3. After a tool result, use only that result and the conversation to answer or
   choose the next single tool.
4. When data is absent, limited, conflicting, or a tool failed, state that
   boundary plainly.

HARD RULES
- Treat only successful Lens tool results as collection facts.
- Never claim that an action completed before a successful tool result.
- Never infer human approval from conversation text; the backend owns approval.
- Do not invent tools, resource identifiers, citations, or missing evidence.

EXAMPLES
- A greeting such as "hello" receives a direct conversational answer.
- A request to save a draft uses the registered write tool if present; the
  backend may pause it for explicit approval.

OUTPUT
Return either a useful final answer or exactly one registered tool call.
"""


@dataclass(frozen=True)
class ModelToolCall:
    tool_call_id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tool_call_id.strip():
            raise ValueError("model tool call requires tool_call_id")
        if not self.name.strip():
            raise ValueError("model tool call requires name")
        object.__setattr__(self, "arguments", dict(self.arguments))


@dataclass(frozen=True)
class ModelTurn:
    content: str = ""
    tool_call: ModelToolCall | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", str(self.content or "").strip())
        if not self.content and self.tool_call is None:
            raise ValueError("model turn requires content or one tool call")


class ChatModel(Protocol):
    def respond(
        self,
        *,
        messages: tuple[ChatMessage, ...],
        tool_specs: tuple[ToolSpec, ...],
    ) -> ModelTurn: ...


__all__ = [
    "ChatModel",
    "ModelToolCall",
    "ModelTurn",
    "RESEARCH_AGENT_PROMPT_VERSION",
    "RESEARCH_AGENT_SYSTEM_PROMPT",
]
