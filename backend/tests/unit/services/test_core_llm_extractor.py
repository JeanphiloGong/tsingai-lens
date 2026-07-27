from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from application.core.semantic_build.llm.extractor import CoreLLMStructuredExtractor
from application.core.semantic_build.llm.prompts import (
    build_objective_evidence_prompt,
    build_finding_synthesis_prompt,
)
from application.core.semantic_build.llm.schemas import (
    StructuredAxisCanonicalizationPlan,
    StructuredDocumentProfile,
    StructuredExtractionBundle,
    StructuredEvidenceSelections,
    StructuredEvidenceExtractions,
    StructuredObjectiveMergePlan,
    StructuredPaperContributionDraft,
    StructuredPaperSkim,
    StructuredResearchObjectives,
    StructuredFindingSynthesisOutcome,
    StructuredFindingSynthesis,
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
    assert client.chat.completions.calls[0]["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


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
    assert "JSON schema:" not in parse_call["messages"][1]["content"]
    assert parse_call["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }



def test_core_llm_extractor_synthesizes_goal_findings_with_distinct_trace():
    parsed = StructuredFindingSynthesis(findings=[])
    client = _FakeOpenAIClient("unused", parsed=parsed)
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")
    payload = {
        "objective": {"question": "How does energy density affect density?"},
        "result_sets": [
            {
                "source_axes": ["energy density"],
                "outcome_properties": ["density"],
                "document_evidence": [
                    {
                        "document_id": "paper-1",
                        "result_units": [
                            {
                                "evidence_id": "evidence-1",
                                "direct_result": True,
                                "statement": (
                                    "Higher energy density increased density."
                                ),
                            }
                        ],
                    }
                ],
            }
        ],
    }

    result = extractor.synthesize_findings(payload)

    assert result == parsed
    parse_call = client.beta.chat.completions.calls[0]
    assert parse_call["response_format"] is StructuredFindingSynthesis
    assert parse_call["max_completion_tokens"] == 2048
    trace = extractor.consume_last_trace()
    assert trace is not None
    assert trace["task_type"] == "finding_synthesis"
    assert trace["prompt_version"] == "finding_synthesis.v1"
    assert trace["parsed_output"] == {"findings": []}


def test_core_llm_extractor_bounds_json_text_finding_synthesis_output():
    client = _FakeOpenAIClient('{"findings": []}')
    extractor = _json_text_extractor(client)

    result = extractor.synthesize_findings(
        {
            "objective": {"question": "How does energy density affect density?"},
            "result_sets": [],
        }
    )

    assert result == StructuredFindingSynthesis(findings=[])
    assert client.chat.completions.calls[0]["max_completion_tokens"] == 2048


def test_finding_synthesis_prompt_uses_goal_level_contract():
    payload = {
        "objective": {"question": "How does energy density affect density?"},
        "result_sets": [],
    }

    system_prompt, user_prompt = build_finding_synthesis_prompt(
        payload
    )

    assert "INPUT SCHEMA" in system_prompt
    assert "DECISION PROCESS" in system_prompt
    assert "one goal-level synthesis pass" in system_prompt
    normalized_system_prompt = " ".join(system_prompt.split())
    assert "paper_contributions" in normalized_system_prompt
    assert "cannot replace direct evidence" in normalized_system_prompt
    assert "direct_evidence" in normalized_system_prompt
    assert "contradictory_evidence" in normalized_system_prompt
    assert "context_evidence" in normalized_system_prompt
    assert "result_sets" in normalized_system_prompt
    assert "copy its `result_set_id`" in normalized_system_prompt
    assert "exactly one outcome for each distinct `outcome_properties` value" in (
        normalized_system_prompt
    )
    assert "must equal that property" in normalized_system_prompt
    assert "Never combine direct-result ids from separate `result_sets`" in (
        normalized_system_prompt
    )
    assert "Keep its linked measured outcomes together" in normalized_system_prompt
    assert "One Finding must preserve all goal-relevant outcomes" in (
        normalized_system_prompt
    )
    assert "Build `source_concept` from `source_axes` only" in (
        normalized_system_prompt
    )
    assert "Never turn `context_evidence` into an unsupported outcome" in (
        normalized_system_prompt
    )
    assert "single-paper composite statement" in (
        normalized_system_prompt
    )
    assert "Context and mechanism id lists must be disjoint" in (
        normalized_system_prompt
    )
    assert "Do not silently discard an explicit regime limitation" in (
        normalized_system_prompt
    )
    assert "use that qualification instead of foregrounding a small endpoint delta" in (
        normalized_system_prompt
    )
    assert "directly supported by one paper" in normalized_system_prompt
    assert "cannot increase the contributing paper count" in normalized_system_prompt
    outcome_schema = StructuredFindingSynthesisOutcome.model_json_schema()
    assert "supporting_evidence_ids" not in outcome_schema["properties"]
    assert "backend binds all matching direct-result ids" in normalized_system_prompt
    assert "`agreement`: at least two independent papers" in user_prompt
    assert "`insufficient_confirmation`" in user_prompt
    assert json.dumps(payload, ensure_ascii=False, separators=(",", ":")) in user_prompt



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

    frame = extractor.assess_objective_paper(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "paper_skim": {"document_id": "paper-1"},
            "section_snippets": [{"section_label": "Results"}],
            "table_summaries": [{"table_id": "table-1"}, {"table_id": "table-2"}],
        }
    )

    assert isinstance(frame, StructuredPaperContributionDraft)
    assert frame.relevance == "high"
    assert frame.relevant_tables == ["table-1"]


def test_core_llm_extractor_validates_objective_evidence_routes_response():
    client = _FakeOpenAIClient(
        """
            {
              "selections": [
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

    routes = extractor.select_objective_evidence(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "paper_frame": {"frame_id": "opf-1"},
            "current_source": {"source_kind": "table", "source_ref": "table-1"},
        }
    )

    assert isinstance(routes, StructuredEvidenceSelections)
    assert routes.selections[0].role == "current_experimental_evidence"
    assert "reason" not in routes.selections[0].model_dump()


def test_core_llm_extractor_rejects_legacy_objective_route_batches():
    client = _FakeOpenAIClient('{"selections": []}')
    extractor = _json_text_extractor(client)

    with pytest.raises(ValueError):
        extractor.select_objective_evidence(
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
          "selections": [
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
        extractor.select_objective_evidence(
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
          "selections": [
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
        extractor.select_objective_evidence(
            {
                "collection_id": "col-1",
                "objective": {"question": "How does heat treatment affect corrosion?"},
                "paper_frame": {"frame_id": "opf-1"},
                "current_source": {"source_kind": "table", "source_ref": "table-1"},
            }
        )


def test_core_llm_extractor_validates_objective_evidence_response():
    client = _FakeOpenAIClient(
        """
        {
          "extractions": [
            {
              "evidence_kind": "measurement",
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

    extractions = extractor.extract_objective_evidence(
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

    assert isinstance(extractions, StructuredEvidenceExtractions)
    assert extractions.extractions[0].evidence_kind == "measurement"
    assert extractions.extractions[0].resolution_status == "resolved"
    assert client.chat.completions.calls[0]["max_completion_tokens"] == 1024


def test_objective_evidence_prompt_limits_text_routes_to_one_extraction():
    _, prompt = build_objective_evidence_prompt(
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

    assert "For text routes, return at most one extraction" in prompt
    assert "Do not enumerate every possible number" in prompt
    assert "The backend binds `source_refs` from the active route" in prompt
    assert "Do not output `source_refs`" in prompt
    assert "one extraction per binding" not in prompt
    assert "Do not merge those bindings into one `interpretation`" not in prompt
    assert "1.43x10^6 C/s for P150" in prompt
    assert "1.65x10^6 C/s for NP" in prompt
    assert "Bad text example" in prompt


def test_core_llm_extractor_rejects_backend_bound_objective_evidence_fields():
    client = _FakeOpenAIClient(
        """
        {
          "extractions": [
            {
              "evidence_kind": "measurement",
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
        extractor.extract_objective_evidence(
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
    assert parse_call["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_core_llm_extractor_routes_document_profiles_directly_to_bounded_json_text(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    client = _FakeOpenAIClient(
        '{"doc_type":"experimental","parsing_warnings":[],"confidence":0.91}'
    )
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    profile = extractor.extract_document_profile(
        {
            "document_title": "LPBF Paper",
            "document_text": "This study reports LPBF experiments on 316L.",
        }
    )

    assert profile == StructuredDocumentProfile(
        doc_type="experimental",
        parsing_warnings=[],
        confidence=0.91,
    )
    assert client.beta.chat.completions.calls == []
    text_call = client.chat.completions.calls[0]
    assert text_call["max_completion_tokens"] == 1024
    assert "JSON schema:" in text_call["messages"][1]["content"]
    assert text_call["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert extractor.consume_last_trace()["extraction_mode"] == "json_text"


def test_core_llm_extractor_can_opt_in_to_provider_thinking(monkeypatch):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    monkeypatch.setenv("LLM_ENABLE_THINKING", "true")
    client = _FakeOpenAIClient("unused", parsed=StructuredTableBatchMentions())
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    extractor.extract_table_batch_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental"},
            "target_rows": [],
            "supporting_text_windows": [],
        }
    )

    assert "extra_body" not in client.beta.chat.completions.calls[0]


def test_core_llm_extractor_routes_objective_selections_directly_to_bounded_json_text(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    client = _FakeOpenAIClient('{"selections":[]}')
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    routes = extractor.select_objective_evidence(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "paper_frame": {"frame_id": "opf-1"},
            "current_source": {"source_kind": "text_window", "source_ref": "b1"},
        }
    )

    assert routes == StructuredEvidenceSelections()
    assert client.beta.chat.completions.calls == []
    text_call = client.chat.completions.calls[0]
    assert text_call["max_completion_tokens"] == 512
    assert "JSON schema:" in text_call["messages"][1]["content"]
    assert text_call["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert extractor.consume_last_trace()["extraction_mode"] == "json_text"


def test_core_llm_extractor_caps_provider_parse_completion_tokens_for_objective_units(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    client = _FakeOpenAIClient('{"extractions": []}')
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    units = extractor.extract_objective_evidence(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "evidence_route": {"source_kind": "text_window", "source_ref": "b1"},
            "source": {"source_kind": "text_window", "source_ref": "b1", "text": "x"},
        }
    )

    assert units == StructuredEvidenceExtractions()
    assert client.beta.chat.completions.calls == []
    text_call = client.chat.completions.calls[0]
    assert text_call["max_completion_tokens"] == 1024
    assert "JSON schema:" in text_call["messages"][1]["content"]
    assert extractor.consume_last_trace()["extraction_mode"] == "json_text"


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
