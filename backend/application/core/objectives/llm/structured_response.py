"""Shared structured-response transport for Objective model judgments."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from contextvars import ContextVar
from time import perf_counter
from typing import Any

import tiktoken
from openai import LengthFinishReasonError, OpenAI
from pydantic import BaseModel, ValidationError

from application.core.structured_extraction.json_support import (
    coerce_message_content,
    extract_json_object,
    load_json_payload,
    trace_json,
    trace_text,
)
from infra.llm.usage import record_llm_completion, record_llm_prompt_version

logger = logging.getLogger(__name__)

_EXTRACTION_MODE_JSON_TEXT = "json_text"
_EXTRACTION_MODE_PROVIDER_PARSE = "provider_parse"
_DEFAULT_EXTRACTION_MODE = _EXTRACTION_MODE_PROVIDER_PARSE
_TRACE_TEXT_LIMIT = 8000
_TRACE_OUTPUT_PREVIEW_CHARS = 1000
_SUPPORTED_EXTRACTION_MODES = {
    _EXTRACTION_MODE_JSON_TEXT,
    _EXTRACTION_MODE_PROVIDER_PARSE,
}


class StructuredOutputSaturatedError(Exception):
    """A bounded structured response reached its completion-token limit."""


class StructuredResponseClient:
    """Invoke models and return schema-validated responses with call traces."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        extraction_mode: str | None = None,
    ) -> None:
        self.model = (
            model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        ).strip() or "gpt-4o-mini"
        self.extraction_mode = self._resolve_extraction_mode(extraction_mode)
        self.enable_thinking = os.getenv("LLM_ENABLE_THINKING", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.reasoning_effort = (
            os.getenv("LLM_REASONING_EFFORT", "").strip() or None
        )
        self._last_trace: ContextVar[dict[str, Any] | None] = ContextVar(
            "structured_response_last_trace",
            default=None,
        )
        self._last_attempts: ContextVar[tuple[dict[str, Any], ...]] = ContextVar(
            "structured_response_last_attempts",
            default=(),
        )
        self.client = client or OpenAI(
            api_key=(api_key or os.getenv("LLM_API_KEY", "").strip() or "not-needed"),
            base_url=(base_url or os.getenv("LLM_BASE_URL", "").strip() or None),
        )

    def estimate_prompt_tokens(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> int:
        """Count one complete schema-bearing structured-response prompt."""

        messages = self._build_messages(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=response_model,
            include_schema=True,
        )
        try:
            encoding = tiktoken.encoding_for_model(self.model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        serialized_messages = json.dumps(
            messages,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return len(encoding.encode(serialized_messages))

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        max_completion_tokens: int | None = None,
        force_json_text: bool = False,
        include_schema_for_forced_json: bool = True,
        json_text_parser: Callable[..., tuple[BaseModel, str | None]] | None = None,
        parsed_validator: Callable[[BaseModel], BaseModel | None] | None = None,
        validation_error_observer: Callable[[Exception], None] | None = None,
        task_type: str | None = None,
        prompt_version: str | None = None,
        fail_on_output_saturation: bool = False,
    ) -> BaseModel:
        if task_type is not None and prompt_version is not None:
            record_llm_prompt_version(task_type, prompt_version)
        parse_json_text = json_text_parser or self.complete_json
        messages = self._build_messages(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=response_model,
            include_schema=self.extraction_mode != _EXTRACTION_MODE_PROVIDER_PARSE,
        )
        self._last_trace.set(None)
        self._last_attempts.set(())
        started_at = perf_counter()
        trace_extraction_mode = self.extraction_mode
        try:
            use_provider_parse = (
                self.extraction_mode == _EXTRACTION_MODE_PROVIDER_PARSE
                and not force_json_text
            )
            if use_provider_parse:
                try:
                    parsed, raw_content = self._parse_provider_structured_response(
                        messages=messages,
                        response_model=response_model,
                        max_completion_tokens=max_completion_tokens,
                    )
                    if parsed_validator is not None:
                        validated = parsed_validator(parsed)
                        if validated is not None:
                            parsed = validated
                except LengthFinishReasonError as exc:
                    if fail_on_output_saturation:
                        error = StructuredOutputSaturatedError(
                            "PaperResearchMap provider output reached the completion-token "
                            "limit"
                        )
                        completion = getattr(exc, "completion", None)
                        choice = (
                            completion.choices[0]
                            if completion is not None
                            and getattr(completion, "choices", None)
                            else None
                        )
                        raw_content = coerce_message_content(
                            getattr(getattr(choice, "message", None), "content", None)
                        )
                        self._last_attempts.set(
                            (
                                self._build_attempt_trace(
                                    attempt=1,
                                    finish_reason=self._finish_reason_from_exception(exc),
                                    raw_content=raw_content,
                                    error=error,
                                ),
                            )
                        )
                        raise error from exc
                    logger.warning(
                        "Objective provider output reached the completion-token limit; "
                        "retrying with json_text model=%s response_model=%s",
                        self.model,
                        response_model.__name__,
                    )
                    messages = self._build_messages(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        response_model=response_model,
                        include_schema=True,
                    )
                    parsed, raw_content = parse_json_text(
                        messages=messages,
                        response_model=response_model,
                        max_completion_tokens=max_completion_tokens,
                    )
                    trace_extraction_mode = (
                        f"{_EXTRACTION_MODE_PROVIDER_PARSE}->{_EXTRACTION_MODE_JSON_TEXT}"
                    )
                except Exception as exc:
                    if validation_error_observer is not None:
                        validation_error_observer(exc)
                    logger.warning(
                        "Objective provider parse failed; retrying with json_text "
                        "model=%s response_model=%s",
                        self.model,
                        response_model.__name__,
                        exc_info=True,
                    )
                    messages = self._build_messages(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        response_model=response_model,
                        include_schema=True,
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "The provider-parsed output failed validation. "
                                "Correct this validation error and return only the "
                                f"schema-valid JSON object: {str(exc)[:1000]}"
                            ),
                        }
                    )
                    parsed, raw_content = parse_json_text(
                        messages=messages,
                        response_model=response_model,
                        max_completion_tokens=max_completion_tokens,
                    )
                    trace_extraction_mode = (
                        f"{_EXTRACTION_MODE_PROVIDER_PARSE}->{_EXTRACTION_MODE_JSON_TEXT}"
                    )
            else:
                if self.extraction_mode == _EXTRACTION_MODE_PROVIDER_PARSE:
                    if include_schema_for_forced_json:
                        messages = self._build_messages(
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            response_model=response_model,
                            include_schema=True,
                        )
                    trace_extraction_mode = _EXTRACTION_MODE_JSON_TEXT
                parsed, raw_content = parse_json_text(
                    messages=messages,
                    response_model=response_model,
                    max_completion_tokens=max_completion_tokens,
                )
        except Exception as exc:
            elapsed_s = perf_counter() - started_at
            attempts = self._last_attempts.get()
            self._last_trace.set(
                self._build_trace(
                    task_type=task_type,
                    prompt_version=prompt_version,
                    response_model=response_model,
                    messages=messages,
                    extraction_mode=trace_extraction_mode,
                    trace_status="failed",
                    elapsed_s=elapsed_s,
                    raw_content=(
                        str(attempts[-1].get("response_preview") or "")
                        if attempts
                        else None
                    ),
                    error=str(exc),
                    error_type=type(exc).__name__,
                    attempts=attempts,
                )
            )
            logger.exception(
                "Objective extraction failed mode=%s model=%s "
                "response_model=%s elapsed_s=%.3f validated=false",
                self.extraction_mode,
                self.model,
                response_model.__name__,
                elapsed_s,
            )
            raise
        elapsed_s = perf_counter() - started_at
        self._last_trace.set(
            self._build_trace(
                task_type=task_type,
                prompt_version=prompt_version,
                response_model=response_model,
                messages=messages,
                extraction_mode=trace_extraction_mode,
                trace_status="available",
                elapsed_s=elapsed_s,
                raw_content=raw_content,
                parsed_output=parsed,
                attempts=self._last_attempts.get(),
            )
        )
        logger.debug(
            "Objective extraction finished mode=%s model=%s "
            "response_model=%s elapsed_s=%.3f validated=true",
            self.extraction_mode,
            self.model,
            response_model.__name__,
            elapsed_s,
        )
        return parsed

    def _build_messages(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        include_schema: bool,
    ) -> list[dict[str, str]]:
        user_content = user_prompt
        if include_schema:
            schema = json.dumps(
                response_model.model_json_schema(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            user_content = (
                f"{user_prompt}\n\n"
                "Return exactly one JSON object that matches this schema. "
                "Do not include markdown fences or commentary.\n"
                f"JSON schema:\n{schema}"
            )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    def complete_json(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        max_completion_tokens: int | None,
        repair_instruction_builder: Callable[[str], str] | None = None,
        payload_normalizer: Callable[[Any], Any] | None = None,
        parsed_validator: Callable[[BaseModel], BaseModel | None] | None = None,
        validation_error_observer: Callable[[Exception], None] | None = None,
        fail_on_output_saturation: bool = False,
        max_attempts: int = 2,
        json_schema_name: str | None = None,
    ) -> tuple[BaseModel, str | None]:
        response_format: dict[str, Any] = {"type": "json_object"}
        if json_schema_name is not None:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": json_schema_name,
                    "schema": response_model.model_json_schema(),
                    "strict": True,
                },
            }
        request_kwargs = {
            "model": self.model,
            "temperature": 0,
            "messages": messages,
            "response_format": response_format,
            **self._provider_request_options(),
        }
        if max_completion_tokens is not None:
            request_kwargs["max_completion_tokens"] = max_completion_tokens
        last_error: Exception | None = None
        attempts: list[dict[str, Any]] = []
        self._last_attempts.set(())
        for attempt in range(max_attempts):
            attempt_kwargs = dict(request_kwargs)
            attempt_messages = [*messages]
            attempt_kwargs["messages"] = attempt_messages
            if attempt:
                if isinstance(last_error, ValidationError):
                    repair_detail = "; ".join(
                        f"{'.'.join(str(part) for part in error['loc'])}: "
                        f"{error['msg']}"
                        for error in last_error.errors(
                            include_input=False,
                            include_url=False,
                        )
                    )
                else:
                    repair_detail = str(last_error or "invalid structured output")
                if repair_instruction_builder is not None:
                    retry_instruction = repair_instruction_builder(repair_detail[:1000])
                else:
                    retry_instruction = (
                        "Previous output was invalid. Return only the smallest valid "
                        "JSON object matching the schema. Do not explain, repeat the "
                        "prompt, or include markdown. Correct these validation errors: "
                        f"{repair_detail[:1000]}"
                    )
                attempt_messages.append(
                    {"role": "user", "content": retry_instruction}
                )
                logger.warning(
                    "Retrying structured JSON response model=%s response_model=%s",
                    self.model,
                    response_model.__name__,
                )
            try:
                raw_content = ""
                finish_reason: str | None = None
                try:
                    completion = self.client.chat.completions.create(**attempt_kwargs)
                except Exception as exc:
                    record_llm_completion(
                        getattr(exc, "completion", None),
                        requested_model=self.model,
                    )
                    completion = getattr(exc, "completion", None)
                    choice = (
                        completion.choices[0]
                        if completion is not None
                        and getattr(completion, "choices", None)
                        else None
                    )
                    raw_content = coerce_message_content(
                        getattr(getattr(choice, "message", None), "content", None)
                    )
                    attempts.append(
                        self._build_attempt_trace(
                            attempt=attempt + 1,
                            finish_reason=self._finish_reason_from_exception(exc),
                            raw_content=raw_content,
                            error=exc,
                        )
                    )
                    self._last_attempts.set(tuple(attempts))
                    raise
                record_llm_completion(completion, requested_model=self.model)
                choice = completion.choices[0] if completion.choices else None
                finish_reason = (
                    str(getattr(choice, "finish_reason", "") or "").strip() or None
                )
                raw_content = coerce_message_content(
                    choice.message.content if choice is not None else None
                )
                if (
                    fail_on_output_saturation
                    and finish_reason == "length"
                ):
                    raise StructuredOutputSaturatedError(
                        "PaperResearchMap JSON output reached the completion-token limit"
                    )
                if not raw_content:
                    raise RuntimeError(
                        "structured extraction returned empty response content"
                    )
                payload = load_json_payload(extract_json_object(raw_content))
                if payload_normalizer is not None:
                    payload = payload_normalizer(payload)
                try:
                    parsed = response_model.model_validate(payload)
                    if parsed_validator is not None:
                        validated = parsed_validator(parsed)
                        if validated is not None:
                            parsed = validated
                    attempts.append(
                        self._build_attempt_trace(
                            attempt=attempt + 1,
                            finish_reason=finish_reason,
                            raw_content=raw_content,
                        )
                    )
                    self._last_attempts.set(tuple(attempts))
                    return parsed, raw_content
                except ValidationError:
                    if isinstance(payload, dict):
                        extra_keys = set(payload) - set(response_model.model_fields)
                        if extra_keys - {"confidence"}:
                            raise
                        filtered_payload = {
                            key: value
                            for key, value in payload.items()
                            if key in response_model.model_fields
                        }
                        if filtered_payload != payload:
                            parsed = response_model.model_validate(filtered_payload)
                            if parsed_validator is not None:
                                validated = parsed_validator(parsed)
                                if validated is not None:
                                    parsed = validated
                            attempts.append(
                                self._build_attempt_trace(
                                    attempt=attempt + 1,
                                    finish_reason=finish_reason,
                                    raw_content=raw_content,
                                )
                            )
                            self._last_attempts.set(tuple(attempts))
                            return parsed, raw_content
                    raise
            except StructuredOutputSaturatedError as exc:
                attempts.append(
                    self._build_attempt_trace(
                        attempt=attempt + 1,
                        finish_reason=finish_reason,
                        raw_content=raw_content,
                        error=exc,
                    )
                )
                self._last_attempts.set(tuple(attempts))
                raise
            except (
                RuntimeError,
                ValueError,
                ValidationError,
                json.JSONDecodeError,
            ) as exc:
                if validation_error_observer is not None:
                    validation_error_observer(exc)
                attempts.append(
                    self._build_attempt_trace(
                        attempt=attempt + 1,
                        finish_reason=finish_reason,
                        raw_content=raw_content,
                        error=exc,
                    )
                )
                self._last_attempts.set(tuple(attempts))
                last_error = exc
                if attempt < max_attempts - 1:
                    continue
                raise
        raise RuntimeError("structured extraction failed after retry") from last_error

    def _parse_provider_structured_response(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        max_completion_tokens: int | None,
    ) -> tuple[BaseModel, str | None]:
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": messages,
            "response_format": response_model,
            **self._provider_request_options(),
        }
        if max_completion_tokens is not None:
            request_kwargs["max_completion_tokens"] = max_completion_tokens
        try:
            completion = self.client.beta.chat.completions.parse(**request_kwargs)
        except Exception as exc:
            record_llm_completion(
                getattr(exc, "completion", None),
                requested_model=self.model,
            )
            raise
        record_llm_completion(completion, requested_model=self.model)
        if not completion.choices:
            raise RuntimeError("structured extraction returned no completion choices")
        message = completion.choices[0].message
        parsed = getattr(message, "parsed", None)
        if parsed is None:
            raw_content = coerce_message_content(getattr(message, "content", None))
            raise RuntimeError(
                "structured extraction returned no parsed response content"
                + (f": {raw_content[:500]}" if raw_content else "")
            )
        raw_content = coerce_message_content(getattr(message, "content", None))
        if isinstance(parsed, response_model):
            return parsed, raw_content
        return response_model.model_validate(parsed), raw_content

    def _provider_request_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if not self.enable_thinking:
            options["extra_body"] = {
                "chat_template_kwargs": {
                    "enable_thinking": False,
                }
            }
        if self.reasoning_effort is not None:
            options["reasoning_effort"] = self.reasoning_effort
        return options

    def consume_last_trace(self) -> dict[str, Any] | None:
        trace = self._last_trace.get()
        self._last_trace.set(None)
        return dict(trace) if trace else None

    def peek_last_trace(self) -> dict[str, Any] | None:
        """Return the current call trace without clearing its downstream owner."""

        trace = self._last_trace.get()
        return dict(trace) if trace else None

    @staticmethod
    def _build_attempt_trace(
        *,
        attempt: int,
        finish_reason: str | None,
        raw_content: str,
        error: Exception | None = None,
    ) -> dict[str, Any]:
        trace = {
            "attempt": attempt,
            "finish_reason": finish_reason,
            "response_chars": len(raw_content),
            "response_preview": trace_text(
                raw_content,
                _TRACE_OUTPUT_PREVIEW_CHARS,
            ),
        }
        if error is not None:
            trace["error_type"] = type(error).__name__
            trace["error"] = trace_text(str(error), 1000)
        return trace

    @staticmethod
    def _finish_reason_from_exception(error: Exception) -> str | None:
        completion = getattr(error, "completion", None)
        choice = (
            completion.choices[0]
            if completion is not None and getattr(completion, "choices", None)
            else None
        )
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason is not None:
            return str(finish_reason).strip() or None
        if isinstance(error, LengthFinishReasonError):
            return "length"
        return None

    def _build_trace(
        self,
        *,
        task_type: str | None,
        prompt_version: str | None,
        response_model: type[BaseModel],
        messages: list[dict[str, str]],
        extraction_mode: str,
        trace_status: str,
        elapsed_s: float,
        raw_content: str | None = None,
        parsed_output: BaseModel | None = None,
        error: str | None = None,
        error_type: str | None = None,
        attempts: tuple[dict[str, Any], ...] = (),
    ) -> dict[str, Any]:
        return {
            "task_type": task_type or response_model.__name__,
            "prompt_version": prompt_version,
            "model": self.model,
            "extraction_mode": extraction_mode,
            "response_model": response_model.__name__,
            "trace_status": trace_status,
            "elapsed_s": round(elapsed_s, 6),
            "messages": [
                {
                    "role": trace_text(message.get("role")),
                    "content": trace_text(message.get("content"), _TRACE_TEXT_LIMIT),
                }
                for message in messages
            ],
            "raw_output": trace_text(raw_content, _TRACE_TEXT_LIMIT),
            "parsed_output": trace_json(
                parsed_output.model_dump(mode="json") if parsed_output else None
            ),
            "attempts": [dict(attempt) for attempt in attempts],
            "error_type": trace_text(error_type, 160),
            "error": trace_text(error, 1000),
        }

    def _resolve_extraction_mode(self, extraction_mode: str | None) -> str:
        candidate = (
            extraction_mode
            or os.getenv("CORE_LLM_EXTRACTION_MODE", _DEFAULT_EXTRACTION_MODE)
        )
        normalized = str(candidate or "").strip().lower() or _DEFAULT_EXTRACTION_MODE
        if normalized in _SUPPORTED_EXTRACTION_MODES:
            return normalized
        logger.warning(
            "Invalid CORE_LLM_EXTRACTION_MODE=%s; falling back to %s",
            normalized,
            _DEFAULT_EXTRACTION_MODE,
        )
        return _DEFAULT_EXTRACTION_MODE


def build_default_structured_response_client() -> StructuredResponseClient:
    return StructuredResponseClient()
