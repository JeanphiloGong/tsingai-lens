"""Bounded model/capability/result loop for one Research Agent turn."""

from __future__ import annotations

from asyncio import to_thread
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import logging
from typing import Any, Callable
from uuid import uuid4

from pydantic import ValidationError

from application.chat.authorization import evaluate_authorization
from application.chat.capabilities import (
    AgentContext,
    CapabilityExecutionContext,
    CapabilityRegistry,
)
from application.chat.context_builder import ChatContextBuilder
from application.chat.model import ChatModel
from domain.chat import (
    ChatMessage,
    ChatToolCall,
    ChatToolResult,
    ToolCallStatus,
    ToolResultStatus,
    ToolRisk,
)


logger = logging.getLogger(__name__)

_TrajectoryCheckpoint = Callable[
    [
        tuple[ChatMessage, ...],
        tuple[ChatToolCall, ...],
        tuple[ChatToolResult, ...],
    ],
    Awaitable[None],
]

_STEP_LIMIT_MESSAGE = (
    "I reached the Research Agent step limit before completing this request. "
    "Please narrow the question or continue in a new message."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentRunStatus(StrEnum):
    COMPLETED = "completed"
    APPROVAL_REQUIRED = "approval_required"
    STEP_LIMIT_REACHED = "step_limit_reached"
    FAILED = "failed"


@dataclass(frozen=True)
class AgentRunResult:
    status: AgentRunStatus
    messages: tuple[ChatMessage, ...]
    tool_calls: tuple[ChatToolCall, ...] = ()
    tool_results: tuple[ChatToolResult, ...] = ()
    pending_approval: ChatToolCall | None = None
    error_code: str | None = None


class ResearchAgentRunner:
    def __init__(
        self,
        *,
        model: ChatModel,
        capabilities: CapabilityRegistry,
        context_builder: ChatContextBuilder | None = None,
        max_model_steps: int = 6,
    ) -> None:
        if max_model_steps < 1:
            raise ValueError("max_model_steps must be positive")
        self.model = model
        self.capabilities = capabilities
        self.context_builder = context_builder or ChatContextBuilder()
        self.max_model_steps = max_model_steps

    async def run_turn(
        self,
        *,
        context: AgentContext,
        previous_messages: tuple[ChatMessage, ...],
        user_message: str,
        checkpoint: _TrajectoryCheckpoint | None = None,
        text_delta_callback: Callable[[str], None] | None = None,
    ) -> AgentRunResult:
        messages = [
            *previous_messages,
            ChatMessage.user(
                message_id=self._message_id(),
                session_id=context.session_id,
                content=user_message,
                created_at=_now_iso(),
            ),
        ]
        calls: list[ChatToolCall] = []
        results: list[ChatToolResult] = []
        await self._checkpoint(checkpoint, messages, calls, results)
        return await self._continue(
            context,
            messages,
            calls,
            results,
            checkpoint=checkpoint,
            text_delta_callback=text_delta_callback,
        )

    async def resume_approved_call(
        self,
        *,
        context: AgentContext,
        previous_messages: tuple[ChatMessage, ...],
        approved_call: ChatToolCall,
        checkpoint: _TrajectoryCheckpoint | None = None,
        text_delta_callback: Callable[[str], None] | None = None,
    ) -> AgentRunResult:
        self._validate_approved_call(context, approved_call)
        messages = list(previous_messages)
        calls = [approved_call]
        results: list[ChatToolResult] = []
        handler = self.capabilities.get(approved_call.name)
        if handler is None or handler.spec.risk is not ToolRisk.WRITE:
            call, result = self._failure(
                approved_call,
                "capability_unavailable",
                "The approved research capability is not available.",
            )
        else:
            call, result = await self._validate_and_execute(
                context,
                approved_call,
                handler,
                messages=messages,
                calls=calls,
                results=results,
                checkpoint=checkpoint,
            )
        calls[-1] = call
        results.append(result)
        messages.append(self._result_message(context, result))
        await self._checkpoint(checkpoint, messages, calls, results)
        return await self._continue(
            context,
            messages,
            calls,
            results,
            checkpoint=checkpoint,
            text_delta_callback=text_delta_callback,
        )

    async def _continue(
        self,
        context: AgentContext,
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
        *,
        checkpoint: _TrajectoryCheckpoint | None,
        text_delta_callback: Callable[[str], None] | None,
    ) -> AgentRunResult:
        for _ in range(self.max_model_steps):
            try:
                model_arguments: dict[str, Any] = {
                    "messages": self.context_builder.for_model(tuple(messages)),
                    "tool_specs": self.capabilities.specs,
                }
                if text_delta_callback is not None:
                    model_arguments["text_delta_callback"] = text_delta_callback
                turn = await to_thread(
                    self.model.respond,
                    **model_arguments,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Research Agent model call failed exception_type=%s",
                    type(exc).__name__,
                )
                messages.append(
                    self._assistant(
                        context,
                        "The research model is unavailable for this turn.",
                    )
                )
                await self._checkpoint(checkpoint, messages, calls, results)
                return self._result(
                    AgentRunStatus.FAILED,
                    messages,
                    calls,
                    results,
                    "model_unavailable",
                )

            if turn.tool_call is None:
                messages.append(self._assistant(context, turn.content))
                await self._checkpoint(checkpoint, messages, calls, results)
                return self._result(AgentRunStatus.COMPLETED, messages, calls, results)

            call, handler = self._requested_call(context, messages, turn)
            calls.append(call)
            await self._checkpoint(checkpoint, messages, calls, results)
            if handler is None:
                call, capability_result = self._failure(
                    call,
                    "unknown_capability",
                    "The requested research capability is not available.",
                )
            else:
                decision = evaluate_authorization(call.risk)
                if decision.requires_approval:
                    pending = call.require_approval()
                    calls[-1] = pending
                    await self._checkpoint(checkpoint, messages, calls, results)
                    return AgentRunResult(
                        status=AgentRunStatus.APPROVAL_REQUIRED,
                        messages=tuple(messages),
                        tool_calls=tuple(calls),
                        tool_results=tuple(results),
                        pending_approval=pending,
                    )
                if not decision.may_execute:
                    call, capability_result = self._failure(
                        call,
                        "capability_not_authorized",
                        "The research capability is not authorized.",
                    )
                else:
                    call, capability_result = await self._validate_and_execute(
                        context,
                        call,
                        handler,
                        messages=messages,
                        calls=calls,
                        results=results,
                        checkpoint=checkpoint,
                    )
            calls[-1] = call
            results.append(capability_result)
            messages.append(self._result_message(context, capability_result))
            await self._checkpoint(checkpoint, messages, calls, results)

        messages.append(self._assistant(context, _STEP_LIMIT_MESSAGE))
        await self._checkpoint(checkpoint, messages, calls, results)
        return self._result(
            AgentRunStatus.STEP_LIMIT_REACHED,
            messages,
            calls,
            results,
            "agent_step_limit_reached",
        )

    def _requested_call(
        self,
        context: AgentContext,
        messages: list[ChatMessage],
        turn: Any,
    ) -> tuple[ChatToolCall, Any]:
        model_call = turn.tool_call
        assistant_message_id = self._message_id()
        tool_call_id = self._tool_call_id()
        messages.append(
            ChatMessage.assistant_tool_call(
                message_id=assistant_message_id,
                session_id=context.session_id,
                content=turn.content,
                tool_call_id=tool_call_id,
                tool_name=model_call.name,
                tool_arguments=model_call.arguments,
                created_at=_now_iso(),
            )
        )
        handler = self.capabilities.get(model_call.name)
        return ChatToolCall.requested(
            tool_call_id=tool_call_id,
            session_id=context.session_id,
            assistant_message_id=assistant_message_id,
            name=model_call.name,
            arguments=model_call.arguments,
            risk=handler.spec.risk if handler is not None else ToolRisk.UNKNOWN,
        ), handler

    async def _validate_and_execute(
        self,
        context: AgentContext,
        call: ChatToolCall,
        handler: Any,
        *,
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
        checkpoint: _TrajectoryCheckpoint | None,
    ) -> tuple[ChatToolCall, ChatToolResult]:
        try:
            arguments = handler.spec.input_model.model_validate(call.arguments)
        except ValidationError:
            return ResearchAgentRunner._failure(
                call,
                "invalid_tool_arguments",
                "The research capability arguments are invalid.",
            )
        call = call.start(_now_iso())
        calls[-1] = call
        await self._checkpoint(checkpoint, messages, calls, results)
        try:
            execution_context = CapabilityExecutionContext.for_call(
                context,
                call.tool_call_id,
            )
            result = (await handler.execute(execution_context, arguments)).for_call(
                call.tool_call_id
            )
            call = (
                call.fail(result.error_code or "capability_failed", _now_iso())
                if result.status is ToolResultStatus.FAILED
                else call.succeed(_now_iso())
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Research capability failed tool=%s exception_type=%s",
                call.name,
                type(exc).__name__,
            )
            call, result = ResearchAgentRunner._failure(
                call,
                "capability_execution_failed",
                "The research capability could not be completed.",
            )
        return call, result

    @staticmethod
    def _validate_approved_call(context: AgentContext, call: ChatToolCall) -> None:
        if call.session_id != context.session_id:
            raise ValueError("approved tool call belongs to another session")
        if call.status is not ToolCallStatus.APPROVED:
            raise ValueError("tool call is not approved")
        if call.decision_user_id != context.user_id:
            raise ValueError("tool call was approved by another user")

    @staticmethod
    def _failure(
        call: ChatToolCall,
        code: str,
        message: str,
    ) -> tuple[ChatToolCall, ChatToolResult]:
        return call.fail(code, _now_iso()), ChatToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolResultStatus.FAILED,
            error_code=code,
            error_message=message,
        )

    @staticmethod
    def _assistant(context: AgentContext, content: str) -> ChatMessage:
        return ChatMessage.assistant(
            message_id=ResearchAgentRunner._message_id(),
            session_id=context.session_id,
            content=content,
            created_at=_now_iso(),
        )

    @staticmethod
    def _result_message(
        context: AgentContext,
        result: ChatToolResult,
    ) -> ChatMessage:
        return ChatMessage.from_tool_result(
            message_id=ResearchAgentRunner._message_id(),
            session_id=context.session_id,
            result=result,
            created_at=_now_iso(),
        )

    @staticmethod
    def _result(
        status: AgentRunStatus,
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
        error_code: str | None = None,
    ) -> AgentRunResult:
        return AgentRunResult(
            status=status,
            messages=tuple(messages),
            tool_calls=tuple(calls),
            tool_results=tuple(results),
            error_code=error_code,
        )

    @staticmethod
    async def _checkpoint(
        checkpoint: _TrajectoryCheckpoint | None,
        messages: list[ChatMessage],
        calls: list[ChatToolCall],
        results: list[ChatToolResult],
    ) -> None:
        if checkpoint is not None:
            await checkpoint(tuple(messages), tuple(calls), tuple(results))

    @staticmethod
    def _message_id() -> str:
        return f"msg_{uuid4().hex[:16]}"

    @staticmethod
    def _tool_call_id() -> str:
        return f"call_{uuid4().hex[:16]}"


__all__ = [
    "AgentRunResult",
    "AgentRunStatus",
    "ResearchAgentRunner",
]
