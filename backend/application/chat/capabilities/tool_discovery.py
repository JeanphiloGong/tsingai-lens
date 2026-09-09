"""Load trusted research tool definitions without executing a research action."""

from __future__ import annotations

from hashlib import sha256
import json

from pydantic import BaseModel, ConfigDict, Field

from application.chat.capabilities.contracts import CapabilityExecutionContext, ToolSpec
from domain.chat import ChatToolResult, ToolRisk


class DiscoverResearchToolsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tool_names: list[str] = Field(
        min_length=1, max_length=6,
        description="Exact names from the catalog needed for the current research request.",
    )
    source_inspection_required: bool = Field(
        description=(
            "Whether the current request requires checking what a particular paper says, "
            "its measurements, or cross-paper scientific support. True also for claims "
            "attributed to reviews or methods papers. False for paper selection, status, "
            "or reviewing already published analysis without a new paper claim. "
            "This records a reading prerequisite, not approval or scientific support."
        ),
    )


class DiscoverResearchToolsCapability:
    def __init__(self, specs: tuple[ToolSpec, ...]) -> None:
        self.tools = {spec.name: spec for spec in specs if spec.risk in {ToolRisk.READ, ToolRisk.DRAFT}}
        self.catalog_version = sha256(json.dumps(
            [spec.model_schema() for spec in self.tools.values()], sort_keys=True,
        ).encode()).hexdigest()
        catalog = "\n".join(
            f"- {spec.name} [{spec.risk.value}]: {spec.description.split('. ', 1)[0].rstrip('.')}."
            for spec in self.tools.values()
        )
        self.spec = ToolSpec(
            name="discover_research_tools",
            description=(
                "Select tools from this catalog to load their complete parameter definitions "
                "for the next decision. Select by meaning, including filenames, identifiers "
                "and conversational references; no special user keywords are required. "
                "Discovery reads metadata only, does not inspect papers, and grants no write approval. "
                "Answer greetings and general discussion directly without discovery.\n" + catalog
            ),
            risk=ToolRisk.READ,
            input_model=DiscoverResearchToolsArguments,
        )

    async def execute(self, context: CapabilityExecutionContext, arguments: DiscoverResearchToolsArguments) -> ChatToolResult:
        names = list(dict.fromkeys(arguments.tool_names))
        if any(name not in self.tools for name in names):
            return ChatToolResult(
                tool_call_id=context.tool_call_id, status="failed",
                error_code="tool_not_discoverable",
                error_message="Select only read or transient-draft tools named in the catalog.",
            )
        return ChatToolResult(
            tool_call_id=context.tool_call_id, status="succeeded",
            data={
                "catalog_version": self.catalog_version,
                "loaded_tool_names": names,
                "source_inspection_required": arguments.source_inspection_required,
                "tools": [
                    {"name": name, "description": self.tools[name].description, "risk": self.tools[name].risk.value}
                    for name in names
                ],
                "scope": "current_user_request",
                "instruction": "The selected parameter definitions are now available, subject to required evidence reads. Use them to complete the current request.",
            },
        )
