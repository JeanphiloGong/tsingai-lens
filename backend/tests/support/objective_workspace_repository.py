from __future__ import annotations

from typing import Any, Mapping

from domain.goal import ExperimentPlanRecord


class InMemoryObjectiveWorkspaceRepository:
    backend_name = "memory"

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.messages: dict[str, list[dict[str, Any]]] = {}
        self.plans: dict[str, ExperimentPlanRecord] = {}

    def read_session(self, session_id: str) -> dict[str, Any] | None:
        session = self.sessions.get(session_id)
        return dict(session) if session is not None else None

    def read_message_context(self, message_id: str) -> dict[str, Any] | None:
        for session_id, messages in self.messages.items():
            for message in messages:
                if message.get("message_id") == message_id:
                    session = self.sessions.get(session_id)
                    if session is None:
                        return None
                    return {"session": dict(session), "message": dict(message)}
        return None

    def write_session(self, payload: Mapping[str, Any]) -> None:
        self.sessions[str(payload["session_id"])] = dict(payload)

    def read_messages(self, session_id: str) -> list[dict[str, Any]]:
        return [dict(message) for message in self.messages.get(session_id, [])]

    def write_messages(
        self,
        session_id: str,
        messages: list[Mapping[str, Any]],
    ) -> None:
        if session_id not in self.sessions:
            raise ValueError(f"session not found: {session_id}")
        self.messages[session_id] = [dict(message) for message in messages]

    def upsert_plan(self, plan: ExperimentPlanRecord) -> ExperimentPlanRecord:
        existing = self.plans.get(plan.plan_id)
        if existing is not None and (
            existing.collection_id != plan.collection_id
            or existing.objective_id != plan.objective_id
        ):
            raise ValueError("experiment plan identity cannot be reassigned")
        self.plans[plan.plan_id] = plan
        return plan

    def read_plan(
        self,
        collection_id: str,
        objective_id: str,
        plan_id: str,
    ) -> ExperimentPlanRecord | None:
        plan = self.plans.get(plan_id)
        if plan is None:
            return None
        if plan.collection_id != collection_id or plan.objective_id != objective_id:
            return None
        return plan

    def list_plans(
        self,
        collection_id: str,
        objective_id: str,
    ) -> tuple[ExperimentPlanRecord, ...]:
        return tuple(
            plan
            for plan in self.plans.values()
            if plan.collection_id == collection_id
            and plan.objective_id == objective_id
        )
