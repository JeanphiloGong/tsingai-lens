from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1

from application.evaluation import FindingFeedbackService
from application.goal.protocol_contract import (
    proposed_design_choices_are_source_independent,
    ved_design_is_scientifically_consistent,
)
from domain.goal import ExperimentPlanRecord
from domain.ports import ExperimentPlanRepository


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
                if _is_historical_grounded_plan(plan)
                else plan
            )
        return tuple(result)

    async def update_plan(
        self,
        *,
        collection_id: str,
        objective_id: str,
        plan_id: str,
        title: str,
        content: str,
        status: str,
    ) -> ExperimentPlanRecord:
        plan = await self.repository.read_plan(
            collection_id, objective_id, plan_id
        )
        if plan is None:
            raise ExperimentPlanNotFoundError(collection_id, objective_id, plan_id)
        historical = _is_historical_grounded_plan(plan)
        if historical:
            _validate_historical_plan_edit(plan, content)
            if status == "ready_for_review":
                checked = await self._with_source_validity(plan)
                if checked.metadata.get("source_validity") != "current":
                    raise ValueError("historical source Findings are stale")
        stored = await self.repository.upsert_plan(
            plan.with_updates(
                title=title,
                content=content,
                status=status,
                updated_at=_now_iso(),
            )
        )
        return await self._with_source_validity(stored) if historical else stored

    async def _with_source_validity(
        self,
        plan: ExperimentPlanRecord,
    ) -> ExperimentPlanRecord:
        if not proposed_design_choices_are_source_independent(
            plan.content
        ) or not ved_design_is_scientifically_consistent(plan.content):
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
    return bool(plan.source_message_id) or (
        plan.metadata.get("source") == "goal_copilot"
        or plan.metadata.get("review_gate") == _HISTORICAL_REVIEW_GATE
    )


def _validate_historical_plan_edit(
    plan: ExperimentPlanRecord,
    content: str,
) -> None:
    if not _has_protocol_draft_structure(content):
        raise ValueError("historical grounded plan is not a structured protocol draft")
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
    if visible_labels and not any(label in content for label in visible_labels):
        raise ValueError("historical grounded plan does not cite a visible source label")


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


__all__ = ["ExperimentPlanNotFoundError", "ExperimentPlanService"]
