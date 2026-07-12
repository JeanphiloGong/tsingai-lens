from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from application.core.semantic_build.llm.extractor import CoreLLMStructuredExtractor
from application.core.semantic_build.llm.prompts import (
    build_objective_evidence_unit_prompt,
)
from application.core.semantic_build.llm.schemas import (
    StructuredAxisCanonicalizationPlan,
    StructuredExtractionBundle,
    StructuredObjectiveEvidenceRoutes,
    StructuredObjectiveEvidenceUnits,
    StructuredObjectiveMergePlan,
    StructuredObjectivePaperFrame,
    StructuredPaperSkim,
    StructuredResearchObjectives,
    StructuredResearchUnderstandingRelations,
    StructuredTableBatchMentions,
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
    def __init__(self, parsed: object, *, error: Exception | None = None) -> None:
        self._parsed = parsed
        self._error = error
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs):  # noqa: ANN003, ARG002
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(parsed=self._parsed, content=None),
                )
            ]
        )


class _FakeBetaChat:
    def __init__(self, parsed: object, *, error: Exception | None = None) -> None:
        self.completions = _FakeBetaCompletions(parsed, error=error)


class _FakeBeta:
    def __init__(self, parsed: object, *, error: Exception | None = None) -> None:
        self.chat = _FakeBetaChat(parsed, error=error)


class _FakeOpenAIClient:
    def __init__(
        self,
        content: str,
        *,
        parsed: object | None = None,
        parse_error: Exception | None = None,
    ) -> None:
        self.chat = _FakeChat(content)
        self.beta = _FakeBeta(parsed, error=parse_error)


def _json_text_extractor(client: _FakeOpenAIClient) -> CoreLLMStructuredExtractor:
    return CoreLLMStructuredExtractor(
        client=client,
        model="fake-model",
        extraction_mode="json_text",
    )


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
    extractor = _json_text_extractor(client)

    mentions = extractor.extract_text_window_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental"},
            "text_window": {"text": "Laser power was 200 W.", "heading_path": "Methods"},
        }
    )

    assert isinstance(mentions, StructuredTextWindowMentions)
    assert mentions.result_claims == []
    assert len(client.chat.completions.calls) == 1
    assert client.beta.chat.completions.calls == []
    assert "JSON schema:" in client.chat.completions.calls[0]["messages"][1]["content"]


def test_core_llm_extractor_ignores_top_level_extra_json_text_fields():
    client = _FakeOpenAIClient(
        """
        {
          "method_mentions": [],
          "material_mentions": [],
          "variant_mentions": [],
          "condition_mentions": [],
          "baseline_mentions": [],
          "result_claims": [],
          "confidence": 0.9
        }
        """
    )
    extractor = _json_text_extractor(client)

    mentions = extractor.extract_text_window_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental"},
            "text_window": {"text": "Laser power was 200 W.", "heading_path": "Methods"},
        }
    )

    assert isinstance(mentions, StructuredTextWindowMentions)
    assert mentions.result_claims == []


def test_core_llm_extractor_defaults_to_provider_parse_mode(monkeypatch):
    monkeypatch.delenv("CORE_LLM_EXTRACTION_MODE", raising=False)
    parsed_mentions = StructuredTextWindowMentions()
    client = _FakeOpenAIClient("unused", parsed=parsed_mentions)
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    mentions = extractor.extract_text_window_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental"},
            "text_window": {"text": "Laser power was 200 W.", "heading_path": "Methods"},
        }
    )

    assert mentions == parsed_mentions
    assert client.chat.completions.calls == []
    assert len(client.beta.chat.completions.calls) == 1
    parse_call = client.beta.chat.completions.calls[0]
    assert parse_call["response_format"] is StructuredTextWindowMentions
    assert "JSON schema:" in parse_call["messages"][1]["content"]


def test_core_llm_extractor_captures_provider_parse_trace_for_relations():
    parsed = StructuredResearchUnderstandingRelations(relations=[])
    client = _FakeOpenAIClient("unused", parsed=parsed)
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    result = extractor.extract_research_understanding_relations(
        {
            "objective": {"question": "How does preheating affect porosity?"},
            "evidence_units": [
                {
                    "evidence_unit_id": "oeu-1",
                    "summary": "Preheating reduces porosity.",
                }
            ],
        }
    )

    assert result == parsed
    trace = extractor.consume_last_trace()
    assert trace is not None
    assert trace["task_type"] == "research_understanding_relation"
    assert trace["prompt_version"] == "research_understanding_relation.v1"
    assert trace["model"] == "fake-model"
    assert trace["trace_status"] == "available"
    assert trace["parsed_output"] == {"relations": []}
    assert trace["raw_output"] is None
    assert "api_key" not in str(trace).lower()
    assert "authorization" not in str(trace).lower()


def test_core_llm_extractor_falls_back_to_json_text_when_provider_parse_fails(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    client = _FakeOpenAIClient(
        '{"relations": []}',
        parse_error=RuntimeError("provider parse failed"),
    )
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    result = extractor.extract_research_understanding_relations(
        {
            "objective": {"question": "How does preheating affect porosity?"},
            "evidence_units": [],
        }
    )

    assert result == StructuredResearchUnderstandingRelations(relations=[])
    assert len(client.beta.chat.completions.calls) == 1
    assert len(client.chat.completions.calls) == 1
    trace = extractor.consume_last_trace()
    assert trace is not None
    assert trace["trace_status"] == "available"
    assert trace["extraction_mode"] == "provider_parse->json_text"
    assert trace["parsed_output"] == {"relations": []}


def test_core_llm_extractor_allows_explicit_json_text_mode(monkeypatch):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "json_text")
    client = _FakeOpenAIClient(
        """
        {
          "method_mentions": [],
          "material_mentions": [],
          "variant_mentions": [],
          "condition_mentions": [],
          "baseline_mentions": [],
          "result_claims": []
        }
        """
    )
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    mentions = extractor.extract_text_window_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental"},
            "text_window": {"text": "Laser power was 200 W.", "heading_path": "Methods"},
        }
    )

    assert isinstance(mentions, StructuredTextWindowMentions)
    assert len(client.chat.completions.calls) == 1
    assert client.beta.chat.completions.calls == []


def test_core_llm_extractor_validates_paper_skim_response():
    client = _FakeOpenAIClient(
        """
        {
          "doc_role": "experimental",
          "candidate_materials": ["316L stainless steel"],
          "candidate_processes": ["LPBF", "heat treatment"],
          "candidate_properties": ["corrosion"],
          "changed_variables": ["temperature"],
          "possible_objectives": [
            "How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?"
          ],
          "evidence_density": "high",
          "confidence": 0.91,
          "warnings": []
        }
        """
    )
    extractor = _json_text_extractor(client)

    skim = extractor.extract_paper_skim(
        {
            "document_id": "paper-1",
            "title": "LPBF 316L corrosion study",
            "text_preview": "LPBF 316L was heat treated.",
            "table_captions": [],
        }
    )

    assert isinstance(skim, StructuredPaperSkim)
    assert skim.doc_role == "experimental"
    assert skim.candidate_materials == ["316L stainless steel"]


def test_core_llm_extractor_validates_research_objective_response():
    client = _FakeOpenAIClient(
        """
        {
          "objectives": [
            {
              "question": "How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?",
              "material_scope": ["316L stainless steel"],
              "process_axes": ["LPBF", "heat treatment"],
              "property_axes": ["corrosion"],
              "comparison_intent": "compare as-built and heat-treated corrosion behavior",
              "seed_document_ids": ["paper-1"],
              "excluded_document_ids": [],
              "confidence": 0.88,
              "reason": "paper skims share the same comparison axis"
            }
          ]
        }
        """
    )
    extractor = _json_text_extractor(client)

    objectives = extractor.discover_research_objectives(
        {
            "collection_id": "col-1",
            "paper_skims": [],
        }
    )

    assert isinstance(objectives, StructuredResearchObjectives)
    assert objectives.objectives[0].question.startswith("How does heat treatment")


def test_core_llm_extractor_validates_axis_canonicalization_response():
    client = _FakeOpenAIClient(
        """
        {
          "axis_groups": [
            {
              "axis_type": "process",
              "canonical": "scanning strategy",
              "aliases": ["scanning strategy", "scan strategy"],
              "confidence": 0.95,
              "reason": "same process variable phrased two ways"
            }
          ]
        }
        """
    )
    extractor = _json_text_extractor(client)

    canonicalization_plan = extractor.canonicalize_research_objective_axes(
        {
            "collection_id": "col-1",
            "paper_skims": [],
            "axis_candidates": {
                "material": [],
                "process": ["scanning strategy", "scan strategy"],
                "property": [],
            },
        }
    )

    assert isinstance(canonicalization_plan, StructuredAxisCanonicalizationPlan)
    assert canonicalization_plan.axis_groups[0].canonical == "scanning strategy"


def test_core_llm_extractor_validates_research_objective_merge_response():
    client = _FakeOpenAIClient(
        """
        {
          "merged_objectives": [
            {
              "source_objective_ids": ["obj-1", "obj-2"],
              "question": "How do SLM parameters affect mechanical properties of 316L stainless steel?",
              "material_scope": ["316L stainless steel"],
              "process_axes": ["Selective Laser Melting", "energy density"],
              "property_axes": ["yield strength", "elongation"],
              "comparison_intent": "compare SLM parameter effects on mechanical properties",
              "confidence": 0.88,
              "reason": "the source objectives describe the same mechanical comparison"
            }
          ]
        }
        """
    )
    extractor = _json_text_extractor(client)

    merge_plan = extractor.merge_research_objectives(
        {
            "collection_id": "col-1",
            "paper_skims": [],
            "candidate_objectives": [],
        }
    )

    assert isinstance(merge_plan, StructuredObjectiveMergePlan)
    assert merge_plan.merged_objectives[0].source_objective_ids == ["obj-1", "obj-2"]


def test_core_llm_extractor_validates_objective_paper_frame_response():
    client = _FakeOpenAIClient(
        """
        {
          "relevance": "high",
          "paper_role": "primary_experiment",
          "background": "Direct current-work evidence for the objective.",
          "material_match": ["316L stainless steel"],
          "changed_variables": ["heat treatment"],
          "measured_property_scope": ["corrosion"],
          "test_environment_scope": ["3.5 wt.% NaCl"],
          "relevant_sections": ["Results"],
          "relevant_tables": ["table-1"],
          "excluded_tables": ["table-2"]
        }
        """
    )
    extractor = _json_text_extractor(client)

    frame = extractor.frame_objective_paper(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "paper_skim": {"document_id": "paper-1"},
            "section_snippets": [{"section_label": "Results"}],
            "table_summaries": [{"table_id": "table-1"}, {"table_id": "table-2"}],
        }
    )

    assert isinstance(frame, StructuredObjectivePaperFrame)
    assert frame.relevance == "high"
    assert frame.relevant_tables == ["table-1"]


def test_core_llm_extractor_validates_objective_evidence_routes_response():
    client = _FakeOpenAIClient(
        """
            {
              "routes": [
                {
                  "role": "current_experimental_evidence",
                  "extractable": true,
                  "confidence": 0.88
                }
              ]
            }
        """
    )
    extractor = _json_text_extractor(client)

    routes = extractor.route_objective_evidence(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "paper_frame": {"frame_id": "opf-1"},
            "current_source": {"source_kind": "table", "source_ref": "table-1"},
        }
    )

    assert isinstance(routes, StructuredObjectiveEvidenceRoutes)
    assert routes.routes[0].role == "current_experimental_evidence"
    assert "reason" not in routes.routes[0].model_dump()


def test_core_llm_extractor_rejects_legacy_objective_route_batches():
    client = _FakeOpenAIClient('{"routes": []}')
    extractor = _json_text_extractor(client)

    with pytest.raises(ValueError):
        extractor.route_objective_evidence(
            {
                "collection_id": "col-1",
                "objective": {"question": "How does heat treatment affect corrosion?"},
                "paper_frame": {"frame_id": "opf-1"},
                "source_candidates": [
                    {"source_kind": "table", "source_ref": "table-1"}
                ],
            }
        )


def test_core_llm_extractor_rejects_verbose_objective_route_objects():
    client = _FakeOpenAIClient(
        """
        {
          "routes": [
            {
              "role": "current_experimental_evidence",
              "extractable": true,
              "reason": "Target result table.",
              "table_schema": {
                "column_headers": ["sample", "corrosion current"]
              },
              "confidence": 0.88
            }
          ]
        }
        """
    )
    extractor = _json_text_extractor(client)

    with pytest.raises(ValidationError):
        extractor.route_objective_evidence(
            {
                "collection_id": "col-1",
                "objective": {"question": "How does heat treatment affect corrosion?"},
                "paper_frame": {"frame_id": "opf-1"},
                "current_source": {"source_kind": "table", "source_ref": "table-1"},
            }
        )


def test_core_llm_extractor_rejects_source_ids_in_objective_routes():
    client = _FakeOpenAIClient(
        """
        {
          "routes": [
            {
              "source_kind": "table",
              "source_ref": "table-1",
              "role": "current_experimental_evidence",
              "extractable": true,
              "reason": "Target result table.",
              "confidence": 0.88
            }
          ]
        }
        """
    )
    extractor = _json_text_extractor(client)

    with pytest.raises(ValidationError):
        extractor.route_objective_evidence(
            {
                "collection_id": "col-1",
                "objective": {"question": "How does heat treatment affect corrosion?"},
                "paper_frame": {"frame_id": "opf-1"},
                "current_source": {"source_kind": "table", "source_ref": "table-1"},
            }
        )


def test_core_llm_extractor_validates_objective_evidence_units_response():
    client = _FakeOpenAIClient(
        """
        {
          "evidence_units": [
            {
              "unit_kind": "measurement",
              "property_normalized": "corrosion current density",
              "material_system": {"family": "316L stainless steel"},
              "sample_context": {"label": "heat-treated"},
              "process_context": {"process": "LPBF"},
              "resolved_condition": {},
              "test_condition": {"environment": "NaCl"},
              "value_payload": {"value": 0.4},
              "unit": "uA/cm2",
              "baseline_context": {},
              "interpretation": null,
              "join_keys": {"sample_key": "heat-treated"},
              "resolution_status": "resolved",
              "confidence": 0.86
            }
          ]
        }
        """
    )
    extractor = _json_text_extractor(client)

    units = extractor.extract_objective_evidence_units(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "evidence_route": {
                "source_kind": "table",
                "source_ref": "table-1",
            },
            "source": {
                "source_kind": "table",
                "source_ref": "table-1",
                "table_matrix": [["sample", "corrosion"], ["HT", "0.4"]],
            },
        }
    )

    assert isinstance(units, StructuredObjectiveEvidenceUnits)
    assert units.evidence_units[0].unit_kind == "measurement"
    assert units.evidence_units[0].resolution_status == "resolved"


def test_objective_evidence_unit_prompt_limits_text_routes_to_one_unit():
    _, prompt = build_objective_evidence_unit_prompt(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does preheating affect 316L?"},
            "evidence_route": {
                "source_kind": "text_window",
                "source_ref": "block-1",
            },
            "source": {
                "source_kind": "text_window",
                "source_ref": "block-1",
                "text": (
                    "The cooling rate values were 1.43x10^6 C/s for P150, "
                    "and 1.65x10^6 C/s for NP."
                ),
            },
        }
    )

    assert "For text routes, return at most one evidence unit" in prompt
    assert "Do not enumerate every possible number" in prompt
    assert "The backend binds `source_refs` from the active route" in prompt
    assert "Do not output `source_refs`" in prompt
    assert "one evidence unit per binding" not in prompt
    assert "Do not merge those bindings into one `interpretation`" not in prompt
    assert "1.43x10^6 C/s for P150" in prompt
    assert "1.65x10^6 C/s for NP" in prompt
    assert "Bad text example" in prompt


def test_core_llm_extractor_rejects_backend_bound_objective_unit_fields():
    client = _FakeOpenAIClient(
        """
        {
          "evidence_units": [
            {
              "unit_kind": "measurement",
              "property_normalized": "yield strength",
              "value_payload": {"value": 450},
              "source_refs": [
                {"source_kind": "text_window", "source_ref": "block-1"}
              ],
              "evidence_anchor_ids": [],
              "confidence": 0.86
            }
          ]
        }
        """
    )
    extractor = _json_text_extractor(client)

    with pytest.raises(ValidationError):
        extractor.extract_objective_evidence_units(
            {
                "collection_id": "col-1",
                "objective": {"question": "How does heat treatment affect strength?"},
                "evidence_route": {
                    "source_kind": "text_window",
                    "source_ref": "block-1",
                },
                "source": {
                    "source_kind": "text_window",
                    "source_ref": "block-1",
                    "text": "Yield strength reached 450 MPa.",
                },
            }
        )


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
    extractor = _json_text_extractor(client)

    mentions = extractor.extract_text_window_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental"},
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


def test_core_llm_extractor_accepts_null_result_property_names():
    client = _FakeOpenAIClient(
        """
        {
          "method_mentions": [],
          "material_mentions": [],
          "variant_mentions": [],
          "condition_mentions": [],
          "baseline_mentions": [],
          "result_claims": [
            {
              "claim_text": "The behavior was improved.",
              "property_normalized": null,
              "result_type": "trend",
              "value_text": null,
              "unit": null,
              "claim_scope": "current_work",
              "eligible_for_measurement_result": false,
              "evidence_quote": "The behavior was improved.",
              "confidence": 0.7
            }
          ]
        }
        """
    )
    extractor = _json_text_extractor(client)

    mentions = extractor.extract_text_window_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental"},
            "text_window": {
                "text": "The behavior was improved.",
                "heading_path": "Results",
            },
        }
    )

    assert mentions.result_claims[0].property_normalized == ""


def test_core_llm_extractor_caps_provider_parse_completion_tokens_for_table_batches(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    client = _FakeOpenAIClient("unused", parsed=StructuredTableBatchMentions())
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    mentions = extractor.extract_table_batch_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental"},
            "target_rows": [{"row_index": 1, "row_summary": "Sample A | 560 MPa", "cells": []}],
            "supporting_text_windows": [],
        }
    )

    assert mentions == StructuredTableBatchMentions()
    parse_call = client.beta.chat.completions.calls[0]
    assert parse_call["response_format"] is StructuredTableBatchMentions
    assert parse_call["max_completion_tokens"] == 4096


def test_core_llm_extractor_does_not_cap_provider_parse_completion_tokens_for_objective_routes(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    client = _FakeOpenAIClient("unused", parsed=StructuredObjectiveEvidenceRoutes())
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    routes = extractor.route_objective_evidence(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "paper_frame": {"frame_id": "opf-1"},
            "current_source": {"source_kind": "text_window", "source_ref": "b1"},
        }
    )

    assert routes == StructuredObjectiveEvidenceRoutes()
    parse_call = client.beta.chat.completions.calls[0]
    assert parse_call["response_format"] is StructuredObjectiveEvidenceRoutes
    assert "max_completion_tokens" not in parse_call


def test_core_llm_extractor_does_not_cap_provider_parse_completion_tokens_for_objective_units(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    client = _FakeOpenAIClient("unused", parsed=StructuredObjectiveEvidenceUnits())
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    units = extractor.extract_objective_evidence_units(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "evidence_route": {"source_kind": "text_window", "source_ref": "b1"},
            "source": {"source_kind": "text_window", "source_ref": "b1", "text": "x"},
        }
    )

    assert units == StructuredObjectiveEvidenceUnits()
    parse_call = client.beta.chat.completions.calls[0]
    assert parse_call["response_format"] is StructuredObjectiveEvidenceUnits
    assert "max_completion_tokens" not in parse_call


def test_core_llm_extractor_validates_lightweight_table_batch_mentions():
    client = _FakeOpenAIClient(
        """
        {
          "row_results": [
            {
              "row_index": 1,
              "row_subjects": [
                {
                  "variant_label": "Sample A",
                  "family": null,
                  "composition": null,
                  "variable_axis_type": null,
                  "variable_value": null,
                  "quote": "Sample A"
                }
              ],
              "process_mentions": null,
              "test_condition_mentions": [
                {
                  "name": "test temperature",
                  "value_text": "25",
                  "unit": "C",
                  "quote": "25 C"
                }
              ],
              "baseline_mentions": [],
              "result_claims": [
                {
                  "property_normalized": "hardness",
                  "result_type": "scalar",
                  "value_text": "210",
                  "unit": "HV",
                  "variant_label": "Sample A",
                  "baseline_label": null,
                  "claim_scope": "current work",
                  "claim_text": "Hardness reached 210 HV.",
                  "quote": "210 HV"
                }
              ]
            }
          ]
        }
        """
    )
    extractor = _json_text_extractor(client)

    mentions = extractor.extract_table_batch_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental"},
            "target_rows": [{"row_index": 1, "row_summary": "Sample A | 210 HV", "cells": []}],
            "supporting_text_windows": [],
        }
    )

    row_result = mentions.row_results[0]
    assert row_result.row_index == 1
    assert row_result.row_subjects[0].variant_label == "Sample A"
    assert row_result.process_mentions == []
    assert row_result.test_condition_mentions[0].name == "test temperature"
    assert row_result.result_claims[0].claim_scope == "current_work"


def test_structured_bundle_defaults_null_backend_metadata():
    bundle = StructuredExtractionBundle.model_validate(
        {
            "sample_variants": [
                {
                    "variant_label": "Sample A",
                    "confidence": None,
                    "epistemic_status": None,
                }
            ],
            "measurement_results": [
                {
                    "claim_text": "Hardness reached 210 HV.",
                    "property_normalized": "hardness",
                    "result_type": "scalar",
                    "confidence": None,
                }
            ],
        }
    )

    assert bundle.sample_variants[0].confidence == 0.85
    assert bundle.sample_variants[0].epistemic_status == "normalized_from_evidence"
    assert bundle.measurement_results[0].confidence == 0.85


def test_core_llm_extractor_accepts_empty_table_batch_mentions():
    client = _FakeOpenAIClient(
        """
        {
          "row_results": []
        }
        """
    )
    extractor = _json_text_extractor(client)

    mentions = extractor.extract_table_batch_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental"},
            "target_rows": [{"row_index": 1, "row_summary": "Sample A | no grounded result", "cells": []}],
            "supporting_text_windows": [],
        }
    )

    assert mentions == StructuredTableBatchMentions()


def test_core_llm_extractor_still_rejects_unknown_table_batch_extra_keys():
    client = _FakeOpenAIClient(
        """
        {
          "keywords": ["yield strength"],
          "row_results": []
        }
        """
    )
    extractor = _json_text_extractor(client)

    with pytest.raises(ValidationError) as exc_info:
        extractor.extract_table_batch_mentions(
            {
                "document_title": "LPBF Paper",
                "document_profile": {"doc_type": "experimental"},
                "target_rows": [{"row_index": 1, "row_summary": "Sample A | 560 MPa", "cells": []}],
                "supporting_text_windows": [],
            }
        )

    assert "keywords" in str(exc_info.value)


def test_core_llm_extractor_falls_back_to_default_for_invalid_mode(monkeypatch, caplog):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "not-a-mode")

    with caplog.at_level("WARNING"):
        extractor = CoreLLMStructuredExtractor(client=_FakeOpenAIClient("{}"), model="fake-model")

    assert extractor.extraction_mode == "provider_parse"
    assert "Invalid CORE_LLM_EXTRACTION_MODE=not-a-mode" in caplog.text
