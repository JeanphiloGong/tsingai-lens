"""Numeric text parsing shared by Source inspection and structural table checks."""

from __future__ import annotations

import re
from typing import Any


NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def numeric_match_tokens(value: Any) -> tuple[str, ...]:
    tokens: list[str] = []
    for match in NUMBER_PATTERN.finditer(str(value or "").replace(",", "")):
        number_text = match.group(0)
        number = coerce_number(number_text)
        if number is None:
            continue
        if number.is_integer():
            tokens.append(str(int(number)))
        else:
            tokens.append(("%f" % number).rstrip("0").rstrip("."))
    return tuple(tokens)


def coerce_number(value: Any) -> float | None:
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    scientific_match = re.search(
        r"([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:[xX\u00d7]\s*10)\s*\^?\s*([-+]?\d+)",
        text,
    )
    if scientific_match is not None:
        return float(scientific_match.group(1)) * (10 ** int(scientific_match.group(2)))
    match = NUMBER_PATTERN.search(text)
    if match is None:
        return None
    return float(match.group(0))


def coerce_result_cell_number(value: Any) -> float | None:
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    matches = list(NUMBER_PATTERN.finditer(text))
    if len(matches) >= 2:
        leading_prefix = text[: matches[0].start()]
        between_first_and_second = text[matches[0].end() : matches[1].start()]
        if "(" in leading_prefix and ")" in between_first_and_second:
            return float(matches[1].group(0))
    return coerce_number(text)
