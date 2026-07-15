from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from domain.goal import ExperimentPlanRecord, GoalMessageRecord, GoalSessionRecord
from domain.ports import ExperimentPlanRepository, GoalSessionRepository
from infra.persistence.factory import (
    build_experiment_plan_repository,
    build_goal_session_repository,
)

PROTOCOL_READY_REVIEW_GATE = "protocol_ready_findings"

BLOCKED_GOAL_COPILOT_WARNINGS = {
    "curated_research_findings_empty",
    "goal_copilot_model_unavailable",
}


class ExperimentPlanNotFoundError(FileNotFoundError):
    def __init__(self, collection_id: str, goal_id: str, plan_id: str) -> None:
        self.collection_id = collection_id
        self.goal_id = goal_id
        self.plan_id = plan_id
        super().__init__(f"experiment plan not found: {plan_id}")


class ExperimentPlanService:
    """Manage human-editable experiment plan drafts produced from goal chat."""

    def __init__(
        self,
        repository: ExperimentPlanRepository | None = None,
        goal_session_repository: GoalSessionRepository | None = None,
    ) -> None:
        self.repository = repository or build_experiment_plan_repository()
        self.goal_session_repository = (
            goal_session_repository or build_goal_session_repository()
        )

    def create_plan(
        self,
        *,
        collection_id: str,
        goal_id: str,
        title: str,
        content: str,
        source_message_id: str | None = None,
        source_links: list[Mapping[str, Any]] | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_by: str | None = None,
    ) -> ExperimentPlanRecord:
        validated_source = self._validate_goal_copilot_source(
            collection_id=collection_id,
            goal_id=goal_id,
            content=content,
            source_message_id=source_message_id,
            source_links=source_links,
            metadata=metadata,
            created_by=created_by,
        )
        if validated_source is not None:
            source_session, source_message = validated_source
            source_links = [link.to_record() for link in source_message.source_links]
            metadata = {
                **dict(metadata or {}),
                "source": "goal_copilot",
                "source_session_id": source_session.session_id,
                "source_mode": source_message.source_mode,
                "used_evidence_ids": list(source_message.used_evidence_ids),
                "review_gate": PROTOCOL_READY_REVIEW_GATE,
            }
        now = _now_iso()
        plan = ExperimentPlanRecord.from_mapping(
            {
                "plan_id": _plan_id(
                    collection_id,
                    goal_id,
                    title,
                    content,
                    source_message_id,
                    now,
                ),
                "collection_id": collection_id,
                "goal_id": goal_id,
                "title": title,
                "content": content,
                "status": "draft",
                "source_message_id": source_message_id,
                "source_links": list(source_links or []),
                "metadata": dict(metadata or {}),
                "created_by": created_by,
                "created_at": now,
                "updated_at": now,
            }
        )
        return self.repository.upsert_plan(plan)

    def _validate_goal_copilot_source(
        self,
        *,
        collection_id: str,
        goal_id: str,
        content: str,
        source_message_id: str | None,
        source_links: list[Mapping[str, Any]] | None,
        metadata: Mapping[str, Any] | None,
        created_by: str | None,
    ) -> tuple[GoalSessionRecord, GoalMessageRecord] | None:
        _ = metadata
        if not source_message_id:
            return None
        context = self.goal_session_repository.read_message_context(source_message_id)
        if context is None:
            raise ValueError("source_message_id does not reference a saved goal message")
        session = GoalSessionRecord.from_mapping(context["session"])
        message = GoalMessageRecord.from_mapping(context["message"])
        if not created_by:
            raise ValueError("source_message_id requires an authenticated user")
        if session.user_id != created_by:
            raise ValueError("source_message_id belongs to a different user")
        if session.collection_id != collection_id:
            raise ValueError("source_message_id belongs to a different collection")
        if session.focused_goal_id != goal_id:
            raise ValueError("source_message_id is not focused on this goal")
        if message.role != "assistant":
            raise ValueError("source_message_id must reference an assistant message")
        if message.source_mode != "collection_grounded":
            raise ValueError("goal copilot experiment plans require collection-grounded answers")
        if message.review_gate != PROTOCOL_READY_REVIEW_GATE:
            raise ValueError(
                "goal copilot experiment plans require protocol-ready findings"
            )
        if BLOCKED_GOAL_COPILOT_WARNINGS.intersection(message.warnings):
            raise ValueError("goal copilot answer is not eligible for experiment plan saving")
        if not message.source_links:
            raise ValueError("goal copilot answer has no auditable source links")
        if not message.used_evidence_ids:
            raise ValueError("goal copilot answer has no evidence citations")
        visible_source_labels = [
            link.label for link in message.source_links if link.label.strip()
        ]
        if visible_source_labels and not any(
            label in message.content for label in visible_source_labels
        ):
            raise ValueError(
                "goal copilot answer does not cite a visible source label"
            )
        if visible_source_labels and not any(
            label in content for label in visible_source_labels
        ):
            raise ValueError(
                "goal copilot answer does not cite a visible source label"
            )
        linked_evidence_ids = {
            evidence_id
            for link in message.source_links
            if (evidence_id := _evidence_id_from_href(link.href))
        }
        if linked_evidence_ids and not linked_evidence_ids.issubset(
            set(message.used_evidence_ids)
        ):
            raise ValueError(
                "goal copilot source links do not match evidence citations"
            )
        missing_linked_evidence_ids = set(message.used_evidence_ids) - linked_evidence_ids
        if missing_linked_evidence_ids:
            raise ValueError(
                "goal copilot answer is missing source links for evidence citations"
            )
        requested_hrefs = {
            str(link.get("href"))
            for link in source_links or []
            if isinstance(link, Mapping) and link.get("href")
        }
        message_hrefs = {link.href for link in message.source_links}
        if requested_hrefs and not requested_hrefs.issubset(message_hrefs):
            raise ValueError("source_links must come from the saved goal message")
        if not _has_protocol_draft_structure(content):
            raise ValueError(
                "goal copilot answer is not a structured protocol draft"
            )
        return session, message

    def list_plans(
        self,
        collection_id: str,
        goal_id: str,
    ) -> tuple[ExperimentPlanRecord, ...]:
        return self.repository.list_plans(collection_id, goal_id)

    def update_plan(
        self,
        *,
        collection_id: str,
        goal_id: str,
        plan_id: str,
        title: str,
        content: str,
        status: str,
    ) -> ExperimentPlanRecord:
        plan = self.repository.read_plan(collection_id, goal_id, plan_id)
        if plan is None:
            raise ExperimentPlanNotFoundError(collection_id, goal_id, plan_id)
        if _is_goal_copilot_plan(plan):
            _validate_goal_copilot_plan_edit(plan, content)
        updated = plan.with_updates(
            title=title,
            content=content,
            status=status,
            updated_at=_now_iso(),
        )
        return self.repository.upsert_plan(updated)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_id(*parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return "exp_" + sha1(payload.encode("utf-8")).hexdigest()[:16]


def _evidence_id_from_href(href: str) -> str:
    parsed = urlparse(href)
    values = parse_qs(parsed.query).get("evidence_id") or []
    return str(values[0]).strip() if values else ""


def _is_goal_copilot_plan(plan: ExperimentPlanRecord) -> bool:
    return (
        bool(plan.source_message_id)
        or plan.metadata.get("source") == "goal_copilot"
        or plan.metadata.get("review_gate") == PROTOCOL_READY_REVIEW_GATE
    )


def _validate_goal_copilot_plan_edit(
    plan: ExperimentPlanRecord,
    content: str,
) -> None:
    if not _has_protocol_draft_structure(content):
        raise ValueError("goal copilot answer is not a structured protocol draft")
    visible_source_labels = [
        label
        for link in plan.source_links
        if (label := str(link.get("label") or "").strip())
    ]
    if visible_source_labels and not any(label in content for label in visible_source_labels):
        raise ValueError("goal copilot answer does not cite a visible source label")


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
