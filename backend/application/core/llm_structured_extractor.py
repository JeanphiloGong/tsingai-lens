from __future__ import annotations

from typing import Any

from application.core.llm_extraction_models import (
    StructuredDocumentProfile,
    StructuredExtractionBundle,
)
from application.core.llm_extraction_prompts import (
    build_document_profile_prompt,
    build_text_window_extraction_prompt,
    build_table_row_extraction_prompt,
)
from infra.llm.openai_structured_client import (
    OpenAIStructuredClient,
    build_openai_structured_client,
)


class CoreLLMStructuredExtractor:
    """Core-owned LLM structured extraction entrypoint."""

    def __init__(
        self,
        client: OpenAIStructuredClient | None = None,
    ) -> None:
        self.client = client or build_openai_structured_client()

    def extract_document_profile(self, payload: dict[str, Any]) -> StructuredDocumentProfile:
        system_prompt, user_prompt = build_document_profile_prompt(payload)
        response = self.client.parse(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredDocumentProfile,
        )
        if not isinstance(response, StructuredDocumentProfile):
            raise TypeError("unexpected document profile response type")
        return response

    def extract_text_window_bundle(self, payload: dict[str, Any]) -> StructuredExtractionBundle:
        system_prompt, user_prompt = build_text_window_extraction_prompt(payload)
        response = self.client.parse(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredExtractionBundle,
        )
        if not isinstance(response, StructuredExtractionBundle):
            raise TypeError("unexpected text window extraction response type")
        return response

    def extract_table_row_bundle(self, payload: dict[str, Any]) -> StructuredExtractionBundle:
        system_prompt, user_prompt = build_table_row_extraction_prompt(payload)
        response = self.client.parse(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredExtractionBundle,
        )
        if not isinstance(response, StructuredExtractionBundle):
            raise TypeError("unexpected table row extraction response type")
        return response


def build_default_core_llm_structured_extractor() -> CoreLLMStructuredExtractor:
    return CoreLLMStructuredExtractor()
