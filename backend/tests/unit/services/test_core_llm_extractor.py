from __future__ import annotations

from types import SimpleNamespace

from application.core.semantic_build.llm.extractor import CoreLLMStructuredExtractor
from application.core.semantic_build.llm.schemas import StructuredExtractionBundle


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):  # noqa: ANN003, ARG002
        self.calls.append(kwargs)
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


class _FakeBetaCompletions:
    def __init__(self, parsed: object) -> None:
        self._parsed = parsed
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs):  # noqa: ANN003, ARG002
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(parsed=self._parsed, content=None),
                )
            ]
        )


class _FakeBetaChat:
    def __init__(self, parsed: object) -> None:
        self.completions = _FakeBetaCompletions(parsed)


class _FakeBeta:
    def __init__(self, parsed: object) -> None:
        self.chat = _FakeBetaChat(parsed)


class _FakeOpenAIClient:
    def __init__(self, content: str, *, parsed: object | None = None) -> None:
        self.chat = _FakeChat(content)
        self.beta = _FakeBeta(parsed)


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
    assert len(client.chat.completions.calls) == 1
    assert client.beta.chat.completions.calls == []
    assert "JSON schema:" in client.chat.completions.calls[0]["messages"][1]["content"]


def test_core_llm_extractor_uses_provider_parse_mode(monkeypatch):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    parsed_bundle = StructuredExtractionBundle()
    client = _FakeOpenAIClient("unused", parsed=parsed_bundle)
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    bundle = extractor.extract_text_window_bundle(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental", "protocol_extractable": "yes"},
            "text_window": {"text": "Laser power was 200 W.", "heading_path": "Methods"},
        }
    )

    assert bundle == parsed_bundle
    assert client.chat.completions.calls == []
    assert len(client.beta.chat.completions.calls) == 1
    parse_call = client.beta.chat.completions.calls[0]
    assert parse_call["response_format"] is StructuredExtractionBundle
    assert "JSON schema:" in parse_call["messages"][1]["content"]


def test_core_llm_extractor_falls_back_to_json_text_for_invalid_mode(monkeypatch, caplog):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "not-a-mode")

    with caplog.at_level("WARNING"):
        extractor = CoreLLMStructuredExtractor(client=_FakeOpenAIClient("{}"), model="fake-model")

    assert extractor.extraction_mode == "json_text"
    assert "Invalid CORE_LLM_EXTRACTION_MODE=not-a-mode" in caplog.text
