"""Model-authored execution progress, stored in the existing chat trajectory."""

from __future__ import annotations

from domain.chat import ToolResultStatus

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from application.chat.capabilities.contracts import CapabilityExecutionContext, ToolSpec
from domain.chat import ChatToolResult, ToolRisk


class ExecutionPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    step_id: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=240)
    status: Literal["pending", "in_progress", "completed", "blocked"]


class UpdateExecutionPlanToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    steps: list[ExecutionPlanStep] = Field(max_length=12)
    status: Literal[
        "in_progress", "completed", "waiting_for_clarification", "scientific_refusal",
    ]
    explanation: str = Field(min_length=1, max_length=800)

    @model_validator(mode="after")
    def validate_steps(self) -> "UpdateExecutionPlanToolRequest":
        if len({step.step_id for step in self.steps}) != len(self.steps):
            raise ValueError("plan step IDs must be unique")
        if sum(step.status == "in_progress" for step in self.steps) > 1:
            raise ValueError("at most one plan step may be in progress")
        if self.status == "in_progress" and not self.steps:
            raise ValueError("an active plan requires steps")
        if self.status == "completed" and any(step.status != "completed" for step in self.steps):
            raise ValueError("a completed plan cannot contain unfinished steps")
        return self


class UpdateExecutionPlanCapability:
    spec = ToolSpec(
        name="update_execution_plan",
        description=(
            "Replace the current request's execution plan with your complete updated steps. "
            "Use short researcher-facing actions and stable step IDs; retain completed work "
            "when revising the remaining steps. Set status to in_progress while continuing, "
            "completed when the requested work is supported, waiting_for_clarification when "
            "a researcher decision is needed, or scientific_refusal when the requested claim "
            "cannot be supported after available checks. Explain the change or specific gap. "
            "A local draft abstention alone does not settle the whole request. Empty steps "
            "are allowed for a clarification or disposition without a multi-step plan. "
            "The runtime reports approvals and technical interruptions separately. "
            "This updates chat progress only; it creates no research artifact, Evidence, "
            "PaperExperiment or experimental research plan and grants no write permission. "
            "Call this tool separately from research tools."
        ),
        risk=ToolRisk.DRAFT,
        input_model=UpdateExecutionPlanToolRequest,
    )

    async def execute(
        self, context: CapabilityExecutionContext, arguments: UpdateExecutionPlanToolRequest,
    ) -> ChatToolResult:
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status=ToolResultStatus.SUCCEEDED,
            data=arguments.model_dump(),
        )
