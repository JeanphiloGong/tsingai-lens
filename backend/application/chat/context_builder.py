"""Build bounded model context without orphaning capability messages."""

from __future__ import annotations

import json

from domain.chat import ChatMessage, ChatMessageRole


class ChatContextBuilder:
    def __init__(self, *, max_messages: int = 40, max_chars: int = 32_000) -> None:
        if max_messages < 2:
            raise ValueError("max_messages must allow one tool call/result pair")
        if max_chars < 1_000:
            raise ValueError("max_chars must be at least 1000")
        self.max_messages = max_messages
        self.max_chars = max_chars

    def for_model(
        self,
        messages: tuple[ChatMessage, ...],
    ) -> tuple[ChatMessage, ...]:
        selected: list[tuple[ChatMessage, ...]] = []
        message_count = 0
        char_count = 0
        for unit in reversed(self._protocol_units(messages)):
            unit_chars = sum(self._size(item) for item in unit)
            if (
                message_count + len(unit) > self.max_messages
                or char_count + unit_chars > self.max_chars
            ):
                break
            selected.append(unit)
            message_count += len(unit)
            char_count += unit_chars
        return tuple(message for unit in reversed(selected) for message in unit)

    @staticmethod
    def _protocol_units(
        messages: tuple[ChatMessage, ...],
    ) -> tuple[tuple[ChatMessage, ...], ...]:
        units: list[tuple[ChatMessage, ...]] = []
        position = 0
        while position < len(messages):
            message = messages[position]
            if message.role is ChatMessageRole.TOOL:
                position += 1
                continue
            if message.role is ChatMessageRole.ASSISTANT and message.tool_call_id:
                following = messages[position + 1] if position + 1 < len(messages) else None
                if (
                    following is not None
                    and following.role is ChatMessageRole.TOOL
                    and following.tool_call_id == message.tool_call_id
                ):
                    units.append((message, following))
                    position += 2
                    continue
                position += 1
                continue
            units.append((message,))
            position += 1
        return tuple(units)

    @staticmethod
    def _size(message: ChatMessage) -> int:
        return len(
            json.dumps(
                message.to_record(),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        )


__all__ = ["ChatContextBuilder"]
