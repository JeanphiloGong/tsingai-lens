"""Approved Objective analysis start and read-only state inspection."""

from __future__ import annotations

from typing import Any, Annotated

from pydantic import BaseModel, ConfigDict, Field

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from application.core.objectives.analysis_service import (
    ObjectiveAnalysisDispatchError,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


ObjectiveId = Annotated[str, Field(min_length=1, max_length=240)]


class StartObjectiveAnalysisArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: ObjectiveId


class InspectObjectiveAnalysisArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: ObjectiveId


class StartObjectiveAnalysisCapability:
    spec = ToolSpec(
        name="start_objective_analysis",
        description=(
            "Confirm one approved research question and queue its canonical "
            "Source-grounded Objective analysis. This write requires explicit user "
            "approval. It uses the same analysis service and state as the collection "
            "workspace and returns immediately after scheduling."
        ),
        risk=ToolRisk.WRITE,
        input_model=StartObjectiveAnalysisArguments,
    )

    def __init__(self, *, collection_service: Any, objective_analysis_service: Any) -> None:
        self.collection_service = collection_service
        self.objective_analysis_service = objective_analysis_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: StartObjectiveAnalysisArguments,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        try:
            payload = await self.objective_analysis_service.start_analysis(
                context.collection_id,
                arguments.objective_id,
            )
        except ObjectiveAnalysisDispatchError:
            payload = await self.objective_analysis_service.get_analysis_state(
                context.collection_id,
                arguments.objective_id,
            )
        projection = _project_analysis(payload)
        status = projection["analysis"]["status"]
        ref = _analysis_ref(context.collection_id, arguments.objective_id, projection)
        if status == "failed":
            return ChatToolResult(
                tool_call_id=context.tool_call_id,
                status="failed",
                data=projection,
                resource_refs=(ref,),
                error_code=(
                    projection["analysis"].get("error_code")
                    or "objective_analysis_failed"
                ),
                error_message=(
                    projection["analysis"].get("error_message")
                    or "The Objective analysis could not be started."
                ),
            )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="queued" if status in {"queued", "running"} else "succeeded",
            data=projection,
            resource_refs=(ref,),
            warnings=tuple(payload.get("warnings") or ()),
        )


class InspectObjectiveAnalysisCapability:
    spec = ToolSpec(
        name="inspect_objective_analysis",
        description=(
            "Read the canonical state of one research-question analysis, including "
            "paper progress, terminal failure, and whether a published result exists. "
            "This read does not start or retry analysis."
        ),
        risk=ToolRisk.READ,
        input_model=InspectObjectiveAnalysisArguments,
    )

    def __init__(self, *, collection_service: Any, objective_analysis_service: Any) -> None:
        self.collection_service = collection_service
        self.objective_analysis_service = objective_analysis_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: InspectObjectiveAnalysisArguments,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        payload = await self.objective_analysis_service.get_analysis_state(
            context.collection_id,
            arguments.objective_id,
        )
        projection = _project_analysis(payload)
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data=projection,
            resource_refs=(
                _analysis_ref(
                    context.collection_id,
                    arguments.objective_id,
                    projection,
                ),
            ),
            warnings=tuple(payload.get("warnings") or ()),
        )


def _project_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    objective = payload["objective"]
    active = payload.get("analysis")
    published = payload.get("published_analysis")
    if active is None:
        analysis = {
            "analysis_version": None,
            "status": "not_started",
            "phase": None,
            "document_progress": None,
            "current_document_id": None,
            "progress_message": None,
            "error_code": None,
            "error_message": None,
        }
    else:
        analysis = {
            "analysis_version": active.analysis_version,
            "status": active.status,
            "phase": active.phase,
            "document_progress": {
                "current": active.processed_document_count,
                "total": active.total_document_count,
            },
            "current_document_id": active.current_document_id,
            "progress_message": active.progress_message,
            "error_code": active.error_code,
            "error_message": active.error_message,
        }
    return {
        "objective_id": objective.objective_id,
        "question": objective.question,
        "confirmation_status": objective.confirmation_status,
        "analysis": analysis,
        "published_analysis_version": (
            published.analysis_version if published is not None else None
        ),
    }


def _analysis_ref(
    collection_id: str,
    objective_id: str,
    projection: dict[str, Any],
) -> ChatResourceRef:
    version = projection["analysis"]["analysis_version"]
    return ChatResourceRef(
        resource_type="objective_analysis",
        resource_id=(f"{objective_id}:{version}" if version is not None else objective_id),
        href=f"/collections/{collection_id}/objectives/{objective_id}",
    )


__all__ = [
    "InspectObjectiveAnalysisArguments",
    "InspectObjectiveAnalysisCapability",
    "StartObjectiveAnalysisArguments",
    "StartObjectiveAnalysisCapability",
]
