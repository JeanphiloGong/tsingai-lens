from __future__ import annotations

import os
from typing import Type

from openai import OpenAI
from pydantic import BaseModel


class OpenAIStructuredClient:
    """Minimal OpenAI-compatible structured parsing client."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or None,
        )

    def parse(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[BaseModel],
    ) -> BaseModel:
        completion = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=response_model,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError("structured extraction returned no parsed payload")
        return parsed


def build_openai_structured_client() -> OpenAIStructuredClient:
    model = os.getenv("LLM_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    api_key = os.getenv("LLM_API_KEY", "").strip() or "not-needed"
    base_url = os.getenv("LLM_BASE_URL", "").strip() or None
    return OpenAIStructuredClient(
        model=model,
        api_key=api_key,
        base_url=base_url,
    )
