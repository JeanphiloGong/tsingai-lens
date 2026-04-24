from __future__ import annotations

import json
import logging
import os
import re
from time import perf_counter
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from .schemas import (
    StructuredDocumentProfile,
    StructuredExtractionBundle,
    StructuredTextWindowMentions,
)
from .prompts import (
    build_document_profile_prompt,
    build_text_window_extraction_prompt,
    build_table_row_extraction_prompt,
)

logger = logging.getLogger(__name__)

_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_EXTRACTION_MODE_JSON_TEXT = "json_text"
_EXTRACTION_MODE_PROVIDER_PARSE = "provider_parse"
_DEFAULT_EXTRACTION_MODE = _EXTRACTION_MODE_JSON_TEXT
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

    def extract_table_row_bundle(self, payload: dict[str, Any]) -> StructuredExtractionBundle:
        system_prompt, user_prompt = build_table_row_extraction_prompt(payload)
        response = self._parse_structured_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredExtractionBundle,
        )
        if not isinstance(response, StructuredExtractionBundle):
            raise TypeError("unexpected table row extraction response type")
        return response

    def _parse_structured_response(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
        messages = self._build_messages(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=response_model,
        )
        started_at = perf_counter()
        try:
            if self.extraction_mode == _EXTRACTION_MODE_PROVIDER_PARSE:
                parsed = self._parse_provider_structured_response(
                    messages=messages,
                    response_model=response_model,
                )
            else:
                parsed = self._parse_json_text_response(
                    messages=messages,
                    response_model=response_model,
                )
        except Exception:
            elapsed_s = perf_counter() - started_at
            logger.exception(
                "Core LLM extraction failed mode=%s model=%s response_model=%s elapsed_s=%.3f validated=false",
                self.extraction_mode,
                self.model,
                response_model.__name__,
                elapsed_s,
            )
            raise
        elapsed_s = perf_counter() - started_at
        logger.info(
            "Core LLM extraction finished mode=%s model=%s response_model=%s elapsed_s=%.3f validated=true",
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
    ) -> list[dict[str, str]]:
        schema = json.dumps(
            response_model.model_json_schema(),
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

    def _parse_json_text_response(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
    ) -> BaseModel:
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
        return response_model.model_validate_json(self._extract_json_object(raw_content))

    def _parse_provider_structured_response(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
    ) -> BaseModel:
        completion = self.client.beta.chat.completions.parse(
            model=self.model,
            temperature=0,
            messages=messages,
            response_format=response_model,
        )
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
        if isinstance(parsed, response_model):
            return parsed
        return response_model.model_validate(parsed)

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


def build_default_core_llm_structured_extractor() -> CoreLLMStructuredExtractor:
    return CoreLLMStructuredExtractor()
