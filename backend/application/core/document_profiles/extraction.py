from __future__ import annotations

import json
import logging
import os
from time import perf_counter
from typing import Any

from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from application.core.document_profiles.prompts import (
    DOCUMENT_PROFILE_PROMPT_VERSION,
    build_document_profile_prompt,
)
from application.core.document_profiles.schemas import StructuredDocumentProfile
from application.core.structured_extraction.json_support import (
    coerce_message_content,
    extract_json_object,
    load_json_payload,
    trace_json,
    trace_text,
)
from infra.llm.usage import record_llm_completion, record_llm_prompt_version

logger = logging.getLogger(__name__)

_DEFAULT_EXTRACTION_MODE = "provider_parse"
_SUPPORTED_EXTRACTION_MODES = {"json_text", "provider_parse"}
_MAX_COMPLETION_TOKENS = 1024
_REPAIR_OUTPUT_CHARS = 4000
_TRACE_OUTPUT_PREVIEW_CHARS = 1000


class DocumentProfileExtractionError(RuntimeError):
    """The model did not produce a usable document classification."""


class DocumentProfileExtractor:
    """Classify documents through the document-profile model contract."""

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
        self.last_trace: dict[str, Any] | None = None
        self.client = client or OpenAI(
            api_key=(api_key or os.getenv("LLM_API_KEY", "").strip() or "not-needed"),
            base_url=(base_url or os.getenv("LLM_BASE_URL", "").strip() or None),
        )

    def extract_document_profile(
        self,
        payload: dict[str, Any],
    ) -> StructuredDocumentProfile:
        record_llm_prompt_version(
            "document_profile",
            DOCUMENT_PROFILE_PROMPT_VERSION,
        )
        system_prompt, user_prompt = build_document_profile_prompt(payload)
        messages = self._build_messages(system_prompt, user_prompt)
        self.last_trace = None
        attempts: list[dict[str, Any]] = []
        started_at = perf_counter()
        try:
            parsed, raw_content = self._request_document_profile(
                messages,
                attempts=attempts,
            )
        except (
            DocumentProfileExtractionError,
            OpenAIError,
            RuntimeError,
            ValueError,
            ValidationError,
            json.JSONDecodeError,
        ) as exc:
            elapsed_s = perf_counter() - started_at
            self.last_trace = self._build_trace(
                messages=messages,
                trace_status="failed",
                elapsed_s=elapsed_s,
                raw_content=(
                    str(attempts[-1].get("response_preview") or "")
                    if attempts
                    else None
                ),
                error=str(exc),
                attempts=attempts,
            )
            logger.exception(
                "Document profile extraction failed mode=json_text model=%s "
                "elapsed_s=%.3f validated=false attempts=%s",
                self.model,
                elapsed_s,
                json.dumps(attempts, ensure_ascii=True, separators=(",", ":")),
            )
            if isinstance(exc, DocumentProfileExtractionError):
                raise
            raise DocumentProfileExtractionError(
                "document profile model returned invalid structured output"
            ) from exc
        elapsed_s = perf_counter() - started_at
        self.last_trace = self._build_trace(
            messages=messages,
            trace_status="available",
            elapsed_s=elapsed_s,
            raw_content=raw_content,
            parsed_output=parsed,
            attempts=attempts,
        )
        return parsed

    def _request_document_profile(
        self,
        messages: list[dict[str, str]],
        *,
        attempts: list[dict[str, Any]],
    ) -> tuple[StructuredDocumentProfile, str]:
        request_kwargs = {
            "model": self.model,
            "temperature": 0,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_completion_tokens": _MAX_COMPLETION_TOKENS,
            **self._provider_request_options(),
        }
        last_error: Exception | None = None
        last_raw_content = ""
        for attempt in range(2):
            attempt_messages = [*messages]
            if attempt:
                if last_raw_content:
                    attempt_messages.append(
                        {
                            "role": "assistant",
                            "content": last_raw_content[:_REPAIR_OUTPUT_CHARS],
                        }
                    )
                attempt_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Previous output was invalid. Return only the smallest valid "
                            "JSON object matching the schema. Do not explain, repeat the "
                            "prompt, or include markdown. Correct these validation errors: "
                            f"{str(last_error or 'invalid structured output')[:1000]}"
                        ),
                    }
                )
                logger.warning(
                    "Retrying document profile JSON response model=%s",
                    self.model,
                )
            attempt_kwargs = dict(request_kwargs)
            attempt_kwargs["messages"] = attempt_messages
            raw_content = ""
            finish_reason: str | None = None
            try:
                try:
                    completion = self.client.chat.completions.create(**attempt_kwargs)
                except Exception as exc:
                    record_llm_completion(
                        getattr(exc, "completion", None),
                        requested_model=self.model,
                    )
                    raise
                record_llm_completion(completion, requested_model=self.model)
                choice = completion.choices[0] if completion.choices else None
                finish_reason = (
                    str(getattr(choice, "finish_reason", "") or "").strip() or None
                )
                raw_content = coerce_message_content(
                    choice.message.content
                    if choice is not None
                    else None
                )
                last_raw_content = raw_content
                if not raw_content:
                    raise RuntimeError(
                        "structured extraction returned empty response content"
                    )
                parsed = StructuredDocumentProfile.model_validate(
                    load_json_payload(extract_json_object(raw_content))
                )
                attempts.append(
                    self._build_attempt_trace(
                        attempt=attempt + 1,
                        finish_reason=finish_reason,
                        raw_content=raw_content,
                    )
                )
                return parsed, raw_content
            except (
                RuntimeError,
                ValueError,
                ValidationError,
                json.JSONDecodeError,
            ) as error:
                attempts.append(
                    self._build_attempt_trace(
                        attempt=attempt + 1,
                        finish_reason=finish_reason,
                        raw_content=raw_content,
                        error=error,
                    )
                )
                last_error = error
                if attempt == 0:
                    continue
                raise
        raise RuntimeError("structured extraction failed after retry") from last_error

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
            trace["error"] = trace_text(str(error), 1000)
        return trace

    @staticmethod
    def _build_messages(
        system_prompt: str,
        user_prompt: str,
    ) -> list[dict[str, str]]:
        schema = json.dumps(
            StructuredDocumentProfile.model_json_schema(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"{user_prompt}\n\n"
                    "Return exactly one JSON object that matches this schema. "
                    "Do not include markdown fences or commentary.\n"
                    f"JSON schema:\n{schema}"
                ),
            },
        ]

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
        trace = self.last_trace
        self.last_trace = None
        return dict(trace) if trace else None

    def _build_trace(
        self,
        *,
        messages: list[dict[str, str]],
        trace_status: str,
        elapsed_s: float,
        raw_content: str | None = None,
        parsed_output: StructuredDocumentProfile | None = None,
        error: str | None = None,
        attempts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "task_type": "document_profile",
            "prompt_version": DOCUMENT_PROFILE_PROMPT_VERSION,
            "model": self.model,
            "extraction_mode": "json_text",
            "trace_status": trace_status,
            "elapsed_s": round(elapsed_s, 6),
            "messages": [
                {
                    "role": trace_text(message.get("role")),
                    "content": trace_text(message.get("content")),
                }
                for message in messages
            ],
            "raw_output": trace_text(raw_content),
            "parsed_output": trace_json(parsed_output),
            "error": trace_text(error, 1000),
            "attempts": [dict(attempt) for attempt in attempts or ()],
        }

    @staticmethod
    def _resolve_extraction_mode(extraction_mode: str | None) -> str:
        candidate = extraction_mode or os.getenv(
            "CORE_LLM_EXTRACTION_MODE",
            _DEFAULT_EXTRACTION_MODE,
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


def build_default_document_profile_extractor() -> DocumentProfileExtractor:
    return DocumentProfileExtractor()
