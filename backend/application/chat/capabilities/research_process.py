"""Research-facing projection of canonical collection build progress."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


_STEP_IDS = (
    "source_understanding",
    "paper_classification",
    "research_scope_screening",
    "objective_formation",
)
_NODE_TO_STEP = {
    "source_artifacts": "source_understanding",
    "document_profiles": "paper_classification",
}
_NODE_STATUS = {
    "queued": "queued",
    "running": "running",
    "succeeded": "completed",
    "failed": "failed",
    "skipped": "skipped",
}
_OBJECTIVE_FORMATION_PHASES = {
    "objective_discovery_started",
    "objective_discovery_batch_finished",
}
_VISIBLE_WARNING_LIMIT = 8
_VISIBLE_FAILURE_LIMIT = 8


class InspectResearchProcessArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InspectResearchProcessCapability:
    spec = ToolSpec(
        name="inspect_research_process",
        description=(
            "Read the current collection research process from canonical build state. "
            "Explain its stages in researcher-facing language: preparing paper content; "
            "assessing each paper's type and research role; identifying materials, "
            "variables, and reported results; and synthesizing candidate research "
            "questions. Report whether each stage has started, is running, is complete, "
            "or needs attention. This returns observable progress and warnings, not "
            "private model reasoning or extraction mechanics."
        ),
        risk=ToolRisk.READ,
        input_model=InspectResearchProcessArguments,
    )

    def __init__(self, *, collection_service: Any, task_service: Any) -> None:
        self.collection_service = collection_service
        self.task_service = task_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        _arguments: InspectResearchProcessArguments,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        tasks = await self.task_service.list_tasks(
            collection_id=context.collection_id,
            limit=1,
            offset=0,
        )
        task = tasks[0] if tasks else None
        process = self._process_record(task)
        warnings = self._bounded_texts(
            task.get("warnings") if task is not None else (),
            limit=_VISIBLE_WARNING_LIMIT,
        )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "collection_id": context.collection_id,
                "task_id": str(task.get("task_id") or "") if task else None,
                "process": process,
            },
            resource_refs=(
                ChatResourceRef(
                    resource_type="collection",
                    resource_id=context.collection_id,
                    href=f"/collections/{context.collection_id}",
                ),
            ),
            warnings=warnings,
        )

    @classmethod
    def _process_record(cls, task: Mapping[str, Any] | None) -> dict[str, Any]:
        if task is None:
            return {
                "status": "not_started",
                "current_step": None,
                "summary": "Literature analysis has not started.",
                "progress_percent": 0,
                "document_progress": None,
                "active_document": None,
                "steps": [
                    {"step_id": step_id, "status": "queued"}
                    for step_id in _STEP_IDS
                ],
                "failures": [],
            }

        task_status = str(task.get("status") or "queued").strip()
        progress_detail = (
            task.get("progress_detail")
            if isinstance(task.get("progress_detail"), Mapping)
            else {}
        )
        phase = str(progress_detail.get("phase") or "").strip()
        steps = cls._steps(task.get("pipeline_nodes"), phase=phase)
        return {
            "status": task_status,
            "current_step": cls._current_step(
                steps,
                task_status=task_status,
                phase=phase,
            ),
            "summary": cls._summary(task_status, progress_detail),
            "progress_percent": cls._progress_percent(task.get("progress_percent")),
            "document_progress": cls._document_progress(progress_detail),
            "active_document": cls._active_document(progress_detail),
            "steps": steps,
            "failures": list(
                cls._bounded_texts(
                    task.get("errors"),
                    limit=_VISIBLE_FAILURE_LIMIT,
                )
            ),
        }

    @classmethod
    def _steps(
        cls,
        pipeline_nodes: Any,
        *,
        phase: str,
    ) -> list[dict[str, str]]:
        nodes = pipeline_nodes if isinstance(pipeline_nodes, Mapping) else {}
        statuses = {step_id: "queued" for step_id in _STEP_IDS}
        for node_id, step_id in _NODE_TO_STEP.items():
            node = nodes.get(node_id)
            statuses[step_id] = cls._node_status(node)

        objective_status = cls._node_status(nodes.get("objective_candidates"))
        if objective_status == "running":
            if phase in _OBJECTIVE_FORMATION_PHASES:
                statuses["research_scope_screening"] = "completed"
                statuses["objective_formation"] = "running"
            else:
                statuses["research_scope_screening"] = "running"
                statuses["objective_formation"] = "queued"
        else:
            statuses["research_scope_screening"] = objective_status
            statuses["objective_formation"] = objective_status

        return [
            {"step_id": step_id, "status": statuses[step_id]}
            for step_id in _STEP_IDS
        ]

    @staticmethod
    def _node_status(node: Any) -> str:
        if not isinstance(node, Mapping):
            return "queued"
        return _NODE_STATUS.get(str(node.get("status") or "").strip(), "queued")

    @staticmethod
    def _current_step(
        steps: list[dict[str, str]],
        *,
        task_status: str,
        phase: str,
    ) -> str | None:
        if task_status in {"completed", "partial_success"}:
            return None
        if phase in _OBJECTIVE_FORMATION_PHASES:
            return "objective_formation"
        for target_status in ("running", "failed", "queued"):
            for step in steps:
                if step["status"] == target_status:
                    return step["step_id"]
        return None

    @staticmethod
    def _summary(task_status: str, progress_detail: Mapping[str, Any]) -> str:
        terminal_summary = {
            "completed": (
                "Paper preparation and candidate research-question synthesis "
                "are complete."
            ),
            "partial_success": (
                "Literature analysis is complete, but some content still needs review."
            ),
            "failed": "Literature analysis stopped before all stages were complete.",
        }.get(task_status)
        if terminal_summary is not None:
            return terminal_summary
        message = str(progress_detail.get("message") or "").strip()
        if message:
            return message[:500]
        if task_status == "running":
            return "Literature analysis is in progress."
        return "Literature analysis is waiting to start."

    @staticmethod
    def _progress_percent(value: Any) -> int:
        try:
            return max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _document_progress(progress_detail: Mapping[str, Any]) -> dict[str, int] | None:
        try:
            current = int(progress_detail.get("current"))
            total = int(progress_detail.get("total"))
        except (TypeError, ValueError):
            return None
        if total < 1 or current < 0:
            return None
        return {"current": min(current, total), "total": total}

    @staticmethod
    def _active_document(progress_detail: Mapping[str, Any]) -> dict[str, str] | None:
        document_id = str(progress_detail.get("active_document_id") or "").strip()
        title = str(progress_detail.get("active_document_title") or "").strip()
        if not document_id and not title:
            return None
        return {
            "document_id": document_id,
            "title": title[:300],
        }

    @staticmethod
    def _bounded_texts(values: Any, *, limit: int) -> tuple[str, ...]:
        return tuple(
            text[:500]
            for value in (values or ())
            if (text := str(value).strip())
        )[:limit]


__all__ = [
    "InspectResearchProcessArguments",
    "InspectResearchProcessCapability",
]
