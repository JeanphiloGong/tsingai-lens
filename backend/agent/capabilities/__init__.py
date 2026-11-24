"""Agent-owned capability registration and execution descriptors."""

from agent.capabilities.registry import (
    CapabilityRegistry,
    ToolExecutionContext,
    ToolHandler,
    ToolSpec,
)

__all__ = [
    "CapabilityRegistry",
    "ToolExecutionContext",
    "ToolHandler",
    "ToolSpec",
]
