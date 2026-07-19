from __future__ import annotations

import json
import logging
import os
import re
from time import perf_counter
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from .schemas import (
    StructuredAxisCanonicalizationPlan,
    StructuredDocumentProfile,
    StructuredObjectiveEvidenceRoutes,
    StructuredObjectiveEvidenceUnits,
    StructuredObjectiveMergePlan,
    StructuredObjectivePaperFrame,
    StructuredPaperSkim,
    StructuredResearchUnderstandingRelations,
    StructuredResearchUnderstandingFindings,
    StructuredResearchObjectives,
    StructuredTableBatchMentions,
    StructuredTableMatrixRepair,
    StructuredTextWindowMentions,
)
from .prompts import (
    RESEARCH_UNDERSTANDING_RELATION_PROMPT_VERSION,
    RESEARCH_UNDERSTANDING_FINDING_SYNTHESIS_PROMPT_VERSION,
    build_document_profile_prompt,
    build_objective_evidence_unit_prompt,
    build_objective_evidence_route_prompt,
    build_objective_paper_frame_prompt,
    build_paper_skim_prompt,
    build_research_axis_canonicalization_prompt,
    build_research_objective_discovery_prompt,
    build_research_objective_merge_prompt,
    build_research_understanding_relation_prompt,
    build_research_understanding_finding_synthesis_prompt,
    build_table_batch_mentions_prompt,
    build_table_matrix_repair_prompt,
    build_text_window_extraction_prompt,
)

logger = logging.getLogger(__name__)

_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_EXTRACTION_MODE_JSON_TEXT = "json_text"
_EXTRACTION_MODE_PROVIDER_PARSE = "provider_parse"
_DEFAULT_EXTRACTION_MODE = _EXTRACTION_MODE_PROVIDER_PARSE
_TABLE_BATCH_PROVIDER_PARSE_MAX_COMPLETION_TOKENS = 4096
_TRACE_TEXT_LIMIT = 8000
_TRACE_JSON_LIMIT = 12000
_SUPPORTED_EXTRACTION_MODES = {
    _EXTRACTION_MODE_JSON_TEXT,
    _EXTRACTION_MODE_PROVIDER_PARSE,
}


class CoreLLMStructuredExtractor:
    """Core-owned LLM structured extraction entrypoint."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        extraction_mode: str | None = None,
    ) -> None:
        self.model = (model or os.getenv("LLM_MODEL", "gpt-4o-mini")).strip() or "gpt-4o-mini"
        self.extraction_mode = self._resolve_extraction_mode(extraction_mode)
        self.last_trace: dict[str, Any] | None = None
        self.client = client or OpenAI(
            api_key=(api_key or os.getenv("LLM_API_KEY", "").strip() or "not-needed"),
            base_url=(base_url or os.getenv("LLM_BASE_URL", "").strip() or None),
        )

    def extract_document_profile(self, payload: dict[str, Any]) -> StructuredDocumentProfile:
        system_prompt, user_prompt = build_document_profile_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredDocumentProfile,
        )
        if not isinstance(response, StructuredDocumentProfile):
            raise TypeError("unexpected document profile response type")
        return response

    def extract_text_window_mentions(self, payload: dict[str, Any]) -> StructuredTextWindowMentions:
        system_prompt, user_prompt = build_text_window_extraction_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredTextWindowMentions,
        )
        if not isinstance(response, StructuredTextWindowMentions):
            raise TypeError("unexpected text window extraction response type")
        return response

    def extract_table_batch_mentions(self, payload: dict[str, Any]) -> StructuredTableBatchMentions:
        system_prompt, user_prompt = build_table_batch_mentions_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredTableBatchMentions,
        )
        if not isinstance(response, StructuredTableBatchMentions):
            raise TypeError("unexpected table batch extraction response type")
        return response

    def repair_table_matrix(
        self,
        payload: dict[str, Any],
    ) -> StructuredTableMatrixRepair:
        system_prompt, user_prompt = build_table_matrix_repair_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredTableMatrixRepair,
        )
        if not isinstance(response, StructuredTableMatrixRepair):
            raise TypeError("unexpected table matrix repair response type")
        return response

    def extract_paper_skim(self, payload: dict[str, Any]) -> StructuredPaperSkim:
        system_prompt, user_prompt = build_paper_skim_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredPaperSkim,
        )
        if not isinstance(response, StructuredPaperSkim):
            raise TypeError("unexpected paper skim response type")
        return response

    def discover_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchObjectives:
        system_prompt, user_prompt = build_research_objective_discovery_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredResearchObjectives,
        )
        if not isinstance(response, StructuredResearchObjectives):
            raise TypeError("unexpected research objective response type")
        return response

    def merge_research_objectives(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveMergePlan:
        system_prompt, user_prompt = build_research_objective_merge_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredObjectiveMergePlan,
        )
        if not isinstance(response, StructuredObjectiveMergePlan):
            raise TypeError("unexpected research objective merge response type")
        return response

    def canonicalize_research_objective_axes(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        system_prompt, user_prompt = build_research_axis_canonicalization_prompt(
            payload
        )
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredAxisCanonicalizationPlan,
        )
        if not isinstance(response, StructuredAxisCanonicalizationPlan):
            raise TypeError("unexpected research axis canonicalization response type")
        return response

    def frame_objective_paper(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectivePaperFrame:
        system_prompt, user_prompt = build_objective_paper_frame_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredObjectivePaperFrame,
        )
        if not isinstance(response, StructuredObjectivePaperFrame):
            raise TypeError("unexpected objective paper frame response type")
        return response

    def route_objective_evidence(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveEvidenceRoutes:
        if not isinstance(payload.get("current_source"), dict):
            raise ValueError("objective evidence routing requires current_source")
        system_prompt, user_prompt = build_objective_evidence_route_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredObjectiveEvidenceRoutes,
        )
        if not isinstance(response, StructuredObjectiveEvidenceRoutes):
            raise TypeError("unexpected objective evidence route response type")
        return response

    def extract_objective_evidence_units(
        self,
        payload: dict[str, Any],
    ) -> StructuredObjectiveEvidenceUnits:
        system_prompt, user_prompt = build_objective_evidence_unit_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredObjectiveEvidenceUnits,
        )
        if not isinstance(response, StructuredObjectiveEvidenceUnits):
            raise TypeError("unexpected objective evidence unit response type")
        return response

    def extract_research_understanding_relations(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchUnderstandingRelations:
        system_prompt, user_prompt = build_research_understanding_relation_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredResearchUnderstandingRelations,
            task_type="research_understanding_relation",
            prompt_version=RESEARCH_UNDERSTANDING_RELATION_PROMPT_VERSION,
        )
        if not isinstance(response, StructuredResearchUnderstandingRelations):
            raise TypeError("unexpected research understanding relations response type")
        return response

    def synthesize_research_understanding_findings(
        self,
        payload: dict[str, Any],
    ) -> StructuredResearchUnderstandingFindings:
        system_prompt, user_prompt = (
            build_research_understanding_finding_synthesis_prompt(payload)
        )
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredResearchUnderstandingFindings,
            task_type="research_understanding_finding_synthesis",
            prompt_version=RESEARCH_UNDERSTANDING_FINDING_SYNTHESIS_PROMPT_VERSION,
        )
        if not isinstance(response, StructuredResearchUnderstandingFindings):
            raise TypeError("unexpected research understanding Findings response type")
        return response

    def _parse_structured_response(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        task_type: str | None = None,
        prompt_version: str | None = None,
    ) -> BaseModel:
        messages = self._build_messages(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=response_model,
            include_schema=self.extraction_mode != _EXTRACTION_MODE_PROVIDER_PARSE,
        )
        self.last_trace = None
        started_at = perf_counter()
        trace_extraction_mode = self.extraction_mode
        try:
            if self.extraction_mode == _EXTRACTION_MODE_PROVIDER_PARSE:
                try:
                    parsed, raw_content = self._parse_provider_structured_response(
                        messages=messages,
                        response_model=response_model,
                    )
                except Exception:
                    logger.warning(
                        "Core LLM provider parse failed; retrying with json_text "
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
                    parsed, raw_content = self._parse_json_text_response(
                        messages=messages,
                        response_model=response_model,
                    )
                    trace_extraction_mode = (
                        f"{_EXTRACTION_MODE_PROVIDER_PARSE}->{_EXTRACTION_MODE_JSON_TEXT}"
                    )
            else:
                parsed, raw_content = self._parse_json_text_response(
                    messages=messages,
                    response_model=response_model,
                )
                if self.extraction_mode == _EXTRACTION_MODE_PROVIDER_PARSE:
                    trace_extraction_mode = (
                        f"{_EXTRACTION_MODE_PROVIDER_PARSE}->{_EXTRACTION_MODE_JSON_TEXT}"
                    )
        except Exception:
            elapsed_s = perf_counter() - started_at
            self.last_trace = self._build_trace(
                task_type=task_type,
                prompt_version=prompt_version,
                response_model=response_model,
                messages=messages,
                extraction_mode=trace_extraction_mode,
                trace_status="failed",
                elapsed_s=elapsed_s,
                error="structured extraction failed",
            )
            logger.exception(
                "Core LLM extraction failed mode=%s model=%s "
                "response_model=%s elapsed_s=%.3f validated=false",
                self.extraction_mode,
                self.model,
                response_model.__name__,
                elapsed_s,
            )
            raise
        elapsed_s = perf_counter() - started_at
        self.last_trace = self._build_trace(
            task_type=task_type,
            prompt_version=prompt_version,
            response_model=response_model,
            messages=messages,
            extraction_mode=trace_extraction_mode,
            trace_status="available",
            elapsed_s=elapsed_s,
            raw_content=raw_content,
            parsed_output=parsed,
        )
        logger.debug(
            "Core LLM extraction finished mode=%s model=%s "
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

    def _parse_json_text_response(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
    ) -> tuple[BaseModel, str | None]:
        completion = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=messages,
        )
        raw_content = self._coerce_message_content(
            completion.choices[0].message.content if completion.choices else None
        )
        if not raw_content:
            raise RuntimeError("structured extraction returned empty response content")
        payload = self._load_json_payload(self._extract_json_object(raw_content))
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
                    return response_model.model_validate(filtered_payload), raw_content
            raise

    def _parse_provider_structured_response(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
    ) -> tuple[BaseModel, str | None]:
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": messages,
            "response_format": response_model,
        }
        if response_model is StructuredTableBatchMentions:
            request_kwargs["max_completion_tokens"] = (
                _TABLE_BATCH_PROVIDER_PARSE_MAX_COMPLETION_TOKENS
            )
        completion = self.client.beta.chat.completions.parse(**request_kwargs)
        if not completion.choices:
            raise RuntimeError("structured extraction returned no completion choices")
        message = completion.choices[0].message
        parsed = getattr(message, "parsed", None)
        if parsed is None:
            raw_content = self._coerce_message_content(getattr(message, "content", None))
            raise RuntimeError(
                "structured extraction returned no parsed response content"
                + (f": {raw_content[:500]}" if raw_content else "")
            )
        raw_content = self._coerce_message_content(getattr(message, "content", None))
        if isinstance(parsed, response_model):
            return parsed, raw_content
        return response_model.model_validate(parsed), raw_content

    def consume_last_trace(self) -> dict[str, Any] | None:
        trace = self.last_trace
        self.last_trace = None
        return dict(trace) if trace else None

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
                    "role": _trace_text(message.get("role")),
                    "content": _trace_text(message.get("content"), _TRACE_TEXT_LIMIT),
                }
                for message in messages
            ],
            "raw_output": _trace_text(raw_content, _TRACE_TEXT_LIMIT),
            "parsed_output": _trace_json(
                parsed_output.model_dump(mode="json") if parsed_output else None
            ),
            "error": _trace_text(error, 1000),
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

    def _coerce_message_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if not isinstance(content, list):
            return str(content or "").strip()

        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                text = item
            else:
                text = getattr(item, "text", None)
                if text is None and isinstance(item, dict):
                    text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return "\n".join(parts).strip()

    def _extract_json_object(self, response_text: str) -> str:
        text = str(response_text or "").strip()
        if not text:
            raise RuntimeError("structured extraction returned empty JSON text")

        fenced_match = _JSON_FENCE_PATTERN.search(text)
        if fenced_match is not None:
            return fenced_match.group(1).strip()

        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise RuntimeError("structured extraction returned no JSON object")
        return text[start : end + 1]

    def _load_json_payload(self, response_text: str) -> Any:
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as error:
            sanitized = self._strip_trailing_commas(response_text)
            if sanitized == response_text:
                raise
            try:
                return json.loads(sanitized)
            except json.JSONDecodeError:
                raise error

    def _strip_trailing_commas(self, response_text: str) -> str:
        result: list[str] = []
        in_string = False
        escape = False

        for char in response_text:
            if in_string:
                result.append(char)
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                result.append(char)
                continue

            if char in "}]":
                last_non_whitespace = len(result) - 1
                while last_non_whitespace >= 0 and result[last_non_whitespace].isspace():
                    last_non_whitespace -= 1
                if last_non_whitespace >= 0 and result[last_non_whitespace] == ",":
                    del result[last_non_whitespace]
                result.append(char)
                continue

            result.append(char)

        return "".join(result)


def build_default_core_llm_structured_extractor() -> CoreLLMStructuredExtractor:
    return CoreLLMStructuredExtractor()


def _trace_text(value: Any, limit: int = _TRACE_TEXT_LIMIT) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _trace_json(
    value: Any,
    limit: int = _TRACE_JSON_LIMIT,
) -> dict[str, Any] | list[Any] | str | None:
    if value is None:
        return None
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) <= limit:
        return value
    return text[:limit] + "...[truncated]"
