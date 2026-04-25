from __future__ import annotations

from types import SimpleNamespace

from application.core.semantic_build.llm.extractor import CoreLLMStructuredExtractor
from application.core.semantic_build.llm.schemas import (
    StructuredExtractionBundle,
    StructuredTextWindowMentions,
)


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
          "method_mentions": [],
          "material_mentions": [],
          "variant_mentions": [],
          "condition_mentions": [],
          "baseline_mentions": [],
          "result_claims": []
        }
        ```"""
    )
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    mentions = extractor.extract_text_window_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental", "protocol_extractable": "yes"},
            "text_window": {"text": "Laser power was 200 W.", "heading_path": "Methods"},
        }
    )

    assert isinstance(mentions, StructuredTextWindowMentions)
    assert mentions.result_claims == []
    assert len(client.chat.completions.calls) == 1
    assert client.beta.chat.completions.calls == []
    assert "JSON schema:" in client.chat.completions.calls[0]["messages"][1]["content"]


def test_core_llm_extractor_uses_provider_parse_mode(monkeypatch):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    parsed_mentions = StructuredTextWindowMentions()
    client = _FakeOpenAIClient("unused", parsed=parsed_mentions)
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    mentions = extractor.extract_text_window_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental", "protocol_extractable": "yes"},
            "text_window": {"text": "Laser power was 200 W.", "heading_path": "Methods"},
        }
    )

    assert mentions == parsed_mentions
    assert client.chat.completions.calls == []
    assert len(client.beta.chat.completions.calls) == 1
    parse_call = client.beta.chat.completions.calls[0]
    assert parse_call["response_format"] is StructuredTextWindowMentions
    assert "JSON schema:" in parse_call["messages"][1]["content"]


def test_core_llm_extractor_sanitizes_json_text_and_coerces_text_window_enums():
    client = _FakeOpenAIClient(
        """
        {
          "method_mentions": [
            {
              "method_role": "simulation",
              "method_name": "finite element model",
              "details": null,
              "evidence_quote": "finite element model",
              "confidence": 0.82
            },
          ],
          "material_mentions": [],
          "variant_mentions": [],
          "condition_mentions": [
            {
              "condition_type": "heating",
              "condition_text": "with in situ heating",
              "normalized_value": null,
              "unit": null,
              "evidence_quote": "with in situ heating",
              "confidence": 0.8
            },
          ],
          "baseline_mentions": [
            {
              "baseline_label": "as-built sample",
              "baseline_type": "as built",
              "evidence_quote": "as-built sample",
              "confidence": 0.76
            }
          ],
          "result_claims": [
            {
              "claim_text": "Prior work reported lower residual stress.",
              "property_normalized": "residual stress",
              "result_type": "trend",
              "value_text": null,
              "unit": null,
              "claim_scope": "prior work",
              "eligible_for_measurement_result": false,
              "evidence_quote": "Prior work reported lower residual stress.",
              "confidence": 0.74
            },
          ],
        }
        """
    )
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    mentions = extractor.extract_text_window_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental", "protocol_extractable": "yes"},
            "text_window": {
                "text": "Prior work reported lower residual stress with in situ heating.",
                "heading_path": "Introduction",
            },
        }
    )

    assert mentions.method_mentions[0].method_role == "other"
    assert mentions.condition_mentions[0].condition_type == "other"
    assert mentions.baseline_mentions[0].baseline_type == "as-built"
    assert mentions.result_claims[0].claim_scope == "prior_work"


def test_core_llm_extractor_caps_provider_parse_completion_tokens_for_table_rows(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    client = _FakeOpenAIClient("unused", parsed=StructuredExtractionBundle())
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    bundle = extractor.extract_table_row_bundle(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental", "protocol_extractable": "yes"},
            "table_row": {"row_summary": "Sample A | 560 MPa", "cells": []},
            "supporting_text_windows": [],
        }
    )

    assert bundle == StructuredExtractionBundle()
    parse_call = client.beta.chat.completions.calls[0]
    assert parse_call["response_format"] is StructuredExtractionBundle
    assert parse_call["max_completion_tokens"] == 4096


def test_core_llm_extractor_coerces_null_nested_table_row_fields():
    client = _FakeOpenAIClient(
        """
        {
          "method_facts": [],
          "sample_variants": [],
          "test_conditions": [
            {
              "property_type": "hardness",
              "condition_payload": {
                "method": null,
                "methods": null,
                "temperatures_c": null,
                "durations": null,
                "atmosphere": null
              },
              "confidence": 0.78,
              "epistemic_status": "normalized_from_evidence"
            }
          ],
          "baseline_references": [],
          "measurement_results": [
            {
              "claim_text": "Hardness reached 210 HV.",
              "property_normalized": "hardness",
              "result_type": "scalar",
              "value_payload": null,
              "unit": "HV",
              "variant_label": null,
              "baseline_label": null,
              "anchors": null,
              "claim_scope": "current work",
              "confidence": 0.81
            }
          ]
        }
        """
    )
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    bundle = extractor.extract_table_row_bundle(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental", "protocol_extractable": "yes"},
            "table_row": {"row_summary": "Sample A | 210 HV", "cells": []},
            "supporting_text_windows": [],
        }
    )

    assert bundle.test_conditions[0].condition_payload.methods == []
    assert bundle.test_conditions[0].condition_payload.temperatures_c == []
    assert bundle.test_conditions[0].condition_payload.durations == []
    assert bundle.measurement_results[0].value_payload.value is None
    assert bundle.measurement_results[0].anchors == []
    assert bundle.measurement_results[0].claim_scope == "current_work"


def test_core_llm_extractor_falls_back_to_json_text_for_invalid_mode(monkeypatch, caplog):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "not-a-mode")

    with caplog.at_level("WARNING"):
        extractor = CoreLLMStructuredExtractor(client=_FakeOpenAIClient("{}"), model="fake-model")

    assert extractor.extraction_mode == "json_text"
    assert "Invalid CORE_LLM_EXTRACTION_MODE=not-a-mode" in caplog.text
