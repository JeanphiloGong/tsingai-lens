from __future__ import annotations

import json
import logging
import os
from time import perf_counter
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError
import tiktoken

from application.core.paper_facts.prompts import (
    PAPER_FACT_TABLE_BATCH_PROMPT_VERSION,
    PAPER_FACT_TABLE_MATRIX_REPAIR_PROMPT_VERSION,
    PAPER_FACT_TEXT_WINDOW_PROMPT_VERSION,
    build_table_batch_mentions_prompt,
    build_table_matrix_repair_prompt,
    build_text_window_extraction_prompt,
)
from application.core.paper_facts.schemas import (
    StructuredTableBatchMentions,
    StructuredTableMatrixRepair,
    StructuredTextWindowMentions,
)
from application.core.structured_extraction.json_support import (
    coerce_message_content,
    extract_json_object,
    load_json_payload,
    trace_json,
    trace_text,
)
from infra.llm.usage import record_llm_completion, record_llm_prompt_version

logger = logging.getLogger(__name__)

_JSON_TEXT = "json_text"
_PROVIDER_PARSE = "provider_parse"
_DEFAULT_EXTRACTION_MODE = _PROVIDER_PARSE
_SUPPORTED_EXTRACTION_MODES = {_JSON_TEXT, _PROVIDER_PARSE}
_TABLE_BATCH_PROVIDER_MAX_COMPLETION_TOKENS = 4096
_TABLE_MATRIX_REPAIR_PROVIDER_MAX_COMPLETION_TOKENS = 4096

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class PaperFactsExtractor:
    """Extract document-scoped paper facts through paper-fact contracts."""

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

    def extract_text_window_mentions(
        self,
        payload: dict[str, Any],
    ) -> StructuredTextWindowMentions:
        system_prompt, user_prompt = build_text_window_extraction_prompt(payload)
        return self._extract(
            task_type="paper_fact_text_window",
            prompt_version=PAPER_FACT_TEXT_WINDOW_PROMPT_VERSION,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredTextWindowMentions,
        )

    def extract_table_batch_mentions(
        self,
        payload: dict[str, Any],
    ) -> StructuredTableBatchMentions:
        system_prompt, user_prompt = build_table_batch_mentions_prompt(payload)
        return self._extract(
            task_type="paper_fact_table_batch",
            prompt_version=PAPER_FACT_TABLE_BATCH_PROMPT_VERSION,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredTableBatchMentions,
            provider_max_completion_tokens=(
                _TABLE_BATCH_PROVIDER_MAX_COMPLETION_TOKENS
            ),
        )

    def repair_table_matrix(
        self,
        payload: dict[str, Any],
    ) -> StructuredTableMatrixRepair:
        system_prompt, user_prompt = build_table_matrix_repair_prompt(payload)
        return self._extract(
            task_type="paper_fact_table_matrix_repair",
            prompt_version=PAPER_FACT_TABLE_MATRIX_REPAIR_PROMPT_VERSION,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredTableMatrixRepair,
            provider_max_completion_tokens=(
                _TABLE_MATRIX_REPAIR_PROVIDER_MAX_COMPLETION_TOKENS
            ),
        )

    def estimate_table_matrix_repair_prompt_tokens(
        self,
        payload: dict[str, Any],
    ) -> int:
        system_prompt, user_prompt = build_table_matrix_repair_prompt(payload)
        messages = self._build_messages(
            system_prompt,
            user_prompt,
            StructuredTableMatrixRepair,
            include_schema=True,
        )
        try:
            encoding = tiktoken.encoding_for_model(self.model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(
            encoding.encode(
                json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
            )
        )

    def _extract(
        self,
        *,
        task_type: str,
        prompt_version: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModel],
        provider_max_completion_tokens: int | None = None,
    ) -> ResponseModel:
        record_llm_prompt_version(task_type, prompt_version)
        messages = self._build_messages(
            system_prompt,
            user_prompt,
            response_model,
            include_schema=self.extraction_mode == _JSON_TEXT,
        )
        self.last_trace = None
        started_at = perf_counter()
        trace_mode = self.extraction_mode
        try:
            if self.extraction_mode == _PROVIDER_PARSE:
                try:
                    parsed, raw_content = self._request_provider_parsed(
                        messages,
                        response_model,
                        max_completion_tokens=provider_max_completion_tokens,
                    )
                except Exception:
                    logger.warning(
                        "Paper-fact provider parse failed; retrying with json_text "
                        "model=%s response_model=%s",
                        self.model,
                        response_model.__name__,
                        exc_info=True,
                    )
                    messages = self._build_messages(
                        system_prompt,
                        user_prompt,
                        response_model,
                        include_schema=True,
                    )
                    parsed, raw_content = self._request_json_text(
                        messages,
                        response_model,
                    )
                    trace_mode = f"{_PROVIDER_PARSE}->{_JSON_TEXT}"
            else:
                parsed, raw_content = self._request_json_text(
                    messages,
                    response_model,
                )
        except Exception:
            elapsed_s = perf_counter() - started_at
            self.last_trace = self._build_trace(
                response_model=response_model,
                task_type=task_type,
                prompt_version=prompt_version,
                messages=messages,
                extraction_mode=trace_mode,
                trace_status="failed",
                elapsed_s=elapsed_s,
                error="structured extraction failed",
            )
            logger.exception(
                "Paper-fact extraction failed mode=%s model=%s "
                "response_model=%s elapsed_s=%.3f validated=false",
                self.extraction_mode,
                self.model,
                response_model.__name__,
                elapsed_s,
            )
            raise
        elapsed_s = perf_counter() - started_at
        self.last_trace = self._build_trace(
            response_model=response_model,
            task_type=task_type,
            prompt_version=prompt_version,
            messages=messages,
            extraction_mode=trace_mode,
            trace_status="available",
            elapsed_s=elapsed_s,
            raw_content=raw_content,
            parsed_output=parsed,
        )
        return parsed

    def _request_json_text(
        self,
        messages: list[dict[str, str]],
        response_model: type[ResponseModel],
    ) -> tuple[ResponseModel, str]:
        request_kwargs = {
            "model": self.model,
            "temperature": 0,
            "messages": messages,
            "response_format": {"type": "json_object"},
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
                    "Retrying paper-fact JSON response model=%s response_model=%s",
                    self.model,
                    response_model.__name__,
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
                payload = load_json_payload(extract_json_object(raw_content))
                try:
                    return response_model.model_validate(payload), raw_content
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
                            return (
                                response_model.model_validate(filtered_payload),
                                raw_content,
                            )
                    raise
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

    def _request_provider_parsed(
        self,
        messages: list[dict[str, str]],
        response_model: type[ResponseModel],
        *,
        max_completion_tokens: int | None,
    ) -> tuple[ResponseModel, str]:
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

    @staticmethod
    def _build_messages(
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        *,
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
        response_model: type[BaseModel],
        task_type: str,
        prompt_version: str,
        messages: list[dict[str, str]],
        extraction_mode: str,
        trace_status: str,
        elapsed_s: float,
        raw_content: str | None = None,
        parsed_output: BaseModel | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "task_type": task_type,
            "prompt_version": prompt_version,
            "model": self.model,
            "response_model": response_model.__name__,
            "extraction_mode": extraction_mode,
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


def build_default_paper_facts_extractor() -> PaperFactsExtractor:
    return PaperFactsExtractor()
