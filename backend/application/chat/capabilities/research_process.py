"""Research-facing projection of per-document preparation progress."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


_VISIBLE_WARNING_LIMIT = 8
_VISIBLE_FAILURE_LIMIT = 8


class InspectResearchProcessArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InspectResearchProcessCapability:
    spec = ToolSpec(
        name="inspect_research_process",
        description=(
            "Read the preparation state of each paper in the current collection. "
            "Report which papers are stored, processing, ready, or failed and the "
            "observable stage of active work. This does not reveal private model "
            "reasoning and does not imply that Objective discovery or analysis ran."
        ),
        risk=ToolRisk.READ,
        input_model=InspectResearchProcessArguments,
    )

    def __init__(self, *, collection_service: Any, pipeline_run_service: Any) -> None:
        self.collection_service = collection_service
        self.pipeline_run_service = pipeline_run_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        _arguments: InspectResearchProcessArguments,
    ) -> ChatToolResult:
        collection = await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        runs = await self.pipeline_run_service.list_runs(
            collection_id=context.collection_id,
            limit=200,
            offset=0,
        )
        latest_by_document: dict[str, Mapping[str, Any]] = {}
        for run in runs:
            if run.get("scope_type") != "document":
                continue
            document_id = str(run.get("scope_id") or "").strip()
            if document_id and document_id not in latest_by_document:
                latest_by_document[document_id] = run

        documents = tuple(collection.get("documents") or ())
        records = tuple(
            self._document_record(document, latest_by_document)
            for document in documents
        )
        counts = Counter(record["status"] for record in records)
        warnings = self._bounded_texts(
            (
                warning
                for run in latest_by_document.values()
                for warning in run.get("warnings") or ()
            ),
            limit=_VISIBLE_WARNING_LIMIT,
        )
        failures = self._bounded_texts(
            (
                error
                for run in latest_by_document.values()
                if str(run.get("current_node") or "") != "interrupted"
                for error in run.get("errors") or ()
            ),
            limit=_VISIBLE_FAILURE_LIMIT,
        )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "collection_id": context.collection_id,
                "process": {
                    "status": self._overall_status(counts, len(records)),
                    "document_count": len(records),
                    "counts": {
                        status: counts.get(status, 0)
                        for status in ("stored", "processing", "ready", "failed")
                    },
                    "documents": list(records),
                    "objective_discovery_started": False,
                    "objective_analysis_started": False,
                    "failures": list(failures),
                },
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

    @staticmethod
    def _document_record(
        document: Mapping[str, Any],
        latest_by_document: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        document_id = str(document.get("document_id") or "")
        run = latest_by_document.get(document_id)
        document_status = str(document.get("status") or "stored")
        run_status = str(run.get("status") or "") if run is not None else ""
        interrupted = (
            run_status == "failed"
            and str(run.get("current_node") or "") == "interrupted"
        )
        status = (
            document_status
            if interrupted
            else {
                "queued": "processing",
                "running": "processing",
                "completed": "ready",
                "partial_success": "ready",
                "failed": "failed",
            }.get(run_status, document_status)
        )
        return {
            "document_id": document_id,
            "filename": str(document.get("original_filename") or "")[:300],
            "status": status,
            "run_id": str(run.get("run_id") or "") or None if run else None,
            "stage": str(run.get("current_node") or "") or None if run else None,
            "progress_percent": (
                max(0, min(100, int(run.get("progress_percent") or 0)))
                if run
                else 0
            ),
        }

    @staticmethod
    def _overall_status(counts: Counter[str], total: int) -> str:
        if total == 0:
            return "empty"
        if counts.get("processing"):
            return "processing"
        if counts.get("ready") == total:
            return "ready"
        if counts.get("failed") and not counts.get("ready"):
            return "attention_required"
        if counts.get("ready"):
            return "partial_ready"
        return "not_started"

    @staticmethod
    def _bounded_texts(values: Any, *, limit: int) -> tuple[str, ...]:
        return tuple(
            text[:500]
            for value in values
            if (text := str(value).strip())
        )[:limit]


__all__ = [
    "InspectResearchProcessArguments",
    "InspectResearchProcessCapability",
]
