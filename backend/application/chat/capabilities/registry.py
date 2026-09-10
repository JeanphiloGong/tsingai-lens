"""Small explicit name-to-handler registry for Lens capabilities."""

from __future__ import annotations

from application.chat.capabilities.contracts import CapabilityHandler, ToolSpec
from application.chat.capabilities.tool_discovery import DiscoverResearchToolsCapability


class CapabilityRegistry:
    def __init__(self, handlers: tuple[CapabilityHandler, ...]) -> None:
        self._handlers: dict[str, CapabilityHandler] = {}
        for handler in handlers:
            name = handler.spec.name.strip()
            if not name:
                raise ValueError("capability name cannot be empty")
            if name == "discover_research_tools":
                raise ValueError("reserved capability name: discover_research_tools")
            if name in self._handlers:
                raise ValueError(f"duplicate capability: {name}")
            self._handlers[name] = handler
        self.discovery = DiscoverResearchToolsCapability(self.specs)

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(handler.spec for handler in self._handlers.values())

    def get(self, name: str) -> CapabilityHandler | None:
        if name == self.discovery.spec.name:
            return self.discovery
        return self._handlers.get(str(name).strip())


__all__ = ["CapabilityRegistry"]
