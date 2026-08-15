from __future__ import annotations

import json
import logging
import os
from time import perf_counter
from typing import Any

from openai import OpenAI
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
        started_at = perf_counter()
        try:
            parsed, raw_content = self._request_document_profile(messages)
        except Exception:
            elapsed_s = perf_counter() - started_at
            self.last_trace = self._build_trace(
                messages=messages,
                trace_status="failed",
                elapsed_s=elapsed_s,
                error="structured extraction failed",
            )
            logger.exception(
                "Document profile extraction failed mode=json_text model=%s "
                "elapsed_s=%.3f validated=false",
                self.model,
                elapsed_s,
            )
            raise
        elapsed_s = perf_counter() - started_at
        self.last_trace = self._build_trace(
            messages=messages,
            trace_status="available",
            elapsed_s=elapsed_s,
            raw_content=raw_content,
            parsed_output=parsed,
        )
        return parsed

    def _request_document_profile(
        self,
        messages: list[dict[str, str]],
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
        for attempt in range(2):
            attempt_messages = [*messages]
            if attempt:
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
                raw_content = coerce_message_content(
                    completion.choices[0].message.content
                    if completion.choices
                    else None
                )
                if not raw_content:
                    raise RuntimeError(
                        "structured extraction returned empty response content"
                    )
                parsed = StructuredDocumentProfile.model_validate(
                    load_json_payload(extract_json_object(raw_content))
                )
                return parsed, raw_content
            except (
                RuntimeError,
                ValueError,
                ValidationError,
                json.JSONDecodeError,
            ) as error:
                last_error = error
                if attempt == 0:
                    continue
                raise
        raise RuntimeError("structured extraction failed after retry") from last_error

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
        if self.enable_thinking:
            return {}
        return {
            "extra_body": {
                "chat_template_kwargs": {
                    "enable_thinking": False,
                }
            }
        }

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
