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
        units = self._protocol_units(messages)
        active_user_index = next(
            (
                index
                for index in range(len(units) - 1, -1, -1)
                if len(units[index]) == 1
                and units[index][0].role is ChatMessageRole.USER
            ),
            None,
        )
        if active_user_index is not None and self._can_reserve_active_user(
            units,
            active_user_index,
        ):
            return self._select_around_active_user(units, active_user_index)

        selected: list[tuple[ChatMessage, ...]] = []
        message_count = 0
        char_count = 0
        for unit in reversed(units):
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

    def _can_reserve_active_user(
        self,
        units: tuple[tuple[ChatMessage, ...], ...],
        active_user_index: int,
    ) -> bool:
        user_unit = units[active_user_index]
        user_chars = sum(self._size(item) for item in user_unit)
        if len(user_unit) > self.max_messages or user_chars > self.max_chars:
            return False
        if active_user_index == len(units) - 1:
            return True
        newest_unit = units[-1]
        newest_chars = sum(self._size(item) for item in newest_unit)
        return (
            len(user_unit) + len(newest_unit) <= self.max_messages
            and user_chars + newest_chars <= self.max_chars
        )

    def _select_around_active_user(
        self,
        units: tuple[tuple[ChatMessage, ...], ...],
        active_user_index: int,
    ) -> tuple[ChatMessage, ...]:
        user_unit = units[active_user_index]
        selected: list[tuple[int, tuple[ChatMessage, ...]]] = [
            (active_user_index, user_unit)
        ]
        message_count = len(user_unit)
        char_count = sum(self._size(item) for item in user_unit)

        for index in range(len(units) - 1, active_user_index, -1):
            unit = units[index]
            unit_chars = sum(self._size(item) for item in unit)
            if (
                message_count + len(unit) > self.max_messages
                or char_count + unit_chars > self.max_chars
            ):
                break
            selected.append((index, unit))
            message_count += len(unit)
            char_count += unit_chars

        for index in range(active_user_index - 1, -1, -1):
            unit = units[index]
            unit_chars = sum(self._size(item) for item in unit)
            if (
                message_count + len(unit) > self.max_messages
                or char_count + unit_chars > self.max_chars
            ):
                break
            selected.append((index, unit))
            message_count += len(unit)
            char_count += unit_chars

        return tuple(
            message
            for _, unit in sorted(selected, key=lambda item: item[0])
            for message in unit
        )

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
        model_message: dict[str, object] = {
            "role": message.role.value,
            "content": message.content,
        }
        if message.tool_call_id:
            model_message["tool_call_id"] = message.tool_call_id
        if message.role is ChatMessageRole.ASSISTANT and message.tool_call_id:
            model_message["tool_name"] = message.tool_name
            model_message["tool_arguments"] = dict(message.tool_arguments or {})
        if message.source_contexts:
            model_message["source_contexts"] = [
                item.to_record() for item in message.source_contexts
            ]
        return len(
            json.dumps(
                model_message,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        )


__all__ = ["ChatContextBuilder"]
