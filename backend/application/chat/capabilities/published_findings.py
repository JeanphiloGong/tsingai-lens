"""Read bounded Finding and Evidence summaries from published analyses only."""

from __future__ import annotations

from typing import Any, Annotated, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from application.chat.capabilities.contracts import (
    CapabilityExecutionContext,
    ToolSpec,
)
from domain.chat import ChatResourceRef, ChatToolResult, ToolRisk


ObjectiveId = Annotated[str, Field(min_length=1, max_length=160)]
_OBJECTIVE_LIMIT = 12


class QueryPublishedFindingsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_ids: list[ObjectiveId] = Field(default_factory=list, max_length=12)
    finding_limit_per_objective: int = Field(default=8, ge=1, le=20)
    evidence_limit_per_objective: int = Field(default=8, ge=1, le=20)

    @field_validator("objective_ids")
    @classmethod
    def _unique_objective_ids(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = value.strip()
            if item in seen:
                continue
            seen.add(item)
            normalized.append(item)
        return normalized


class InspectPublishedFindingArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: ObjectiveId
    finding_id: str = Field(min_length=1, max_length=128)
    analysis_version: int | None = Field(default=None, ge=1)
    evidence_offset: int = Field(default=0, ge=0)
    evidence_limit: int = Field(default=40, ge=1, le=100)


class QueryPublishedFindingsCapability:
    spec = ToolSpec(
        name="query_published_findings",
        description=(
            "Read bounded Finding and source-linked Evidence summaries from published "
            "Research Objective analyses. A successful empty result means the collection "
            "does not yet contain published evidence for the selected Objectives. "
            "Evidence explicitly reports whether it is eligible for new Finding "
            "authorship."
        ),
        risk=ToolRisk.READ,
        input_model=QueryPublishedFindingsArguments,
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
        arguments: QueryPublishedFindingsArguments,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        objectives = await self.objective_repository.list_objectives(
            context.collection_id
        )
        objectives_by_id = {item.objective_id: item for item in objectives}
        requested_ids = arguments.objective_ids or [
            item.objective_id for item in objectives[:_OBJECTIVE_LIMIT]
        ]
        missing_ids = [item for item in requested_ids if item not in objectives_by_id]
        selected = [
            objectives_by_id[item]
            for item in requested_ids
            if item in objectives_by_id
        ]

        records: list[dict[str, Any]] = []
        refs: list[ChatResourceRef] = []
        finding_count = 0
        evidence_count = 0
        unpublished_count = 0
        for objective in selected:
            version = objective.published_analysis_version
            if version is None:
                unpublished_count += 1
                continue
            findings = await self.objective_analysis_service.list_findings(
                context.collection_id,
                objective.objective_id,
                analysis_version=version,
                offset=0,
                limit=arguments.finding_limit_per_objective,
            )
            evidence = await self.objective_analysis_service.list_evidence(
                context.collection_id,
                objective.objective_id,
                analysis_version=version,
                offset=0,
                limit=arguments.evidence_limit_per_objective,
            )
            finding_items = [
                self._finding_summary(item)
                for item in findings.get("items", ())
                if isinstance(item, Mapping)
            ]
            evidence_items = [
                self._evidence_summary(item)
                for item in evidence.get("items", ())
                if isinstance(item, Mapping)
            ]
            finding_count += len(finding_items)
            evidence_count += len(evidence_items)
            records.append(
                {
                    "objective_id": objective.objective_id,
                    "question": objective.question[:500],
                    "analysis_version": version,
                    "finding_total": int(findings.get("total") or 0),
                    "evidence_total": int(evidence.get("total") or 0),
                    "findings": finding_items,
                    "evidence": evidence_items,
                }
            )
            refs.append(self._objective_ref(context.collection_id, objective.objective_id))
            refs.extend(
                self._finding_ref(
                    context.collection_id,
                    objective.objective_id,
                    version,
                    item["finding_id"],
                )
                for item in finding_items
            )
            refs.extend(
                self._evidence_ref(
                    context.collection_id,
                    objective.objective_id,
                    item["document_id"],
                    item["evidence_id"],
                )
                for item in evidence_items
            )

        warnings: list[str] = []
        if missing_ids:
            warnings.append(
                "Unknown Objective IDs were ignored: " + ", ".join(missing_ids)
            )
        if unpublished_count and not records:
            warnings.append("No selected Objective has a published analysis.")
        elif unpublished_count:
            warnings.append(
                f"{unpublished_count} selected Objectives have no published analysis."
            )
        scientific_absence = finding_count == 0 and evidence_count == 0
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "selected_objective_count": len(selected),
                "published_objective_count": len(records),
                "finding_count": finding_count,
                "evidence_count": evidence_count,
                "scientific_absence": scientific_absence,
                "objectives": records,
            },
            resource_refs=tuple(refs),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _finding_summary(item: Mapping[str, Any]) -> dict[str, Any]:
        contributions = item.get("paper_contributions") or ()
        return {
            "finding_id": str(item.get("finding_id") or ""),
            "statement": str(item.get("statement") or "")[:1_000],
            "factors": [str(value)[:160] for value in item.get("factors") or ()][:6],
            "outcome": str(item.get("outcome") or "")[:160],
            "direction": str(item.get("direction") or "unknown")[:80],
            "assertion_strength": str(
                item.get("assertion_strength") or "uncertain"
            )[:80],
            "synthesis_status": str(item.get("synthesis_status") or "unknown")[:80],
            "certainty": item.get("certainty"),
            "document_ids": [
                str(value.get("document_id"))
                for value in contributions
                if isinstance(value, Mapping) and value.get("document_id")
            ][:12],
        }

    @staticmethod
    def _evidence_summary(item: Mapping[str, Any]) -> dict[str, Any]:
        result = item.get("reported_result")
        return {
            "evidence_id": str(item.get("evidence_id") or ""),
            "document_id": str(item.get("document_id") or ""),
            "source_kind": str(item.get("source_kind") or ""),
            "source_ref": str(item.get("source_ref") or "")[:500],
            "source_excerpt": str(item.get("source_excerpt") or "")[:800],
            "evidence_role": item.get("evidence_role"),
            "reported_result": dict(result) if isinstance(result, Mapping) else None,
            "attribution_scope": item.get("attribution_scope"),
            "resolution_status": item.get("resolution_status"),
            "confidence": item.get("confidence"),
            "supports_finding": item.get("supports_finding") is True,
        }

    @staticmethod
    def _objective_ref(collection_id: str, objective_id: str) -> ChatResourceRef:
        return ChatResourceRef(
            resource_type="research_objective",
            resource_id=objective_id,
            href=f"/collections/{collection_id}/objectives/{objective_id}",
        )

    @staticmethod
    def _finding_ref(
        collection_id: str,
        objective_id: str,
        version: int,
        finding_id: str,
    ) -> ChatResourceRef:
        return ChatResourceRef(
            resource_type="finding",
            resource_id=f"{objective_id}:{version}:{finding_id}",
            href=(
                f"/collections/{collection_id}/objectives/{objective_id}"
                f"?finding_id={finding_id}"
            ),
        )

    @staticmethod
    def _evidence_ref(
        collection_id: str,
        objective_id: str,
        document_id: str,
        evidence_id: str,
    ) -> ChatResourceRef:
        return ChatResourceRef(
            resource_type="evidence",
            resource_id=f"{objective_id}:{evidence_id}",
            href=(
                f"/collections/{collection_id}/documents/{document_id}"
                f"?evidence_id={evidence_id}"
            ),
        )


class InspectPublishedFindingCapability:
    spec = ToolSpec(
        name="inspect_published_finding",
        description=(
            "Read one exact complete published Finding and a bounded page of its "
            "Source-linked Evidence. Use this before proposing feedback, curation, or a "
            "new Finding derived from this parent. The complete Finding object is the "
            "only valid basis for a curation or parent-derived authoring write; do not "
            "reconstruct omitted fields from a summary."
        ),
        risk=ToolRisk.READ,
        input_model=InspectPublishedFindingArguments,
    )

    def __init__(self, *, collection_service: Any, objective_analysis_service: Any) -> None:
        self.collection_service = collection_service
        self.objective_analysis_service = objective_analysis_service

    async def execute(
        self,
        context: CapabilityExecutionContext,
        arguments: InspectPublishedFindingArguments,
    ) -> ChatToolResult:
        await self.collection_service.get_collection_for_user(
            context.collection_id,
            context.user_id,
        )
        detail = await self.objective_analysis_service.get_finding(
            context.collection_id,
            arguments.objective_id,
            arguments.finding_id,
            analysis_version=arguments.analysis_version,
        )
        version = int(detail["analysis_version"])
        evidence = await self.objective_analysis_service.list_evidence(
            context.collection_id,
            arguments.objective_id,
            analysis_version=version,
            finding_id=arguments.finding_id,
            offset=arguments.evidence_offset,
            limit=arguments.evidence_limit,
        )
        evidence_items = [
            QueryPublishedFindingsCapability._evidence_summary(item)
            for item in evidence.get("items", ())
            if isinstance(item, Mapping)
        ]
        evidence_total = int(evidence.get("total") or 0)
        next_offset = arguments.evidence_offset + len(evidence_items)
        if next_offset >= evidence_total:
            next_offset = None
        warnings: tuple[str, ...] = ()
        if next_offset is not None:
            warnings = (
                "Additional Finding Evidence was omitted from this bounded page; "
                "inspect the next evidence_offset before proposing a complete review.",
            )
        finding_ref = QueryPublishedFindingsCapability._finding_ref(
            context.collection_id,
            arguments.objective_id,
            version,
            arguments.finding_id,
        )
        return ChatToolResult(
            tool_call_id=context.tool_call_id,
            status="succeeded",
            data={
                "objective_id": arguments.objective_id,
                "analysis_version": version,
                "finding": dict(detail["finding"]),
                "finding_is_published": True,
                "evidence": evidence_items,
                "evidence_total": evidence_total,
                "evidence_offset": arguments.evidence_offset,
                "evidence_limit": arguments.evidence_limit,
                "next_evidence_offset": next_offset,
            },
            resource_refs=(
                finding_ref,
                *(
                    QueryPublishedFindingsCapability._evidence_ref(
                        context.collection_id,
                        arguments.objective_id,
                        item["document_id"],
                        item["evidence_id"],
                    )
                    for item in evidence_items
                ),
            ),
            warnings=warnings,
        )


__all__ = [
    "InspectPublishedFindingArguments",
    "InspectPublishedFindingCapability",
    "QueryPublishedFindingsArguments",
    "QueryPublishedFindingsCapability",
]
