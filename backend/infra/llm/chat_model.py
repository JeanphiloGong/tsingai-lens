"""OpenAI-compatible transport adapter for the Research Agent."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from openai import AsyncOpenAI

from application.chat.capabilities import ToolSpec
from application.chat.context_builder import ChatContextBuilder, ChatModelContext
from application.chat.model import (
    RESEARCH_AGENT_PROMPT_VERSION,
    RESEARCH_AGENT_SYSTEM_PROMPT,
    RESEARCH_COMPACTION_SYSTEM_PROMPT,
    ModelResponseError,
    ModelToolCall,
    ModelTurn,
    ModelUsage,
)
from application.repositories.chat_repository import ModelCallInput, ModelCallOutcome
from domain.chat import ToolRisk
from infra.llm.usage import record_llm_completion, record_llm_prompt_version

logger = logging.getLogger(__name__)


class OpenAIChatModel:
    def __init__(
        self,
        *,
        client: Any | None = None,
        model: str | None = None,
    ) -> None:
        self.model = (
            model
            or os.getenv("LLM_MODEL")
            or "gpt-4o-mini"
        ).strip()
        self.request_timeout = _env_float("LLM_REQUEST_TIMEOUT_SECONDS", 180.0)
        self.reasoning_effort = os.getenv("LLM_REASONING_EFFORT", "").strip() or None
        if client is not None:
            self.client = client.with_options(max_retries=0)
        else:
            self.client = AsyncOpenAI(
                api_key=os.getenv("LLM_API_KEY", "").strip() or "not-needed",
                base_url=os.getenv("LLM_BASE_URL", "").strip() or None,
                timeout=self.request_timeout,
                max_retries=0,
            )

    async def respond(
        self,
        *,
        context: ChatModelContext,
        tool_specs: tuple[ToolSpec, ...],
        text_delta_callback: Callable[[str], None] | None = None,
        timeout_seconds: float = 180.0,
        max_output_tokens: int = 16_384,
    ) -> ModelTurn:
        request: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.2,
            "timeout": min(timeout_seconds, self.request_timeout),
            "max_completion_tokens": max_output_tokens,
            "messages": context.provider_messages(
                RESEARCH_COMPACTION_SYSTEM_PROMPT if context.compacting else
                RESEARCH_AGENT_SYSTEM_PROMPT
            ),
        }
        if self.reasoning_effort is not None:
            request["reasoning_effort"] = self.reasoning_effort
        if context.compacting:
            if tool_specs or context.require_tool_call:
                raise ValueError("context compaction cannot expose executable tools")
            request["response_format"] = {"type": "json_object"}
        if tool_specs:
            request.update(
                tools=[spec.model_schema() for spec in tool_specs],
                tool_choice="required" if context.require_tool_call else "auto",
                parallel_tool_calls=all(spec.risk is ToolRisk.READ for spec in tool_specs),
            )
        request_tokens = ChatContextBuilder.estimate_tokens({
            "messages": request["messages"], "tools": request.get("tools", []),
        })
        if request_tokens + max_output_tokens + 1024 > context.max_context_tokens:
            raise ModelResponseError("Model request exceeds its context window.",
                                     reason="context_window_exceeded", retryable=False)
        provider_request = dict(request)
        streaming = text_delta_callback is not None
        if streaming:
            provider_request.update(stream=True, stream_options={"include_usage": True})

        observer = context.model_call_observer
        call_id: str | None = None
        call_finished = False
        if observer is not None:
            session_id = context.model_call_session_id or next(
                (message.session_id for message in context.messages), ""
            )
            if not session_id:
                raise ModelResponseError(
                    "The model call has no conversation identity.",
                    reason="model_call_identity_missing",
                    retryable=False,
                )
            request_snapshot = _json_snapshot(provider_request)
            call_id = await observer.start(ModelCallInput(
                session_id=session_id,
                trigger_message_id=context.active_user_message_id,
                response_message_id=context.model_call_response_message_id,
                purpose=context.model_call_purpose,
                request=request_snapshot,
            ))

        async def finish(
            status: str,
            *,
            error_code: str | None = None,
            usage: ModelUsage | None = None,
        ) -> None:
            nonlocal call_finished
            if observer is None or call_id is None or call_finished:
                return
            try:
                await observer.finish(call_id, ModelCallOutcome(
                    status=status,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    error_code=error_code,
                    prompt_tokens=usage.prompt_tokens if usage else None,
                    completion_tokens=usage.completion_tokens if usage else None,
                    total_tokens=usage.total_tokens if usage else None,
                ))
            except Exception as exc:  # noqa: BLE001
                raise ModelResponseError(
                    "The model call could not be saved.",
                    reason="model_call_persistence_failed",
                    retryable=False,
                ) from exc
            call_finished = True

        if streaming:
            usage: ModelUsage | None = None
            try:
                chunks = await self.client.chat.completions.create(**provider_request)
                try:
                    turn = await self._stream_turn(chunks, text_delta_callback)
                    usage = turn.usage
                finally:
                    await chunks.close()
                await finish("provider_succeeded", usage=usage)
                return turn
            except ModelResponseError as exc:
                await finish("response_invalid", error_code=exc.reason, usage=exc.usage)
                raise
            except asyncio.CancelledError:
                await finish("cancelled", error_code="request_cancelled", usage=usage)
                raise
            except Exception as exc:  # noqa: BLE001
                await finish("provider_failed", error_code=_provider_error_code(exc), usage=usage)
                raise

        usage = None
        try:
            completion = await self.client.chat.completions.create(**provider_request)
            record_llm_prompt_version(
                "research_agent", RESEARCH_AGENT_PROMPT_VERSION,
            )
            record_llm_completion(completion, requested_model=self.model)
            usage = _model_usage(getattr(completion, "usage", None))
            choices = getattr(completion, "choices", None)
            if not choices:
                logger.warning(
                    "Research model response shape invalid model=%s reason=%s "
                    "message=%s response_type=%s choices_type=%s choices_count=%s "
                    "response_fields=%s usage_present=%s",
                    self.model,
                    "empty_response",
                    "research model returned no choices",
                    type(completion).__name__,
                    type(choices).__name__,
                    _safe_length(choices),
                    _safe_shape_fields(completion),
                    usage is not None,
                )
                raise _invalid_response(
                    "research model returned no choices",
                    reason="empty_response",
                    usage=usage,
                )
            try:
                choice = choices[0]
            except (AttributeError, IndexError, KeyError, TypeError) as exc:
                logger.warning(
                    "Research model response shape invalid model=%s reason=%s "
                    "message=%s response_type=%s choices_type=%s choices_count=%s "
                    "response_fields=%s",
                    self.model,
                    "invalid_response_shape",
                    "research model returned an invalid response shape",
                    type(completion).__name__,
                    type(choices).__name__,
                    _safe_length(choices),
                    _safe_shape_fields(completion),
                )
                raise _invalid_response(
                    "research model returned an invalid response shape",
                    reason="invalid_response_shape",
                    usage=usage,
                ) from exc
            message = getattr(choice, "message", None)
            if message is None:
                logger.warning(
                    "Research model response shape invalid model=%s reason=%s "
                    "message=%s missing_field=message response_type=%s "
                    "choices_type=%s choices_count=%s choice_type=%s choice_fields=%s "
                    "message_attribute_present=%s message_is_none=%s finish_reason=%s "
                    "response_fields=%s usage_present=%s",
                    self.model,
                    "invalid_response_shape",
                    "research model returned an invalid response shape",
                    type(completion).__name__,
                    type(choices).__name__,
                    _safe_length(choices),
                    type(choice).__name__,
                    _safe_shape_fields(choice),
                    _safe_has_field(choice, "message"),
                    message is None,
                    _safe_finish_reason(getattr(choice, "finish_reason", None)),
                    _safe_shape_fields(completion),
                    usage is not None,
                )
                raise _invalid_response(
                    "research model returned an invalid response shape",
                    reason="invalid_response_shape",
                    usage=usage,
                )
            tool_calls = tuple(getattr(message, "tool_calls", None) or ())
            content = str(getattr(message, "content", None) or "").strip()
            if not content and not tool_calls:
                finish_reason = getattr(choice, "finish_reason", None)
                logger.warning(
                    "Research model returned no answer or calls model=%s finish=%s "
                    "reasoning_present=%s completion_tokens=%s required_tool=%s",
                    self.model,
                    finish_reason if finish_reason in {"stop", "length", "tool_calls", "content_filter"} else "unknown",
                    bool(getattr(message, "reasoning_content", None) or getattr(message, "reasoning", None)),
                    usage.completion_tokens if usage else None,
                    context.require_tool_call,
                )
            if getattr(choice, "finish_reason", None) == "length":
                raise _invalid_response(
                    "research model exhausted its output allowance",
                    reason="output_token_limit", retryable=False,
                    partial_content=bool(content), usage=usage,
                )
            if not tool_calls:
                try:
                    turn = ModelTurn(content=content, usage=usage)
                except ValueError as exc:
                    raise _invalid_response(
                        "research model returned no usable content",
                        reason=(
                            "reasoning_only_response"
                            if getattr(message, "reasoning_content", None) or getattr(message, "reasoning", None)
                            else "empty_response"
                        ),
                        usage=usage,
                    ) from exc
                await finish("provider_succeeded", usage=usage)
                return turn

            parsed = []
            for raw_call in tool_calls:
                if getattr(raw_call, "type", "function") != "function":
                    raise _invalid_response("unsupported tool call", reason="unsupported_tool_call", partial_content=bool(content))
                function = getattr(raw_call, "function", None)
                parsed.append(_parse_call(
                    str(getattr(function, "name", None) or ""),
                    str(getattr(function, "arguments", None) or "{}"),
                    partial_content=bool(content),
                ))
            turn = ModelTurn(content=content, tool_calls=tuple(parsed), usage=usage)
            await finish("provider_succeeded", usage=usage)
            return turn
        except ModelResponseError as exc:
            await finish("response_invalid", error_code=exc.reason, usage=exc.usage)
            raise
        except asyncio.CancelledError:
            await finish("cancelled", error_code="request_cancelled", usage=usage)
            raise
        except Exception as exc:  # noqa: BLE001
            await finish("provider_failed", error_code=_provider_error_code(exc), usage=usage)
            raise

    async def _stream_turn(
        self,
        chunks: Any,
        text_delta_callback: Callable[[str], None],
    ) -> ModelTurn:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        parts_by_index: dict[int, tuple[list[str], list[str]]] = {}
        last_chunk = None
        usage = None
        finish_reason = None
        try:
            async for chunk in chunks:
                last_chunk = chunk
                if getattr(chunk, "usage", None) is not None:
                    usage = _model_usage(chunk.usage)
                choices = tuple(getattr(chunk, "choices", None) or ())
                if not choices:
                    continue
                try:
                    choice = choices[0]
                    finish_reason = getattr(choice, "finish_reason", None) or finish_reason
                    delta = getattr(choice, "delta", None)
                except (AttributeError, IndexError, KeyError, TypeError) as exc:
                    logger.warning(
                        "Research model stream response shape invalid model=%s reason=%s "
                        "message=%s chunk_type=%s choices_type=%s choices_count=%s "
                        "chunk_fields=%s",
                        self.model,
                        "invalid_stream",
                        "research model returned an invalid streamed response",
                        type(chunk).__name__,
                        type(getattr(chunk, "choices", None)).__name__,
                        _safe_length(getattr(chunk, "choices", None)),
                        _safe_shape_fields(chunk),
                    )
                    raise _invalid_response(
                        "research model returned an invalid streamed response",
                        reason="invalid_stream",
                        partial_content=bool(content_parts),
                        usage=usage,
                    ) from exc
                if delta is None:
                    logger.warning(
                        "Research model stream response shape invalid model=%s reason=%s "
                        "message=%s missing_field=delta chunk_type=%s choices_type=%s "
                        "choices_count=%s choice_type=%s choice_fields=%s finish_reason=%s "
                        "chunk_fields=%s usage_present=%s",
                        self.model,
                        "invalid_stream",
                        "research model returned an invalid streamed response",
                        type(chunk).__name__,
                        type(getattr(chunk, "choices", None)).__name__,
                        _safe_length(getattr(chunk, "choices", None)),
                        type(choice).__name__,
                        _safe_shape_fields(choice),
                        _safe_finish_reason(getattr(choice, "finish_reason", None)),
                        _safe_shape_fields(chunk),
                        usage is not None,
                    )
                    raise _invalid_response(
                        "research model returned an invalid streamed response",
                        reason="invalid_stream",
                        partial_content=bool(content_parts),
                        usage=usage,
                    )
                content = str(getattr(delta, "content", None) or "")
                if content:
                    content_parts.append(content)
                    text_delta_callback(content)
                reasoning = str(
                    getattr(delta, "reasoning_content", None)
                    or getattr(delta, "reasoning", None)
                    or ""
                )
                if reasoning:
                    reasoning_parts.append(reasoning)
                for raw_call in tuple(getattr(delta, "tool_calls", None) or ()):
                    index = int(getattr(raw_call, "index", 0) or 0)
                    if index < 0:
                        raise ValueError("negative tool call index")
                    tool_name_parts, tool_argument_parts = parts_by_index.setdefault(index, ([], []))
                    if (getattr(raw_call, "type", None) or "function") != "function":
                        raise _invalid_response(
                            "research model returned an unsupported tool call type",
                            reason="unsupported_tool_call",
                            partial_content=bool(content_parts),
                        )
                    function = getattr(raw_call, "function", None)
                    tool_name_parts.append(
                        str(getattr(function, "name", None) or "")
                    )
                    tool_argument_parts.append(
                        str(getattr(function, "arguments", None) or "")
                    )
        except ModelResponseError as exc:
            exc.usage = usage
            raise
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise _invalid_response(
                "research model returned an invalid streamed response",
                reason="invalid_stream",
                partial_content=bool(content_parts),
                usage=usage,
            ) from exc

        record_llm_prompt_version(
            "research_agent", RESEARCH_AGENT_PROMPT_VERSION,
        )
        record_llm_completion(last_chunk, requested_model=self.model)
        content = "".join(content_parts).strip()
        if finish_reason == "length":
            raise _invalid_response(
                "research model exhausted its output allowance",
                reason="output_token_limit", retryable=False,
                partial_content=bool(content), usage=usage,
            )
        if not parts_by_index:
            if not content:
                raise _invalid_response(
                    "research model returned no usable streamed content",
                    reason=(
                        "reasoning_only_response"
                        if reasoning_parts
                        else "empty_response"
                    ),
                    usage=usage,
                )
            try:
                return ModelTurn(content=content, usage=usage)
            except ValueError as exc:
                raise _invalid_response(
                    "research model returned no usable streamed content",
                    reason="empty_response",
                    usage=usage,
                ) from exc

        try:
            return ModelTurn(
                content=content, usage=usage,
                tool_calls=tuple(
                    _parse_call("".join(names), "".join(arguments) or "{}", partial_content=bool(content))
                    for _, (names, arguments) in sorted(parts_by_index.items())
                ),
            )
        except ModelResponseError as exc:
            exc.usage = usage
            raise


def _parse_call(name: str, raw_arguments: str, *, partial_content: bool) -> ModelToolCall:
    try:
        arguments = json.loads(raw_arguments)
        if not isinstance(arguments, Mapping):
            raise ValueError("arguments must be an object")
    except (TypeError, ValueError) as exc:
        raise _invalid_response("invalid tool arguments", reason="invalid_tool_arguments", partial_content=partial_content) from exc
    try:
        return ModelToolCall(name=name, arguments=arguments)
    except (TypeError, ValueError) as exc:
        raise _invalid_response("invalid tool call", reason="invalid_tool_call", partial_content=partial_content) from exc


def _model_usage(raw_usage: Any) -> ModelUsage | None:
    if raw_usage is None:
        return None
    prompt = int(getattr(raw_usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(raw_usage, "completion_tokens", 0) or 0)
    total = int(getattr(raw_usage, "total_tokens", 0) or 0)
    return ModelUsage(prompt, completion, max(total, prompt + completion))


def _safe_length(value: Any) -> int | None:
    try:
        return len(value)
    except Exception:  # noqa: BLE001
        return None


def _safe_shape_fields(value: Any) -> str:
    if isinstance(value, Mapping):
        raw_names = value.keys()
    else:
        try:
            raw_names = vars(value).keys()
        except Exception:  # noqa: BLE001
            return "unknown"
    names: set[str] = set()
    for raw_name in raw_names:
        name = str(raw_name)[:40]
        sanitized = "".join(
            character if character.isascii() and (character.isalnum() or character in "_.-") else "_"
            for character in name
        )
        if sanitized:
            names.add(sanitized)
    return ",".join(sorted(names)[:16]) or "none"


def _safe_has_field(value: Any, name: str) -> bool:
    try:
        if isinstance(value, Mapping):
            return name in value
        return hasattr(value, name)
    except Exception:  # noqa: BLE001
        return False


def _safe_finish_reason(value: Any) -> str:
    return value if isinstance(value, str) and value in {
        "stop", "length", "tool_calls", "content_filter",
    } else "unknown"


def _json_snapshot(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze the exact JSON-compatible request before it reaches the SDK."""
    try:
        return json.loads(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise ModelResponseError(
            "The model request could not be serialized for audit.",
            reason="model_request_not_serializable",
            retryable=False,
        ) from exc


def _provider_error_code(exc: BaseException) -> str:
    """Persist a stable transport class without provider bodies or credentials."""
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "provider_timeout"
    if "rate" in name or "429" in str(getattr(exc, "status_code", "")):
        return "provider_rate_limited"
    if "connection" in name:
        return "provider_connection_error"
    return "provider_error"


def _invalid_response(
    message: str,
    *,
    reason: str,
    partial_content: bool = False,
    retryable: bool = True,
    usage: ModelUsage | None = None,
) -> ModelResponseError:
    return ModelResponseError(
        message,
        reason=reason,
        partial_content=partial_content,
        retryable=retryable,
        usage=usage,
    )


__all__ = ["OpenAIChatModel"]


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default
