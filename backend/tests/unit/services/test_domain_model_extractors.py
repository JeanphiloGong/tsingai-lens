from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from openai import LengthFinishReasonError
from pydantic import ValidationError

from application.core.document_profiles.extraction import DocumentProfileExtractor
from application.core.objectives.extraction import (
    ObjectiveExtractor,
    PaperSkimOutputSaturatedError,
)
from application.core.paper_facts.extraction import PaperFactsExtractor
from application.core.objectives.prompts import (
    build_objective_evidence_prompt,
    build_paper_skim_prompt,
    build_paper_signal_reconciliation_prompt,
    build_research_axis_canonicalization_prompt,
    build_finding_synthesis_prompt,
)
from application.core.document_profiles.schemas import StructuredDocumentProfile
from application.core.objectives.schemas import (
    StructuredAxisCanonicalizationPlan,
    StructuredEvidenceContext,
    StructuredEvidenceExtraction,
    StructuredEvidenceSelections,
    StructuredEvidenceExtractions,
    StructuredPaperContributionDraft,
    StructuredPaperSignalReconciliation,
    StructuredPaperSkim,
    StructuredFindingMechanism,
    StructuredFindingSynthesis,
)
from application.core.paper_facts.schemas import (
    StructuredExtractionBundle,
    StructuredTableBatchMentions,
    StructuredTextWindowMentions,
)
from domain.pipeline import ModelUsage, TokenUsage
from infra.llm.usage import capture_llm_usage


def test_paper_skim_contract_bounds_model_output():
    model_schema = StructuredPaperSkim.model_json_schema()
    schema = model_schema["properties"]

    assert schema["studies"]["maxItems"] == 8
    assert schema["unresolved_signals"]["maxItems"] == 12
    assert schema["output_saturated"]["type"] == "boolean"
    study_schema = model_schema["$defs"]["StructuredPaperStudy"]["properties"]
    relationship_schema = model_schema["$defs"][
        "StructuredPaperStudyRelationship"
    ]["properties"]
    assert study_schema["material_scope"]["maxItems"] == 8
    assert study_schema["process_context"]["maxItems"] == 4
    assert study_schema["sample_context"]["maxItems"] == 4
    assert study_schema["test_context"]["maxItems"] == 4
    assert study_schema["fixed_conditions"]["maxItems"] == 12
    assert study_schema["relationships"]["maxItems"] == 8
    assert relationship_schema["varied_factors"]["maxItems"] == 8
    assert relationship_schema["source_unit_ids"]["minItems"] == 1
    signal_schema = model_schema["$defs"]["StructuredPaperStudySignal"][
        "properties"
    ]
    assert signal_schema["signal_type"]["enum"] == ["variable", "outcome"]
    assert signal_schema["source_unit_ids"]["minItems"] == 1
    assert "source_unit_coverage" not in schema
    assert "StructuredPaperSourceUnitCoverage" not in model_schema.get("$defs", {})
    assert schema["warnings"]["items"]["maxLength"] == 240


def test_paper_signal_reconciliation_contract_requires_source_signal_ids():
    parsed = StructuredPaperSignalReconciliation.model_validate(
        {
            "studies": [
                {
                    "relationships": [
                        {
                            "signal_ids": ["signal-variable", "signal-outcome"],
                            "confidence": 0.88,
                        }
                    ]
                }
            ],
            "unresolved_signals": [
                {
                    "signal_id": "signal-unlinked",
                    "reason": "The result belongs to a different experiment.",
                }
            ],
        }
    )

    assert parsed.studies[0].relationships[0].signal_ids == [
        "signal-variable",
        "signal-outcome",
    ]
    with pytest.raises(ValidationError):
        StructuredPaperSignalReconciliation.model_validate(
            {
                "studies": [
                    {
                        "relationships": [
                            {"signal_ids": ["signal-variable"]}
                        ]
                    }
                ]
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("warnings", ["warning-1", "warning-2", "warning-3"]),
        ("warnings", ["w" * 241]),
    ],
)
def test_paper_skim_contract_rejects_oversized_values(field, value):
    with pytest.raises(ValidationError):
        StructuredPaperSkim.model_validate({field: value})


def test_paper_skim_prompt_defines_structured_research_map_contract():
    _, user_prompt = build_paper_skim_prompt(
        {
            "document_id": "paper-1",
            "title": "Density study",
            "window_id": "results-1",
            "window_role": "results",
            "source_units": [
                {
                    "source_unit_id": "results-1-source-1",
                    "source_kind": "block",
                    "source_ref": "block-1",
                    "section_path": "Results",
                    "content": (
                        "Laser power was varied and relative density was measured."
                    ),
                }
            ],
        }
    )

    assert "TASK MODEL" in user_prompt
    assert "Extract source-supported paper studies" in user_prompt
    assert "`window_id` is this bounded window's identity" in user_prompt
    assert "absence from this window is not evidence of absence elsewhere" in user_prompt
    assert "return one relationship per outcome" in user_prompt
    assert "full jointly varied, compared, or modeled factor set" in user_prompt
    assert "Return empty arrays rather than guessing" in user_prompt
    assert "Return every distinct, explicitly supported study and relationship" in user_prompt
    assert "Return `studies=[]`; do not" in user_prompt
    assert "Return the explicit axis in `unresolved_signals`" in user_prompt
    assert "copy `source_unit_ids`" in user_prompt
    assert "Return two studies" in user_prompt
    assert "up to 2 `warnings`, each at most 240 characters" in user_prompt
    assert "up to 8 studies" in user_prompt
    assert "up to 8 relationships per study" in user_prompt
    assert "up to 12 unresolved signals" in user_prompt
    assert "output_saturated=true" in user_prompt
    assert "neutral scientific axis" in user_prompt
    assert "L-VED, M-VED, and H-VED" in user_prompt
    assert "varied_factors=['volumetric energy density']" in user_prompt
    assert "outcome='fatigue strength'" in user_prompt
    assert "result direction, value, or comparison sentence" in user_prompt
    assert "source_unit_coverage" not in user_prompt


def test_research_axis_canonicalization_prompt_defines_membership_boundaries():
    _, user_prompt = build_research_axis_canonicalization_prompt(
        {
            "collection_id": "collection-test",
            "axis_pairs": [
                {
                    "pair_id": "axis_pair_0001",
                    "axis_type": "material",
                    "left": "SS316L",
                    "right": "316L stainless steel",
                },
                {
                    "pair_id": "axis_pair_0002",
                    "axis_type": "outcome",
                    "left": "porosity",
                    "right": "relative density",
                },
            ],
        }
    )

    assert "before collection objective grouping" in user_prompt
    assert "pair classification" in user_prompt
    assert "`decisions` array" in user_prompt
    assert "every input pair" in user_prompt
    assert "boolean `equivalent`" in user_prompt
    assert "SS316L and 316L stainless steel" in user_prompt
    assert "SS316 and 316L stainless steel are different grades" in user_prompt
    assert "porosity" in user_prompt
    assert "relative density" in user_prompt
    assert "reject" in user_prompt
    assert "tensile strength and ultimate tensile strength" in user_prompt
    assert "surface hardness and hardness" in user_prompt


def test_paper_signal_reconciliation_prompt_requires_complete_accounting():
    _, user_prompt = build_paper_signal_reconciliation_prompt(
        {
            "document_id": "paper-1",
            "signals": [
                {
                    "signal_id": "signal-variable",
                    "signal_type": "variable",
                    "label": "laser power",
                    "sources": [
                        {
                            "source_kind": "block",
                            "source_ref": "methods-1",
                            "section_path": "Methods",
                            "excerpt": "Laser power was varied from 150 to 250 W.",
                        }
                    ],
                },
                {
                    "signal_id": "signal-outcome",
                    "signal_type": "outcome",
                    "label": "relative density",
                    "sources": [
                        {
                            "source_kind": "block",
                            "source_ref": "results-1",
                            "section_path": "Results",
                            "excerpt": "Relative density was recorded for each condition.",
                        }
                    ],
                },
            ],
        }
    )

    assert "membership adjudication" in user_prompt
    assert "Do not link signals merely because they occur in the same paper" in user_prompt
    assert "Every input signal must be accounted for" in user_prompt
    assert "copy only input `signal_id` values" in user_prompt
    assert "Methods variable and Results outcome" in user_prompt
    assert "different experiments" in user_prompt.lower()


class _FakeCompletions:
    def __init__(self, content: str | list[str]) -> None:
        self._contents = [content] if isinstance(content, str) else list(content)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):  # noqa: ANN003, ARG002
        self.calls.append(kwargs)
        content = self._contents[min(len(self.calls) - 1, len(self._contents) - 1)]
        return SimpleNamespace(
            model="fake-model",
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
            ),
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                )
            ]
        )


class _FakeChat:
    def __init__(self, content: str | list[str]) -> None:
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
            model="fake-model",
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
            ),
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
        content: str | list[str],
        *,
        parsed: object | None = None,
        parse_error: Exception | None = None,
    ) -> None:
        self.chat = _FakeChat(content)
        self.beta = _FakeBeta(parsed, error=parse_error)


def _objective_extractor(client: _FakeOpenAIClient) -> ObjectiveExtractor:
    return ObjectiveExtractor(
        client=client,
        model="fake-model",
        extraction_mode="json_text",
    )


def _document_profile_extractor(
    client: _FakeOpenAIClient,
) -> DocumentProfileExtractor:
    return DocumentProfileExtractor(
        client=client,
        model="fake-model",
        extraction_mode="json_text",
    )


def _paper_facts_extractor(client: _FakeOpenAIClient) -> PaperFactsExtractor:
    return PaperFactsExtractor(
        client=client,
        model="fake-model",
        extraction_mode="json_text",
    )


def test_domain_model_extractors_validate_json_text_response():
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
    extractor = _paper_facts_extractor(client)

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


def test_domain_model_extractors_record_provider_reported_usage() -> None:
    document_client = _FakeOpenAIClient(
        '{"doc_type":"experimental","confidence":0.9,"parsing_warnings":[]}'
    )
    facts_client = _FakeOpenAIClient(
        '{"method_mentions":[],"material_mentions":[],"variant_mentions":[],'
        '"condition_mentions":[],"baseline_mentions":[],"result_claims":[]}'
    )
    objective_client = _FakeOpenAIClient(
        "unused",
        parsed=StructuredFindingSynthesis(findings=[]),
    )

    with capture_llm_usage() as usage:
        _document_profile_extractor(document_client).extract_document_profile(
            {"title": "Paper", "abstract_or_lead_text": "Experimental study."}
        )
        _paper_facts_extractor(facts_client).extract_text_window_mentions(
            {
                "document_title": "Paper",
                "document_profile": {"doc_type": "experimental"},
                "text_window": {"text": "Laser power was 200 W."},
            }
        )
        ObjectiveExtractor(
            client=objective_client,
            model="fake-model",
        ).synthesize_findings(
            {
                "objective": {"question": "How does power affect density?"},
                "result_set": {},
            }
        )

    assert usage.execution_stats().model_usage == (
        ModelUsage("fake-model", 3, TokenUsage(300, 60, 360)),
    )
    assert usage.prompt_versions == {
        "document_profile": "document_profile.v1",
        "finding_synthesis": "finding_synthesis.v8",
        "paper_fact_text_window": "paper_fact_text_window.v1",
    }


def test_domain_model_extractors_uses_last_complete_json_after_model_reasoning():
    client = _FakeOpenAIClient(
        'The draft was {"doc_type": experimental,}\n'
        'Final answer:\n{"doc_type":"experimental","confidence":0.9,"parsing_warnings":[]}'
    )
    extractor = _document_profile_extractor(client)

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


def test_domain_model_extractors_ignores_top_level_extra_json_text_fields():
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
    extractor = _paper_facts_extractor(client)

    mentions = extractor.extract_text_window_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental"},
            "text_window": {"text": "Laser power was 200 W.", "heading_path": "Methods"},
        }
    )

    assert isinstance(mentions, StructuredTextWindowMentions)
    assert mentions.result_claims == []


def test_domain_model_extractors_defaults_to_provider_parse_mode(monkeypatch):
    monkeypatch.delenv("CORE_LLM_EXTRACTION_MODE", raising=False)
    parsed_mentions = StructuredTextWindowMentions()
    client = _FakeOpenAIClient("unused", parsed=parsed_mentions)
    extractor = PaperFactsExtractor(client=client, model="fake-model")

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


def test_objective_extractor_does_not_generate_backend_owned_objective_lineage():
    assert not hasattr(ObjectiveExtractor, "discover_research_objectives")


def test_paper_skim_prompt_token_estimate_counts_complete_schema_prompt():
    client = _FakeOpenAIClient("unused")
    extractor = ObjectiveExtractor(
        client=client,
        model="fake-model",
        extraction_mode="provider_parse",
    )
    payload = {
        "document_id": "paper-1",
        "title": "Density study",
        "window_id": "results-1",
        "window_role": "results",
        "source_units": [
            {
                "source_unit_id": "source-unit-1",
                "source_kind": "block",
                "source_ref": "block-1",
                "section_path": "Results",
                "content": "Laser power was varied.",
            }
        ],
    }

    estimated_tokens = extractor.estimate_paper_skim_prompt_tokens(payload)

    assert estimated_tokens > 1_000
    assert client.beta.chat.completions.calls == []
    assert client.chat.completions.calls == []


def test_paper_skim_provider_length_finish_skips_whole_window_json_repair():
    completion = SimpleNamespace(
        usage=SimpleNamespace(completion_tokens=4096),
    )
    client = _FakeOpenAIClient(
        '{"studies":[]}',
        parse_error=LengthFinishReasonError(completion=completion),
    )
    extractor = ObjectiveExtractor(client=client, model="fake-model")

    with pytest.raises(PaperSkimOutputSaturatedError):
        extractor.extract_paper_skim(
            {
                "document_id": "paper-1",
                "title": "Density study",
                "window_id": "results-1",
                "window_role": "results",
                "source_units": [],
            }
        )

    assert len(client.beta.chat.completions.calls) == 1
    assert client.chat.completions.calls == []


def test_paper_skim_json_length_finish_skips_whole_window_json_repair():
    client = _FakeOpenAIClient('{"studies":[]}')

    def create_with_length_finish(**kwargs):  # noqa: ANN003
        client.chat.completions.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(content='{"studies":[]}'),
                )
            ]
        )

    client.chat.completions.create = create_with_length_finish
    extractor = ObjectiveExtractor(
        client=client,
        model="fake-model",
        extraction_mode="json_text",
    )

    with pytest.raises(PaperSkimOutputSaturatedError):
        extractor.extract_paper_skim(
            {
                "document_id": "paper-1",
                "title": "Density study",
                "window_id": "results-1",
                "window_role": "results",
                "source_units": [],
            }
        )

    assert len(client.chat.completions.calls) == 1


def test_domain_model_extractors_synthesizes_goal_findings_with_distinct_trace():
    parsed = StructuredFindingSynthesis(findings=[])
    client = _FakeOpenAIClient("unused", parsed=parsed)
    extractor = ObjectiveExtractor(client=client, model="fake-model")
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
    assert trace["prompt_version"] == "finding_synthesis.v8"
    assert trace["parsed_output"] == {"findings": []}


def test_domain_model_extractors_bounds_json_text_finding_synthesis_output():
    client = _FakeOpenAIClient('{"findings": []}')
    extractor = _objective_extractor(client)

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
    assert "Do not output limitations" in normalized_system_prompt
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


def test_finding_synthesis_prompt_excludes_excerpt_only_numbers_during_repair():
    payload = {
        "objective": {
            "question": "How does laser power affect relative density?",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        },
        "result_set": {
            "result_set_id": "result-set-density",
            "factors": ["laser power"],
            "outcome": "relative density",
            "result_evidence": [
                {
                    "evidence_id": "density-160-200",
                    "source_excerpt": (
                        "At 160 W relative density was 96.1%, while at 200 W "
                        "it reached 98.7%."
                    ),
                    "changed_variables": [
                        {
                            "name": "laser power",
                            "baseline_value": 160,
                            "target_value": 200,
                            "unit": "W",
                        }
                    ],
                    "reported_result": {
                        "outcome": "relative density",
                        "value": 98.7,
                        "unit": "%",
                        "direction": "increase",
                        "result_text": "it reached 98.7%",
                    },
                    "attribution_scope": "isolated_effect",
                }
            ],
        },
        "paper_contributions": [],
        "context_evidence": [],
        "candidate_rejection": {
            "reason": (
                "candidate statement combines numeric values not bound to one "
                "supporting Evidence record"
            ),
            "previous_candidate": {
                "statement": (
                    "Increasing laser power from 160 W to 200 W increased "
                    "relative density from 96.1% to 98.7%."
                )
            },
        },
    }

    system_prompt, user_prompt = build_finding_synthesis_prompt(payload)
    contract = f"{system_prompt}\n{user_prompt}"

    assert "Numbers present only in `source_excerpt` are not allowed" in contract
    assert "remove every number available only in `source_excerpt`" in user_prompt
    assert "`changed_variables` endpoints" in user_prompt
    assert "`reported_result.value` or `reported_result.result_text`" in user_prompt
    assert "96.1" not in user_prompt
    assert "previous_candidate" not in user_prompt
    assert "98.7" in user_prompt


def test_finding_synthesis_prompt_treats_multiple_intervals_as_condition_series():
    payload = {
        "objective": {
            "question": "How does scan rotation affect yield strength?"
        },
        "result_set": {
            "result_set_id": "result-set-rotation",
            "factors": ["scan rotation"],
            "outcome": "yield strength",
            "result_evidence": [
                {
                    "evidence_id": "rotation-0-30",
                    "changed_variables": [
                        {
                            "name": "scan rotation",
                            "baseline_value": 0,
                            "target_value": 30,
                            "unit": "degree",
                        }
                    ],
                    "reported_result": {
                        "outcome": "yield strength",
                        "value": 515,
                        "unit": "MPa",
                        "direction": "decrease",
                    },
                },
                {
                    "evidence_id": "rotation-30-45",
                    "changed_variables": [
                        {
                            "name": "scan rotation",
                            "baseline_value": 30,
                            "target_value": 45,
                            "unit": "degree",
                        }
                    ],
                    "reported_result": {
                        "outcome": "yield strength",
                        "value": 545,
                        "unit": "MPa",
                        "direction": "increase",
                    },
                },
            ],
        },
        "paper_contributions": [],
        "context_evidence": [],
    }

    _system_prompt, user_prompt = build_finding_synthesis_prompt(payload)

    assert "one reported condition series" in user_prompt
    assert (
        "Across the reported condition series, scan rotation showed "
        "heterogeneous or opposing responses in yield strength"
    ) in user_prompt
    assert "Do not include numeric values in the statement" in user_prompt
    assert "heterogeneous or opposing across conditions" in user_prompt
    assert "source-reported result detail `515`" not in user_prompt


def test_finding_synthesis_prompt_carries_backend_semantic_rejection():
    payload = {
        "objective": {"question": "How does energy density affect density?"},
        "result_set": {
            "result_set_id": "result-set-1",
            "factors": ["energy density"],
            "outcome": "density",
            "result_evidence": [],
        },
        "candidate_rejection": {
            "reason": "candidate direction decrease has no supporting result Evidence",
            "previous_candidate": {
                "result_set_id": "result-set-1",
                "statement": "Energy density decreased density.",
                "direction": "decrease",
            },
        },
    }

    system_prompt, user_prompt = build_finding_synthesis_prompt(payload)

    assert "present only for one bounded repair attempt" in system_prompt
    assert "correction guidance, not Evidence" in system_prompt
    assert "Semantic repair required:" in user_prompt
    assert payload["candidate_rejection"]["reason"] in user_prompt
    assert "Re-read result_evidence for its exact direction" in user_prompt


def test_domain_model_extractors_allows_explicit_json_text_mode(monkeypatch):
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
    extractor = PaperFactsExtractor(client=client, model="fake-model")

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


def test_domain_model_extractors_validates_paper_skim_response():
    client = _FakeOpenAIClient(
        """
        {
          "doc_role": "experimental",
          "studies": [
            {
              "experiment_label": "LPBF heat-treatment study",
              "design_type": "experimental",
              "claim_scope": "current_work",
              "material_scope": ["316L stainless steel"],
              "process_context": ["LPBF", "heat treatment"],
              "relationships": [
                {
                  "varied_factors": ["heat treatment"],
                  "outcome": "corrosion resistance",
                  "source_unit_ids": ["window-source-1"],
                  "confidence": 0.91
                }
              ],
              "confidence": 0.91
            }
          ],
          "unresolved_signals": [],
          "evidence_density": "high",
          "confidence": 0.91,
          "warnings": []
        }
        """
    )
    extractor = _objective_extractor(client)

    skim = extractor.extract_paper_skim(
        {
            "document_id": "paper-1",
            "title": "LPBF 316L corrosion study",
            "source_units": [
                {
                    "source_unit_id": "window-source-1",
                    "source_kind": "block",
                    "source_ref": "block-1",
                    "content": "LPBF 316L was heat treated.",
                }
            ],
        }
    )

    assert isinstance(skim, StructuredPaperSkim)
    assert skim.doc_role == "experimental"
    assert skim.studies[0].material_scope == ["316L stainless steel"]
    assert skim.studies[0].relationships[0].outcome == "corrosion resistance"
    assert client.chat.completions.calls[0]["max_completion_tokens"] == 4096


def test_structured_paper_skim_rejects_duplicate_study_identities():
    study = {
        "experiment_label": "LPBF parameter study",
        "design_type": "experimental",
        "claim_scope": "current_work",
        "material_scope": ["316L stainless steel"],
        "process_context": ["LPBF"],
        "relationships": [
            {
                "varied_factors": ["laser power"],
                "outcome": "porosity",
                "source_unit_ids": ["window-source-1"],
            }
        ],
    }

    with pytest.raises(ValidationError, match="duplicate study identities"):
        StructuredPaperSkim.model_validate(
            {
                "studies": [study, study],
            }
        )


def test_paper_skim_retries_duplicate_study_identities_before_returning():
    first_study = {
        "experiment_label": "LPBF parameter study",
        "design_type": "experimental",
        "claim_scope": "current_work",
        "material_scope": ["316L stainless steel"],
        "process_context": ["LPBF"],
        "relationships": [
            {
                "varied_factors": ["laser power"],
                "outcome": "porosity",
                "source_unit_ids": ["window-source-1"],
            }
        ],
    }
    second_study = {
        **first_study,
        "relationships": [
            {
                **first_study["relationships"][0],
                "source_unit_ids": ["window-source-2"],
            }
        ],
    }
    invalid = {
        "doc_role": "experimental",
        "studies": [first_study, second_study],
        "unresolved_signals": [],
        "evidence_density": "high",
        "confidence": 0.9,
        "warnings": [],
    }
    valid = {
        **invalid,
        "studies": [
            {
                **first_study,
                "relationships": [
                    {
                        **first_study["relationships"][0],
                        "source_unit_ids": [
                            "window-source-1",
                            "window-source-2",
                        ],
                    }
                ],
            }
        ],
    }
    client = _FakeOpenAIClient([json.dumps(invalid), json.dumps(valid)])
    extractor = _objective_extractor(client)

    skim = extractor.extract_paper_skim(
        {
            "document_id": "paper-1",
            "title": "LPBF parameter study",
            "source_units": [
                {
                    "source_unit_id": "window-source-1",
                    "source_kind": "block",
                    "source_ref": "block-1",
                    "content": "Laser power was varied and porosity was measured.",
                },
                {
                    "source_unit_id": "window-source-2",
                    "source_kind": "block",
                    "source_ref": "block-1",
                    "content": "Porosity results for the laser-power series.",
                },
            ],
        }
    )

    assert len(skim.studies) == 1
    assert len(client.chat.completions.calls) == 2
    assert "duplicate study identities" in client.chat.completions.calls[1][
        "messages"
    ][-1]["content"]


def test_provider_parsed_paper_skim_repairs_duplicate_study_identities(monkeypatch):
    monkeypatch.delenv("CORE_LLM_EXTRACTION_MODE", raising=False)
    first_study = {
        "experiment_label": "LPBF parameter study",
        "design_type": "experimental",
        "claim_scope": "current_work",
        "material_scope": ["316L stainless steel"],
        "process_context": ["LPBF"],
        "relationships": [
            {
                "varied_factors": ["laser power"],
                "outcome": "porosity",
                "source_unit_ids": ["window-source-1"],
            }
        ],
    }
    second_study = {
        **first_study,
        "relationships": [
            {
                **first_study["relationships"][0],
                "source_unit_ids": ["window-source-2"],
            }
        ],
    }
    invalid = {
        "doc_role": "experimental",
        "studies": [first_study, second_study],
    }
    valid = {
        **invalid,
        "studies": [
            {
                **first_study,
                "relationships": [
                    {
                        **first_study["relationships"][0],
                        "source_unit_ids": [
                            "window-source-1",
                            "window-source-2",
                        ],
                    }
                ],
            }
        ],
    }
    client = _FakeOpenAIClient(
        json.dumps(valid),
        parsed=StructuredPaperSkim.model_validate(invalid),
    )
    extractor = ObjectiveExtractor(client=client, model="fake-model")

    skim = extractor.extract_paper_skim(
        {
            "document_id": "paper-1",
            "title": "LPBF parameter study",
            "source_units": [
                {
                    "source_unit_id": source_unit_id,
                    "source_kind": "block",
                    "source_ref": "block-1",
                    "content": content,
                }
                for source_unit_id, content in (
                    ("window-source-1", "Laser power was varied."),
                    ("window-source-2", "Porosity was measured."),
                )
            ],
        }
    )

    assert len(skim.studies) == 1
    assert len(client.beta.chat.completions.calls) == 1
    assert len(client.chat.completions.calls) == 1
    assert (
        extractor.consume_last_trace()["extraction_mode"]
        == "provider_parse->json_text"
    )


def test_paper_skim_preserves_multi_material_multi_outcome_study():
    client = _FakeOpenAIClient(
        json.dumps(
            {
                "doc_role": "experimental",
                "studies": [
                    {
                        "experiment_label": "base plate preheating study",
                        "design_type": "experimental",
                        "claim_scope": "current_work",
                        "material_scope": [
                            "Al7075",
                            "Hastelloy X",
                            "H13 tool steel",
                            "CoCr",
                        ],
                        "process_context": ["selective laser melting"],
                        "relationships": [
                            {
                                "varied_factors": [
                                    "base plate preheating temperature"
                                ],
                                "outcome": outcome,
                                "source_unit_ids": ["window-source-1"],
                                "confidence": 0.92,
                            }
                            for outcome in (
                                "part density",
                                "crack formation",
                                "internal stresses",
                                "microstructure",
                                "mechanical properties",
                            )
                        ],
                        "confidence": 0.92,
                    }
                ],
                "unresolved_signals": [],
                "evidence_density": "high",
                "confidence": 0.92,
                "warnings": [
                    "Material names are taken from the study overview and should be "
                    "verified against the material-specific experiment sections."
                ],
            }
        )
    )
    extractor = _objective_extractor(client)

    skim = extractor.extract_paper_skim(
        {
            "document_id": "paper-1",
            "title": "Application of base plate preheating during selective laser melting",
            "source_units": [
                {
                    "source_unit_id": "window-source-1",
                    "source_kind": "block",
                    "source_ref": "block-1",
                    "content": "Base plate preheating was applied to four materials.",
                }
            ],
        }
    )

    study = skim.studies[0]
    assert study.material_scope == [
        "Al7075",
        "Hastelloy X",
        "H13 tool steel",
        "CoCr",
    ]
    assert [relationship.outcome for relationship in study.relationships] == [
        "part density",
        "crack formation",
        "internal stresses",
        "microstructure",
        "mechanical properties",
    ]
    assert len(skim.warnings[0]) <= 240


def test_paper_skim_retries_oversized_study_without_truncating_relationships():
    invalid = {
        "doc_role": "experimental",
        "studies": [
            {
                "design_type": "experimental",
                "claim_scope": "current_work",
                "material_scope": [f"material-{index}" for index in range(9)],
                "process_context": ["selective laser melting"],
                "relationships": [
                    {
                        "varied_factors": ["preheating temperature"],
                        "outcome": "density",
                        "source_unit_ids": ["window-source-1"],
                        "confidence": 0.8,
                    }
                ],
                "confidence": 0.8,
            }
        ],
        "unresolved_signals": [],
        "evidence_density": "medium",
        "confidence": 0.8,
        "warnings": [],
    }
    valid = {
        **invalid,
        "studies": [
            {
                **invalid["studies"][0],
                "material_scope": [f"material-{index}" for index in range(8)],
            },
            {
                "design_type": "experimental",
                "claim_scope": "current_work",
                "material_scope": ["material-9"],
                "process_context": ["selective laser melting"],
                "relationships": [
                    {
                        "varied_factors": ["scan speed"],
                        "outcome": "porosity",
                        "source_unit_ids": ["window-source-1"],
                        "confidence": 0.75,
                    }
                ],
                "confidence": 0.75,
            },
        ],
    }
    client = _FakeOpenAIClient(
        [json.dumps(invalid), json.dumps(valid)]
    )
    extractor = _objective_extractor(client)

    skim = extractor.extract_paper_skim(
        {
            "document_id": "paper-1",
            "title": "Multi-material preheating study",
            "source_units": [
                {
                    "source_unit_id": "window-source-1",
                    "source_kind": "block",
                    "source_ref": "block-1",
                    "content": "Preheating was evaluated across several materials.",
                }
            ],
        }
    )

    assert len(skim.studies) == 2
    assert skim.studies[0].material_scope == [
        f"material-{index}" for index in range(8)
    ]
    assert skim.studies[1].relationships[0].varied_factors == ["scan speed"]
    assert len(client.chat.completions.calls) == 2


def test_domain_model_extractors_validates_paper_signal_reconciliation():
    client = _FakeOpenAIClient(
        json.dumps(
            {
                "studies": [
                    {
                        "relationships": [
                            {
                                "signal_ids": [
                                    "signal-variable",
                                    "signal-outcome",
                                ],
                                "confidence": 0.89,
                            }
                        ]
                    }
                ],
                "unresolved_signals": [],
            }
        )
    )
    extractor = _objective_extractor(client)

    reconciliation = extractor.reconcile_paper_signals(
        {
            "document_id": "paper-1",
            "signals": [
                {"signal_id": "signal-variable", "signal_type": "variable"},
                {"signal_id": "signal-outcome", "signal_type": "outcome"},
            ],
        }
    )

    assert isinstance(reconciliation, StructuredPaperSignalReconciliation)
    assert reconciliation.studies[0].relationships[0].signal_ids == [
        "signal-variable",
        "signal-outcome",
    ]
    assert client.chat.completions.calls[0]["max_completion_tokens"] == 4096


@pytest.mark.parametrize(
    ("context_field", "variable_context", "outcome_context"),
    [
        ("material_scope", ["316L stainless steel"], ["Ti-6Al-4V"]),
        ("process_context", ["laser powder bed fusion"], ["heat treatment"]),
        ("sample_context", ["as-built specimen"], ["annealed specimen"]),
        ("test_context", ["tensile test"], ["corrosion test"]),
    ],
)
def test_paper_signal_reconciliation_repairs_conflicting_contexts(
    context_field,
    variable_context,
    outcome_context,
):
    invalid = {
        "studies": [
            {
                "relationships": [
                    {
                        "signal_ids": ["signal-variable", "signal-outcome"],
                        "confidence": 0.89,
                    }
                ]
            }
        ],
        "unresolved_signals": [],
    }
    repaired = {
        "studies": [],
        "unresolved_signals": [
            {
                "signal_id": "signal-variable",
                "reason": "The signals describe different experimental contexts.",
            },
            {
                "signal_id": "signal-outcome",
                "reason": "The signals describe different experimental contexts.",
            },
        ],
    }
    client = _FakeOpenAIClient([json.dumps(invalid), json.dumps(repaired)])
    extractor = _objective_extractor(client)

    reconciliation = extractor.reconcile_paper_signals(
        {
            "document_id": "paper-1",
            "signals": [
                {
                    "signal_id": "signal-variable",
                    "signal_type": "variable",
                    context_field: variable_context,
                },
                {
                    "signal_id": "signal-outcome",
                    "signal_type": "outcome",
                    context_field: outcome_context,
                },
            ],
        }
    )

    assert reconciliation.studies == []
    assert len(reconciliation.unresolved_signals) == 2
    assert len(client.chat.completions.calls) == 2
    repair_prompt = client.chat.completions.calls[1]["messages"][-1]["content"]
    assert "context-compatible" in repair_prompt
    assert context_field in repair_prompt


def test_provider_parsed_signal_reconciliation_repairs_conflicting_contexts(
    monkeypatch,
):
    monkeypatch.delenv("CORE_LLM_EXTRACTION_MODE", raising=False)
    invalid = StructuredPaperSignalReconciliation.model_validate(
        {
            "studies": [
                {
                    "relationships": [
                        {
                            "signal_ids": ["signal-variable", "signal-outcome"],
                            "confidence": 0.89,
                        }
                    ]
                }
            ]
        }
    )
    repaired = {
        "studies": [],
        "unresolved_signals": [
            {
                "signal_id": signal_id,
                "reason": "The signals describe different material contexts.",
            }
            for signal_id in ("signal-variable", "signal-outcome")
        ],
    }
    client = _FakeOpenAIClient(json.dumps(repaired), parsed=invalid)
    extractor = ObjectiveExtractor(client=client, model="fake-model")

    reconciliation = extractor.reconcile_paper_signals(
        {
            "document_id": "paper-1",
            "signals": [
                {
                    "signal_id": "signal-variable",
                    "signal_type": "variable",
                    "material_scope": ["316L stainless steel"],
                },
                {
                    "signal_id": "signal-outcome",
                    "signal_type": "outcome",
                    "material_scope": ["Ti-6Al-4V"],
                },
            ],
        }
    )

    assert reconciliation.studies == []
    assert len(reconciliation.unresolved_signals) == 2
    assert len(client.beta.chat.completions.calls) == 1
    assert len(client.chat.completions.calls) == 1
    repair_prompt = client.chat.completions.calls[0]["messages"][-1]["content"]
    assert "context-compatible" in repair_prompt
    assert "material_scope" in repair_prompt


def test_unrepaired_signal_context_conflict_keeps_valid_relationships():
    invalid = {
        "studies": [
            {
                "relationships": [
                    {
                        "signal_ids": ["signal-variable", "signal-outcome"],
                        "confidence": 0.9,
                    },
                    {
                        "signal_ids": [
                            "signal-conflicting-variable",
                            "signal-outcome",
                        ],
                        "confidence": 0.8,
                    },
                ]
            }
        ],
        "unresolved_signals": [],
    }
    client = _FakeOpenAIClient([json.dumps(invalid), json.dumps(invalid)])
    extractor = _objective_extractor(client)

    reconciliation = extractor.reconcile_paper_signals(
        {
            "document_id": "paper-1",
            "signals": [
                {
                    "signal_id": "signal-variable",
                    "signal_type": "variable",
                    "process_context": ["laser powder bed fusion"],
                },
                {
                    "signal_id": "signal-conflicting-variable",
                    "signal_type": "variable",
                    "process_context": ["heat treatment"],
                },
                {
                    "signal_id": "signal-outcome",
                    "signal_type": "outcome",
                    "process_context": ["laser powder bed fusion"],
                },
            ],
        }
    )

    assert len(reconciliation.studies) == 1
    assert len(reconciliation.studies[0].relationships) == 1
    assert reconciliation.studies[0].relationships[0].signal_ids == [
        "signal-variable",
        "signal-outcome",
    ]
    assert [
        signal.signal_id for signal in reconciliation.unresolved_signals
    ] == ["signal-conflicting-variable"]
    assert "process_context" in reconciliation.unresolved_signals[0].reason
    assert len(client.chat.completions.calls) == 2


def test_domain_model_extractors_validates_axis_canonicalization_response():
    client = _FakeOpenAIClient(
        """
        {
          "decisions": [
            {"pair_id": "axis_pair_0001", "equivalent": true}
          ]
        }
        """
    )
    extractor = _objective_extractor(client)

    canonicalization_plan = extractor.canonicalize_research_objective_axes(
        {
            "collection_id": "col-1",
            "axis_pairs": [
                {
                    "pair_id": "axis_pair_0001",
                    "axis_type": "variable",
                    "left": "scanning strategy",
                    "right": "scan strategy",
                }
            ],
        }
    )

    assert isinstance(canonicalization_plan, StructuredAxisCanonicalizationPlan)
    assert [item.model_dump() for item in canonicalization_plan.decisions] == [
        {"pair_id": "axis_pair_0001", "equivalent": True}
    ]


def test_axis_canonicalization_repairs_ungrounded_and_overlapping_groups():
    invalid = json.dumps(
        {
            "decisions": [
                {"pair_id": "axis_pair_9999", "equivalent": True},
                {"pair_id": "axis_pair_9999", "equivalent": False},
            ]
        }
    )
    repaired = json.dumps(
        {
            "decisions": [
                {"pair_id": "axis_pair_0001", "equivalent": True},
                {"pair_id": "axis_pair_0002", "equivalent": False},
            ]
        }
    )
    client = _FakeOpenAIClient([invalid, repaired])
    extractor = _objective_extractor(client)

    plan = extractor.canonicalize_research_objective_axes(
        {
            "collection_id": "col-1",
            "axis_pairs": [
                {
                    "pair_id": "axis_pair_0001",
                    "axis_type": "material",
                    "left": "316L stainless steel",
                    "right": "SS316L",
                },
                {
                    "pair_id": "axis_pair_0002",
                    "axis_type": "variable",
                    "left": "scan speed",
                    "right": "scanning speed",
                },
            ],
        }
    )

    assert len(client.chat.completions.calls) == 2
    assert [item.model_dump() for item in plan.decisions] == [
        {"pair_id": "axis_pair_0001", "equivalent": True},
        {"pair_id": "axis_pair_0002", "equivalent": False},
    ]
    repair_prompt = client.chat.completions.calls[1]["messages"][-1]["content"]
    assert "axis pair classification" in repair_prompt
    assert "equivalent=false" in repair_prompt


def test_domain_model_extractors_validates_objective_paper_frame_response():
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
    extractor = _objective_extractor(client)

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


def test_domain_model_extractors_validates_objective_evidence_routes_response():
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
    extractor = _objective_extractor(client)

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


def test_domain_model_extractors_rejects_legacy_objective_route_batches():
    client = _FakeOpenAIClient('{"selections": []}')
    extractor = _objective_extractor(client)

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


def test_domain_model_extractors_rejects_verbose_objective_route_objects():
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
    extractor = _objective_extractor(client)

    with pytest.raises(ValidationError):
        extractor.select_objective_evidence(
            {
                "collection_id": "col-1",
                "objective": {"question": "How does heat treatment affect corrosion?"},
                "paper_frame": {"frame_id": "opf-1"},
                "current_source": {"source_kind": "table", "source_ref": "table-1"},
            }
        )


def test_domain_model_extractors_rejects_source_ids_in_objective_routes():
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
    extractor = _objective_extractor(client)

    with pytest.raises(ValidationError):
        extractor.select_objective_evidence(
            {
                "collection_id": "col-1",
                "objective": {"question": "How does heat treatment affect corrosion?"},
                "paper_frame": {"frame_id": "opf-1"},
                "current_source": {"source_kind": "table", "source_ref": "table-1"},
            }
        )


def test_domain_model_extractors_validates_objective_evidence_response():
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
    extractor = _objective_extractor(client)

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
    assert client.chat.completions.calls[0]["max_completion_tokens"] == 2048


def test_structured_objective_evidence_normalizes_compact_context_attributes():
    context = StructuredEvidenceContext.model_validate(
        {
            "material": ["316L stainless steel"],
            "sample": [
                {
                    "name": "cylindrical specimen",
                    "shape": "cylindrical",
                    "size": "10 mm diameter x 10 mm height",
                }
            ],
            "process": [
                {
                    "name": "hatch spacing",
                    "value": [0.12, 0.111],
                    "unit": "mm",
                }
            ],
            "test": [
                {
                    "name": "density measurement",
                    "method": "Archimedes",
                }
            ],
        }
    )

    assert context.material[0].model_dump() == {
        "name": "material",
        "value": "316L stainless steel",
        "unit": None,
    }
    assert json.loads(str(context.sample[0].value)) == {
        "shape": "cylindrical",
        "size": "10 mm diameter x 10 mm height",
    }
    assert json.loads(str(context.process[0].value)) == [0.12, 0.111]
    assert json.loads(str(context.test[0].value)) == {"method": "Archimedes"}


def test_structured_objective_evidence_repairs_single_variable_joint_effect():
    extraction = StructuredEvidenceExtraction.model_validate(
        {
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "energy density",
                    "baseline_value": 70,
                    "target_value": 150,
                    "unit": "J/mm3",
                }
            ],
            "comparison": {
                "baseline_label": "70 J/mm3",
                "target_label": "150 J/mm3",
                "axis_names": ["energy density"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "relative density",
                "value": 99.5,
                "unit": "%",
                "direction": "increase",
                "result_text": "Relative density increased to 99.5%.",
            },
            "attribution_scope": "joint_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    assert extraction.attribution_scope == "isolated_effect"


def test_structured_objective_evidence_rejects_repeated_variable_intervals():
    with pytest.raises(
        ValidationError,
        match="changed variable names must be unique per extraction",
    ):
        StructuredEvidenceExtraction.model_validate(
            {
                "evidence_role": "direct_result",
                "changed_variables": [
                    {
                        "name": "laser power",
                        "baseline_value": 160,
                        "target_value": 200,
                        "unit": "W",
                    },
                    {
                        "name": "laser power",
                        "baseline_value": 160,
                        "target_value": 240,
                        "unit": "W",
                    },
                ],
                "comparison": {
                    "baseline_label": "160 W",
                    "target_label": "200 W and 240 W",
                    "axis_names": ["laser power"],
                    "comparable": True,
                },
                "reported_result": {
                    "outcome": "relative density",
                    "value": 99.1,
                    "unit": "%",
                    "direction": "increase",
                    "result_text": "Relative density increased to 99.1%.",
                },
                "attribution_scope": "joint_effect",
                "scientific_context": {},
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )


def test_structured_objective_evidence_downgrades_unbound_experimental_attribution():
    extraction = StructuredEvidenceExtraction.model_validate(
        {
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "energy density",
                    "baseline_value": None,
                    "target_value": 150,
                    "unit": "J/mm3",
                }
            ],
            "comparison": {
                "baseline_label": "lower energy density",
                "target_label": "150 J/mm3",
                "axis_names": ["energy density"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "relative density",
                "value": 99.5,
                "unit": "%",
                "direction": "increase",
                "result_text": "Relative density increased to 99.5%.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )

    assert extraction.attribution_scope == "association_only"


def test_domain_model_extractors_ignores_top_level_prompt_echo_for_evidence():
    response = json.dumps(
        {
            "extractions": [
                {
                    "evidence_role": "direct_result",
                    "changed_variables": [],
                    "comparison": None,
                    "reported_result": {
                        "outcome": "relative density",
                        "value": 99.5,
                        "unit": "%",
                        "direction": "unknown",
                        "result_text": "Relative density reached 99.5%.",
                    },
                    "attribution_scope": "descriptive_only",
                    "scientific_context": {},
                    "resolution_status": "resolved",
                    "confidence": 0.9,
                }
            ],
            "OBJECTIVE": "How does energy density affect relative density?",
            "SOURCE KIND": "text_window",
            "SOURCE": "Relative density reached 99.5%.",
        }
    )
    extractor = _objective_extractor(_FakeOpenAIClient(response))

    parsed = extractor.extract_objective_evidence(
        {
            "objective": {
                "question": "How does energy density affect relative density?"
            },
            "evidence_route": {
                "source_kind": "text_window",
                "source_ref": "block-1",
            },
            "source": {
                "source_kind": "text_window",
                "source_ref": "block-1",
                "text": "Relative density reached 99.5%.",
            },
        }
    )

    assert len(parsed.extractions) == 1
    assert parsed.extractions[0].reported_result is not None


def test_domain_model_extractors_rejects_unknown_top_level_evidence_fields():
    response = json.dumps(
        {
            "extractions": [],
            "unexpected_model_field": "must not be silently discarded",
        }
    )
    client = _FakeOpenAIClient(response)
    extractor = _objective_extractor(client)

    with pytest.raises(ValidationError):
        extractor.extract_objective_evidence(
            {
                "objective": {
                    "question": "How does energy density affect relative density?"
                },
                "evidence_route": {
                    "source_kind": "text_window",
                    "source_ref": "block-1",
                },
                "source": {
                    "source_kind": "text_window",
                    "source_ref": "block-1",
                    "text": "Relative density reached 99.5%.",
                },
            }
        )

    assert len(client.chat.completions.calls) == 2


def test_domain_model_extractors_rejects_prompt_only_evidence_echo():
    response = json.dumps(
        {
            "OBJECTIVE": "How does energy density affect relative density?",
            "OBJECTIVE VARIABLES": ["energy density"],
            "OBJECTIVE OUTCOMES": ["relative density"],
            "ROUTE HINT ONLY (DO NOT COPY AS EVIDENCE ROLE)": (
                "process_or_treatment"
            ),
            "SOURCE KIND": "text_window",
            "SOURCE": "Relative density reached 99.5%.",
        }
    )
    client = _FakeOpenAIClient(response)
    extractor = _objective_extractor(client)

    with pytest.raises(ValueError, match="echoed input fields"):
        extractor.extract_objective_evidence(
            {
                "objective": {
                    "question": "How does energy density affect relative density?"
                },
                "evidence_route": {
                    "source_kind": "text_window",
                    "source_ref": "block-1",
                },
                "source": {
                    "source_kind": "text_window",
                    "source_ref": "block-1",
                    "text": "Relative density reached 99.5%.",
                },
            }
        )

    assert len(client.chat.completions.calls) == 2
    assert "only echoed the input fields" in client.chat.completions.calls[1][
        "messages"
    ][-1]["content"]


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
            "paper_frame": {"background": "must not become evidence"},
            "evidence_route": {
                "source_kind": "text_window",
                "source_ref": "block-1",
            },
            "document_state": {"prior_value": "must not be copied"},
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

    assert "Extract at most one objective-relevant fact" in system_prompt
    assert "`SOURCE` is the only scientific authority" in system_prompt
    assert "Return at most one extraction" in system_prompt
    assert "one top-level key: `extractions`" in system_prompt
    assert "1.43x10^6 C/s for P150" in prompt
    assert "1.65x10^6 C/s for NP" in prompt
    assert "OUTPUT JSON:" in prompt
    assert "collection_id" not in prompt
    assert "paper_frame" not in prompt
    assert "document_state" not in prompt
    assert "must not become evidence" not in prompt
    assert "must not be copied" not in prompt
    assert "Identify every changed" in system_prompt
    assert "exact source group labels" in system_prompt
    assert "absent, off, or without condition to numeric 0" in system_prompt
    assert "one baseline-to-target comparison interval" in system_prompt
    assert "Never repeat a changed-variable name" in system_prompt
    assert "choose one complete source-supported pair" in system_prompt
    assert "Context source" in system_prompt
    assert "numeric `confidence` for every extraction" in system_prompt
    assert "Generic composition or background" in system_prompt
    assert "Unrelated composition example" in system_prompt


def test_domain_model_extractors_rejects_backend_bound_objective_evidence_fields():
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
    extractor = _objective_extractor(client)

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


def test_domain_model_extractors_sanitizes_json_text_and_coerces_text_window_enums():
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
    extractor = _paper_facts_extractor(client)

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


def test_domain_model_extractors_accepts_null_result_property_names():
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
    extractor = _paper_facts_extractor(client)

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


def test_domain_model_extractors_caps_provider_parse_completion_tokens_for_table_batches(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    client = _FakeOpenAIClient("unused", parsed=StructuredTableBatchMentions())
    extractor = PaperFactsExtractor(client=client, model="fake-model")

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


def test_domain_model_extractors_routes_document_profiles_directly_to_bounded_json_text(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    client = _FakeOpenAIClient(
        '{"doc_type":"experimental","parsing_warnings":[],"confidence":0.91}'
    )
    extractor = DocumentProfileExtractor(client=client, model="fake-model")

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


def test_domain_model_extractors_can_opt_in_to_provider_thinking(monkeypatch):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    monkeypatch.setenv("LLM_ENABLE_THINKING", "true")
    client = _FakeOpenAIClient("unused", parsed=StructuredTableBatchMentions())
    extractor = PaperFactsExtractor(client=client, model="fake-model")

    extractor.extract_table_batch_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental"},
            "target_rows": [],
            "supporting_text_windows": [],
        }
    )

    assert "extra_body" not in client.beta.chat.completions.calls[0]


def test_domain_model_extractors_routes_objective_selections_directly_to_bounded_json_text(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    client = _FakeOpenAIClient('{"selections":[]}')
    extractor = ObjectiveExtractor(client=client, model="fake-model")

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


def test_domain_model_extractors_routes_objective_units_through_bounded_json_text(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    client = _FakeOpenAIClient(
        '{"extractions":[]}',
        parsed=StructuredEvidenceExtractions(),
    )
    extractor = ObjectiveExtractor(client=client, model="fake-model")

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
    assert text_call["max_completion_tokens"] == 2048
    assert text_call["response_format"]["type"] == "json_schema"
    assert text_call["response_format"]["json_schema"]["name"] == (
        "structured_evidence_extractions"
    )
    assert text_call["response_format"]["json_schema"]["strict"] is True
    assert text_call["response_format"]["json_schema"]["schema"] == (
        StructuredEvidenceExtractions.model_json_schema()
    )
    assert "JSON schema:" not in text_call["messages"][1]["content"]
    assert extractor.consume_last_trace()["extraction_mode"] == "json_text"


def test_objective_evidence_prompt_requires_verbatim_outcome_bound_result_text() -> None:
    system_prompt, user_prompt = build_objective_evidence_prompt(
        {
            "objective": {"outcomes": ["microstructure"]},
            "source": {"text": "P150 formed an equiaxed cellular structure."},
        }
    )

    contract = f"{system_prompt}\n{user_prompt}"

    assert "verbatim substring" in contract
    assert "direction describes the objective outcome" in contract
    assert "Use `mixed` for an unordered qualitative change" in contract
    assert "mixes current work with cited literature" in contract
    assert "`incomparability_reasons` must be empty" in contract
    assert "Conditions from cited literature" in contract
    assert "TASK MODEL" in system_prompt
    assert "INPUT SCHEMA" in system_prompt
    assert "DECISION PROCESS" in system_prompt
    assert "BOUNDARY EXAMPLES" in system_prompt
    assert '{"extractions":[]}' in system_prompt
    assert "`result_text` is the only source text" in system_prompt
    assert "Do not output source excerpts" not in system_prompt


def test_domain_model_extractors_retries_with_structured_validation_error(monkeypatch):
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
    extractor = ObjectiveExtractor(client=client, model="fake-model")

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
    assert "Return at most one schema-valid extraction" in repair_prompt
    assert "distinct changed-variable name" in repair_prompt
    assert "Never repeat a changed-variable name" in repair_prompt
    assert "one complete source-supported pair" in repair_prompt
    assert "For finding synthesis" not in repair_prompt



def test_domain_model_extractors_validates_lightweight_table_batch_mentions():
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
    extractor = _paper_facts_extractor(client)

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


def test_domain_model_extractors_accepts_empty_table_batch_mentions():
    client = _FakeOpenAIClient(
        """
        {
          "row_results": []
        }
        """
    )
    extractor = _paper_facts_extractor(client)

    mentions = extractor.extract_table_batch_mentions(
        {
            "document_title": "LPBF Paper",
            "document_profile": {"doc_type": "experimental"},
            "target_rows": [{"row_index": 1, "row_summary": "Sample A | no grounded result", "cells": []}],
            "supporting_text_windows": [],
        }
    )

    assert mentions == StructuredTableBatchMentions()


def test_domain_model_extractors_still_rejects_unknown_table_batch_extra_keys():
    client = _FakeOpenAIClient(
        """
        {
          "keywords": ["yield strength"],
          "row_results": []
        }
        """
    )
    extractor = _paper_facts_extractor(client)

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


def test_domain_model_extractors_falls_back_to_default_for_invalid_mode(monkeypatch, caplog):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "not-a-mode")

    with caplog.at_level("WARNING"):
        extractor = ObjectiveExtractor(client=_FakeOpenAIClient("{}"), model="fake-model")

    assert extractor.extraction_mode == "provider_parse"
    assert "Invalid CORE_LLM_EXTRACTION_MODE=not-a-mode" in caplog.text
