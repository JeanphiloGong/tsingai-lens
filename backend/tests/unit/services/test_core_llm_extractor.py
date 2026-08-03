from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from application.core.semantic_build.llm.extractor import CoreLLMStructuredExtractor
from application.core.semantic_build.llm.prompts import (
    build_objective_evidence_prompt,
    build_research_objective_discovery_prompt,
    build_finding_synthesis_prompt,
)
from application.core.semantic_build.llm.schemas import (
    StructuredAxisCanonicalizationPlan,
    StructuredDocumentProfile,
    StructuredExtractionBundle,
    StructuredEvidenceExtraction,
    StructuredEvidenceSelections,
    StructuredEvidenceExtractions,
    StructuredObjectiveMergePlan,
    StructuredPaperContributionDraft,
    StructuredPaperSkim,
    StructuredResearchObjective,
    StructuredResearchObjectives,
    StructuredFindingMechanism,
    StructuredFindingSynthesis,
    StructuredTableBatchMentions,
    StructuredTextWindowMentions,
)


@pytest.mark.parametrize("field", ["variables", "outcomes"])
def test_structured_research_objective_requires_primary_scientific_axes(field):
    payload = {
        "question": "How does heat treatment affect yield strength?",
        "variables": ["heat treatment"],
        "outcomes": ["yield strength"],
    }
    payload[field] = []

    with pytest.raises(ValidationError):
        StructuredResearchObjective.model_validate(payload)


def test_research_objective_discovery_contract_bounds_model_output():
    objective = {
        "question": "How does heat treatment affect yield strength?",
        "variables": ["heat treatment"],
        "outcomes": ["yield strength"],
    }

    with pytest.raises(ValidationError):
        StructuredResearchObjectives.model_validate(
            {"objectives": [objective for _ in range(7)]}
        )

    schema = StructuredResearchObjectives.model_json_schema()
    objective_schema = schema["$defs"]["StructuredResearchObjective"]["properties"]
    assert schema["properties"]["objectives"]["maxItems"] == 6
    assert objective_schema["question"]["maxLength"] == 180
    assert objective_schema["requested_comparator"]["anyOf"][0]["maxLength"] == 160
    assert objective_schema["reason"]["anyOf"][0]["maxLength"] == 120


def test_research_objective_discovery_prompt_requires_focused_concise_objectives():
    _, user_prompt = build_research_objective_discovery_prompt(
        {"collection_id": "col-1", "paper_skims": []}
    )

    assert "at most six objectives" in user_prompt
    assert "only tightly related outcomes" in user_prompt
    assert "Do not put another measured property in `mechanisms`" in user_prompt
    assert "Set `reason` to null" in user_prompt


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
    assert client.chat.completions.calls[0]["response_format"] == {
        "type": "json_object"
    }
    assert client.chat.completions.calls[0]["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_core_llm_extractor_uses_last_complete_json_after_model_reasoning():
    client = _FakeOpenAIClient(
        'The draft was {"doc_type": experimental,}\n'
        'Final answer:\n{"doc_type":"experimental","confidence":0.9,"parsing_warnings":[]}'
    )
    extractor = _json_text_extractor(client)

    result = extractor.extract_document_profile(
        {
            "title": "LPBF paper",
            "source_filename": "paper.pdf",
            "abstract_or_lead_text": "This is an experimental study.",
            "headings": ["Methods", "Results"],
        }
    )

    assert result.doc_type == "experimental"
    assert result.confidence == 0.9


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
        "result_set": {
            "result_set_id": "result-set-1",
            "factors": ["energy density"],
            "outcome": "density",
            "result_evidence": [],
        },
    }

    result = extractor.synthesize_findings(payload)

    assert result == parsed
    parse_call = client.beta.chat.completions.calls[0]
    assert parse_call["response_format"] is StructuredFindingSynthesis
    assert parse_call["max_completion_tokens"] == 1024
    trace = extractor.consume_last_trace()
    assert trace is not None
    assert trace["task_type"] == "finding_synthesis"
    assert trace["prompt_version"] == "finding_synthesis.v4"
    assert trace["parsed_output"] == {"findings": []}


def test_core_llm_extractor_bounds_json_text_finding_synthesis_output():
    client = _FakeOpenAIClient('{"findings": []}')
    extractor = _json_text_extractor(client)

    result = extractor.synthesize_findings(
        {
            "objective": {"question": "How does energy density affect density?"},
            "result_set": {},
        }
    )

    assert result == StructuredFindingSynthesis(findings=[])
    assert client.chat.completions.calls[0]["max_completion_tokens"] == 1024


def test_finding_synthesis_schema_rejects_model_owned_result_assignment():
    payload = {
        "result_set_id": "result-set-1",
        "statement": "Energy density increases relative density.",
        "direction": "increase",
        "assertion_strength": "associative",
        "supporting_evidence_ids": ["evidence-1", "evidence-1"],
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StructuredFindingSynthesis.model_validate({"findings": [payload]})


def test_finding_synthesis_prompt_uses_atomic_evidence_contract():
    payload = {
        "objective": {"question": "How does energy density affect density?"},
        "result_set": {
            "result_set_id": "result-set-1",
            "factors": ["laser power", "scan speed", "energy density"],
            "outcome": "maximum defect length",
            "result_evidence": [
                {
                    "evidence_id": "evidence-1",
                    "attribution_scope": "joint_effect",
                }
            ],
        },
        "paper_contributions": [],
        "context_evidence": [],
    }

    system_prompt, user_prompt = build_finding_synthesis_prompt(
        payload
    )

    assert "INPUT SCHEMA" in system_prompt
    assert "DECISION PROCESS" in system_prompt
    normalized_system_prompt = " ".join(system_prompt.split())
    assert "paper_contributions" in normalized_system_prompt
    assert "cannot become Evidence" in normalized_system_prompt
    assert "result_evidence" in normalized_system_prompt
    assert "context_evidence" in normalized_system_prompt
    assert "exactly one reported outcome" in normalized_system_prompt
    assert "do not output support or contradiction ids" in normalized_system_prompt
    assert "Do not output factors, outcome, paper count" in normalized_system_prompt
    assert "Joint factors must remain the complete factor set" in normalized_system_prompt
    assert "Mechanisms explain the main Finding" in normalized_system_prompt
    assert "Choose one direction that accounts for every" in user_prompt
    assert "`laser power`" in user_prompt
    assert "`scan speed`" in user_prompt
    assert "`energy density`" in user_prompt
    assert "`maximum defect length`" in user_prompt
    assert "assertion_strength` must be `associative`" in user_prompt
    assert "Joint changes in laser power, scan speed, and energy density" in user_prompt
    mechanism_schema = StructuredFindingMechanism.model_json_schema()
    assert "supporting_evidence_ids" in mechanism_schema["properties"]
    assert json.dumps(payload, ensure_ascii=False, separators=(",", ":")) in user_prompt


def test_finding_synthesis_prompt_requires_specific_single_factor_result():
    payload = {
        "objective": {
            "question": "How does build platform preheating affect microstructure?"
        },
        "result_set": {
            "result_set_id": "result-set-preheating",
            "factors": ["preheating build platform temperature"],
            "outcome": "microstructure",
            "result_evidence": [
                {
                    "evidence_id": "evidence-preheating",
                    "changed_variables": [
                        {
                            "name": "preheating build platform temperature",
                            "baseline_value": "P150",
                            "target_value": "NP",
                            "unit": None,
                        }
                    ],
                    "reported_result": {
                        "outcome": "microstructure",
                        "value": "cellular structure",
                        "unit": None,
                        "direction": "mixed",
                        "result_text": (
                            "Comparing P150 with NP, cellular structure was seen "
                            "in P150."
                        ),
                    },
                    "attribution_scope": "isolated_effect",
                }
            ],
        },
        "paper_contributions": [],
        "context_evidence": [],
    }

    _system_prompt, user_prompt = build_finding_synthesis_prompt(payload)

    assert (
        "`preheating build platform temperature: P150 -> NP`" in user_prompt
    )
    assert "source-reported result detail `cellular structure`" in user_prompt
    assert (
        "For preheating build platform temperature, P150 versus NP showed a "
        "difference in microstructure:" in user_prompt
    )
    assert "Never return a generic restatement" in user_prompt



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
              "variables": ["heat treatment"],
              "outcomes": ["corrosion"],
              "constraints": ["LPBF"],
              "requested_comparator": "compare as-built and heat-treated corrosion behavior",
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
    text_call = client.chat.completions.calls[0]
    assert text_call["max_completion_tokens"] == 1400
    assert text_call["response_format"] == {"type": "json_object"}


def test_core_llm_extractor_validates_axis_canonicalization_response():
    client = _FakeOpenAIClient(
        """
        {
          "axis_groups": [
            {
              "axis_type": "variable",
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
                "variable": ["scanning strategy", "scan strategy"],
                "outcome": [],
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
              "variables": ["energy density"],
              "outcomes": ["yield strength", "elongation"],
              "constraints": ["Selective Laser Melting"],
              "requested_comparator": "compare SLM parameter effects on mechanical properties",
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
              "evidence_role": "direct_result",
              "changed_variables": [
                {
                  "name": "heat treatment",
                  "baseline_value": null,
                  "target_value": "heat-treated",
                  "unit": null
                }
              ],
              "comparison": null,
              "reported_result": {
                "outcome": "corrosion current density",
                "value": 0.4,
                "unit": "uA/cm2",
                "direction": "unknown",
                "result_text": "The heat-treated sample reported 0.4 uA/cm2."
              },
              "attribution_scope": "association_only",
              "scientific_context": {
                "material": [
                  {"name": "family", "value": "316L stainless steel"}
                ],
                "sample": [
                  {"name": "label", "value": "heat-treated"}
                ],
                "process": [
                  {"name": "process", "value": "LPBF"}
                ],
                "test": [
                  {"name": "environment", "value": "NaCl"}
                ]
              },
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
    extraction = extractions.extractions[0]
    assert extraction.evidence_role == "direct_result"
    assert extraction.changed_variables[0].name == "heat treatment"
    assert extraction.reported_result is not None
    assert extraction.reported_result.outcome == "corrosion current density"
    assert extraction.attribution_scope == "association_only"
    assert extractions.extractions[0].resolution_status == "resolved"
    assert client.chat.completions.calls[0]["max_completion_tokens"] == 1024


def test_structured_objective_evidence_rejects_effect_without_variable_change():
    with pytest.raises(ValidationError, match="requires changed variable values"):
        StructuredEvidenceExtraction.model_validate(
            {
                "evidence_role": "direct_result",
                "changed_variables": [
                    {
                        "name": "laser power",
                        "baseline_value": 200,
                        "target_value": 200,
                    }
                ],
                "comparison": {
                    "baseline_label": "A",
                    "target_label": "B",
                    "axis_names": ["laser power"],
                    "comparable": True,
                },
                "reported_result": {
                    "outcome": "density",
                    "value": 98.9,
                    "unit": "%",
                    "direction": "no_change",
                    "result_text": "Density was 98.9% in condition B.",
                },
                "attribution_scope": "isolated_effect",
                "scientific_context": {},
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )


def test_structured_objective_evidence_allows_unbound_variable_draft():
    extraction = StructuredEvidenceExtraction.model_validate(
        {
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "preheating build platform temperature",
                    "baseline_value": None,
                    "target_value": None,
                }
            ],
            "comparison": {
                "baseline_label": "NP",
                "target_label": "P150",
                "axis_names": ["preheating build platform temperature"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "microstructure",
                "value": None,
                "unit": None,
                "direction": "mixed",
                "result_text": "P150 had a coarser cellular structure than NP.",
            },
            "attribution_scope": "association_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )

    assert extraction.changed_variables[0].baseline_value is None
    assert extraction.changed_variables[0].target_value is None


def test_objective_evidence_prompt_limits_text_routes_to_one_extraction():
    system_prompt, prompt = build_objective_evidence_prompt(
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
    assert "The backend binds the exact source excerpt and Source locators" in prompt
    assert "Do not output `source_refs`" in prompt
    assert "one extraction per binding" not in prompt
    assert "Do not merge those bindings into one `interpretation`" not in prompt
    assert "1.43x10^6 C/s for P150" in prompt
    assert "1.65x10^6 C/s for NP" in prompt
    assert "Bad text example" in prompt
    assert "Every changed variable should include" in system_prompt
    assert "exact source group labels as endpoints" in system_prompt
    assert "Context roles must return `reported_result: null`" in system_prompt
    assert "numeric `confidence` after `resolution_status`" in system_prompt
    assert "qualitative observation" in prompt
    assert "it is not mechanism_context" in prompt


def test_core_llm_extractor_rejects_backend_bound_objective_evidence_fields():
    client = _FakeOpenAIClient(
        """
        {
          "extractions": [
            {
              "evidence_role": "direct_result",
              "changed_variables": [],
              "comparison": null,
              "reported_result": {
                "outcome": "yield strength",
                "value": 450,
                "unit": "MPa",
                "direction": "unknown",
                "result_text": "Yield strength reached 450 MPa."
              },
              "attribution_scope": "descriptive_only",
              "scientific_context": {},
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
    assert text_call["response_format"] == {"type": "json_object"}
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
    assert text_call["response_format"] == {"type": "json_object"}
    assert "JSON schema:" in text_call["messages"][1]["content"]
    assert text_call["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert extractor.consume_last_trace()["extraction_mode"] == "json_text"


def test_core_llm_extractor_routes_objective_units_through_bounded_provider_parse(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    client = _FakeOpenAIClient(
        "unused",
        parsed=StructuredEvidenceExtractions(),
    )
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
    assert client.chat.completions.calls == []
    parse_call = client.beta.chat.completions.calls[0]
    assert parse_call["max_completion_tokens"] == 1024
    assert parse_call["response_format"] is StructuredEvidenceExtractions
    assert "JSON schema:" not in parse_call["messages"][1]["content"]
    assert extractor.consume_last_trace()["extraction_mode"] == "provider_parse"


def test_objective_evidence_prompt_requires_verbatim_outcome_bound_result_text() -> None:
    _system_prompt, user_prompt = build_objective_evidence_prompt(
        {
            "objective": {"outcomes": ["microstructure"]},
            "source": {"text": "P150 formed an equiaxed cellular structure."},
        }
    )

    assert "one short verbatim substring" in user_prompt
    assert "direction must describe that outcome" in user_prompt
    assert "use `mixed` for a qualitative morphology change" in user_prompt
    assert "mixes the authors' current result with cited literature" in user_prompt
    assert "`incomparability_reasons` must be empty" in user_prompt
    assert "conditions from cited literature" in user_prompt


def test_core_llm_extractor_retries_with_structured_validation_error(monkeypatch):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    invalid = json.dumps(
        {
            "extractions": [
                {
                    "evidence_role": "direct_result",
                    "changed_variables": [
                        {
                            "name": "preheating build platform temperature",
                            "baseline_value": "NP",
                            "target_value": "P150",
                        }
                    ],
                    "comparison": None,
                    "reported_result": {
                        "outcome": "microstructure",
                        "value": None,
                        "unit": None,
                        "direction": "mixed",
                        "result_text": "P150 formed an equiaxed cellular structure.",
                    },
                    "attribution_scope": "isolated_effect",
                    "scientific_context": {},
                    "resolution_status": "partial",
                    "confidence": 0.8,
                }
            ]
        }
    )
    valid = json.dumps(
        {
            "extractions": [
                {
                    "evidence_role": "direct_result",
                    "changed_variables": [
                        {
                            "name": "preheating build platform temperature",
                            "baseline_value": "NP",
                            "target_value": "P150",
                        }
                    ],
                    "comparison": {
                        "baseline_label": "NP",
                        "target_label": "P150",
                        "axis_names": ["preheating build platform temperature"],
                        "comparable": True,
                    },
                    "reported_result": {
                        "outcome": "microstructure",
                        "value": None,
                        "unit": None,
                        "direction": "mixed",
                        "result_text": "P150 formed an equiaxed cellular structure.",
                    },
                    "attribution_scope": "isolated_effect",
                    "scientific_context": {},
                    "resolution_status": "resolved",
                    "confidence": 0.8,
                }
            ]
        }
    )
    client = _FakeOpenAIClient(invalid)
    responses = iter((invalid, valid))

    def create(**kwargs):  # noqa: ANN003
        client.chat.completions.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=next(responses)),
                )
            ]
        )

    client.chat.completions.create = create
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    parsed = extractor.extract_objective_evidence(
        {
            "objective": {
                "question": "How does preheating affect microstructure?"
            },
            "evidence_route": {
                "source_kind": "text_window",
                "source_ref": "block-1",
            },
            "source": {
                "source_kind": "text_window",
                "source_ref": "block-1",
                "text": "P150 formed an equiaxed cellular structure compared with NP.",
            },
        }
    )

    assert parsed.extractions[0].comparison is not None
    assert len(client.chat.completions.calls) == 2
    repair_prompt = client.chat.completions.calls[1]["messages"][-1]["content"]
    assert "experimental attribution requires comparison" in repair_prompt



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
