from __future__ import annotations

import json
import logging
import os
from time import perf_counter
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
import tiktoken

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
_TABLE_MATRIX_REPAIR_PROVIDER_MAX_COMPLETION_TOKENS = 4096

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class TableMatrixRepairItemModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    row_index: int | None = None
    column: str | None = None
    before: str | None = None
    after: str | None = None
    reason: str | None = None


class TableMatrixRepairModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    repaired_table_matrix: list[list[str]] = Field(default_factory=list)
    repairs: list[TableMatrixRepairItemModelOutput] = Field(default_factory=list)
    confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)

    @field_validator("repaired_table_matrix", "repairs", "warnings", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> object:
        return [] if value is None else value

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_default_confidence(cls, value: object) -> object:
        return 0.0 if value is None else value


PAPER_FACT_TABLE_MATRIX_REPAIR_PROMPT_VERSION = "paper_fact_table_matrix_repair.v5"

_TABLE_MATRIX_REPAIR_SYSTEM_PROMPT = """
You are repairing parsed table structure for a materials-literature backend.

Non-negotiable rules:
- This is table repair only, not fact extraction.
- Return exactly one JSON object and nothing else.
- Use only the provided table source; do not use outside knowledge.
- Preserve the table's row order, column order, numeric values, units, and headers.
- Repair fragmented cells, dangling parentheses/brackets, and row-label spillover only when supported by nearby table cells.
- If repair is uncertain, preserve the original cell and add a warning.
""".strip()


def build_table_matrix_repair_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    model_payload = {
        "table_role": payload.get("table_role"),
        "repair_focus": list(payload.get("repair_focus") or ()),
        "source": {
            key: source[key]
            for key in (
                "caption_text",
                "heading_path",
                "column_headers",
                "table_markdown",
                "table_visual_text",
            )
            if source.get(key) not in (None, "", [], {})
        },
    }
    user_prompt = (
        "Repair this parsed table matrix before objective evidence extraction.\n\n"
        f"Input JSON:\n{json.dumps(model_payload, ensure_ascii=False, indent=2)}\n\n"
        "Return only schema-valid structured data with `repaired_table_matrix`, "
        "`repairs`, `confidence`, and `warnings`.\n"
        "Repair structure only. Do not extract measurements, comparisons, or "
        "interpretations.\n"
        "Read the complete continuous table or table slice from "
        "`source.table_markdown`. Its first row is the canonical flattened header "
        "from `source.column_headers`; caption and heading context apply to every "
        "row in the slice.\n"
        "`source.table_visual_text` is an additional clipped view of the same "
        "PDF table region. Use it to resolve visual line wrapping, but never "
        "change a value that is not present in either supplied table view.\n"
        "`repaired_table_matrix` must contain that header followed by every logical "
        "data row in the Markdown, in the same order and with the same logical "
        "columns. Do not add, reorder, summarize, or truncate logical data rows. "
        "A final row containing only a carried specimen-label fragment and a "
        "carried uncertainty fragment may be merged into the preceding logical row "
        "and omitted; record that merge in `repairs`.\n"
        "For a mean-plus-uncertainty result column, preserve the complete numeric "
        "sequence from top to bottom. A leading uncertainty fragment before a new "
        "mean belongs to the preceding unresolved mean; the new mean receives the "
        "next uncertainty fragment in that column. Never duplicate one uncertainty "
        "to fill another row.\n"
        "Nearby complete rows may support joining a cell fragment with an adjacent "
        "fragment from the same table. Preserve every label token that is present "
        "in the supplied table and do not invent specimen names, process labels, "
        "or numeric levels. A token may move into its structurally repaired cell "
        "only when the token already occurs in the supplied table slice.\n"
        "Record each changed cell in `repairs` with its Markdown-local row_index "
        "(header is row 0), column, before, after, and reason. If no confident "
        "repair is possible, return the Markdown matrix unchanged and explain the "
        "uncertainty in `warnings`."
    )
    return _TABLE_MATRIX_REPAIR_SYSTEM_PROMPT, user_prompt


class PaperFactsExtractor:
    """Repair table structure before Objective evidence extraction."""

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
        self.reasoning_effort = (
            os.getenv("LLM_REASONING_EFFORT", "").strip() or None
        )
        self.last_trace: dict[str, Any] | None = None
        self.client = client or OpenAI(
            api_key=(api_key or os.getenv("LLM_API_KEY", "").strip() or "not-needed"),
            base_url=(base_url or os.getenv("LLM_BASE_URL", "").strip() or None),
        )

    def repair_table_matrix(
        self,
        payload: dict[str, Any],
    ) -> TableMatrixRepairModelOutput:
        system_prompt, user_prompt = build_table_matrix_repair_prompt(payload)
        return self._extract(
            task_type="paper_fact_table_matrix_repair",
            prompt_version=PAPER_FACT_TABLE_MATRIX_REPAIR_PROMPT_VERSION,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=TableMatrixRepairModelOutput,
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
            TableMatrixRepairModelOutput,
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
                return response_model.model_validate(payload), raw_content
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
        # Core extraction needs compact schema output; provider thinking is
        # intentionally disabled and is not a runtime configuration option.
        options: dict[str, Any] = {
            "extra_body": {
                "chat_template_kwargs": {"enable_thinking": False}
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
