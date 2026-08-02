from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from application.core.semantic_build.llm.extractor import CoreLLMStructuredExtractor
from application.core.semantic_build.llm.prompts import (
    build_objective_evidence_route_prompt,
    build_objective_evidence_prompt,
    build_finding_synthesis_prompt,
    build_paper_skim_prompt,
    build_research_objective_discovery_prompt,
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
    StructuredResearchObjective,
    StructuredResearchObjectives,
    StructuredFindingSynthesisOutcome,
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
    client = _FakeOpenAIClient('{"findings": []}', parsed=parsed)
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
    assert client.beta.chat.completions.calls == []
    text_call = client.chat.completions.calls[0]
    assert text_call["response_format"] == {"type": "json_object"}
    assert text_call["max_completion_tokens"] == 2048
    trace = extractor.consume_last_trace()
    assert trace is not None
    assert trace["task_type"] == "finding_synthesis"
    assert trace["prompt_version"] == "finding_synthesis.v2"
    assert trace["extraction_mode"] == "json_text"
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
    assert client.chat.completions.calls[0]["response_format"] == {
        "type": "json_object"
    }


def test_finding_synthesis_prompt_uses_relationship_level_contract():
    payload = {
        "objective": {"question": "How does energy density affect density?"},
        "result_sets": [],
    }

    system_prompt, user_prompt = build_finding_synthesis_prompt(
        payload
    )

    assert "INPUT SCHEMA" in system_prompt
    assert "DECISION PROCESS" in system_prompt
    assert "one relationship within" in system_prompt
    assert "Produce one final Finding" in system_prompt
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
    assert "A small numeric difference alone is not a significance test" in (
        normalized_system_prompt
    )
    assert "cannot increase the contributing paper count" in normalized_system_prompt
    outcome_schema = StructuredFindingSynthesisOutcome.model_json_schema()
    assert "supporting_evidence_ids" not in outcome_schema["properties"]
    assert "backend binds all matching direct-result ids" in normalized_system_prompt
    assert "`agreement`: at least two independent papers" in user_prompt
    assert "`insufficient_confirmation`" in user_prompt
    assert "only one paper provides a direct result" in user_prompt
    assert "directly supported by one paper" in normalized_system_prompt
    assert "Return at most one Finding" in user_prompt
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
    text_call = client.chat.completions.calls[0]
    assert text_call["response_format"] == {"type": "json_object"}
    assert text_call["max_completion_tokens"] == 1024


def test_paper_skim_prompt_defines_standalone_task_contract():
    system_prompt, user_prompt = build_paper_skim_prompt(
        {
            "title": "LPBF 316L density study",
            "profile_hint": {
                "role_hint": "experimental",
                "source_quality_warnings": [],
                "role_hint_confidence": 0.9,
            },
            "text_preview": "Laser energy density was varied and density was measured.",
            "headings": ["Methods", "Results"],
            "table_captions": [],
            "figure_captions": [],
        }
    )
    prompt = f"{system_prompt}\n{user_prompt}"

    assert "TASK MODEL" in system_prompt
    assert "INPUT SCHEMA" in system_prompt
    assert "DECISION PROCESS" in system_prompt
    assert "HARD RULES" in system_prompt
    assert "FEW-SHOTS" in system_prompt
    assert "OUTPUT CONTRACT" in system_prompt
    assert "profile_hint.role_hint" in system_prompt
    assert "document_profile" not in prompt
    assert '"doc_type"' not in prompt
    assert "common experimental paper" in system_prompt.lower()
    assert "review paper" in system_prompt.lower()
    assert "insufficient or conflicting input" in system_prompt.lower()


def test_paper_skim_schema_defines_warning_and_confidence_contract():
    schema = StructuredPaperSkim.model_json_schema()

    assert schema["properties"]["doc_role"]["description"]
    assert schema["properties"]["evidence_density"]["description"]
    assert schema["properties"]["confidence"]["minimum"] == 0
    assert schema["properties"]["confidence"]["maximum"] == 1
    assert set(schema["properties"]["warnings"]["items"]["enum"]) == {
        "classification_uncertain",
        "insufficient_content",
        "modeling_only",
        "objective_uncertain",
        "profile_content_conflict",
        "review_only",
    }


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


def test_research_objective_discovery_prompt_defines_selection_contract():
    system_prompt, user_prompt = build_research_objective_discovery_prompt(
        {
            "collection_id": "col-1",
            "paper_skims": [
                {
                    "document_id": "paper-1",
                    "doc_role": "experimental",
                    "candidate_materials": ["316L stainless steel"],
                    "candidate_processes": ["LPBF"],
                    "changed_variables": ["laser energy density"],
                    "candidate_properties": ["relative density"],
                    "possible_objectives": [
                        "How does laser energy density affect relative density of LPBF 316L stainless steel?"
                    ],
                }
            ],
        }
    )

    assert "TASK MODEL" in system_prompt
    assert "INPUT SCHEMA" in system_prompt
    assert "DECISION PROCESS" in system_prompt
    assert "HARD RULES" in system_prompt
    assert "FEW-SHOTS" in system_prompt
    assert "OUTPUT CONTRACT" in system_prompt
    assert "candidate selection and binding" in system_prompt
    assert "not final evidence extraction" in system_prompt
    assert "not axis canonicalization" in system_prompt
    assert "not objective merge" in system_prompt
    assert "`collection_id`" in system_prompt
    assert "`paper_skims[].document_id`" in system_prompt
    assert "`paper_skims[].possible_objectives`" in system_prompt
    assert "copy" in system_prompt.lower()
    assert "If more than 6 candidates remain" in system_prompt
    assert "Shared objective across papers" in system_prompt
    assert "Unrelated candidates stay separate" in system_prompt
    assert "Review or insufficient candidates" in system_prompt
    assert '{"objectives":[]}' in system_prompt
    assert "Input JSON:" in user_prompt


def test_research_objective_schema_requires_bounded_complete_records():
    schema = StructuredResearchObjectives.model_json_schema()
    objective_schema = schema["$defs"]["StructuredResearchObjective"]

    assert schema["required"] == ["objectives"]
    assert schema["properties"]["objectives"]["maxItems"] == 6
    assert set(objective_schema["required"]) == {
        "question",
        "material_scope",
        "process_axes",
        "property_axes",
        "comparison_intent",
        "seed_document_ids",
        "excluded_document_ids",
        "confidence",
        "reason",
    }
    assert objective_schema["properties"]["material_scope"]["maxItems"] == 3
    assert objective_schema["properties"]["process_axes"]["maxItems"] == 8
    assert objective_schema["properties"]["property_axes"]["maxItems"] == 8
    assert objective_schema["properties"]["seed_document_ids"]["maxItems"] == 12
    assert objective_schema["properties"]["excluded_document_ids"]["maxItems"] == 12
    assert objective_schema["properties"]["confidence"]["minimum"] == 0
    assert objective_schema["properties"]["confidence"]["maximum"] == 1

    with pytest.raises(ValidationError, match="objectives"):
        StructuredResearchObjectives.model_validate({})


def test_research_objective_schema_rejects_overlapping_document_roles():
    with pytest.raises(ValidationError, match="must be disjoint"):
        StructuredResearchObjective(
            question="How does laser energy density affect relative density?",
            material_scope=["316L stainless steel"],
            process_axes=["laser energy density"],
            property_axes=["relative density"],
            comparison_intent="Compare relative density across energy densities.",
            seed_document_ids=["paper-1"],
            excluded_document_ids=["paper-1"],
            confidence=0.9,
            reason="The skim provides a direct process-property candidate.",
        )


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
    text_call = client.chat.completions.calls[0]
    assert text_call["max_completion_tokens"] == 2048
    assert text_call["response_format"] == {"type": "json_object"}


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
    text_call = client.chat.completions.calls[0]
    assert text_call["max_completion_tokens"] == 2048
    assert text_call["response_format"] == {"type": "json_object"}


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
    text_call = client.chat.completions.calls[0]
    assert text_call["max_completion_tokens"] == 1024
    assert text_call["response_format"] == {"type": "json_object"}


def test_objective_evidence_route_prompt_matches_selection_schema():
    system_prompt, user_prompt = build_objective_evidence_route_prompt(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "paper_frame": {"relevance": "high"},
            "current_source": {"source_kind": "text_window", "text": "Result."},
        }
    )
    prompt = f"{system_prompt}\n{user_prompt}"

    assert "`selections`" in prompt
    assert '{"selections":[]}' in prompt.replace(" ", "")
    assert "`routes`" not in prompt
    assert '{"routes":[]}' not in prompt.replace(" ", "")


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
    text_call = client.chat.completions.calls[0]
    assert text_call["response_format"] == {"type": "json_object"}


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
    assert client.chat.completions.calls[0]["max_completion_tokens"] == 2048
    assert client.chat.completions.calls[0]["response_format"] == {
        "type": "json_object"
    }


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
    assert "The backend binds `source_refs` from the active route" in prompt
    assert "Do not output `source_refs`" in prompt
    assert "one extraction per binding" not in prompt
    assert "Do not merge those bindings into one `interpretation`" not in prompt
    assert "1.43x10^6 C/s for P150" in prompt
    assert "1.65x10^6 C/s for NP" in prompt
    assert "Bad text example" in prompt
    normalized_system_prompt = " ".join(system_prompt.split())
    assert "objective and paper frame are not factual evidence" in normalized_system_prompt
    assert "Never infer sample ids, standards, orientations" in normalized_system_prompt


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


def test_core_llm_extractor_uses_provider_parse_with_sufficient_paper_skim_budget(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    client = _FakeOpenAIClient(
        "unused",
        parsed=StructuredPaperSkim(
            doc_role="experimental",
            candidate_materials=["316L stainless steel"],
            candidate_processes=["LPBF"],
            candidate_properties=["density"],
            changed_variables=["laser energy density"],
            possible_objectives=[
                "How does laser energy density affect LPBF 316L density?"
            ],
            evidence_density="high",
            confidence=0.9,
            warnings=[],
        ),
    )
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    skim = extractor.extract_paper_skim(
        {
            "document_id": "paper-1",
            "title": "LPBF 316L density study",
            "text_preview": "Laser energy density was varied for LPBF 316L.",
            "table_captions": [],
        }
    )

    assert skim.doc_role == "experimental"
    assert client.chat.completions.calls == []
    parse_call = client.beta.chat.completions.calls[0]
    assert parse_call["max_completion_tokens"] == 1024
    assert parse_call["response_format"] is StructuredPaperSkim
    assert extractor.consume_last_trace()["extraction_mode"] == "provider_parse"


def test_core_llm_extractor_logs_invalid_json_output_diagnostics(caplog):
    client = _FakeOpenAIClient(
        "I need to analyze the paper before producing the requested structure."
    )
    extractor = _json_text_extractor(client)

    with pytest.raises(RuntimeError, match="no JSON object"):
        extractor.extract_paper_skim(
            {
                "document_id": "paper-1",
                "title": "LPBF 316L density study",
                "text_preview": "Laser energy density was varied for LPBF 316L.",
                "table_captions": [],
            }
        )

    assert "response_model=StructuredPaperSkim attempt=2" in caplog.text
    assert "raw_output_length=69" in caplog.text


def test_paper_skim_retry_uses_task_specific_validation_contract():
    client = _FakeOpenAIClient(
        """
        {
          "doc_type": "experimental",
          "doc_role": "experimental",
          "candidate_materials": ["316L stainless steel"],
          "candidate_processes": ["LPBF"],
          "candidate_properties": ["density"],
          "changed_variables": ["laser energy density"],
          "possible_objectives": ["How does laser energy density affect density?"],
          "evidence_density": "high",
          "confidence": 0.9,
          "warnings": []
        }
        """
    )
    extractor = _json_text_extractor(client)

    with pytest.raises(ValidationError, match="doc_type"):
        extractor.extract_paper_skim(
            {
                "title": "LPBF 316L density study",
                "profile_hint": {"role_hint": "experimental"},
                "text_preview": "Laser energy density was varied and density was measured.",
                "headings": ["Methods", "Results"],
                "table_captions": [],
                "figure_captions": [],
            }
        )

    retry_instruction = client.chat.completions.calls[1]["messages"][-1]["content"]
    assert "Previous PaperSkim output failed validation" in retry_instruction
    assert "doc_type" in retry_instruction
    assert "exactly these keys" in retry_instruction
    assert "For finding synthesis" not in retry_instruction


def test_research_objective_retry_uses_task_specific_validation_contract():
    client = _FakeOpenAIClient(
        """
        {
          "objectives": [
            {
              "question": "How does laser energy density affect relative density?",
              "material_scope": ["316L stainless steel"]
            }
          ]
        }
        """
    )
    extractor = _json_text_extractor(client)

    with pytest.raises(ValidationError, match="process_axes"):
        extractor.discover_research_objectives(
            {
                "collection_id": "col-1",
                "paper_skims": [],
            }
        )

    retry_instruction = client.chat.completions.calls[1]["messages"][-1]["content"]
    assert "Previous ResearchObjective discovery output failed validation" in retry_instruction
    assert "process_axes" in retry_instruction
    assert "exactly one top-level key: objectives" in retry_instruction
    assert "exactly these objective keys" in retry_instruction
    assert "For finding synthesis" not in retry_instruction


@pytest.mark.parametrize(
    ("method_name", "payload", "invalid_content", "response_label", "top_level_key"),
    [
        (
            "select_objective_evidence",
            {
                "objective": {"question": "How does preheating affect elongation?"},
                "current_source": {"source_kind": "table", "source_ref": "table-1"},
            },
            '{"objective":{"question":"copied input"}}',
            "evidence routing",
            "selections",
        ),
        (
            "extract_objective_evidence",
            {
                "objective": {"question": "How does preheating affect elongation?"},
                "evidence_route": {"role": "current_experimental_evidence"},
                "source": {"source_kind": "table", "source_ref": "table-1"},
            },
            '{"source":{"source_kind":"table"}}',
            "evidence extraction",
            "extractions",
        ),
        (
            "synthesize_findings",
            {
                "objective": {"question": "How does preheating affect elongation?"},
                "result_sets": [{"result_set_id": "result_set_1"}],
            },
            '{"result_sets":[{"result_set_id":"result_set_1"}]}',
            "Finding synthesis",
            "findings",
        ),
    ],
)
def test_objective_pipeline_retries_use_task_specific_top_level_contract(
    method_name,
    payload,
    invalid_content,
    response_label,
    top_level_key,
):
    client = _FakeOpenAIClient(invalid_content)
    extractor = _json_text_extractor(client)

    with pytest.raises(ValidationError):
        getattr(extractor, method_name)(payload)

    retry_instruction = client.chat.completions.calls[1]["messages"][-1]["content"]
    assert f"Previous {response_label} output failed validation" in retry_instruction
    assert f"exactly one top-level key: {top_level_key}" in retry_instruction
    assert "copied input" in retry_instruction


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


def test_core_llm_extractor_routes_objective_selections_with_provider_schema(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    parsed = StructuredEvidenceSelections()
    client = _FakeOpenAIClient("unused", parsed=parsed)
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    routes = extractor.select_objective_evidence(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "paper_frame": {"frame_id": "opf-1"},
            "current_source": {"source_kind": "text_window", "source_ref": "b1"},
        }
    )

    assert routes == parsed
    assert client.chat.completions.calls == []
    parse_call = client.beta.chat.completions.calls[0]
    assert parse_call["max_completion_tokens"] == 512
    assert parse_call["response_format"] is StructuredEvidenceSelections
    assert "JSON schema:" not in parse_call["messages"][1]["content"]
    assert parse_call["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert extractor.consume_last_trace()["extraction_mode"] == "provider_parse"


def test_core_llm_extractor_extracts_objective_evidence_with_provider_schema(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    parsed = StructuredEvidenceExtractions()
    client = _FakeOpenAIClient("unused", parsed=parsed)
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    units = extractor.extract_objective_evidence(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "evidence_route": {"source_kind": "text_window", "source_ref": "b1"},
            "source": {"source_kind": "text_window", "source_ref": "b1", "text": "x"},
        }
    )

    assert units == parsed
    assert client.chat.completions.calls == []
    parse_call = client.beta.chat.completions.calls[0]
    assert parse_call["max_completion_tokens"] == 2048
    assert parse_call["response_format"] is StructuredEvidenceExtractions
    assert "JSON schema:" not in parse_call["messages"][1]["content"]
    assert extractor.consume_last_trace()["extraction_mode"] == "provider_parse"


def test_core_llm_extractor_removes_unsupported_evidence_context(monkeypatch):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    parsed = StructuredEvidenceExtractions(
        extractions=[
            {
                "evidence_kind": "measurement",
                "property_normalized": "elongation",
                "material_system": {"material": "316L stainless steel"},
                "sample_context": {
                    "condition": "non-preheated",
                    "sample_id": "NP",
                    "orientation": "XY",
                },
                "process_context": {"process": "LPBF", "power": "200 W"},
                "test_condition": {"standard": "ASTM E8/E8M"},
                "resolved_condition": {"temperature": "room temperature"},
                "value_payload": {
                    "non_preheated": 72,
                    "preheated": 82,
                    "cooling_rate": "1.43x10^6 C/s",
                },
                "baseline_context": {"condition": "non-preheated", "value": 72},
                "join_keys": {"row_index": 1, "col_index": 1},
                "resolution_status": "resolved",
                "confidence": 0.95,
            }
        ]
    )
    client = _FakeOpenAIClient("unused", parsed=parsed)
    extractor = CoreLLMStructuredExtractor(client=client, model="fake-model")

    result = extractor.extract_objective_evidence(
        {
            "objective": {
                "question": "How does preheating affect 316L elongation?"
            },
            "document_state": {"retained_evidence": []},
            "evidence_route": {"role": "current_experimental_evidence"},
            "source": {
                "source_kind": "table",
                "table_matrix": [
                    ["Condition", "Elongation (%)"],
                    ["Non-preheated", "72"],
                    ["Preheated", "82"],
                ],
            },
        }
    )

    extraction = result.extractions[0]
    assert extraction.material_system == {}
    assert extraction.sample_context == {"condition": "non-preheated"}
    assert extraction.process_context == {}
    assert extraction.test_condition == {}
    assert extraction.resolved_condition == {}
    assert extraction.baseline_context == {
        "condition": "non-preheated",
        "value": 72,
    }
    assert extraction.value_payload == {"non_preheated": 72, "preheated": 82}
    assert extraction.join_keys == {"row_index": 1, "col_index": 1}


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
