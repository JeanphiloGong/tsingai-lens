"""Build bounded model context without orphaning capability messages."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from domain.chat import ChatMessage, ChatMessageRole


@dataclass(frozen=True)
class ChatModelContext:
    messages: tuple[ChatMessage, ...]
    rollover_summary: str = ""
    require_tool_call: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "rollover_summary", self.rollover_summary.strip())


_LINEAGE_FIELDS = {
    "collection_id", "document_id", "document_ids", "objective_id", "finding_id",
    "evidence_id", "source_ref", "source_kind", "table_ref", "table_id", "source_digest",
    "digest", "resource_id", "resource_type", "href", "task_id", "run_id", "status",
    "draft_id", "analysis_version", "source_analysis_version", "source_finding_ids",
    "source_evidence_ids", "offset", "next_offset", "row_offset", "next_row_offset",
    "limit", "page", "error_code", "content_truncated", "has_more", "paper_total",
}


class ChatContextBuilder:
    def __init__(
        self,
        *,
        max_messages: int = 40,
        max_chars: int = 128_000,
        max_summary_chars: int | None = None,
    ) -> None:
        if max_messages < 2:
            raise ValueError("max_messages must allow one tool call/result pair")
        if max_chars < 1_000:
            raise ValueError("max_chars must be at least 1000")
        self.max_messages = max_messages
        self.max_chars = max_chars
        self.max_summary_chars = (
            min(4_000, max_chars // 4)
            if max_summary_chars is None else max_summary_chars
        )
        if not 0 < self.max_summary_chars < max_chars:
            raise ValueError("summary budget must be positive and less than context budget")

    def for_model(
        self,
        messages: tuple[ChatMessage, ...],
        *,
        active_user_message_id: str | None = None,
    ) -> ChatModelContext:
        units = self._protocol_units(messages)
        active_index = next(
            (
                i for i in range(len(units) - 1, -1, -1)
                if units[i][0].role is ChatMessageRole.USER
                and (
                    active_user_message_id is None
                    or units[i][0].message_id == active_user_message_id
                )
            ),
            None,
        )
        if active_user_message_id is not None and active_index is None:
            raise ValueError("active user message is missing from context")
        # Runner instructions follow the real user message and are transient.
        pinned = {
            i for i, unit in enumerate(units)
            if active_index is not None and i >= active_index
            and unit[0].role is ChatMessageRole.USER
        }
        selected = set(pinned)
        char_count = sum(self._size(message) for i in pinned for message in units[i])
        message_count = sum(len(units[i]) for i in pinned)
        if char_count > self.max_chars or message_count > self.max_messages:
            raise ValueError("active question and selected Source exceed context budget")
        needs_rollover = (
            sum(self._size(message) for message in messages) > self.max_chars
            or len(messages) > self.max_messages
            or sum(map(len, units)) != len(messages)
        )
        summary_budget = (
            min(self.max_summary_chars, self.max_chars - char_count)
            if needs_rollover else 0
        )
        for i in range(len(units) - 1, -1, -1):
            if i in selected:
                continue
            size = sum(self._size(message) for message in units[i])
            if (
                char_count + size <= self.max_chars - summary_budget
                and message_count + len(units[i]) <= self.max_messages
            ):
                selected.add(i)
                char_count += size
                message_count += len(units[i])
        selected_messages = tuple(message for i in sorted(selected) for message in units[i])
        selected_ids = {message.message_id for message in selected_messages}
        omitted = tuple(
            message for message in messages if message.message_id not in selected_ids
        )
        summary = self._rollover_summary(
            omitted, min(self.max_summary_chars, self.max_chars - char_count)
        )
        return ChatModelContext(selected_messages, summary)

    @staticmethod
    def _rollover_summary(messages: tuple[ChatMessage, ...], budget: int) -> str:
        def project(value: Any) -> Any:
            if isinstance(value, Mapping):
                result = {}
                for key, item in value.items():
                    if key in _LINEAGE_FIELDS and (
                        isinstance(item, (str, int, float, bool)) or item is None
                    ):
                        result[key] = item
                    elif (
                        key in _LINEAGE_FIELDS and isinstance(item, (list, tuple))
                        and all(isinstance(part, (str, int)) for part in item)
                    ):
                        result[key] = list(item)
                    elif isinstance(item, (Mapping, list, tuple)):
                        child = project(item)
                        if child:
                            result[key] = child
                return result
            if isinstance(value, (list, tuple)):
                return [
                    child for item in value
                    if isinstance(item, Mapping) and (child := project(item))
                ]
            return None

        entries = []
        for message in reversed(messages):
            if message.tool_result:
                result = message.tool_result
                for ref in result.resource_refs:
                    entries.append({
                        "tool_call_id": result.tool_call_id, "resource": ref.to_record(),
                    })
                entries.append({
                    "tool_call_id": result.tool_call_id, "status": result.status.value,
                    "error_code": result.error_code, "data": project(result.data),
                })
            for request in message.tool_calls:
                entries.append({
                    "tool_call_id": request.tool_call_id, "name": request.name,
                    "position": request.position, "arguments": project(request.arguments),
                })
            for source in message.source_contexts:
                entries.append({
                    "document_id": source.document_id, "source_ref": source.source_ref,
                    "source_digest": source.source_digest,
                    "resource": source.resource_ref.to_record(),
                })
        if not entries:
            return ""
        kept = []
        summary = ""
        for entry in entries:
            candidate = json.dumps(
                {"entries": [*kept, entry]}, ensure_ascii=True, separators=(",", ":")
            )
            if len(candidate) <= budget:
                kept.append(entry)
                summary = candidate
        return summary

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
            if message.role is ChatMessageRole.ASSISTANT and message.tool_calls:
                following = messages[position + 1:position + 1 + len(message.tool_calls)]
                if len(following) == len(message.tool_calls) and all(
                    result.role is ChatMessageRole.TOOL
                    and result.tool_call_id == request.tool_call_id
                    for request, result in zip(message.tool_calls, following)
                ):
                    units.append((message, *following))
                    position += 1 + len(following)
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
        if message.tool_calls:
            model_message["tool_calls"] = [
                request.to_record() for request in message.tool_calls
            ]
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


__all__ = ["ChatContextBuilder", "ChatModelContext"]
