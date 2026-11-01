"""Canonical references from Chat results to owned Lens resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any




@dataclass(frozen=True)
class ChatResourceRef:
    resource_type: str
    resource_id: str
    href: str | None = None



__all__ = ["ChatResourceRef"]
