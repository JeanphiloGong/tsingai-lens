from __future__ import annotations

from types import SimpleNamespace

from application.core.semantic_build.llm.extractor import CoreLLMStructuredExtractor
from application.core.semantic_build.llm.schemas import StructuredExtractionBundle


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content

    def create(self, **kwargs):  # noqa: ANN003, ARG002
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self._content),
                )
            ]
        )


class _FakeChat:
    def __init__(self, content: str) -> None:
        self.completions = _FakeCompletions(content)


class _FakeOpenAIClient:
    def __init__(self, content: str) -> None:
        self.chat = _FakeChat(content)


def test_core_llm_extractor_validates_json_text_response():
    client = _FakeOpenAIClient(
        """```json
        {
          "method_facts": [],
          "sample_variants": [],
          "test_conditions": [],
          "baseline_references": [],
          "measurement_results": []
        }
        ```"""
    )
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    bundle = extractor.extract_text_window_bundle(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental", "protocol_extractable": "yes"},
            "text_window": {"text": "Laser power was 200 W.", "heading_path": "Methods"},
        }
    )

    assert isinstance(bundle, StructuredExtractionBundle)
    assert bundle.measurement_results == []
