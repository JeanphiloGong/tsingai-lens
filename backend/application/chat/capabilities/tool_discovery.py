"""Load trusted research tool definitions without executing a research action."""

from __future__ import annotations

from domain.chat import ToolResultStatus

from domain.chat import ToolResultStatus

from pydantic import BaseModel, ConfigDict, Field

from application.chat.capabilities.contracts import CapabilityExecutionContext, ToolSpec
from domain.chat import ChatToolResult, ToolRisk


class DiscoverResearchToolsToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tool_names: list[str] = Field(
        min_length=1,
        description=(
            "Exact names from the catalog needed for the current research request. "
            "Load the complete set needed for the next decision in one discovery call."
        ),
    )
    source_inspection_required: bool = Field(
        description=(
            "Whether the current request requires checking what a particular paper says, "
            "its measurements, or cross-paper scientific support. True also for claims "
            "attributed to reviews or methods papers, and for rechecking or correcting an "
            "existing Finding against its original papers, even if the first tool only "
            "reads that Finding. Classify the entire user request, not only the next tool. "
            "False for paper selection, status, or merely recalling saved analysis/review "
            "records without checking their scientific correctness. "
            "This records a reading prerequisite, not approval or scientific support."
        ),
    )
    deferred_tool_names: list[str] = Field(
        default_factory=list,
        description=(
            "Exact catalog names for actions the researcher explicitly deferred or excluded "
            "from this request. Interpret their meaning, including conversational context. "
            "Include both draft and save actions for an excluded deliverable. This narrows "
            "the current request only, grants no permission, and persists across discovery "
            "updates until the next user request. Leave empty when nothing was excluded."
        ),
    )


class DiscoverResearchToolsCapability:
    def __init__(self, specs: tuple[ToolSpec, ...]) -> None:
        self.tools = {
            spec.name: spec
            for spec in specs
            if spec.risk in {ToolRisk.READ, ToolRisk.DRAFT, ToolRisk.WRITE}
        }
        self.spec = self.spec_for_permission(allow_writes=True)

    def spec_for_permission(self, *, allow_writes: bool) -> ToolSpec:
        """Build the catalog visible under the caller's deterministic mode."""
        visible = tuple(
            spec for spec in self.tools.values()
            if allow_writes or spec.risk is not ToolRisk.WRITE
        )
        catalog = "\n".join(
            f"- {spec.name} [{spec.risk.value}]: {spec.description.split('. ', 1)[0].rstrip('.')}."
            for spec in visible
        )
        return ToolSpec(
            name="discover_research_tools",
            description=(
                "Select tools from this catalog to load their complete parameter definitions "
                "for the next decision. Select by meaning, including filenames, identifiers "
                "and conversational references; no special user keywords are required. "
                "Discovery reads metadata only, does not inspect papers, and grants no write approval. "
                "Answer greetings and general discussion directly without discovery.\n" + catalog
            ),
            risk=ToolRisk.READ,
            input_model=DiscoverResearchToolsToolRequest,
        )

    async def execute(self, context: CapabilityExecutionContext, arguments: DiscoverResearchToolsToolRequest) -> ChatToolResult:
        names = list(dict.fromkeys(arguments.tool_names))
        if any(name not in self.tools for name in (*names, *arguments.deferred_tool_names)):
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
                "source_inspection_required": arguments.source_inspection_required,
                "deferred_tool_names": list(dict.fromkeys(arguments.deferred_tool_names)),
                "tools": [
                    {"name": name, "description": self.tools[name].description, "risk": self.tools[name].risk.value}
                    for name in names
                ],
                "scope": "current_user_request",
                "instruction": "The selected parameter definitions are now available, subject to required evidence reads. Use them to complete the current request.",
            },
        )
