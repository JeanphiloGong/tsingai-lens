"""Approved Objective analysis start and read-only state inspection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Annotated
from urllib.parse import urlencode

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
_QUALITY_INSPECTION_LIMIT = 12
_QUALITY_TEXT_LIMIT = 500


class ConfirmObjectiveArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: ObjectiveId


class StartObjectiveAnalysisArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: ObjectiveId
    document_ids: list[str] = Field(min_length=1)


class InspectObjectiveAnalysisArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: ObjectiveId


class AssessObjectiveQualityArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: ObjectiveId


class ConfirmObjectiveCapability:
    spec = ToolSpec(
        name="confirm_objective",
        description=(
            "Confirm one reviewed research question without starting an analysis. "
            "This write requires explicit user approval. Use it after a candidate and "
            "its scope have been reviewed, before either automatic or Agent-authored "
            "analysis."
        ),
        risk=ToolRisk.WRITE,
        input_model=ConfirmObjectiveArguments,
    )

    def __init__(self, *, objective_authoring_service: Any) -> None:
        self.objective_authoring_service = objective_authoring_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: ConfirmObjectiveArguments,
    ) -> ChatToolResult:
        objective = await self.objective_authoring_service.confirm_objective(
            collection_id=context.collection_id,
            user_id=context.user_id,
            objective_id=arguments.objective_id,
        )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "objective_id": objective.objective_id,
                "confirmation_status": objective.confirmation_status,
                "analysis_started": objective.active_analysis_version is not None,
            },
            resource_refs=(
                ChatResourceRef(
                    resource_type="research_objective",
                    resource_id=objective.objective_id,
                    href=(
                        f"/collections/{context.collection_id}/objectives/"
                        f"{objective.objective_id}"
                    ),
                ),
            ),
        )


class StartObjectiveAnalysisCapability:
    spec = ToolSpec(
        name="start_objective_analysis",
        description=(
            "Queue the canonical Source-grounded analysis for one already confirmed "
            "research question and exact paper scope. This write requires explicit "
            "user approval. It uses the same analysis service and state as the "
            "collection workspace and returns immediately after scheduling."
        ),
        risk=ToolRisk.WRITE,
        input_model=StartObjectiveAnalysisArguments,
    )

    def __init__(
        self,
        *,
        collection_service: Any,
        objective_repository: Any,
        objective_analysis_service: Any,
    ) -> None:
        self.collection_service = collection_service
        self.objective_repository = objective_repository
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
        objective = await self.objective_repository.read_objective(
            context.collection_id,
            arguments.objective_id,
        )
        if objective is None:
            raise FileNotFoundError(
                "research objective not found: "
                f"{context.collection_id}/{arguments.objective_id}"
            )
        if objective.confirmation_status != "confirmed":
            raise ValueError(
                "confirm the research objective before starting analysis"
            )
        try:
            payload = await self.objective_analysis_service.start_analysis(
                context.collection_id,
                arguments.objective_id,
                tuple(arguments.document_ids),
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


class AssessObjectiveQualityCapability:
    spec = ToolSpec(
        name="assess_objective_quality",
        description=(
            "Read the published quality ledger for one research question. Separate "
            "technical extraction failures from scientific gaps such as missing "
            "same-paper context or non-comparability, and return bounded Source "
            "locations for the next inspection. This read does not create Evidence, "
            "a Finding, or a new quality judgment."
        ),
        risk=ToolRisk.READ,
        input_model=AssessObjectiveQualityArguments,
    )

    def __init__(
        self,
        *,
        collection_service: Any,
        objective_analysis_service: Any,
    ) -> None:
        self.collection_service = collection_service
        self.objective_analysis_service = objective_analysis_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: AssessObjectiveQualityArguments,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        payload = await self.objective_analysis_service.get_analysis_state(
            context.collection_id,
            arguments.objective_id,
        )
        published = payload.get("published_analysis")
        active = payload.get("analysis")
        active_version = _field(active, "analysis_version")
        published_version = _field(published, "analysis_version")
        active_failed = _field(active, "status") == "failed"
        newer_failed_analysis = bool(
            active_failed
            and active_version is not None
            and (
                published_version is None
                or int(active_version) != int(published_version)
            )
        )
        evidence_review = dict(payload.get("evidence_review") or {})
        gaps = [
            dict(item)
            for item in evidence_review.get("gaps") or ()
            if isinstance(item, dict)
        ]
        status_counts = {
            str(status): int(count)
            for status, count in dict(
                evidence_review.get("status_counts") or {}
            ).items()
        }
        technical_failure_count = status_counts.get("extraction_failed", 0)
        scientific_gaps = [
            item
            for item in gaps
            if str(item.get("evidence_status") or "") != "extraction_failed"
        ]
        findings = tuple(payload.get("findings") or ())
        finding_count = len(findings)
        total_evidence_count = int(
            evidence_review.get("total_evidence_count") or 0
        )
        contributions = tuple(payload.get("paper_contributions") or ())
        contribution_records = [
            {
                "document_id": str(_field(item, "document_id", "") or ""),
                "evidence_disposition": _field(
                    item, "evidence_disposition"
                ),
                "reason": _field(item, "evidence_disposition_reason"),
            }
            for item in contributions
        ]
        failed_paper_count = sum(
            item["evidence_disposition"] == "extraction_failed"
            for item in contribution_records
        )
        if published is None:
            quality_status = "not_analyzed"
        elif finding_count:
            quality_status = (
                "finding_available_with_gaps"
                if gaps or technical_failure_count or failed_paper_count
                else "finding_available"
            )
        elif total_evidence_count == 0:
            quality_status = "no_grounded_evidence"
        else:
            quality_status = "scientific_abstention"
        runtime_state = (
            "previous_published_result_available"
            if newer_failed_analysis and published is not None
            else "failed"
            if newer_failed_analysis
            else "stable"
        )
        next_inspections = [
            _quality_gap_summary(item)
            for item in gaps[:_QUALITY_INSPECTION_LIMIT]
        ]
        source_refs = tuple(
            ChatResourceRef(
                resource_type="source",
                resource_id=(
                    f"{item.get('document_id', '')}:"
                    f"{item.get('source_kind', '')}:"
                    f"{item.get('source_ref', '')}"
                ),
                href=(
                    f"/collections/{context.collection_id}/documents/"
                    f"{item.get('document_id', '')}?"
                    + urlencode(
                        {
                            "view": "parsed-paper",
                            "source_ref": str(item.get("source_ref") or ""),
                        }
                    )
                ),
            )
            for item in next_inspections
            if item.get("document_id") and item.get("source_ref")
        )
        published_version = _field(published, "analysis_version")
        warnings_list = [str(item)[:500] for item in payload.get("warnings") or ()]
        if newer_failed_analysis:
            warnings_list.append(
                "A newer analysis failed before publication; the published result "
                "is retained and must not be treated as the failed run's result."
            )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "objective_id": arguments.objective_id,
                "published_analysis_version": published_version,
                "active_analysis_version": active_version,
                "active_analysis_status": _field(active, "status"),
                "active_analysis_error_code": _field(active, "error_code"),
                "active_analysis_error_message": _field(active, "error_message"),
                "runtime_state": runtime_state,
                "quality_status": quality_status,
                "finding_count": finding_count,
                "total_evidence_count": total_evidence_count,
                "comparable_evidence_count": int(
                    evidence_review.get("comparable_evidence_count") or 0
                ),
                "technical_failure_count": technical_failure_count,
                "failed_paper_count": failed_paper_count,
                "scientific_gap_count": len(scientific_gaps),
                "status_counts": status_counts,
                "abstention_reason": _field(published, "abstention_reason"),
                "abstention_note": _field(published, "abstention_note"),
                "paper_contributions": contribution_records[:50],
                "next_inspections": next_inspections,
                "omitted_inspection_count": max(
                    0,
                    len(gaps) - _QUALITY_INSPECTION_LIMIT,
                )
                + int(evidence_review.get("omitted_gap_count") or 0),
                "requires_researcher_review": bool(
                    published is None or gaps or not finding_count or newer_failed_analysis
                ),
                "support_is_evidence": False,
            },
            resource_refs=(
                ChatResourceRef(
                    resource_type="objective_analysis",
                    resource_id=(
                        f"{arguments.objective_id}:{published_version}"
                        if published_version is not None
                        else arguments.objective_id
                    ),
                    href=(
                        f"/collections/{context.collection_id}/objectives/"
                        f"{arguments.objective_id}"
                    ),
                ),
                *source_refs,
            ),
            warnings=tuple(warnings_list[:20]),
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


def _quality_gap_summary(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": str(item.get("evidence_id") or "")[:240],
        "document_id": str(item.get("document_id") or "")[:240],
        "source_kind": str(item.get("source_kind") or "")[:80],
        "source_ref": str(item.get("source_ref") or "")[:240],
        "page_numbers": [
            int(page)
            for page in item.get("page_numbers") or ()
            if isinstance(page, int) and page > 0
        ][:20],
        "evidence_status": str(item.get("evidence_status") or "")[:80],
        "reason": str(item.get("reason") or "")[:_QUALITY_TEXT_LIMIT],
        "outcome": str(item.get("outcome") or "")[:240] or None,
        "source_excerpt": str(item.get("source_excerpt") or "")[
            :_QUALITY_TEXT_LIMIT
        ],
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


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


__all__ = [
    "AssessObjectiveQualityArguments",
    "AssessObjectiveQualityCapability",
    "ConfirmObjectiveArguments",
    "ConfirmObjectiveCapability",
    "InspectObjectiveAnalysisArguments",
    "InspectObjectiveAnalysisCapability",
    "StartObjectiveAnalysisArguments",
    "StartObjectiveAnalysisCapability",
]
