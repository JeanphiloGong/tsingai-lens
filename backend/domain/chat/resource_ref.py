"""Canonical references from Chat results to owned Lens resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} cannot be empty")
    return text


@dataclass(frozen=True)
class ChatResourceRef:
    resource_type: str
    resource_id: str
    href: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "resource_type", _required_text(self.resource_type, "resource_type")
        )
        object.__setattr__(
            self, "resource_id", _required_text(self.resource_id, "resource_id")
        )
        if self.href is not None:
            object.__setattr__(self, "href", _required_text(self.href, "href"))


__all__ = ["ChatResourceRef"]
