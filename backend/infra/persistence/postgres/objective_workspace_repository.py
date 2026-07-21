"""Direct PostgreSQL persistence for Objective sessions, messages, and plans."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from domain.goal import ExperimentPlanRecord
from infra.persistence.postgres.models.objective_workspace import (
    ObjectiveExperimentPlan,
    ObjectiveMessage,
    ObjectiveSession,
)


class PostgresObjectiveWorkspaceRepository:
    backend_name = "postgresql"

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def read_session(self, session_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            row = session.get(ObjectiveSession, session_id)
            return _session_record(row) if row is not None else None

    def read_message_context(self, message_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            message = session.get(ObjectiveMessage, message_id)
            if message is None:
                return None
            workspace = session.get(ObjectiveSession, message.session_id)
            if workspace is None:
                return None
            return {
                "message": _message_record(message),
                "session": _session_record(workspace),
            }

    def write_session(self, payload: Mapping[str, Any]) -> None:
        with self.session_factory.begin() as session:
            session_id = str(payload["session_id"])
            row = session.get(ObjectiveSession, session_id)
            if row is not None and (
                row.user_id != str(payload["user_id"])
                or row.collection_id != str(payload["collection_id"])
            ):
                raise ValueError("session identity cannot be reassigned")
            if row is None:
                row = ObjectiveSession(
                    session_id=session_id,
                    user_id=str(payload["user_id"]),
                    collection_id=str(payload["collection_id"]),
                    focused_material_id=None,
                    focused_paper_id=None,
                    focused_objective_id=None,
                    goal_text=None,
                    intent_brief={},
                    answer_mode="hybrid",
                    rolling_summary="",
                    last_evidence_ids=[],
                    last_material_ids=[],
                    last_paper_ids=[],
                    collection_data_version=None,
                    created_at=_datetime(str(payload["created_at"])),
                    updated_at=_datetime(str(payload["updated_at"])),
                )
                session.add(row)
            row.focused_material_id = _optional_text(
                payload.get("focused_material_id")
            )
            row.focused_paper_id = _optional_text(payload.get("focused_paper_id"))
            row.focused_objective_id = _optional_text(
                payload.get("focused_objective_id")
            )
            row.goal_text = _optional_text(payload.get("goal_text"))
            row.intent_brief = _mapping(payload.get("goal_brief_json"))
            row.answer_mode = str(payload["answer_mode"])
            row.rolling_summary = str(payload.get("rolling_summary") or "")
            row.last_evidence_ids = _list(payload.get("last_evidence_ids"))
            row.last_material_ids = _list(payload.get("last_material_ids"))
            row.last_paper_ids = _list(payload.get("last_paper_ids"))
            row.collection_data_version = _optional_text(
                payload.get("collection_data_version")
            )
            row.created_at = _datetime(str(payload["created_at"]))
            row.updated_at = _datetime(str(payload["updated_at"]))

    def read_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(ObjectiveMessage)
                .where(ObjectiveMessage.session_id == session_id)
                .order_by(ObjectiveMessage.position)
            )
            return [_message_record(row) for row in rows]

    def write_messages(
        self,
        session_id: str,
        messages: list[Mapping[str, Any]],
    ) -> None:
        with self.session_factory.begin() as session:
            if session.get(ObjectiveSession, session_id) is None:
                raise ValueError(f"session not found: {session_id}")
            incoming_ids = {str(message["message_id"]) for message in messages}
            session.execute(
                delete(ObjectiveMessage).where(
                    ObjectiveMessage.session_id == session_id,
                    ObjectiveMessage.message_id.not_in(incoming_ids),
                )
            )
            for position, payload in enumerate(messages):
                message_id = str(payload["message_id"])
                row = session.get(ObjectiveMessage, message_id)
                if row is not None and row.session_id != session_id:
                    raise ValueError("message identity cannot be reassigned")
                if row is None:
                    row = ObjectiveMessage(
                        message_id=message_id,
                        session_id=session_id,
                        position=position,
                        role=str(payload["role"]),
                        content="",
                        source_mode=None,
                        used_evidence_ids=[],
                        warnings=[],
                        links={},
                        source_links=[],
                        review_gate=None,
                        source_finding_refs=[],
                        created_at=_datetime(str(payload["created_at"])),
                    )
                    session.add(row)
                row.position = position
                row.role = str(payload["role"])
                row.content = str(payload.get("content") or payload.get("answer") or "")
                row.source_mode = _optional_text(payload.get("source_mode"))
                row.used_evidence_ids = _list(payload.get("used_evidence_ids"))
                row.warnings = _list(payload.get("warnings"))
                row.links = _mapping(payload.get("links"))
                row.source_links = _mapping_list(payload.get("source_links"))
                row.review_gate = _optional_text(payload.get("review_gate"))
                row.source_finding_refs = _mapping_list(
                    payload.get("source_finding_refs")
                )
                row.created_at = _datetime(str(payload["created_at"]))

    def upsert_plan(self, plan: ExperimentPlanRecord) -> ExperimentPlanRecord:
        with self.session_factory.begin() as session:
            if plan.source_message_id is not None:
                message = session.get(ObjectiveMessage, plan.source_message_id)
                workspace = (
                    session.get(ObjectiveSession, message.session_id)
                    if message is not None
                    else None
                )
                if (
                    message is None
                    or workspace is None
                    or workspace.collection_id != plan.collection_id
                    or workspace.focused_objective_id != plan.objective_id
                ):
                    raise ValueError(
                        "source message must belong to the plan's Objective workspace"
                    )
            row = session.get(ObjectiveExperimentPlan, plan.plan_id)
            if row is not None and (
                row.collection_id != plan.collection_id
                or row.objective_id != plan.objective_id
            ):
                raise ValueError("experiment plan identity cannot be reassigned")
            if row is None:
                row = ObjectiveExperimentPlan(
                    plan_id=plan.plan_id,
                    collection_id=plan.collection_id,
                    objective_id=plan.objective_id,
                    title=plan.title,
                    content=plan.content,
                    status=plan.status,
                    source_message_id=plan.source_message_id,
                    source_links=[dict(item) for item in plan.source_links],
                    metadata_json=dict(plan.metadata),
                    created_by=plan.created_by,
                    created_at=_datetime(plan.created_at),
                    updated_at=_datetime(plan.updated_at),
                )
                session.add(row)
            row.title = plan.title
            row.content = plan.content
            row.status = plan.status
            row.source_message_id = plan.source_message_id
            row.source_links = [dict(item) for item in plan.source_links]
            row.metadata_json = dict(plan.metadata)
            row.created_by = plan.created_by
            row.updated_at = _datetime(plan.updated_at)
            session.flush()
            return _plan_record(row)

    def read_plan(
        self,
        collection_id: str,
        objective_id: str,
        plan_id: str,
    ) -> ExperimentPlanRecord | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(ObjectiveExperimentPlan).where(
                    ObjectiveExperimentPlan.plan_id == plan_id,
                    ObjectiveExperimentPlan.collection_id == collection_id,
                    ObjectiveExperimentPlan.objective_id == objective_id,
                )
            )
            return _plan_record(row) if row is not None else None

    def list_plans(
        self,
        collection_id: str,
        objective_id: str,
    ) -> tuple[ExperimentPlanRecord, ...]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(ObjectiveExperimentPlan)
                .where(
                    ObjectiveExperimentPlan.collection_id == collection_id,
                    ObjectiveExperimentPlan.objective_id == objective_id,
                )
                .order_by(
                    ObjectiveExperimentPlan.updated_at.desc(),
                    ObjectiveExperimentPlan.created_at.desc(),
                    ObjectiveExperimentPlan.plan_id,
                )
            )
            return tuple(_plan_record(row) for row in rows)


def _session_record(row: ObjectiveSession) -> dict[str, Any]:
    return {
        "session_id": row.session_id,
        "user_id": row.user_id,
        "collection_id": row.collection_id,
        "focused_material_id": row.focused_material_id,
        "focused_paper_id": row.focused_paper_id,
        "focused_objective_id": row.focused_objective_id,
        "goal_text": row.goal_text,
        "goal_brief_json": dict(row.intent_brief),
        "answer_mode": row.answer_mode,
        "rolling_summary": row.rolling_summary,
        "last_evidence_ids": list(row.last_evidence_ids),
        "last_material_ids": list(row.last_material_ids),
        "last_paper_ids": list(row.last_paper_ids),
        "collection_data_version": row.collection_data_version,
        "created_at": _isoformat(row.created_at),
        "updated_at": _isoformat(row.updated_at),
    }


def _message_record(row: ObjectiveMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "message_id": row.message_id,
        "session_id": row.session_id,
        "role": row.role,
        "content": row.content,
        "created_at": _isoformat(row.created_at),
    }
    if row.role == "assistant":
        payload.update(
            {
                "answer": row.content,
                "source_mode": row.source_mode,
                "used_evidence_ids": list(row.used_evidence_ids),
                "warnings": list(row.warnings),
                "links": dict(row.links),
                "source_links": [dict(item) for item in row.source_links],
                "review_gate": row.review_gate,
                "source_finding_refs": [
                    dict(item) for item in row.source_finding_refs
                ],
            }
        )
    return payload


def _plan_record(row: ObjectiveExperimentPlan) -> ExperimentPlanRecord:
    return ExperimentPlanRecord.from_mapping(
        {
            "plan_id": row.plan_id,
            "collection_id": row.collection_id,
            "objective_id": row.objective_id,
            "title": row.title,
            "content": row.content,
            "status": row.status,
            "source_message_id": row.source_message_id,
            "source_links": [dict(item) for item in row.source_links],
            "metadata": dict(row.metadata_json),
            "created_by": row.created_by,
            "created_at": _isoformat(row.created_at),
            "updated_at": _isoformat(row.updated_at),
        }
    )


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list | tuple):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


__all__ = ["PostgresObjectiveWorkspaceRepository"]
