from __future__ import annotations

import json
import re
from typing import Any


_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def coerce_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return str(content or "").strip()

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            text = item
        else:
            text = getattr(item, "text", None)
            if text is None and isinstance(item, dict):
                text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts).strip()


def extract_json_object(response_text: str) -> str:
    text = str(response_text or "").strip()
    if not text:
        raise RuntimeError("structured extraction returned empty JSON text")

    fenced_match = _JSON_FENCE_PATTERN.search(text)
    if fenced_match is not None:
        return fenced_match.group(1).strip()

    candidates: list[str] = []
    start: int | None = None
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{" and depth == 0:
            start = index
        if char == "{":
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start : index + 1])
                start = None

    if not candidates:
        raise RuntimeError("structured extraction returned no JSON object")
    return candidates[-1].strip()


def load_json_payload(response_text: str) -> Any:
    try:
        return json.loads(response_text)
    except json.JSONDecodeError as error:
        sanitized = strip_trailing_commas(response_text)
        if sanitized == response_text:
            raise
        try:
            return json.loads(sanitized)
        except json.JSONDecodeError:
            raise error


def strip_trailing_commas(response_text: str) -> str:
    result: list[str] = []
    in_string = False
    escape = False

    for char in response_text:
        if in_string:
            result.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            result.append(char)
            continue

        if char in "}]":
            last_non_whitespace = len(result) - 1
            while last_non_whitespace >= 0 and result[last_non_whitespace].isspace():
                last_non_whitespace -= 1
            if last_non_whitespace >= 0 and result[last_non_whitespace] == ",":
                del result[last_non_whitespace]
            result.append(char)
            continue

        result.append(char)

    return "".join(result)


def trace_text(value: Any, limit: int = 8000) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def trace_json(
    value: Any,
    limit: int = 12000,
) -> dict[str, Any] | list[Any] | str | None:
    if value is None:
        return None
    if isinstance(value, BaseException):
        return trace_text(str(value), limit)
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return trace_text(value, limit)
    if len(encoded) <= limit:
        return value
    return encoded[:limit] + "...[truncated]"
