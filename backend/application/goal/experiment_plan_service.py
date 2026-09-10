from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Mapping

from application.evaluation import FindingFeedbackService
from application.goal.protocol_contract import (
    proposed_design_choices_are_source_independent,
    ved_design_is_scientifically_consistent,
)
from application.goal.research_plan_contract import ResearchPlanStructure
from domain.goal import ExperimentPlanRecord
from application.repositories.experiment_plan_repository import ExperimentPlanRepository


_HISTORICAL_REVIEW_GATE = "reviewed_findings"


class ExperimentPlanNotFoundError(FileNotFoundError):
    def __init__(self, collection_id: str, objective_id: str, plan_id: str) -> None:
        self.collection_id = collection_id
        self.objective_id = objective_id
        self.plan_id = plan_id
        super().__init__(f"experiment plan not found: {plan_id}")


class ExperimentPlanService:
    """Manage manual plans and retain audits for historical grounded drafts."""

    def __init__(
        self,
        repository: ExperimentPlanRepository,
        finding_feedback_service: FindingFeedbackService,
    ) -> None:
        self.repository = repository
        self.finding_feedback_service = finding_feedback_service

    async def create_plan(
        self,
        *,
        collection_id: str,
        objective_id: str,
        title: str,
        content: str,
        structured_plan: Mapping[str, Any] | None = None,
        created_by: str | None = None,
    ) -> ExperimentPlanRecord:
        now = _now_iso()
        plan = ExperimentPlanRecord.from_mapping(
            {
                "plan_id": _plan_id(
                    collection_id,
                    objective_id,
                    title,
                    content,
                    now,
                ),
                "collection_id": collection_id,
                "objective_id": objective_id,
                "title": title,
                "content": content,
                "status": "draft",
                "source_message_id": None,
                "source_links": [],
                "metadata": {"source": "manual"},
                "created_by": created_by,
                "updated_by": created_by,
                "structured_plan": _validated_structure(structured_plan),
                "created_at": now,
                "updated_at": now,
            }
        )
        return await self.repository.upsert_plan(plan)

    async def create_agent_plan(
        self,
        *,
        collection_id: str,
        objective_id: str,
        title: str,
        content: str,
        source_links: list[Mapping[str, Any]],
        source_findings: list[Mapping[str, Any]],
        structured_plan: Mapping[str, Any],
        created_by: str,
        created_by_tool_call_id: str,
    ) -> ExperimentPlanRecord:
        """Persist one approved plan draft against current Finding snapshots."""

        if not str(created_by or "").strip():
            raise ValueError("research plan requires an authenticated creator")
        if not str(created_by_tool_call_id or "").strip():
            raise ValueError("research plan requires an approved tool call")
        if not source_findings:
            raise ValueError("research plan requires at least one source Finding")
        if not source_links:
            raise ValueError("research plan requires at least one Evidence link")
        normalized_links = [_source_link(item) for item in source_links]
        labels = [item["label"] for item in normalized_links]
        missing_labels = [label for label in labels if label not in content]
        if missing_labels:
            raise ValueError(
                "research plan content is missing visible Evidence citations: "
                + ", ".join(missing_labels)
            )
        if not _has_protocol_draft_structure(content):
            raise ValueError("research plan is not a complete structured draft")
        validity, reasons = await self.finding_feedback_service.source_snapshot_validity(
            collection_id=collection_id,
            objective_id=objective_id,
            source_findings=source_findings,
        )
        if validity != "current":
            raise ValueError(
                "research plan sources are stale"
                + (f": {', '.join(reasons)}" if reasons else "")
            )

        now = _now_iso()
        plan = ExperimentPlanRecord.from_mapping(
            {
                "plan_id": _plan_id(
                    collection_id,
                    objective_id,
                    title,
                    content,
                    created_by_tool_call_id,
                    now,
                ),
                "collection_id": collection_id,
                "objective_id": objective_id,
                "title": title,
                "content": content,
                "status": "draft",
                "source_message_id": None,
                "source_links": normalized_links,
                "metadata": {
                    "source": "research_agent",
                    "review_gate": _HISTORICAL_REVIEW_GATE,
                    "source_findings": [dict(item) for item in source_findings],
                    "created_by_tool_call_id": created_by_tool_call_id,
                    "source_validity": "current",
                    "source_validity_reasons": [],
                },
                "created_by": created_by,
                "updated_by": created_by,
                "structured_plan": _validated_structure(structured_plan),
                "created_at": now,
                "updated_at": now,
            }
        )
        return await self.repository.upsert_plan(plan)

    async def list_plans(
        self,
        collection_id: str,
        objective_id: str,
    ) -> tuple[ExperimentPlanRecord, ...]:
        plans = await self.repository.list_plans(collection_id, objective_id)
        result: list[ExperimentPlanRecord] = []
        for plan in plans:
            result.append(
                await self._with_source_validity(plan)
                if _is_source_grounded_plan(plan)
                else plan
            )
        return tuple(result)

    async def read_plan(
        self,
        collection_id: str,
        objective_id: str,
        plan_id: str,
    ) -> ExperimentPlanRecord:
        plan = await self.repository.read_plan(collection_id, objective_id, plan_id)
        if plan is None:
            raise ExperimentPlanNotFoundError(collection_id, objective_id, plan_id)
        return (
            await self._with_source_validity(plan)
            if _is_source_grounded_plan(plan)
            else plan
        )

    async def update_plan(
        self,
        *,
        collection_id: str,
        objective_id: str,
        plan_id: str,
        title: str,
        content: str,
        status: str,
        structured_plan: Mapping[str, Any] | None,
        updated_by: str,
        source_links: list[Mapping[str, Any]] | None = None,
        source_findings: list[Mapping[str, Any]] | None = None,
        updated_by_tool_call_id: str | None = None,
    ) -> ExperimentPlanRecord:
        plan = await self.repository.read_plan(
            collection_id, objective_id, plan_id
        )
        if plan is None:
            raise ExperimentPlanNotFoundError(collection_id, objective_id, plan_id)
        source_grounded = _is_source_grounded_plan(plan)
        replacing_basis = any(
            value is not None
            for value in (
                source_links,
                source_findings,
                updated_by_tool_call_id,
            )
        )
        next_links: tuple[Mapping[str, str], ...] | None = None
        next_metadata: Mapping[str, Any] | None = None
        if replacing_basis:
            if not source_links or not source_findings:
                raise ValueError(
                    "research plan revision requires Evidence links and Finding snapshots"
                )
            if not str(updated_by_tool_call_id or "").strip():
                raise ValueError(
                    "research plan revision requires an approved tool call"
                )
            normalized_links = tuple(_source_link(item) for item in source_links)
            missing_labels = [
                item["label"] for item in normalized_links if item["label"] not in content
            ]
            if missing_labels:
                raise ValueError(
                    "research plan content is missing visible Evidence citations: "
                    + ", ".join(missing_labels)
                )
            if not _has_protocol_draft_structure(content):
                raise ValueError("research plan is not a complete structured draft")
            validity, reasons = (
                await self.finding_feedback_service.source_snapshot_validity(
                    collection_id=collection_id,
                    objective_id=objective_id,
                    source_findings=source_findings,
                )
            )
            if validity != "current":
                raise ValueError(
                    "research plan sources are stale"
                    + (f": {', '.join(reasons)}" if reasons else "")
                )
            next_links = normalized_links
            next_metadata = {
                **dict(plan.metadata),
                "source": "research_agent",
                "review_gate": _HISTORICAL_REVIEW_GATE,
                "source_findings": [dict(item) for item in source_findings],
                "updated_by_tool_call_id": str(updated_by_tool_call_id).strip(),
                "source_validity": "current",
                "source_validity_reasons": [],
            }
            source_grounded = True
        elif source_grounded:
            _validate_source_grounded_plan_edit(plan, content)
            if status == "ready_for_review":
                checked = await self._with_source_validity(plan)
                if checked.metadata.get("source_validity") != "current":
                    raise ValueError("historical source Findings are stale")
        if not str(updated_by or "").strip():
            raise ValueError("research plan revision requires an authenticated updater")
        now = _now_iso()
        next_structure = (
            _validated_structure(structured_plan)
            if structured_plan is not None
            else plan.structured_plan
        )
        stored = await self.repository.append_plan_revision(
            plan.next_revision(
                plan_id=_plan_id(
                    plan.plan_id,
                    plan.plan_version + 1,
                    title,
                    content,
                    status,
                    updated_by,
                    now,
                ),
                title=title,
                content=content,
                status=status,
                structured_plan=next_structure,
                updated_by=updated_by,
                updated_at=now,
                source_links=next_links,
                metadata=next_metadata,
            )
        )
        return await self._with_source_validity(stored) if source_grounded else stored

    async def _with_source_validity(
        self,
        plan: ExperimentPlanRecord,
    ) -> ExperimentPlanRecord:
        if _is_historical_grounded_plan(plan) and (
            not proposed_design_choices_are_source_independent(plan.content)
            or not ved_design_is_scientifically_consistent(plan.content)
        ):
            validity, reasons = "stale", ["protocol_design_inconsistent"]
        else:
            source_findings = tuple(
                item
                for item in plan.metadata.get("source_findings", [])
                if isinstance(item, dict)
            )
            validity, reasons = await self.finding_feedback_service.source_snapshot_validity(
                collection_id=plan.collection_id,
                objective_id=plan.objective_id,
                source_findings=source_findings,
            )
        payload = plan.to_record()
        payload["metadata"] = {
            **dict(plan.metadata),
            "source_validity": validity,
            "source_validity_reasons": reasons,
        }
        return ExperimentPlanRecord.from_mapping(payload)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_id(*parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return "exp_" + sha1(payload.encode("utf-8")).hexdigest()[:16]


def _is_historical_grounded_plan(plan: ExperimentPlanRecord) -> bool:
    return plan.metadata.get("source") != "research_agent" and (
        bool(plan.source_message_id)
        or plan.metadata.get("source") == "goal_copilot"
        or plan.metadata.get("review_gate") == _HISTORICAL_REVIEW_GATE
    )


def _is_source_grounded_plan(plan: ExperimentPlanRecord) -> bool:
    return (
        plan.metadata.get("source") == "research_agent"
        or _is_historical_grounded_plan(plan)
    )


def _validate_source_grounded_plan_edit(
    plan: ExperimentPlanRecord,
    content: str,
) -> None:
    if not _has_protocol_draft_structure(content):
        raise ValueError("source-grounded plan is not a structured protocol draft")
    if _is_historical_grounded_plan(plan):
        if not proposed_design_choices_are_source_independent(content):
            raise ValueError(
                "Proposed design choice contains an unattributed numeric or named detail"
            )
        if not ved_design_is_scientifically_consistent(content):
            raise ValueError(
                "VED design violates the constituent-state or causal-boundary contract"
            )
    visible_labels = [
        label
        for link in plan.source_links
        if (label := str(link.get("label") or "").strip())
    ]
    if plan.metadata.get("source") == "research_agent":
        if any(label not in content for label in visible_labels):
            raise ValueError("research plan does not cite every visible Evidence label")
    elif visible_labels and not any(label in content for label in visible_labels):
        raise ValueError("historical grounded plan does not cite a visible source label")


def _source_link(value: Mapping[str, Any]) -> dict[str, str]:
    kind = str(value.get("kind") or "").strip()
    label = str(value.get("label") or "").strip()
    href = str(value.get("href") or "").strip()
    if kind != "evidence" or not label or not href:
        raise ValueError(
            "research plan source links require Evidence kind, label, and href"
        )
    return {"kind": kind, "label": label, "href": href}


def _has_protocol_draft_structure(content: str) -> bool:
    normalized = content.lower()
    required_terms = (
        ("hypothesis", "假设"),
        ("variable matrix", "变量矩阵", "变量"),
        ("measurement", "measurements", "表征", "测试指标", "测量"),
        ("control", "controls", "对照"),
        ("risk", "risks", "limit", "limits", "风险", "限制"),
    )
    return all(any(term in normalized for term in terms) for terms in required_terms)


def _validated_structure(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return ResearchPlanStructure.model_validate(value).model_dump()


__all__ = ["ExperimentPlanNotFoundError", "ExperimentPlanService"]
