from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace

from application.chat.model_calls import ModelCallOutcome
from application.repositories.chat_repository import (
    ChatModelCall,
    ChatResponseSnapshot,
    ChatSessionBusyError,
)
from domain.chat import (
    ChatCorrectionCase,
    ChatMessage,
    ChatSession,
    ChatToolCall,
    ChatToolResult,
)
from domain.chat.permissions import change_permission, permission_record, permits_automatic


class MemoryChatRepository:
    backend_name = "memory"

    def __init__(self) -> None:
        self.sessions: dict[str, ChatSession] = {}
        self.messages: dict[str, tuple[ChatMessage, ...]] = {}
        self.calls: dict[str, ChatToolCall] = {}
        self.results: dict[str, ChatToolResult] = {}
        self.active_sessions: set[str] = set()
        self.response_snapshots: dict[str, ChatResponseSnapshot] = {}
        self.model_calls: dict[str, ChatModelCall] = {}
        self.correction_cases: dict[str, ChatCorrectionCase] = {}
        self.permissions = {}
        self.proposed_revisions = {}

    async def read_permission(self, session_id, user_id):
        session = self.sessions.get(session_id)
        if session is None or session.user_id != user_id:
            raise FileNotFoundError("chat session not found")
        return permission_record(self.permissions.get(session_id))

    async def set_permission(self, session_id, user_id, **changes):
        current = await self.read_permission(session_id, user_id)
        self.permissions[session_id] = change_permission(current, **changes)
        return dict(self.permissions[session_id])

    async def claim_automatic_call(self, *, session_id, tool_call_id, user_id, started_at):
        permission = await self.read_permission(session_id, user_id)
        call = self.calls[tool_call_id]
        if call.session_id != session_id:
            raise FileNotFoundError("chat tool call not found")
        if (call.status.value != "approval_required"
                or self.proposed_revisions[tool_call_id] != permission["revision"]
                or not permits_automatic(permission, call.name, now=started_at)):
            return None
        claimed = replace(call.approve(user_id=user_id, arguments_digest=call.arguments_digest,
                                       decided_at=started_at), decision_basis="scope_grant",
                          authorization_revision=permission["revision"]).start(started_at)
        self.calls[tool_call_id] = claimed
        return claimed

    @asynccontextmanager
    async def session_execution(self, session_id: str):
        if session_id in self.active_sessions:
            raise ChatSessionBusyError()
        self.active_sessions.add(session_id)
        try:
            yield
        finally:
            self.active_sessions.remove(session_id)

    async def is_session_running(self, session_id: str) -> bool:
        return session_id in self.active_sessions

    async def read_response_snapshot(self, session_id: str) -> ChatResponseSnapshot | None:
        return self.response_snapshots.get(session_id)

    async def save_response_snapshot(self, session_id: str, snapshot: ChatResponseSnapshot) -> None:
        self.response_snapshots[session_id] = snapshot

    async def start_model_call(self, call: ChatModelCall) -> ChatModelCall:
        session = self.sessions.get(call.session_id)
        if session is None:
            raise FileNotFoundError(f"chat session not found: {call.session_id}")
        existing = self.model_calls.get(call.call_id)
        if existing is not None:
            if existing.request_digest != call.request_digest or existing.request != call.request:
                raise ValueError("model call identity cannot be reassigned")
            return existing
        self.model_calls[call.call_id] = call
        return call

    async def finish_model_call(self, *, session_id: str, call_id: str, outcome: ModelCallOutcome) -> ChatModelCall:
        call = self.model_calls.get(call_id)
        if call is None or call.session_id != session_id:
            raise FileNotFoundError(f"chat model call not found: {call_id}")
        if call.finished_at is not None:
            if call.status != outcome.status:
                raise ValueError("model call outcome cannot be reassigned")
            return call
        saved = replace(
            call,
            status=outcome.status,
            finished_at=outcome.finished_at,
            error_code=outcome.error_code,
            provider_confirmed=outcome.status == "provider_succeeded",
            prompt_tokens=outcome.prompt_tokens,
            completion_tokens=outcome.completion_tokens,
            total_tokens=outcome.total_tokens,
        )
        self.model_calls[call_id] = saved
        return saved

    async def read_model_calls(self, session_id: str, *, limit: int = 50, offset: int = 0) -> tuple[ChatModelCall, ...]:
        calls = sorted(
            (call for call in self.model_calls.values() if call.session_id == session_id),
            key=lambda call: (call.started_at, call.call_id),
        )
        return tuple(calls[max(0, offset):max(0, offset) + max(1, min(limit, 200))])

    async def read_model_call(self, session_id: str, call_id: str) -> ChatModelCall | None:
        call = self.model_calls.get(call_id)
        return call if call is not None and call.session_id == session_id else None

    async def save_correction_case(self, case: ChatCorrectionCase) -> ChatCorrectionCase:
        if case.session_id not in self.sessions:
            raise FileNotFoundError(f"chat session not found: {case.session_id}")
        existing = self.correction_cases.get(case.case_id)
        if existing is not None:
            if existing.to_record() != case.to_record():
                raise ValueError("correction case identity cannot be reassigned")
            return existing
        for existing in self.correction_cases.values():
            if (
                existing.session_id == case.session_id
                and existing.original_message_id == case.original_message_id
                and existing.feedback_message_id == case.feedback_message_id
                and existing.corrected_message_id == case.corrected_message_id
            ):
                if existing.to_record() != case.to_record():
                    raise ValueError("correction case identity already exists")
                return existing
        self.correction_cases[case.case_id] = case
        return case

    async def read_correction_cases(
        self, session_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[ChatCorrectionCase, ...]:
        cases = sorted(
            (case for case in self.correction_cases.values() if case.session_id == session_id),
            key=lambda case: (case.created_at, case.case_id),
        )
        start = max(0, int(offset))
        return tuple(cases[start : start + max(1, min(int(limit), 200))])

    async def read_correction_case(
        self, session_id: str, case_id: str
    ) -> ChatCorrectionCase | None:
        case = self.correction_cases.get(case_id)
        return case if case is not None and case.session_id == session_id else None

    async def read_session_family(self, session: ChatSession) -> tuple[ChatSession, ...]:
        return (session,)

    async def add_session(self, record: ChatSession) -> None:
        self.sessions[record.session_id] = record
        self.messages[record.session_id] = ()

    async def read_session(self, session_id: str) -> ChatSession | None:
        return self.sessions.get(session_id)

    async def read_messages(self, session_id: str) -> tuple[ChatMessage, ...]:
        return self.messages.get(session_id, ())

    async def read_feedback(self, session_id: str, user_id: str) -> tuple:
        return ()

    async def read_tool_call(self, tool_call_id: str) -> ChatToolCall | None:
        return self.calls.get(tool_call_id)

    async def save_trajectory(
        self,
        *,
        session: ChatSession,
        messages: tuple[ChatMessage, ...],
        tool_calls: tuple[ChatToolCall, ...],
        tool_results: tuple[ChatToolResult, ...],
    ) -> None:
        self.sessions[session.session_id] = session
        self.messages[session.session_id] = messages
        for call in tool_calls:
            self.proposed_revisions.setdefault(call.tool_call_id, permission_record(self.permissions.get(session.session_id))["revision"])
        self.calls.update((item.tool_call_id, item) for item in tool_calls)
        self.results.update((item.tool_call_id, item) for item in tool_results)

    async def decide_tool_call(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        user_id: str,
        arguments_digest: str,
        decision: str,
        decided_at: str,
    ) -> ChatToolCall:
        session = self.sessions.get(session_id)
        if session is None or session.user_id != user_id:
            raise FileNotFoundError(f"chat session not found: {session_id}")
        call = self.calls.get(tool_call_id)
        if call is None or call.session_id != session_id:
            raise FileNotFoundError(f"chat tool call not found: {tool_call_id}")
        permission = await self.read_permission(session_id, user_id)
        if decision == "approved" and permission["mode"] == "read_only":
            raise ValueError("permission_read_only")
        decided = (
            call.approve(
                user_id=user_id,
                arguments_digest=arguments_digest,
                decided_at=decided_at,
            )
            if decision == "approved"
            else call.reject(
                user_id=user_id,
                arguments_digest=arguments_digest,
                decided_at=decided_at,
            )
        )
        if decision == "approved":
            decided = replace(decided, authorization_revision=permission["revision"])
        self.calls[tool_call_id] = decided
        return decided

    async def claim_approved_tool_call(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        user_id: str,
        started_at: str,
    ) -> ChatToolCall | None:
        session = self.sessions.get(session_id)
        if session is None or session.user_id != user_id:
            raise FileNotFoundError(f"chat session not found: {session_id}")
        call = self.calls.get(tool_call_id)
        if call is None or call.session_id != session_id:
            raise FileNotFoundError(f"chat tool call not found: {tool_call_id}")
        if call.status.value == "approved":
            permission = await self.read_permission(session_id, user_id)
            if permission["mode"] == "read_only" or (call.authorization_revision or 0) != permission["revision"]:
                raise ValueError("permission_changed_before_execution")
            claimed = call.start(started_at)
            self.calls[tool_call_id] = claimed
            return claimed
        if call.status.value in {"running", "succeeded", "failed"}:
            return None
        raise ValueError(f"cannot claim tool call in status {call.status.value}")


__all__ = ["MemoryChatRepository"]
