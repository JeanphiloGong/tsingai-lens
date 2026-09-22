"""Explicit per-turn boundaries for Research Agent capabilities."""

from enum import StrEnum


class ToolPermissionMode(StrEnum):
    """Controls which capability risks a single chat turn may use."""

    CONFIRM = "confirm"
    READ_ONLY = "read_only"
    NONE = "none"


__all__ = ["ToolPermissionMode"]
