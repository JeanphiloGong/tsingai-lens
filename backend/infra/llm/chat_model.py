"""OpenAI-compatible transport adapter for the Research Agent."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

from openai import OpenAI

from application.chat.capabilities import ToolSpec
from application.chat.model import (
    ModelToolCall,
    ModelTurn,
    RESEARCH_AGENT_PROMPT_VERSION,
    RESEARCH_AGENT_SYSTEM_PROMPT,
)
from domain.chat import ChatMessage, ChatMessageRole
from infra.llm.usage import record_llm_completion, record_llm_prompt_version


class OpenAIChatModel:
    def __init__(
        self,
        *,
        client: Any | None = None,
        model: str | None = None,
    ) -> None:
        self.model = (
            model
            or os.getenv("LLM_MODEL")
            or "gpt-4o-mini"
        ).strip()
        self.client = client or OpenAI(
            api_key=os.getenv("LLM_API_KEY", "").strip() or "not-needed",
            base_url=os.getenv("LLM_BASE_URL", "").strip() or None,
        )

    def respond(
        self,
        *,
        messages: tuple[ChatMessage, ...],
        tool_specs: tuple[ToolSpec, ...],
    ) -> ModelTurn:
        request: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": RESEARCH_AGENT_SYSTEM_PROMPT},
                *(_provider_message(message) for message in messages),
            ],
        }
        if tool_specs:
            request.update(
                tools=[spec.model_schema() for spec in tool_specs],
                tool_choice="auto",
                parallel_tool_calls=False,
            )
        completion = self.client.chat.completions.create(**request)
        record_llm_prompt_version("research_agent", RESEARCH_AGENT_PROMPT_VERSION)
        record_llm_completion(completion, requested_model=self.model)
        if not getattr(completion, "choices", None):
            raise ValueError("research model returned no choices")
        message = completion.choices[0].message
        tool_calls = tuple(getattr(message, "tool_calls", None) or ())
        if len(tool_calls) > 1:
            raise ValueError("research model must return exactly one tool call")
        content = str(getattr(message, "content", None) or "").strip()
        if not tool_calls:
            return ModelTurn(content=content)

        raw_call = tool_calls[0]
        if getattr(raw_call, "type", "function") != "function":
            raise ValueError("research model returned an unsupported tool call type")
        function = raw_call.function
        arguments = json.loads(str(function.arguments or "{}"))
        if not isinstance(arguments, Mapping):
            raise ValueError("research tool arguments must be a JSON object")
        return ModelTurn(
            content=content,
            tool_call=ModelToolCall(
                tool_call_id=str(raw_call.id),
                name=str(function.name),
                arguments=dict(arguments),
            ),
        )


def _provider_message(message: ChatMessage) -> dict[str, Any]:
    if message.role is ChatMessageRole.USER:
        return {"role": "user", "content": message.content}
    if message.role is ChatMessageRole.TOOL:
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": message.content,
        }
    if message.tool_call_id:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": message.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": message.tool_name,
                        "arguments": json.dumps(
                            dict(message.tool_arguments or {}),
                            ensure_ascii=True,
                            separators=(",", ":"),
                        ),
                    },
                }
            ],
        }
    return {"role": "assistant", "content": message.content}


__all__ = ["OpenAIChatModel"]
