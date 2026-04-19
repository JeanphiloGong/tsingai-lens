"""Active Source indexing modes."""

from __future__ import annotations

from enum import Enum


class IndexingMethod(str, Enum):
    """Enum for the active Source indexing modes."""

    Standard = "standard"
    Fast = "fast"
