"""Read conversation context and model-call coverage for feedback workers."""

from __future__ import annotations

from typing import Any

from application.feedback.source_coverage import ChatCoverageAudit
from domain.chat import ChatMessage, ChatMessageRole
from repositories.chat_repository import ChatRepo

def conversation_before_answer(messages: tuple[ChatMessage, ...], answer: ChatMessage) -> list[dict[str, str]]:
    """Capture visible input turns, excluding the target and all later corrections."""
    result: list[dict[str, str]] = []
    for message in messages:
        if message.message_id == answer.message_id:
            break
        if message.role in {ChatMessageRole.USER, ChatMessageRole.ASSISTANT} and message.content and not message.tool_calls:
            result.append({"role": message.role.value, "content": message.content})
    # Tool-use commentary after the question is not a prior conversation turn.
    while result and result[-1]["role"] != "user":
        result.pop()
    return result


async def read_chat_coverage_audit(
    session_id: str,
    messages: tuple[ChatMessage, ...],
) -> ChatCoverageAudit:
    """Read optional audit records without making legacy trajectories fail.

    P1 trajectories may predate model-call/tool-call persistence.  In that
    case ``None`` is passed to the projection, which keeps selected context as
    a request signal and leaves inspection status unknown/partial.
    """

    try:
        collected: list[Any] = []
        offset = 0
        while offset < 10_000:
            batch = await ChatRepo.read_model_calls(session_id, limit=200, offset=offset)
            collected.extend(batch)
            if len(batch) < 200:
                break
            offset += len(batch)
        model_calls: tuple[Any, ...] | None = tuple(collected)
    except TypeError:
        raise
    except Exception:  # noqa: BLE001
        # An unavailable audit cannot establish that a Source was inspected.
        model_calls = None

    tool_ids = {
        request.tool_call_id
        for message in messages
        for request in message.tool_calls
    }
    tool_calls: dict[str, Any] = {}
    tool_audit_error = False
    for tool_call_id in tool_ids:
        try:
            record = await ChatRepo.read_tool_call(tool_call_id)
        except Exception:  # noqa: BLE001
            tool_audit_error = True
            continue
        if record is not None:
            tool_calls[tool_call_id] = record
    return ChatCoverageAudit(
        model_calls=model_calls,
        tool_calls=tool_calls,
        tool_audit_error=tool_audit_error,
    )
