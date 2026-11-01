"""Load trusted research tool definitions without executing a research action."""

from __future__ import annotations

from domain.chat import ToolResultStatus

from pydantic import BaseModel, ConfigDict, Field

from application.chat.capabilities.contracts import CapabilityExecutionContext, ToolSpec
from domain.chat import ChatToolResult, ToolRisk


class DiscoverResearchToolsToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tool_names: list[str] = Field(
        min_length=1,
        description=(
            "Exact names from the unloaded-tool catalog needed for the current request. "
            "Loaded definitions remain available throughout this request."
        ),
    )


class DiscoverResearchToolsCapability:
    def __init__(self, specs: tuple[ToolSpec, ...]) -> None:
        self.tools = {
            spec.name: spec
            for spec in specs
            if spec.risk in {ToolRisk.READ, ToolRisk.DRAFT, ToolRisk.WRITE}
        }
        self.spec = self.spec_for_names(set(self.tools))

    def spec_for_names(self, names: set[str]) -> ToolSpec:
        """Describe only definitions absent from the current request."""
        visible = tuple(
            spec for spec in self.tools.values()
            if spec.name in names
        )
        catalog = "\n".join(
            f"- {spec.name} [{spec.risk.value}]: {spec.description.split('. ', 1)[0].rstrip('.')}."
            for spec in visible
        )
        return ToolSpec(
            name="discover_research_tools",
            description=(
                "Load missing parameter definitions from this catalog. Definitions already "
                "exposed in tools stay available for this request and are absent from the catalog. "
                "Discovery reads metadata only, does not inspect papers, and grants no write approval. "
                "Answer greetings and general discussion directly without discovery.\n" + catalog
            ),
            risk=ToolRisk.READ,
            input_model=DiscoverResearchToolsToolRequest,
        )

    async def execute(self, context: CapabilityExecutionContext, arguments: DiscoverResearchToolsToolRequest) -> ChatToolResult:
        names = list(dict.fromkeys(arguments.tool_names))
        if any(name not in self.tools for name in names):
            return ChatToolResult(
                tool_call_id=context.tool_call_id, status=ToolResultStatus.FAILED,
                error_code="tool_not_discoverable",
                error_message=(
                    "Select only registered research tools named in the catalog. "
                    "Discovery grants no execution approval."
                ),
            )
        return ChatToolResult(
            tool_call_id=context.tool_call_id, status=ToolResultStatus.SUCCEEDED,
            data={
                "loaded_tool_names": names,
                "tools": [
                    {"name": name, "description": self.tools[name].description, "risk": self.tools[name].risk.value}
                    for name in names
                ],
                "scope": "current_user_request",
            },
        )
