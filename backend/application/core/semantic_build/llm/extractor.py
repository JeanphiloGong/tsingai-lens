from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from .schemas import (
    StructuredDocumentProfile,
    StructuredExtractionBundle,
)
from .prompts import (
    build_document_profile_prompt,
    build_text_window_extraction_prompt,
    build_table_row_extraction_prompt,
)

logger = logging.getLogger(__name__)

_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


class CoreLLMStructuredExtractor:
    """Core-owned LLM structured extraction entrypoint."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model = (model or os.getenv("LLM_MODEL", "gpt-4o-mini")).strip() or "gpt-4o-mini"
        self.client = client or OpenAI(
            api_key=(api_key or os.getenv("LLM_API_KEY", "").strip() or "not-needed"),
            base_url=(base_url or os.getenv("LLM_BASE_URL", "").strip() or None),
        )

    def extract_document_profile(self, payload: dict[str, Any]) -> StructuredDocumentProfile:
        system_prompt, user_prompt = build_document_profile_prompt(payload)
        response = self._parse_json_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredDocumentProfile,
        )
        if not isinstance(response, StructuredDocumentProfile):
            raise TypeError("unexpected document profile response type")
        return response

    def extract_text_window_bundle(self, payload: dict[str, Any]) -> StructuredExtractionBundle:
        system_prompt, user_prompt = build_text_window_extraction_prompt(payload)
        response = self._parse_json_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredExtractionBundle,
        )
        if not isinstance(response, StructuredExtractionBundle):
            raise TypeError("unexpected text window extraction response type")
        return response

    def extract_table_row_bundle(self, payload: dict[str, Any]) -> StructuredExtractionBundle:
        system_prompt, user_prompt = build_table_row_extraction_prompt(payload)
        response = self._parse_json_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredExtractionBundle,
        )
        if not isinstance(response, StructuredExtractionBundle):
            raise TypeError("unexpected table row extraction response type")
        return response

    def _parse_json_response(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
        schema = json.dumps(
            response_model.model_json_schema(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        completion = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
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
            ],
        )
        raw_content = self._coerce_message_content(
            completion.choices[0].message.content if completion.choices else None
        )
        if not raw_content:
            raise RuntimeError("structured extraction returned empty response content")
        try:
            return response_model.model_validate_json(self._extract_json_object(raw_content))
        except Exception:
            logger.exception(
                "Core LLM JSON validation failed model=%s response_model=%s raw_response=%s",
                self.model,
                response_model.__name__,
                raw_content[:2000],
            )
            raise

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
