from __future__ import annotations

import re
from typing import Any


_TEMP_RE = re.compile(
    r"(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>°\s?C|℃|C|K)\b",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>d|day|days|h|hr|hrs|hour|hours|min|mins|minute|minutes|s|sec|secs|second|seconds)\b",
    re.IGNORECASE,
)

_AMBIGUOUS_TEMP_TERMS = (
    "room temperature",
    "ambient temperature",
    "ambient conditions",
    "elevated temperature",
    "at room temperature",
    "室温",
    "常温",
    "环境温度",
)
_AMBIGUOUS_DURATION_TERMS = (
    "overnight",
    "several hours",
    "a short time",
    "briefly",
    "prolonged",
    "过夜",
    "长时间",
    "短时间",
)
_ATMOSPHERE_PATTERNS = {
    "AR": re.compile(r"\bAr\b|氩气", re.IGNORECASE),
    "N2": re.compile(r"\bN2\b|氮气", re.IGNORECASE),
    "AIR": re.compile(r"\bair\b|空气", re.IGNORECASE),
    "VACUUM": re.compile(r"\bvacuum\b|真空", re.IGNORECASE),
    "O2": re.compile(r"\bO2\b|氧气", re.IGNORECASE),
    "H2": re.compile(r"\bH2\b|氢气", re.IGNORECASE),
}


class ProtocolNormalizeService:
    """Normalize procedural conditions into stable scalar payloads."""

    def normalize_conditions(self, text: str) -> dict[str, Any]:
        return {
            "temperature": self.normalize_temperature(text),
            "duration": self.normalize_duration(text),
            "atmosphere": self.normalize_atmosphere(text),
            "raw_text": text.strip(),
        }

    def normalize_temperature(self, text: str) -> dict[str, Any]:
        match = _TEMP_RE.search(text)
        if match:
            value = float(match.group("value"))
            unit = match.group("unit").replace(" ", "").upper()
            normalized = value if unit == "K" else round(value + 273.15, 2)
            return {
                "value": normalized,
                "unit": "K",
                "raw_value": match.group(0),
                "status": "reported",
            }

        ambiguous = self._find_term(text, _AMBIGUOUS_TEMP_TERMS)
        if ambiguous:
            return {
                "value": None,
                "unit": None,
                "raw_value": ambiguous,
                "status": "ambiguous",
            }

        return self._not_reported_scalar()

    def normalize_duration(self, text: str) -> dict[str, Any]:
        match = _DURATION_RE.search(text)
        if match:
            value = float(match.group("value"))
            unit = match.group("unit").lower()
            normalized = self._duration_to_seconds(value, unit)
            return {
                "value": normalized,
                "unit": "s",
                "raw_value": match.group(0),
                "status": "reported",
            }

        ambiguous = self._find_term(text, _AMBIGUOUS_DURATION_TERMS)
        if ambiguous:
            return {
                "value": None,
                "unit": None,
                "raw_value": ambiguous,
                "status": "ambiguous",
            }

        return self._not_reported_scalar()

    def normalize_atmosphere(self, text: str) -> dict[str, Any]:
        for name, pattern in _ATMOSPHERE_PATTERNS.items():
            if pattern.search(text):
                return {
                    "value": name,
                    "status": "reported",
                    "raw_value": pattern.search(text).group(0),
                }
        return {
            "value": None,
            "status": "not_reported",
            "raw_value": None,
        }

    def _find_term(self, text: str, terms: tuple[str, ...]) -> str | None:
        lowered = text.lower()
        for term in terms:
            if term.lower() in lowered:
                return term
        return None

    def _duration_to_seconds(self, value: float, unit: str) -> float:
        if unit in {"d", "day", "days"}:
            return value * 86400.0
        if unit in {"h", "hr", "hrs", "hour", "hours"}:
            return value * 3600.0
        if unit in {"min", "mins", "minute", "minutes"}:
            return value * 60.0
        return value

    def _not_reported_scalar(self) -> dict[str, Any]:
        return {
            "value": None,
            "unit": None,
            "raw_value": None,
            "status": "not_reported",
        }
