from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
import tiktoken
from openai import LengthFinishReasonError
from pydantic import ValidationError

from application.core.document_profiles.extraction import (
    DocumentProfileExtractionError,
    DocumentProfileExtractor,
)
from application.core.document_profiles.schemas import StructuredDocumentProfile
from application.core.objectives.analysis.evidence_routing import (
    ObjectiveEvidenceRouter,
    StructuredEvidenceSelections,
)
from application.core.objectives.analysis.finding_synthesis import (
    FindingAssertionJudge,
    StructuredFindingMechanism,
    StructuredFindingSynthesis,
    build_finding_synthesis_prompt,
)
from application.core.objectives.analysis.source_extraction import (
    ObjectiveSourceExtractor,
    StructuredEvidenceContext,
    StructuredEvidenceExtraction,
    StructuredEvidenceExtractions,
    _normalize_objective_evidence_payload,
    _objective_evidence_repair_instruction,
    build_objective_evidence_prompt,
)
from application.core.objectives.analysis.source_screening import (
    ObjectiveSourceScreener,
    StructuredPaperFrameBatch,
    build_objective_paper_frame_prompt,
)
from application.core.objectives.discovery.axis_equivalence import (
    ResearchAxisEquivalenceClassifier,
    StructuredAxisCanonicalizationPlan,
    build_research_axis_canonicalization_prompt,
)
from application.core.objectives.discovery.signal_reconciliation import (
    PaperSignalReconciler,
    StructuredPaperSignalReconciliation,
    build_paper_signal_reconciliation_prompt,
)
from application.core.objectives.discovery.study_window import (
    PaperStudyWindowExtractor,
    StructuredPaperSkim,
    StructuredPaperSourceSignalScreen,
    build_paper_skim_prompt,
    build_paper_source_signal_prompt,
)
from application.core.objectives.llm.structured_response import (
    StructuredOutputSaturatedError,
    StructuredResponseClient,
)
from application.core.paper_facts.extraction import PaperFactsExtractor
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

    assert schema["studies"]["maxItems"] == 4
    assert schema["unresolved_signals"]["maxItems"] == 8
    assert schema["output_saturated"]["type"] == "boolean"
    study_schema = model_schema["$defs"]["StructuredPaperStudy"]["properties"]
    relationship_schema = model_schema["$defs"][
        "StructuredPaperStudyRelationship"
    ]["properties"]
    assert study_schema["material_scope"]["maxItems"] == 8
    assert study_schema["process_context"]["maxItems"] == 12
    assert study_schema["process_context"]["items"]["maxLength"] == 160
    assert study_schema["sample_context"]["maxItems"] == 12
    assert study_schema["sample_context"]["items"]["maxLength"] == 160
    assert study_schema["test_context"]["maxItems"] == 12
    assert study_schema["test_context"]["items"]["maxLength"] == 160
    assert study_schema["fixed_conditions"]["maxItems"] == 12
    assert study_schema["relationships"]["maxItems"] == 6
    assert relationship_schema["varied_factors"]["maxItems"] == 12
    assert relationship_schema["source_unit_ids"]["minItems"] == 1
    assert relationship_schema["source_unit_ids"]["maxItems"] == 12
    signal_schema = model_schema["$defs"]["StructuredPaperStudySignal"][
        "properties"
    ]
    assert signal_schema["signal_type"]["enum"] == ["variable", "outcome"]
    assert signal_schema["process_context"]["maxItems"] == 12
    assert signal_schema["process_context"]["items"]["maxLength"] == 160
    assert signal_schema["sample_context"]["maxItems"] == 12
    assert signal_schema["test_context"]["maxItems"] == 12
    assert signal_schema["source_unit_ids"]["minItems"] == 1
    assert signal_schema["source_unit_ids"]["maxItems"] == 12
    assert "source_unit_coverage" not in schema
    assert "StructuredPaperSourceUnitCoverage" not in model_schema.get("$defs", {})
    assert schema["warnings"]["items"]["maxLength"] == 240
    review_schema = model_schema["$defs"]["StructuredReviewSynthesisMap"][
        "properties"
    ]
    review_item_schema = model_schema["$defs"]["StructuredReviewKnowledgeItem"][
        "properties"
    ]
    assert review_schema["synthesis_claims"]["maxItems"] == 4
    assert review_schema["disputes"]["maxItems"] == 4
    assert review_schema["evidence_gaps"]["maxItems"] == 4
    assert review_schema["citation_leads"]["maxItems"] == 6
    assert review_item_schema["content"]["maxLength"] == 400
    assert review_item_schema["source_unit_ids"]["minItems"] == 1
    assert review_item_schema["source_unit_ids"]["maxItems"] == 4


def test_paper_source_signal_screen_contract_is_source_local_and_compact():
    model_schema = StructuredPaperSourceSignalScreen.model_json_schema()
    schema = model_schema["properties"]
    signal_schema = model_schema["$defs"]["StructuredPaperSourceSignal"][
        "properties"
    ]

    assert schema["signals"]["maxItems"] == 12
    assert schema["output_saturated"]["type"] == "boolean"
    assert signal_schema["signal_type"]["enum"] == ["variable", "outcome"]
    assert signal_schema["material_scope"]["maxItems"] == 4
    assert signal_schema["process_context"]["maxItems"] == 4
    assert signal_schema["sample_context"]["maxItems"] == 4
    assert signal_schema["test_context"]["maxItems"] == 4
    assert signal_schema["fixed_conditions"]["maxItems"] == 4
    assert "source_unit_ids" not in signal_schema
    assert "relationships" not in schema
    assert "studies" not in schema


@pytest.mark.parametrize(
    ("left_context", "right_context"),
    [
        ({"design_type": "experimental"}, {"design_type": "observational"}),
        ({"comparator": "as-built"}, {"comparator": "heat-treated"}),
        (
            {"fixed_conditions": ["room temperature"]},
            {"fixed_conditions": ["400 C"]},
        ),
    ],
)
def test_paper_source_signal_identity_preserves_distinct_experiment_context(
    left_context: dict[str, object],
    right_context: dict[str, object],
):
    common = {
        "signal_type": "outcome",
        "label": "yield strength",
        "experiment_label": "tensile test",
        "claim_scope": "current_work",
        "material_scope": ["Ti-6Al-4V"],
    }

    parsed = StructuredPaperSourceSignalScreen.model_validate(
        {
            "signals": [
                {**common, **left_context},
                {**common, **right_context},
            ]
        }
    )

    assert len(parsed.signals) == 2


def test_paper_source_signal_screen_isolates_one_malformed_signal():
    parsed = StructuredPaperSourceSignalScreen.model_validate(
        {
            "signals": [
                {"signal_type": "variable", "label": "reheating cycle"},
                {"signal_type": "outcome", "label": "grain morphology"},
                {
                    "signal_type": "outcome",
                    "label": "a complete observation sentence " * 4,
                },
            ]
        }
    )

    assert [signal.label for signal in parsed.signals] == [
        "reheating cycle",
        "grain morphology",
    ]
    assert parsed.output_saturated is False
    assert parsed.warnings == [
        (
            "Omitted 1 malformed source signal; retained the valid source-local "
            "signals."
        )
    ]


def test_paper_source_signal_screen_marks_all_malformed_signals_incomplete():
    parsed = StructuredPaperSourceSignalScreen.model_validate(
        {
            "signals": [
                {
                    "signal_type": "outcome",
                    "label": "a complete observation sentence " * 4,
                }
            ]
        }
    )

    assert parsed.signals == []
    assert parsed.output_saturated is True


def test_paper_source_signal_prompt_preserves_review_and_primary_source_roles():
    _, user_prompt = build_paper_source_signal_prompt(
        {
            "document_id": "review-paper",
            "title": "Heat treatment review",
            "window_id": "results-1.retry-left",
            "window_role": "results",
            "source_units": [
                {
                    "source_unit_id": "source-unit-000071",
                    "source_kind": "block",
                    "source_ref": "block-71",
                    "section_path": "Review > Preheating",
                    "content": (
                        "Miranda et al. increased build plate temperature and "
                        "reported lower residual stress."
                    ),
                }
            ],
        }
    )

    assert "source-local scientific signal screening" in user_prompt
    assert "not relationship construction" in user_prompt
    assert "paper-level reconciliation" in user_prompt
    assert "claim_scope=background" in user_prompt
    assert "claim_scope=current_work" in user_prompt
    assert "Do not return or copy Source-unit IDs" in user_prompt
    assert "Do not infer a causal relationship" in user_prompt
    assert "Miranda et al." in user_prompt
    assert "phase, grain shape, or other observation on that axis" in user_prompt
    assert "outcome='microstructure'" in user_prompt
    assert "do not also return 'mechanical properties'" in user_prompt
    assert "'etc.' or 'including' do not name hidden axes" in user_prompt
    assert "only when more than 12 distinct explicit research axes" in user_prompt


def test_paper_source_signal_screen_binds_source_identity_in_backend():
    client = _FakeOpenAIClient(
        json.dumps(
            {
                "doc_role": "review",
                "signals": [
                    {
                        "signal_type": "variable",
                        "label": "build plate temperature",
                        "experiment_label": "Miranda et al.",
                        "claim_scope": "background",
                        "material_scope": ["Ti-6Al-4V"],
                        "process_context": ["laser powder bed fusion"],
                        "confidence": 0.88,
                    },
                    {
                        "signal_type": "outcome",
                        "label": "residual stress",
                        "experiment_label": "Miranda et al.",
                        "claim_scope": "background",
                        "material_scope": ["Ti-6Al-4V"],
                        "process_context": ["laser powder bed fusion"],
                        "confidence": 0.86,
                    },
                ],
                "evidence_density": "medium",
                "confidence": 0.87,
            }
        )
    )
    extractor = PaperStudyWindowExtractor(_response_client(client))

    skim = extractor.extract_source_signals(
        {
            "document_id": "review-paper",
            "window_id": "results-1.retry-left",
            "window_role": "results",
            "source_units": [
                {
                    "source_unit_id": "source-unit-000071",
                    "source_kind": "block",
                    "source_ref": "block-71",
                    "section_path": "Review > Preheating",
                    "content": (
                        "Miranda et al. increased build plate temperature and "
                        "reported lower residual stress."
                    ),
                }
            ],
        }
    )

    assert skim.studies == []
    assert skim.doc_role == "review"
    assert [signal.claim_scope for signal in skim.unresolved_signals] == [
        "background",
        "background",
    ]
    assert [signal.source_unit_ids for signal in skim.unresolved_signals] == [
        ["source-unit-000071"],
        ["source-unit-000071"],
    ]
    assert client.chat.completions.calls[0]["max_completion_tokens"] == 2048


def test_paper_skim_contract_represents_a_full_bounded_experiment_context():
    sample_context = [
        f"HIP condition {index}: temperature, pressure, and cooling schedule"
        for index in range(1, 12)
    ]
    varied_factors = [
        "HIP temperature",
        "HIP pressure",
        "cooling rate",
        "prior beta grain size",
        "alpha lath thickness",
        "alpha phase fraction",
        "beta phase fraction",
        "pore fraction",
        "pore diameter",
        "build orientation",
    ]

    parsed = StructuredPaperSkim.model_validate(
        {
            "studies": [
                {
                    "process_context": [
                        "laser powder bed fusion",
                        "hot isostatic pressing",
                        "sandblasting",
                        "mechanical polishing",
                        "chemical etching",
                    ],
                    "sample_context": sample_context,
                    "test_context": [
                        "room-temperature tensile testing",
                        "optical microscopy",
                        "scanning electron microscopy",
                        "electron backscatter diffraction",
                        "X-ray computed tomography",
                    ],
                    "relationships": [
                        {
                            "varied_factors": varied_factors,
                            "outcome": "yield strength",
                            "source_unit_ids": ["table-8"],
                        }
                    ],
                }
            ]
        }
    )

    assert parsed.studies[0].sample_context == sample_context
    assert parsed.studies[0].relationships[0].varied_factors == varied_factors


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


def test_paper_signal_reconciliation_contract_is_bounded_to_one_neighborhood():
    model_schema = StructuredPaperSignalReconciliation.model_json_schema()
    response_schema = model_schema["properties"]
    study_schema = model_schema["$defs"]["StructuredPaperSignalStudy"]["properties"]

    assert response_schema["studies"]["maxItems"] == 1
    assert response_schema["unresolved_signals"]["maxItems"] == 12
    assert study_schema["relationships"]["maxItems"] == 11


def test_paper_signal_reconciliation_bounds_diagnostic_reason_text():
    parsed = StructuredPaperSignalReconciliation.model_validate(
        {
            "studies": [],
            "unresolved_signals": [
                {
                    "signal_id": "signal-outcome",
                    "reason": "reason " * 100,
                }
            ],
        }
    )

    assert len(parsed.unresolved_signals[0].reason) == 240


def test_paper_skim_contract_bounds_diagnostic_warnings():
    parsed = StructuredPaperSkim.model_validate(
        {"warnings": ["w" * 241, "second", "third"]}
    )

    assert parsed.warnings == ["w" * 240, "second"]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "studies": [
                {
                    "relationships": [
                        {
                            "varied_factors": ["laser power"],
                            "outcome": "relative density",
                            "source_unit_ids": ["source-1", "source-1"],
                        }
                    ]
                }
            ]
        },
        {
            "unresolved_signals": [
                {
                    "signal_type": "variable",
                    "label": "laser power",
                    "source_unit_ids": ["source-1", "source-1"],
                }
            ]
        },
    ],
)
def test_paper_skim_contract_rejects_duplicate_source_unit_ids(payload):
    with pytest.raises(ValidationError, match="source-unit ids must be unique"):
        StructuredPaperSkim.model_validate(payload)


def test_paper_skim_prompt_defines_lightweight_research_map_contract():
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
    assert "Map the paper's stated research scope" in user_prompt
    assert "not full experiment reconstruction" in user_prompt
    assert "candidate scope, not proven Evidence" in user_prompt
    assert "Leave sample_context, test_context, comparator, and fixed_conditions empty" in user_prompt
    assert "`window_id` is this bounded window's identity" in user_prompt
    assert "absence from this window is not evidence of absence elsewhere" in user_prompt
    assert "return one relationship per outcome" in user_prompt
    assert "full jointly varied, compared, or modeled factor set" in user_prompt
    assert "never label the cited study current_work" in user_prompt
    assert "Miranda et al. [20]" in user_prompt
    assert "Return empty arrays rather than guessing" in user_prompt
    assert "Return `studies=[]`; do not" in user_prompt
    assert "Return the explicit axis in `unresolved_signals`" in user_prompt
    assert "copy `source_unit_ids`" in user_prompt
    assert "at most 12 unique `source_unit_ids`" in user_prompt
    assert "up to 2 `warnings`, each at most 240 characters" in user_prompt
    assert "up to 4 studies" in user_prompt
    assert "up to 6 relationships per study" in user_prompt
    assert "up to 8 unresolved signals" in user_prompt
    assert "output_saturated=true" in user_prompt
    assert "neutral scientific axis" in user_prompt
    assert "at most 12 varied-factor labels" in user_prompt
    assert "L-VED, M-VED, and H-VED" in user_prompt
    assert "varied_factors=['volumetric energy density']" in user_prompt
    assert "outcome='fatigue strength'" in user_prompt
    assert "result direction, value, or comparison sentence" in user_prompt
    assert "source_unit_coverage" not in user_prompt


def test_review_paper_skim_prompt_extracts_synthesis_not_cited_experiments():
    _, user_prompt = build_paper_skim_prompt(
        {
            "document_id": "review-paper",
            "title": "Review of preheating in LPBF",
            "window_id": "unknown-1",
            "window_role": "unknown",
            "document_profile": {"doc_type": "review"},
            "source_units": [
                {
                    "source_unit_id": "source-unit-000001",
                    "source_kind": "block",
                    "source_ref": "block-1",
                    "section_path": "Preheating",
                    "content": (
                        "Miranda et al. [20] reported lower residual stress. "
                        "Across studies, preheating generally reduced residual stress."
                    ),
                }
            ],
        }
    )

    assert "review-author synthesis mapping" in user_prompt
    assert "not cited-study reconstruction" in user_prompt
    assert "claim_scope=synthesis" in user_prompt
    assert "return no study or unresolved signal" in user_prompt
    assert "Across studies, preheating generally reduced residual stress" in user_prompt
    assert "Miranda et al. [20]" in user_prompt
    assert "synthesis_claims" in user_prompt
    assert "disputes" in user_prompt
    assert "evidence_gaps" in user_prompt
    assert "citation_leads" in user_prompt
    assert "never primary Evidence" in user_prompt


def test_review_paper_skim_extractor_keeps_only_review_author_synthesis():
    source_unit_id = "source-unit-000001"
    client = _FakeOpenAIClient(
        json.dumps(
            {
                "doc_role": "review",
                "studies": [
                    {
                        "experiment_label": "Miranda et al.",
                        "claim_scope": "background",
                        "relationships": [
                            {
                                "varied_factors": ["build plate temperature"],
                                "outcome": "residual stress",
                                "source_unit_ids": [source_unit_id],
                            }
                        ],
                    },
                    {
                        "experiment_label": "review synthesis",
                        "claim_scope": "synthesis",
                        "relationships": [
                            {
                                "varied_factors": ["preheating condition"],
                                "outcome": "residual stress",
                                "source_unit_ids": [source_unit_id],
                            }
                        ],
                    },
                ],
                "unresolved_signals": [
                    {
                        "signal_type": "outcome",
                        "label": "porosity",
                        "claim_scope": "background",
                        "source_unit_ids": [source_unit_id],
                    }
                ],
                "review_synthesis": {
                    "synthesis_claims": [
                        {
                            "content": "Preheating generally reduces residual stress.",
                            "variables": ["preheating condition"],
                            "outcomes": ["residual stress"],
                            "source_unit_ids": [source_unit_id],
                            "confidence": 0.9,
                        }
                    ],
                    "citation_leads": [
                        {
                            "content": "Miranda et al. [20]",
                            "outcomes": ["residual stress"],
                            "source_unit_ids": [source_unit_id],
                            "confidence": 0.8,
                        }
                    ],
                },
            }
        )
    )

    skim = PaperStudyWindowExtractor(_response_client(client)).extract(
        {
            "document_id": "review-paper",
            "document_profile": {"doc_type": "review"},
            "source_units": [
                {
                    "source_unit_id": source_unit_id,
                    "source_kind": "block",
                    "source_ref": "block-1",
                    "content": (
                        "Miranda et al. [20] reported lower residual stress. "
                        "Across studies, preheating generally reduced residual stress."
                    ),
                }
            ],
        }
    )

    assert skim.doc_role == "review"
    assert [study.claim_scope for study in skim.studies] == ["synthesis"]
    assert skim.studies[0].relationships[0].outcome == "residual stress"
    assert skim.unresolved_signals == []
    assert skim.review_synthesis.synthesis_claims[0].content.startswith(
        "Preheating"
    )
    assert skim.review_synthesis.citation_leads[0].content == "Miranda et al. [20]"


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
                {
                    "pair_id": "axis_pair_0003",
                    "axis_type": "variable",
                    "left": "build orientation",
                    "right": "laser speed",
                    "left_observations": [
                        {
                            "varied_factors": ["build orientation", "laser speed"],
                            "process_context": ["laser powder bed fusion"],
                            "sample_context": ["vertical and horizontal coupons"],
                        }
                    ],
                    "right_observations": [
                        {
                            "varied_factors": ["build orientation", "laser speed"],
                            "process_context": ["laser powder bed fusion"],
                            "sample_context": ["vertical and horizontal coupons"],
                        }
                    ],
                },
            ],
        }
    )

    assert "before collection objective grouping" in user_prompt
    assert "pair classification" in user_prompt
    assert "`decisions` array" in user_prompt
    assert "every input pair" in user_prompt
    assert "bounded PaperStudy observations" in user_prompt
    assert "co-occurrence is not equivalence evidence" in user_prompt
    assert "build orientation and laser speed" in user_prompt.casefold()
    assert "boolean `equivalent`" in user_prompt
    assert "SS316L and 316L stainless steel" in user_prompt
    assert "SS316 and 316L stainless steel are different grades" in user_prompt
    assert "porosity" in user_prompt
    assert "relative density" in user_prompt
    assert "equivalent=false" in user_prompt
    assert "tensile strength and ultimate tensile strength" in user_prompt
    assert "surface hardness and hardness" in user_prompt


def test_paper_signal_reconciliation_prompt_defines_backend_owned_accounting():
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
    assert "same stated paper-owned research scope" in user_prompt
    assert "one bounded candidate neighborhood" in user_prompt
    assert "exactly one outcome anchor" in user_prompt
    assert "omitted paper signals are outside this batch" in user_prompt
    assert "backend derives final whole-paper accounting" in user_prompt
    assert "Do not link signals merely because they occur in the same paper" in user_prompt
    assert "backend treats every omitted input signal as unresolved" in user_prompt
    assert "never invent a reason merely to repeat an ID" in user_prompt
    assert "copy only input `signal_id` values" in user_prompt
    assert "same signal membership more than once" in user_prompt
    assert "Split high-level statement" in user_prompt
    assert "Different scopes" in user_prompt
    assert "Do not infer sample groups, controls, test settings" in user_prompt


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
                    finish_reason="stop",
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


def _response_client(client: _FakeOpenAIClient) -> StructuredResponseClient:
    return StructuredResponseClient(
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
        FindingAssertionJudge(
            StructuredResponseClient(
                client=objective_client,
                model="fake-model",
                extraction_mode="provider_parse",
            )
        ).judge_result_set(
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
        "finding_synthesis": "finding_synthesis.v13",
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


def test_document_profile_retry_includes_the_invalid_output_it_must_correct():
    client = _FakeOpenAIClient(
        [
            "The document appears to be an experimental paper.",
            '{"doc_type":"experimental","confidence":0.9,"parsing_warnings":[]}',
        ]
    )
    extractor = _document_profile_extractor(client)

    result = extractor.extract_document_profile(
        {
            "title": "LPBF paper",
            "abstract_or_lead_text": "This study varies laser power.",
        }
    )

    assert result.doc_type == "experimental"
    retry_messages = client.chat.completions.calls[1]["messages"]
    assert retry_messages[-2] == {
        "role": "assistant",
        "content": "The document appears to be an experimental paper.",
    }
    assert "Previous output was invalid" in retry_messages[-1]["content"]


def test_document_profile_failure_trace_preserves_bounded_attempt_diagnostics():
    invalid_output = "classification: experimental"
    client = _FakeOpenAIClient(invalid_output)
    extractor = _document_profile_extractor(client)

    with pytest.raises(DocumentProfileExtractionError):
        extractor.extract_document_profile(
            {
                "title": "LPBF paper",
                "abstract_or_lead_text": "This study varies laser power.",
            }
        )

    trace = extractor.consume_last_trace()
    assert trace is not None
    assert trace["trace_status"] == "failed"
    assert trace["error"] == "structured extraction returned no JSON object"
    assert trace["attempts"] == [
        {
            "attempt": 1,
            "finish_reason": "stop",
            "response_chars": len(invalid_output),
            "response_preview": invalid_output,
            "error": "structured extraction returned no JSON object",
        },
        {
            "attempt": 2,
            "finish_reason": "stop",
            "response_chars": len(invalid_output),
            "response_preview": invalid_output,
            "error": "structured extraction returned no JSON object",
        },
    ]


def test_document_profile_extractor_does_not_hide_programming_errors():
    client = _FakeOpenAIClient("unused")

    def raise_programming_error(**kwargs):  # noqa: ANN003, ARG001
        raise AssertionError("unexpected extractor bug")

    client.chat.completions.create = raise_programming_error
    extractor = _document_profile_extractor(client)

    with pytest.raises(AssertionError, match="unexpected extractor bug"):
        extractor.extract_document_profile(
            {
                "title": "LPBF paper",
                "abstract_or_lead_text": "This study varies laser power.",
            }
        )


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


def test_response_client_does_not_generate_backend_owned_objective_lineage():
    assert not hasattr(StructuredResponseClient, "discover_research_objectives")


def test_paper_skim_prompt_token_estimate_counts_complete_schema_prompt():
    client = _FakeOpenAIClient("unused")
    extractor = StructuredResponseClient(
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

    estimated_tokens = PaperStudyWindowExtractor(extractor).estimate_prompt_tokens(payload)

    assert estimated_tokens > 1_000
    assert client.beta.chat.completions.calls == []
    assert client.chat.completions.calls == []


def test_signal_reconciliation_prompt_token_estimate_counts_complete_schema_prompt():
    client = _FakeOpenAIClient("unused")
    extractor = StructuredResponseClient(
        client=client,
        model="fake-model",
        extraction_mode="provider_parse",
    )
    payload = {
        "document_id": "paper-1",
        "signals": [
            {
                "signal_id": "signal-variable",
                "signal_type": "variable",
                "label": "laser power",
                "sources": [
                    {
                        "source_unit_id": "source-unit-000001",
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
                        "source_unit_id": "source-unit-000010",
                        "section_path": "Results",
                        "excerpt": "Relative density was measured for each condition.",
                    }
                ],
            },
        ],
    }

    estimated_tokens = PaperSignalReconciler(extractor).estimate_prompt_tokens(
        payload
    )

    assert estimated_tokens > 500
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
    extractor = StructuredResponseClient(
        client=client,
        model="fake-model",
        extraction_mode="provider_parse",
    )

    with pytest.raises(StructuredOutputSaturatedError):
        PaperStudyWindowExtractor(extractor).extract(
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

    def create_with_length_finish(**kwargs):
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
    extractor = StructuredResponseClient(
        client=client,
        model="fake-model",
        extraction_mode="json_text",
    )

    with pytest.raises(StructuredOutputSaturatedError):
        PaperStudyWindowExtractor(extractor).extract(
            {
                "document_id": "paper-1",
                "title": "Density study",
                "window_id": "results-1",
                "window_role": "results",
                "source_units": [],
            }
        )

    assert len(client.chat.completions.calls) == 1
    trace = extractor.consume_last_trace()
    assert trace is not None
    assert trace["trace_status"] == "failed"
    assert trace["error_type"] == "StructuredOutputSaturatedError"
    assert trace["error"] == (
        "PaperSkim JSON output reached the completion-token limit"
    )
    assert trace["raw_output"] == '{"studies":[]}'
    assert trace["attempts"] == [
        {
            "attempt": 1,
            "finish_reason": "length",
            "response_chars": len('{"studies":[]}'),
            "response_preview": '{"studies":[]}',
            "error_type": "StructuredOutputSaturatedError",
            "error": "PaperSkim JSON output reached the completion-token limit",
        }
    ]


def test_paper_skim_saturation_logs_bounded_source_trace(caplog):
    raw_output = '{"studies":[' + ('"repeated",' * 400) + "]}"
    client = _FakeOpenAIClient(raw_output)

    def create_with_length_finish(**kwargs):
        client.chat.completions.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(content=raw_output),
                )
            ]
        )

    client.chat.completions.create = create_with_length_finish
    extractor = PaperStudyWindowExtractor(
        StructuredResponseClient(
            client=client,
            model="fake-model",
            extraction_mode="json_text",
        )
    )
    source_text = "Laser power was varied and porosity was measured."

    with caplog.at_level(
        "WARNING",
        logger="application.core.objectives.discovery.study_window",
    ), pytest.raises(StructuredOutputSaturatedError):
        extractor.extract(
            {
                "document_id": "paper-1",
                "window_id": "results-1",
                "window_role": "results",
                "source_units": [
                    {
                        "source_unit_id": "source-unit-000071",
                        "source_kind": "block",
                        "source_ref": "block-71",
                        "content": source_text,
                    }
                ],
            }
        )

    trace_message = next(
        record.getMessage()
        for record in caplog.records
        if "Paper skim saturation trace" in record.getMessage()
    )
    assert "contract=paper_skim" in trace_message
    assert "window_id=results-1" in trace_message
    assert 'source_unit_ids=["source-unit-000071"]' in trace_message
    assert f"input_chars={len(source_text)}" in trace_message
    assert '"finish_reason":"length"' in trace_message
    assert f'"response_chars":{len(raw_output)}' in trace_message
    assert len(trace_message) < 2_000


def test_shared_structured_failure_trace_preserves_each_invalid_json_attempt():
    invalid_output = "classification: experimental"
    extractor = _response_client(_FakeOpenAIClient(invalid_output))

    with pytest.raises(RuntimeError, match="returned no JSON object"):
        extractor.complete(
            system_prompt="Return structured findings.",
            user_prompt="No Source content is needed for this transport test.",
            response_model=StructuredFindingSynthesis,
            task_type="finding_synthesis",
            prompt_version="finding_synthesis.test",
        )

    trace = extractor.consume_last_trace()
    assert trace is not None
    assert trace["trace_status"] == "failed"
    assert trace["error_type"] == "RuntimeError"
    assert trace["error"] == "structured extraction returned no JSON object"
    assert trace["raw_output"] == invalid_output
    assert trace["attempts"] == [
        {
            "attempt": 1,
            "finish_reason": "stop",
            "response_chars": len(invalid_output),
            "response_preview": invalid_output,
            "error_type": "RuntimeError",
            "error": "structured extraction returned no JSON object",
        },
        {
            "attempt": 2,
            "finish_reason": "stop",
            "response_chars": len(invalid_output),
            "response_preview": invalid_output,
            "error_type": "RuntimeError",
            "error": "structured extraction returned no JSON object",
        },
    ]


def test_domain_model_extractors_synthesizes_goal_findings_with_distinct_trace():
    parsed = StructuredFindingSynthesis(findings=[])
    client = _FakeOpenAIClient("unused", parsed=parsed)
    extractor = StructuredResponseClient(
        client=client,
        model="fake-model",
        extraction_mode="provider_parse",
    )
    payload = {
        "objective": {"question": "How does energy density affect density?"},
        "result_set": {
            "result_set_id": "result-set-1",
            "factors": ["energy density"],
            "outcome": "density",
            "result_evidence": [],
        },
    }

    result = FindingAssertionJudge(extractor).judge_result_set(payload)

    assert result == parsed
    parse_call = client.beta.chat.completions.calls[0]
    assert parse_call["response_format"] is StructuredFindingSynthesis
    assert parse_call["max_completion_tokens"] == 1024
    trace = extractor.consume_last_trace()
    assert trace is not None
    assert trace["task_type"] == "finding_synthesis"
    assert trace["prompt_version"] == "finding_synthesis.v13"
    assert trace["parsed_output"] == {"findings": []}


def test_structured_response_traces_are_isolated_between_concurrent_calls():
    client = _response_client(_FakeOpenAIClient('{"findings": []}'))
    calls_completed = Barrier(2)

    def complete_and_consume_trace(task_type: str):
        client.complete(
            system_prompt="Return structured findings.",
            user_prompt=f"Analyze {task_type}.",
            response_model=StructuredFindingSynthesis,
            task_type=task_type,
            prompt_version="test.v1",
        )
        calls_completed.wait(timeout=2)
        return client.consume_last_trace()

    with ThreadPoolExecutor(max_workers=2) as executor:
        traces = tuple(
            executor.map(
                complete_and_consume_trace,
                ("collection-one", "collection-two"),
            )
        )

    assert {trace["task_type"] for trace in traces if trace is not None} == {
        "collection-one",
        "collection-two",
    }


def test_domain_model_extractors_bounds_json_text_finding_synthesis_output():
    client = _FakeOpenAIClient('{"findings": []}')
    extractor = _response_client(client)

    result = FindingAssertionJudge(extractor).judge_result_set(
        {
            "objective": {"question": "How does energy density affect density?"},
            "result_set": {},
        }
    )

    assert result == StructuredFindingSynthesis(findings=[])
    assert client.chat.completions.calls[0]["max_completion_tokens"] == 1024


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("result_set_id", "result-set-1"),
        ("statement", "Energy density increases relative density."),
        ("direction", "increase"),
        ("condition_boundary_evidence_ids", ["evidence-1"]),
        ("supporting_evidence_ids", ["evidence-1"]),
        ("contradicting_evidence_ids", ["evidence-2"]),
    ),
)
def test_finding_synthesis_schema_rejects_backend_owned_fields(
    field: str,
    value: object,
) -> None:
    payload = {
        "assertion_strength": "associative",
        "context_evidence_ids": [],
        "mechanisms": [],
        field: value,
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StructuredFindingSynthesis.model_validate({"findings": [payload]})


def test_finding_synthesis_schema_accepts_only_model_judgment_fields() -> None:
    parsed = StructuredFindingSynthesis.model_validate(
        {
            "findings": [
                {
                    "assertion_strength": "associative",
                    "context_evidence_ids": ["mechanism-1"],
                    "mechanisms": [
                        {
                            "source_term": "melt-pool stability",
                            "relation_type": "associated_with",
                            "target_term": "relative density",
                            "direction": "increase",
                            "assertion_strength": "associative",
                            "supporting_evidence_ids": ["mechanism-1"],
                        }
                    ],
                }
            ]
        }
    )

    assert parsed.model_dump() == {
        "findings": [
            {
                "assertion_strength": "associative",
                "context_evidence_ids": ["mechanism-1"],
                "mechanisms": [
                    {
                        "source_term": "melt-pool stability",
                        "relation_type": "associated_with",
                        "target_term": "relative density",
                        "direction": "increase",
                        "assertion_strength": "associative",
                        "supporting_evidence_ids": ["mechanism-1"],
                    }
                ],
            }
        ]
    }


def test_finding_synthesis_prompt_assigns_backend_and_model_ownership():
    payload = {
        "objective": {"question": "How does energy density affect density?"},
        "result_set": {
            "result_set_id": "result-set-1",
            "factors": ["laser power", "scan speed", "energy density"],
            "outcome": "maximum defect length",
            "primary_direction": "decrease",
            "total_evidence_count": 21,
            "result_evidence": [
                {
                    "evidence_id": "evidence-1",
                    "document_id": "paper-1",
                    "attribution_scope": "joint_effect",
                }
            ],
            "document_evidence_summaries": [
                {
                    "document_id": "paper-1",
                    "evidence_count": 21,
                    "direction_counts": {"decrease": 21},
                    "attribution_scope_counts": {"joint_effect": 21},
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
    assert "HARD RULES" in system_prompt
    assert "BOUNDARY EXAMPLES" in system_prompt
    assert "OUTPUT CONTRACT" in system_prompt
    normalized_system_prompt = " ".join(system_prompt.split())
    assert "backend owns" in normalized_system_prompt
    assert "primary_direction" in normalized_system_prompt
    assert "model decides only" in normalized_system_prompt
    assert "assertion_strength" in normalized_system_prompt
    assert "context_evidence_ids" in normalized_system_prompt
    assert "mechanisms" in normalized_system_prompt
    assert "result_set_id" not in user_prompt
    assert "statement" not in user_prompt
    assert "condition_boundary_evidence_ids" not in user_prompt
    assert "21" in user_prompt
    assert "paper-1" in user_prompt
    mechanism_schema = StructuredFindingMechanism.model_json_schema()
    assert "supporting_evidence_ids" in mechanism_schema["properties"]


def test_finding_synthesis_prompt_carries_bounded_semantic_repair():
    payload = {
        "objective": {"question": "How does energy density affect density?"},
        "result_set": {
            "result_set_id": "result-set-1",
            "factors": ["energy density"],
            "outcome": "density",
            "result_evidence": [],
        },
        "candidate_rejection": {
            "reason": "candidate references unavailable context Evidence",
            "previous_candidate": {
                "assertion_strength": "associative",
                "context_evidence_ids": ["missing-context"],
                "mechanisms": [],
            },
        },
    }

    system_prompt, user_prompt = build_finding_synthesis_prompt(payload)

    assert "present only for one bounded repair attempt" in system_prompt
    assert "correction guidance, not Evidence" in system_prompt
    assert "Semantic repair required:" in user_prompt
    assert payload["candidate_rejection"]["reason"] in user_prompt
    assert "previous_candidate" not in user_prompt
    assert "Return only ids present in `context_evidence`" in user_prompt


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
                      "outcome": "corrosion current density",
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
    extractor = _response_client(client)

    skim = PaperStudyWindowExtractor(extractor).extract(
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
    assert skim.studies[0].relationships[0].outcome == "corrosion current density"
    assert client.chat.completions.calls[0]["max_completion_tokens"] == 2048


def test_paper_skim_bounds_diagnostic_warnings_without_retrying_scientific_output():
    response = {
        "doc_role": "experimental",
        "studies": [],
        "unresolved_signals": [],
        "warnings": ["  " + ("diagnostic " * 30) + "  "],
    }
    client = _FakeOpenAIClient(json.dumps(response))

    skim = PaperStudyWindowExtractor(_response_client(client)).extract(
        {
            "document_id": "paper-ti64",
            "source_units": [],
        }
    )

    assert len(client.chat.completions.calls) == 1
    assert len(skim.warnings) == 1
    assert len(skim.warnings[0]) == 240
    assert skim.warnings[0].startswith("diagnostic diagnostic")


def test_paper_skim_downgrades_empty_factor_relationship_without_losing_siblings():
    response = {
        "doc_role": "experimental",
        "studies": [
            {
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
                        "confidence": 0.91,
                    },
                    {
                        "varied_factors": [],
                        "outcome": "microhardness",
                        "source_unit_ids": ["window-source-2"],
                        "confidence": 0.84,
                    },
                ],
                "confidence": 0.9,
            }
        ],
        "unresolved_signals": [],
        "evidence_density": "high",
        "confidence": 0.9,
        "warnings": [],
    }
    client = _FakeOpenAIClient(json.dumps(response))
    extractor = _response_client(client)

    skim = PaperStudyWindowExtractor(extractor).extract(
        {
            "document_id": "paper-1",
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
                    "source_ref": "block-2",
                    "content": "Microhardness was also reported.",
                },
            ],
        }
    )

    assert len(client.chat.completions.calls) == 1
    assert len(skim.studies) == 1
    assert [item.outcome for item in skim.studies[0].relationships] == ["porosity"]
    assert len(skim.unresolved_signals) == 1
    unresolved = skim.unresolved_signals[0]
    assert unresolved.signal_type == "outcome"
    assert unresolved.label == "microhardness"
    assert unresolved.material_scope == ["316L stainless steel"]
    assert unresolved.process_context == ["LPBF"]
    assert unresolved.source_unit_ids == ["window-source-2"]


def test_paper_skim_downgrades_descriptive_factor_clause_to_unresolved_outcome():
    response = {
        "doc_role": "experimental",
        "studies": [
            {
                "experiment_label": "microstructure characterization",
                "design_type": "experimental",
                "claim_scope": "current_work",
                "relationships": [
                    {
                        "varied_factors": [
                            "microstructural features including grain morphology, "
                            "phase distribution, and crystallographic texture from "
                            "pole figures"
                        ],
                        "outcome": "alpha phase fraction",
                        "source_unit_ids": ["window-source-1"],
                    }
                ],
            }
        ],
        "unresolved_signals": [],
    }
    client = _FakeOpenAIClient(json.dumps(response))

    skim = PaperStudyWindowExtractor(_response_client(client)).extract(
        {
            "document_id": "paper-ti64",
            "source_units": [
                {
                    "source_unit_id": "window-source-1",
                    "source_kind": "figure",
                    "source_ref": "figure-7",
                    "content": "Alpha phase fraction was quantified from imaging.",
                }
            ],
        }
    )

    assert len(client.chat.completions.calls) == 1
    assert skim.studies == []
    assert len(skim.unresolved_signals) == 1
    assert skim.unresolved_signals[0].signal_type == "outcome"
    assert skim.unresolved_signals[0].label == "alpha phase fraction"
    assert skim.unresolved_signals[0].source_unit_ids == ["window-source-1"]


def test_paper_skim_downgrades_compound_and_generic_outcomes_without_losing_siblings():
    response = {
        "doc_role": "experimental",
        "studies": [
            {
                "experiment_label": "SLM Ti-6Al-4V annealing study",
                "design_type": "experimental",
                "claim_scope": "current_work",
                "material_scope": ["Ti-6Al-4V"],
                "process_context": ["post-build annealing"],
                "relationships": [
                    {
                        "varied_factors": ["annealing temperature"],
                        "outcome": "microstructure",
                        "source_unit_ids": ["window-source-1"],
                        "confidence": 0.91,
                    },
                    {
                        "varied_factors": ["annealing temperature"],
                        "outcome": "strength and ductility of SLMed Ti-6Al-4V",
                        "source_unit_ids": ["window-source-2"],
                        "confidence": 0.86,
                    },
                    {
                        "varied_factors": ["annealing temperature"],
                        "outcome": "mechanical property combination",
                        "source_unit_ids": ["window-source-3"],
                        "confidence": 0.81,
                    },
                    {
                        "varied_factors": ["annealing temperature"],
                        "outcome": (
                            "microstructure (grain size, shape, phase fraction, "
                            "composition)"
                        ),
                        "source_unit_ids": ["window-source-4"],
                        "confidence": 0.79,
                    },
                ],
                "confidence": 0.9,
            }
        ],
        "unresolved_signals": [],
        "evidence_density": "high",
        "confidence": 0.9,
        "warnings": [],
    }
    client = _FakeOpenAIClient(json.dumps(response))

    skim = PaperStudyWindowExtractor(_response_client(client)).extract(
        {
            "document_id": "paper-ti64",
            "source_units": [
                {
                    "source_unit_id": f"window-source-{index}",
                    "source_kind": "block",
                    "source_ref": f"block-{index}",
                    "content": "Annealing results for SLM Ti-6Al-4V.",
                }
                for index in range(1, 5)
            ],
        }
    )

    assert [
        relationship.outcome
        for study in skim.studies
        for relationship in study.relationships
    ] == []
    assert [signal.label for signal in skim.unresolved_signals] == [
        "microstructure",
        "strength and ductility of SLMed Ti-6Al-4V",
        "mechanical property combination",
        "microstructure (grain size, shape, phase fraction, composition)",
    ]
    assert [signal.source_unit_ids for signal in skim.unresolved_signals] == [
        ["window-source-1"],
        ["window-source-2"],
        ["window-source-3"],
        ["window-source-4"],
    ]
    assert all(
        signal.material_scope == ["Ti-6Al-4V"]
        and signal.process_context == ["post-build annealing"]
        for signal in skim.unresolved_signals
    )
    prompt = client.chat.completions.calls[0]["messages"][-1]["content"]
    assert "one specific outcome" in prompt
    assert "compound outcome" in prompt
    assert "unresolved_signals" in prompt


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
    extractor = _response_client(client)

    skim = PaperStudyWindowExtractor(extractor).extract(
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
    assert "at most 12 IDs" in client.chat.completions.calls[1]["messages"][-1][
        "content"
    ]


def test_paper_skim_repairs_unknown_source_unit_ids_before_returning():
    invalid = {
        "doc_role": "experimental",
        "studies": [
            {
                "design_type": "experimental",
                "claim_scope": "current_work",
                "relationships": [
                    {
                        "varied_factors": ["HIP temperature"],
                        "outcome": "yield strength",
                        "source_unit_ids": ["invented-source-unit"],
                    }
                ],
            }
        ],
    }
    valid = {
        **invalid,
        "studies": [
            {
                **invalid["studies"][0],
                "relationships": [
                    {
                        **invalid["studies"][0]["relationships"][0],
                        "source_unit_ids": ["window-source-1"],
                    }
                ],
            }
        ],
    }
    client = _FakeOpenAIClient([json.dumps(invalid), json.dumps(valid)])

    skim = PaperStudyWindowExtractor(_response_client(client)).extract(
        {
            "document_id": "paper-ti64",
            "source_units": [
                {
                    "source_unit_id": "window-source-1",
                    "source_kind": "table",
                    "source_ref": "table-8",
                    "content": "HIP temperature was varied and yield strength measured.",
                }
            ],
        }
    )

    assert skim.studies[0].relationships[0].source_unit_ids == [
        "window-source-1"
    ]
    assert len(client.chat.completions.calls) == 2
    repair_prompt = client.chat.completions.calls[1]["messages"][-1]["content"]
    assert "invented-source-unit" in repair_prompt
    assert "Copy only unique Source-unit IDs from the input" in repair_prompt
    assert (
        'ALLOWED SOURCE-UNIT IDS: ["window-source-1"]'
        in client.chat.completions.calls[0]["messages"][-1]["content"]
    )
    assert 'ALLOWED SOURCE-UNIT IDS: ["window-source-1"]' in repair_prompt


def test_paper_skim_repairs_unknown_signal_source_unit_ids_before_returning():
    invalid = {
        "doc_role": "experimental",
        "unresolved_signals": [
            {
                "signal_type": "outcome",
                "label": "elongation",
                "source_unit_ids": ["invented-source-unit"],
            }
        ],
    }
    valid = {
        **invalid,
        "unresolved_signals": [
            {
                **invalid["unresolved_signals"][0],
                "source_unit_ids": ["window-source-1"],
            }
        ],
    }
    client = _FakeOpenAIClient([json.dumps(invalid), json.dumps(valid)])

    skim = PaperStudyWindowExtractor(_response_client(client)).extract(
        {
            "document_id": "paper-ti64",
            "source_units": [
                {
                    "source_unit_id": "window-source-1",
                    "source_kind": "table",
                    "source_ref": "table-8",
                    "content": "Total elongation was reported for each HIP condition.",
                }
            ],
        }
    )

    assert skim.unresolved_signals[0].source_unit_ids == ["window-source-1"]
    assert len(client.chat.completions.calls) == 2
    assert "invented-source-unit" in client.chat.completions.calls[1]["messages"][
        -1
    ]["content"]


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
    extractor = StructuredResponseClient(client=client, model="fake-model")

    skim = PaperStudyWindowExtractor(extractor).extract(
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
    extractor = _response_client(client)

    skim = PaperStudyWindowExtractor(extractor).extract(
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
    ]
    assert [signal.label for signal in skim.unresolved_signals] == [
        "microstructure",
        "mechanical properties"
    ]
    assert skim.unresolved_signals[0].source_unit_ids == ["window-source-1"]
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
    extractor = _response_client(client)

    skim = PaperStudyWindowExtractor(extractor).extract(
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
    extractor = _response_client(client)

    reconciliation = PaperSignalReconciler(extractor).reconcile(
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
    extractor = _response_client(client)

    reconciliation = PaperSignalReconciler(extractor).reconcile(
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
    extractor = StructuredResponseClient(client=client, model="fake-model")

    reconciliation = PaperSignalReconciler(extractor).reconcile(
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
    extractor = _response_client(client)

    reconciliation = PaperSignalReconciler(extractor).reconcile(
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
            {
              "pair_id": "axis_pair_0001",
              "equivalent": true
            }
          ]
        }
        """
    )
    classifier = ResearchAxisEquivalenceClassifier(_response_client(client))

    canonicalization_plan = classifier.classify(
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
        {
            "pair_id": "axis_pair_0001",
            "equivalent": True,
        }
    ]
    prompt = client.chat.completions.calls[0]["messages"][-1]["content"]
    assert "exact scientific question" in prompt
    assert "Different settings or components" in prompt
    assert "Shared material, shared measured outcome" in prompt
    assert "Build orientation and laser power" in prompt
    assert "different processing stages" in prompt


def test_axis_canonicalization_repairs_ungrounded_and_overlapping_groups():
    invalid = json.dumps(
        {
            "decisions": [
                {
                    "pair_id": "axis_pair_9999",
                    "equivalent": True,
                },
                {
                    "pair_id": "axis_pair_9999",
                    "equivalent": False,
                },
            ]
        }
    )
    repaired = json.dumps(
        {
            "decisions": [
                {
                    "pair_id": "axis_pair_0001",
                    "equivalent": True,
                },
                {
                    "pair_id": "axis_pair_0002",
                    "equivalent": False,
                },
            ]
        }
    )
    client = _FakeOpenAIClient([invalid, repaired])
    classifier = ResearchAxisEquivalenceClassifier(_response_client(client))

    plan = classifier.classify(
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
        {
            "pair_id": "axis_pair_0001",
            "equivalent": True,
        },
        {
            "pair_id": "axis_pair_0002",
            "equivalent": False,
        },
    ]
    repair_prompt = client.chat.completions.calls[1]["messages"][-1]["content"]
    assert "axis pair classification" in repair_prompt
    assert "exact same scientific axis" in repair_prompt


def test_domain_model_extractors_validates_objective_paper_frame_response():
    client = _FakeOpenAIClient(
        """
        {
          "relevance": "high",
          "paper_role": "primary_experiment",
          "screening_note": "Direct current-work evidence for the objective.",
          "material_match": ["316L stainless steel"],
          "changed_variables": ["heat treatment"],
          "measured_property_scope": ["corrosion"],
          "test_environment_scope": ["3.5 wt.% NaCl"],
          "relevant_source_unit_ids": ["frame-section-results"],
          "excluded_source_unit_ids": ["frame-table-2"]
        }
        """
    )
    extractor = _response_client(client)

    frame = ObjectiveSourceScreener(extractor).screen_batch(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "paper_prior": {"doc_role": "experimental"},
            "source_units": [
                {
                    "source_unit_id": "frame-section-results",
                    "source_kind": "section",
                    "source_ref": "results",
                    "section_label": "Results",
                    "text": "Heat treatment changed corrosion resistance.",
                },
                {
                    "source_unit_id": "frame-table-2",
                    "source_kind": "table",
                    "source_ref": "table-2",
                    "caption_text": "Composition only.",
                },
            ],
        }
    )

    assert isinstance(frame, StructuredPaperFrameBatch)
    assert frame.relevance == "high"
    assert frame.relevant_source_unit_ids == ["frame-section-results"]
    assert frame.excluded_source_unit_ids == ["frame-table-2"]
    assert frame.source_accounting_origin == "model"
    assert frame.source_accounting_errors == ()
    frame_schema = StructuredPaperFrameBatch.model_json_schema()
    assert "source_accounting_origin" not in frame_schema["properties"]
    assert "source_accounting_errors" not in frame_schema["properties"]
    assert client.chat.completions.calls[0]["max_completion_tokens"] == 1024


def test_objective_paper_frame_bounds_screening_note_without_rejecting_source_ids():
    client = _FakeOpenAIClient(
        json.dumps(
            {
                "relevance": "high",
                "paper_role": "primary_experiment",
                "screening_note": "x" * 400,
                "relevant_source_unit_ids": ["frame-section-results"],
                "excluded_source_unit_ids": [],
            }
        )
    )
    extractor = _response_client(client)

    frame = ObjectiveSourceScreener(extractor).screen_batch(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "source_units": [
                {
                    "source_unit_id": "frame-section-results",
                    "source_kind": "section",
                    "source_ref": "results",
                    "section_label": "Results",
                    "text": "Heat treatment changed corrosion resistance.",
                }
            ],
        }
    )

    assert frame.screening_note == "x" * 320
    assert frame.relevant_source_unit_ids == ["frame-section-results"]
    assert len(client.chat.completions.calls) == 1
    assert "background" not in StructuredPaperFrameBatch.model_json_schema()[
        "properties"
    ]


def test_objective_paper_frame_json_repair_rejects_unknown_source_id():
    invalid = json.dumps(
        {
            "relevance": "high",
            "paper_role": "primary_experiment",
            "relevant_source_unit_ids": ["frame-section-results"],
            "excluded_source_unit_ids": ["frame-unknown"],
        }
    )
    repaired = json.dumps(
        {
            "relevance": "high",
            "paper_role": "primary_experiment",
            "relevant_source_unit_ids": ["frame-section-results"],
            "excluded_source_unit_ids": ["frame-table-background"],
        }
    )
    client = _FakeOpenAIClient([invalid, repaired])
    extractor = _response_client(client)

    frame = ObjectiveSourceScreener(extractor).screen_batch(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "source_units": [
                {
                    "source_unit_id": "frame-section-results",
                    "source_kind": "section",
                    "source_ref": "results",
                    "text": "Heat treatment changed corrosion resistance.",
                },
                {
                    "source_unit_id": "frame-table-background",
                    "source_kind": "table",
                    "source_ref": "table-background",
                    "caption_text": "Nominal composition.",
                },
            ],
        }
    )

    assert frame.relevant_source_unit_ids == ["frame-section-results"]
    assert frame.excluded_source_unit_ids == ["frame-table-background"]
    assert frame.source_accounting_origin == "repair"
    assert "unknown_source_unit_ids=['frame-unknown']" in (
        frame.source_accounting_errors[0]
    )
    assert len(client.chat.completions.calls) == 2
    assert "account for every source-unit id" in client.chat.completions.calls[1][
        "messages"
    ][-1]["content"]
    assert "frame-section-results" in client.chat.completions.calls[1]["messages"][-1][
        "content"
    ]
    assert "frame-table-background" in client.chat.completions.calls[1]["messages"][
        -1
    ]["content"]
    assert "frame-unknown" in client.chat.completions.calls[1]["messages"][-1][
        "content"
    ]


def test_objective_paper_frame_repairs_omitted_source_unit():
    incomplete = json.dumps(
        {
            "relevance": "irrelevant",
            "paper_role": "irrelevant",
            "relevant_source_unit_ids": [
                "frame-section-1",
                "frame-section-2",
                "frame-section-3",
                "frame-section-4",
                "frame-section-5",
                "frame-section-6",
                "frame-section-7",
            ],
            "excluded_source_unit_ids": [],
        }
    )
    repaired = json.dumps(
        {
            "relevance": "uncertain",
            "paper_role": "uncertain",
            "relevant_source_unit_ids": [
                "frame-section-1",
                "frame-section-2",
                "frame-section-3",
                "frame-section-4",
                "frame-section-5",
                "frame-section-6",
                "frame-section-7",
            ],
            "excluded_source_unit_ids": ["frame-section-8"],
        }
    )
    client = _FakeOpenAIClient([incomplete, repaired])
    extractor = _response_client(client)
    source_unit_ids = [f"frame-section-{position}" for position in range(1, 9)]

    frame = ObjectiveSourceScreener(extractor).screen_batch(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "source_units": [
                {
                    "source_unit_id": source_unit_id,
                    "source_kind": "section",
                    "source_ref": f"section-{position}",
                    "text": "Potentially relevant scientific evidence.",
                }
                for position, source_unit_id in enumerate(source_unit_ids, start=1)
            ],
        }
    )

    assert frame.relevance == "uncertain"
    assert frame.relevant_source_unit_ids == source_unit_ids[:-1]
    assert frame.excluded_source_unit_ids == [source_unit_ids[-1]]
    assert frame.source_accounting_origin == "repair"
    assert "missing_source_unit_ids=['frame-section-8']" in (
        frame.source_accounting_errors[0]
    )
    assert len(client.chat.completions.calls) == 2
    repair_prompt = client.chat.completions.calls[1]["messages"][-1]["content"]
    assert "missing_source_unit_ids=['frame-section-8']" in repair_prompt


@pytest.mark.parametrize(
    "invalid_partition",
    [
        {
            "relevant_source_unit_ids": ["frame-section-results"],
            "excluded_source_unit_ids": ["frame-unknown"],
        },
        {
            "relevant_source_unit_ids": [
                "frame-section-results",
                "frame-section-results",
            ],
            "excluded_source_unit_ids": ["frame-table-background"],
        },
        {
            "relevant_source_unit_ids": ["frame-section-results"],
            "excluded_source_unit_ids": [
                "frame-section-results",
                "frame-table-background",
            ],
        },
    ],
    ids=["unknown", "duplicate", "overlap"],
)
def test_objective_paper_frame_still_rejects_invalid_ids_after_repair(
    invalid_partition,
):
    response = json.dumps(
        {
            "relevance": "high",
            "paper_role": "primary_experiment",
            **invalid_partition,
        }
    )
    client = _FakeOpenAIClient([response, response])
    extractor = _response_client(client)

    with pytest.raises((ValueError, ValidationError)):
        ObjectiveSourceScreener(extractor).screen_batch(
            {
                "collection_id": "col-1",
                "objective": {
                    "question": "How does heat treatment affect corrosion?"
                },
                "source_units": [
                    {
                        "source_unit_id": "frame-section-results",
                        "source_kind": "section",
                        "source_ref": "results",
                        "text": "Heat treatment changed corrosion resistance.",
                    },
                    {
                        "source_unit_id": "frame-table-background",
                        "source_kind": "table",
                        "source_ref": "table-background",
                        "caption_text": "Nominal composition.",
                    },
                ],
            }
        )

    assert len(client.chat.completions.calls) == 2


def test_provider_parsed_objective_paper_frame_repairs_omission(
    monkeypatch,
):
    monkeypatch.delenv("CORE_LLM_EXTRACTION_MODE", raising=False)
    incomplete = StructuredPaperFrameBatch.model_validate(
        {
            "relevance": "irrelevant",
            "paper_role": "irrelevant",
            "relevant_source_unit_ids": ["frame-section-results"],
            "excluded_source_unit_ids": [],
        }
    )
    repaired = json.dumps(
        {
            "relevance": "low",
            "paper_role": "supporting_background",
            "relevant_source_unit_ids": ["frame-section-results"],
            "excluded_source_unit_ids": ["frame-table-background"],
        }
    )
    client = _FakeOpenAIClient(repaired, parsed=incomplete)
    extractor = StructuredResponseClient(client=client, model="fake-model")

    frame = ObjectiveSourceScreener(extractor).screen_batch(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "source_units": [
                {
                    "source_unit_id": "frame-section-results",
                    "source_kind": "section",
                    "source_ref": "results",
                    "text": "Heat treatment changed corrosion resistance.",
                },
                {
                    "source_unit_id": "frame-table-background",
                    "source_kind": "table",
                    "source_ref": "table-background",
                    "caption_text": "Nominal composition.",
                },
            ],
        }
    )

    assert frame.relevance == "low"
    assert frame.relevant_source_unit_ids == ["frame-section-results"]
    assert frame.excluded_source_unit_ids == ["frame-table-background"]
    assert frame.source_accounting_origin == "repair"
    assert "missing_source_unit_ids=['frame-table-background']" in (
        frame.source_accounting_errors[0]
    )
    assert len(client.beta.chat.completions.calls) == 1
    assert len(client.chat.completions.calls) == 1


def test_provider_parsed_objective_paper_frame_repairs_source_accounting(
    monkeypatch,
):
    monkeypatch.delenv("CORE_LLM_EXTRACTION_MODE", raising=False)
    invalid = StructuredPaperFrameBatch.model_validate(
        {
            "relevance": "high",
            "paper_role": "primary_experiment",
            "relevant_source_unit_ids": ["frame-section-results"],
            "excluded_source_unit_ids": ["frame-unknown"],
        }
    )
    repaired = {
        "relevance": "high",
        "paper_role": "primary_experiment",
        "relevant_source_unit_ids": ["frame-section-results"],
        "excluded_source_unit_ids": ["frame-table-background"],
    }
    client = _FakeOpenAIClient(json.dumps(repaired), parsed=invalid)
    extractor = StructuredResponseClient(client=client, model="fake-model")

    frame = ObjectiveSourceScreener(extractor).screen_batch(
        {
            "collection_id": "col-1",
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "source_units": [
                {
                    "source_unit_id": "frame-section-results",
                    "source_kind": "section",
                    "source_ref": "results",
                    "text": "Heat treatment changed corrosion resistance.",
                },
                {
                    "source_unit_id": "frame-table-background",
                    "source_kind": "table",
                    "source_ref": "table-background",
                    "caption_text": "Nominal composition.",
                },
            ],
        }
    )

    assert frame.excluded_source_unit_ids == ["frame-table-background"]
    assert frame.source_accounting_origin == "repair"
    assert "unknown_source_unit_ids=['frame-unknown']" in (
        frame.source_accounting_errors[0]
    )
    assert len(client.beta.chat.completions.calls) == 1
    assert len(client.chat.completions.calls) == 1
    repair_prompt = client.chat.completions.calls[0]["messages"][-1]["content"]
    assert "account for every source-unit id" in repair_prompt
    assert "frame-section-results" in repair_prompt
    assert "frame-table-background" in repair_prompt
    assert (
        extractor.consume_last_trace()["extraction_mode"]
        == "provider_parse->json_text"
    )


def test_objective_paper_frame_prompt_defines_bounded_source_accounting():
    _, user_prompt = build_objective_paper_frame_prompt(
        {
            "objective": {"question": "How does heat treatment affect corrosion?"},
            "paper_prior": {"doc_role": "experimental"},
            "source_units": [
                {
                    "source_unit_id": "frame-section-results",
                    "source_kind": "section",
                    "source_ref": "results",
                    "section_label": "Results",
                    "text": "Heat treatment changed corrosion resistance.",
                }
            ],
        }
    )

    assert "bounded source-candidate classification" in user_prompt
    assert "one partial neighborhood" in user_prompt
    assert "`collection_id`: backend scope identity" in user_prompt
    assert "`document_profile`: backend document-type metadata" in user_prompt
    assert "table-row chunks" in user_prompt
    assert "Every input `source_unit_id`" in user_prompt
    assert "relevant_source_unit_ids" in user_prompt
    assert "excluded_source_unit_ids" in user_prompt
    assert "Do not infer whole-paper irrelevance" in user_prompt
    assert '"relevant_source_unit_ids":["unit-methods"]' in user_prompt
    assert '"excluded_source_unit_ids":["unit-composition"]' in user_prompt
    assert '"paper_role":"uncertain"' in user_prompt
    assert '"relevant_source_unit_ids":[]' in user_prompt
    assert "This batch contains nominal composition only." in user_prompt


def test_objective_paper_frame_prompt_token_estimate_counts_complete_schema():
    client = _FakeOpenAIClient("unused")
    extractor = _response_client(client)
    payload = {
        "objective": {"question": "How does heat treatment affect corrosion?"},
        "paper_prior": {"doc_role": "experimental"},
        "source_units": [
            {
                "source_unit_id": "frame-section-results",
                "source_kind": "section",
                "source_ref": "results",
                "section_label": "Results",
                "text": "Heat treatment changed corrosion resistance.",
            }
        ],
    }

    estimated_tokens = ObjectiveSourceScreener(extractor).estimate_prompt_tokens(
        payload
    )
    system_prompt, user_prompt = build_objective_paper_frame_prompt(payload)
    prompt_without_schema = json.dumps(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    prompt_tokens_without_schema = len(
        tiktoken.get_encoding("cl100k_base").encode(prompt_without_schema)
    )

    assert estimated_tokens > prompt_tokens_without_schema + 100
    assert client.beta.chat.completions.calls == []
    assert client.chat.completions.calls == []


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
    extractor = _response_client(client)

    routes = ObjectiveEvidenceRouter(extractor).route_source(
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
    extractor = _response_client(client)

    with pytest.raises(ValueError):
        ObjectiveEvidenceRouter(extractor).route_source(
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
    extractor = _response_client(client)

    with pytest.raises(ValidationError):
        ObjectiveEvidenceRouter(extractor).route_source(
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
    extractor = _response_client(client)

    with pytest.raises(ValidationError):
        ObjectiveEvidenceRouter(extractor).route_source(
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
    extractor = _response_client(client)

    extractions = ObjectiveSourceExtractor(extractor).extract_source(
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


def test_objective_evidence_extractor_has_no_grounding_repair_call_contract():
    client = _FakeOpenAIClient('{"extractions":[]}')
    extractor = _response_client(client)
    payload = {
        "collection_id": "col-1",
        "objective": {"question": "How does laser power affect density?"},
        "evidence_route": {
            "source_kind": "text_window",
            "source_ref": "block-1",
        },
        "source": {
            "source_kind": "text_window",
            "source_ref": "block-1",
            "text": (
                "At laser powers of 100 W and 140 W, relative density "
                "increased to 98.05%."
            ),
        },
    }
    with pytest.raises(TypeError, match="invalid_extraction"):
        ObjectiveSourceExtractor(extractor).extract_source(
            payload,
            invalid_extraction={"changed_variables": []},
        )

    assert client.chat.completions.calls == []


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


def test_structured_objective_evidence_rejects_single_variable_joint_effect():
    with pytest.raises(
        ValidationError,
        match="joint effect requires multiple changed variables",
    ):
        StructuredEvidenceExtraction.model_validate(
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


def test_structured_objective_evidence_rejects_unbound_experimental_attribution():
    with pytest.raises(
        ValidationError,
        match="experimental attribution requires baseline and target values",
    ):
        StructuredEvidenceExtraction.model_validate(
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
    extractor = _response_client(_FakeOpenAIClient(response))

    parsed = ObjectiveSourceExtractor(extractor).extract_source(
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
    extractor = _response_client(client)

    with pytest.raises(ValidationError):
        ObjectiveSourceExtractor(extractor).extract_source(
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

    assert len(client.chat.completions.calls) == 3


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
    extractor = _response_client(client)

    with pytest.raises(ValueError, match="echoed input fields"):
        ObjectiveSourceExtractor(extractor).extract_source(
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

    assert len(client.chat.completions.calls) == 3
    assert "only echoed the input fields" in client.chat.completions.calls[1][
        "messages"
    ][-1]["content"]


@pytest.mark.parametrize(
    "attribution_scope",
    ("isolated_effect", "association_only"),
)
def test_structured_objective_evidence_rejects_unchanged_factor_as_changed_variable(
    attribution_scope,
):
    with pytest.raises(
        ValidationError,
        match="changed variables require distinct baseline and target values",
    ):
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
                "attribution_scope": attribution_scope,
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
            "paper_frame": {"screening_note": "must not become evidence"},
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
    contract = " ".join(system_prompt.split())

    assert "Extract at most one objective-relevant, source-local fact" in contract
    assert "`SOURCE` is the only scientific authority" in contract
    assert "Return at most one extraction" in contract
    assert "one top-level key: `extractions`" in contract
    assert "1.43x10^6 C/s for P150" in prompt
    assert "1.65x10^6 C/s for NP" in prompt
    assert "OUTPUT JSON:" in prompt
    assert "collection_id" not in prompt
    assert "paper_frame" not in prompt
    assert "document_state" not in prompt
    assert "must not become evidence" not in prompt
    assert "must not be copied" not in prompt
    assert "Return a changed variable only when this SOURCE explicitly names" in contract
    assert "The backend may bind another grounded Source later" in contract
    assert "absent, off, or without condition to numeric 0" in contract
    assert "one baseline-to-target comparison interval" in contract
    assert "Never repeat a changed-variable name" in contract
    assert "choose one adjacent source-supported pair" in contract
    assert "copy the exact group labels" in contract
    assert "no statistically significant difference" in contract
    assert "use association_only" in contract
    assert "Context source" in contract
    assert "numeric `confidence` for every extraction" in contract
    assert "Generic composition or background" in contract
    assert "Unrelated composition example" in contract


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
    extractor = _response_client(client)

    with pytest.raises(ValidationError):
        ObjectiveSourceExtractor(extractor).extract_source(
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


def test_domain_model_extractors_leave_reasoning_effort_unset_by_default(monkeypatch):
    monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
    extractor = StructuredResponseClient(
        client=_FakeOpenAIClient("unused"),
        model="fake-model",
    )

    assert "reasoning_effort" not in extractor._provider_request_options()


@pytest.mark.parametrize(
    "extractor_type",
    (DocumentProfileExtractor, PaperFactsExtractor, StructuredResponseClient),
)
def test_domain_model_extractors_forward_configured_reasoning_effort(
    monkeypatch,
    extractor_type,
):
    monkeypatch.setenv("LLM_REASONING_EFFORT", "none")
    extractor = extractor_type(
        client=_FakeOpenAIClient("unused"),
        model="fake-model",
    )

    assert extractor._provider_request_options()["reasoning_effort"] == "none"


def test_domain_model_extractors_routes_objective_selections_directly_to_bounded_json_text(
    monkeypatch,
):
    monkeypatch.setenv("CORE_LLM_EXTRACTION_MODE", "provider_parse")
    client = _FakeOpenAIClient('{"selections":[]}')
    extractor = StructuredResponseClient(client=client, model="fake-model")

    routes = ObjectiveEvidenceRouter(extractor).route_source(
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
    extractor = StructuredResponseClient(client=client, model="fake-model")

    units = ObjectiveSourceExtractor(extractor).extract_source(
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
    normalized_contract = " ".join(contract.split())

    assert "verbatim substring" in contract
    assert "direction describes the objective outcome" in contract
    assert "Use `mixed` for an unordered qualitative change" in contract
    assert "mixes current work with cited literature" in contract
    assert "`incomparability_reasons` must be empty" in contract
    assert "Conditions from cited literature" in contract
    assert "identical baseline and target values are fixed context" in contract
    assert "Keep the exact concise SOURCE term" in normalized_contract
    assert "must not be copied when absent from SOURCE" in normalized_contract
    assert "cellular-dendritic microstructure" in normalized_contract
    assert '"changed_variables":[]' in normalized_contract
    assert "TASK MODEL" in system_prompt
    assert "INPUT SCHEMA" in system_prompt
    assert "DECISION PROCESS" in system_prompt
    assert "BOUNDARY EXAMPLES" in system_prompt
    assert '{"extractions":[]}' in system_prompt
    assert "`result_text` is the only source text" in system_prompt
    assert "Do not output source excerpts" not in system_prompt


def test_domain_model_extractors_repairs_layered_structured_validation_errors(
    monkeypatch,
):
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
    still_invalid_payload = json.loads(valid)
    still_invalid_comparison = still_invalid_payload["extractions"][0]["comparison"]
    still_invalid_comparison["comparable"] = False
    still_invalid_comparison["incomparability_reasons"] = [
        "comparison conditions are incomplete"
    ]
    still_invalid = json.dumps(still_invalid_payload)
    client = _FakeOpenAIClient(invalid)
    responses = iter((invalid, still_invalid, valid))

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
    extractor = StructuredResponseClient(
        client=client,
        model="fake-model",
        extraction_mode="json_text",
    )

    parsed = ObjectiveSourceExtractor(extractor).extract_source(
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
    assert len(client.chat.completions.calls) == 3
    repair_prompt = client.chat.completions.calls[1]["messages"][-1]["content"]
    assert "experimental attribution requires comparison" in repair_prompt
    invalid_item = json.dumps(
        json.loads(invalid)["extractions"][0],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert "INVALID EXTRACTION" in repair_prompt
    assert invalid_item in repair_prompt
    assert "Correct only values supported by SOURCE" in repair_prompt
    assert "do not invent comparison endpoints" in repair_prompt
    assert "Return only {\"extractions\":[<one corrected extraction>]}" in repair_prompt
    assert "fixed context, not a changed variable" in repair_prompt
    assert "choose one complete source-supported interval" in repair_prompt
    assert "never merge separate intervals" in repair_prompt
    assert "For finding synthesis" not in repair_prompt
    second_repair_prompt = client.chat.completions.calls[2]["messages"][-1][
        "content"
    ]
    assert "incomparable evidence cannot be attributed" in second_repair_prompt
    still_invalid_item = json.dumps(
        json.loads(still_invalid)["extractions"][0],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert still_invalid_item in second_repair_prompt


def test_objective_evidence_normalizes_fixed_endpoint_and_joint_scope_without_repair():
    invalid = json.dumps(
        {
            "extractions": [
                {
                    "evidence_role": "direct_result",
                    "changed_variables": [
                        {
                            "name": "laser power",
                            "baseline_value": 100,
                            "target_value": 140,
                            "unit": "W",
                        },
                        {
                            "name": "scan speed",
                            "baseline_value": 100,
                            "target_value": 100,
                            "unit": "mm/s",
                        },
                    ],
                    "comparison": {
                        "baseline_label": "100 W at 100 mm/s",
                        "target_label": "140 W at 100 mm/s",
                        "axis_names": ["laser power", "scan speed"],
                        "comparable": True,
                    },
                    "reported_result": {
                        "outcome": "density",
                        "value": 98.05,
                        "unit": "%",
                        "direction": "increase",
                        "result_text": "the average density was found to be 98.05%",
                    },
                    "attribution_scope": "joint_effect",
                    "scientific_context": {},
                    "resolution_status": "resolved",
                    "confidence": 0.9,
                }
            ]
        }
    )
    client = _FakeOpenAIClient(invalid)
    extractor = StructuredResponseClient(
        client=client,
        model="fake-model",
        extraction_mode="json_text",
    )

    parsed = ObjectiveSourceExtractor(extractor).extract_source(
        {
            "objective": {
                "question": "How do laser power and scan speed affect density?"
            },
            "evidence_route": {
                "source_kind": "text_window",
                "source_ref": "block-1",
            },
            "source": {
                "source_kind": "text_window",
                "source_ref": "block-1",
                "text": (
                    "At 100 and 140 W with scan speed fixed at 100 mm/s, "
                    "the average density was found to be 98.05%."
                ),
            },
        }
    )

    assert [item.name for item in parsed.extractions[0].changed_variables] == [
        "laser power"
    ]
    assert parsed.extractions[0].attribution_scope == "isolated_effect"
    assert parsed.extractions[0].comparison is not None
    assert parsed.extractions[0].comparison.axis_names == ["laser power"]
    assert len(client.chat.completions.calls) == 1


def test_objective_evidence_recovers_empty_comparison_axes_from_changed_variables():
    response = json.dumps(
        {
            "extractions": [
                {
                    "evidence_role": "direct_result",
                    "changed_variables": [
                        {
                            "name": "laser power",
                            "baseline_value": 100,
                            "target_value": 140,
                            "unit": "W",
                        }
                    ],
                    "comparison": {
                        "baseline_label": "100 W",
                        "target_label": "140 W",
                        "axis_names": [],
                        "comparable": True,
                    },
                    "reported_result": {
                        "outcome": "relative density",
                        "value": 98.05,
                        "unit": "%",
                        "direction": "increase",
                        "result_text": "the average density was found to be 98.05%",
                    },
                    "attribution_scope": "isolated_effect",
                    "scientific_context": {},
                    "resolution_status": "resolved",
                    "confidence": 0.9,
                }
            ]
        }
    )
    client = _FakeOpenAIClient(response)
    extractor = StructuredResponseClient(
        client=client,
        model="fake-model",
        extraction_mode="json_text",
    )

    parsed = ObjectiveSourceExtractor(extractor).extract_source(
        {
            "objective": {
                "question": "How does laser power affect relative density?"
            },
            "evidence_route": {
                "source_kind": "text_window",
                "source_ref": "block-1",
            },
            "source": {
                "source_kind": "text_window",
                "source_ref": "block-1",
                "text": (
                    "At laser powers of 100 W and 140 W, the average density "
                    "was found to be 98.05%."
                ),
            },
        }
    )

    comparison = parsed.extractions[0].comparison
    assert comparison is not None
    assert comparison.axis_names == ["laser power"]
    assert len(client.chat.completions.calls) == 1


@pytest.mark.parametrize(
    ("changed_variables", "axis_names"),
    (
        (
            [
                {
                    "name": "scan speed",
                    "baseline_value": 800,
                    "target_value": 800,
                    "unit": "mm/s",
                }
            ],
            ["scan speed"],
        ),
        ([], []),
    ),
    ids=("all-variables-are-fixed", "model-returned-no-axis"),
)
def test_objective_evidence_downgrades_axisless_result_to_descriptive_result(
    changed_variables,
    axis_names,
):
    response = json.dumps(
        {
            "extractions": [
                {
                    "evidence_role": "direct_result",
                    "changed_variables": changed_variables,
                    "comparison": {
                        "baseline_label": "sample A",
                        "target_label": "sample B",
                        "axis_names": axis_names,
                        "comparable": True,
                    },
                    "reported_result": {
                        "outcome": "porosity",
                        "value": 1.2,
                        "unit": "%",
                        "direction": "unknown",
                        "result_text": "The measured porosity was 1.2%.",
                    },
                    "attribution_scope": "isolated_effect",
                    "scientific_context": {},
                    "resolution_status": "resolved",
                    "confidence": 0.8,
                }
            ]
        }
    )
    client = _FakeOpenAIClient(response)
    extractor = StructuredResponseClient(
        client=client,
        model="fake-model",
        extraction_mode="json_text",
    )

    parsed = ObjectiveSourceExtractor(extractor).extract_source(
        {
            "objective": {"question": "How does scan speed affect porosity?"},
            "evidence_route": {
                "source_kind": "text_window",
                "source_ref": "block-1",
            },
            "source": {
                "source_kind": "text_window",
                "source_ref": "block-1",
                "text": "At 800 mm/s, the measured porosity was 1.2%.",
            },
        }
    )

    extraction = parsed.extractions[0]
    assert extraction.changed_variables == []
    assert extraction.comparison is None
    assert extraction.attribution_scope == "descriptive_only"
    assert extraction.reported_result is not None
    assert len(client.chat.completions.calls) == 1


@pytest.mark.parametrize("baseline_value", (None, "", [], {}))
def test_objective_evidence_does_not_invent_axes_for_incomplete_variables(
    baseline_value,
):
    payload = {
        "extractions": [
            {
                "changed_variables": [
                    {
                        "name": "laser power",
                        "baseline_value": baseline_value,
                        "target_value": 140,
                    }
                ],
                "comparison": {"axis_names": []},
                "attribution_scope": "isolated_effect",
            }
        ]
    }

    normalized = _normalize_objective_evidence_payload(payload)

    assert normalized == payload


def test_objective_evidence_demotes_unbound_experimental_result_without_repair():
    payload = {
        "extractions": [
            {
                "evidence_role": "direct_result",
                "changed_variables": [
                    {
                        "name": "laser power",
                        "baseline_value": None,
                        "target_value": 120,
                        "unit": "W",
                    }
                ],
                "comparison": {
                    "baseline_label": "lower laser power",
                    "target_label": "120 W",
                    "axis_names": ["laser power"],
                    "comparable": True,
                },
                "reported_result": {
                    "outcome": "density",
                    "value": None,
                    "unit": None,
                    "direction": "increase",
                    "result_text": "Average density increased with scan speed.",
                },
                "attribution_scope": "isolated_effect",
                "scientific_context": {},
                "resolution_status": "resolved",
                "confidence": 0.8,
            }
        ]
    }

    normalized = _normalize_objective_evidence_payload(payload)

    extraction = normalized["extractions"][0]
    assert extraction["attribution_scope"] == "association_only"
    assert extraction["resolution_status"] == "partial"
    assert extraction["changed_variables"] == payload["extractions"][0][
        "changed_variables"
    ]
    assert extraction["comparison"] == payload["extractions"][0]["comparison"]
    assert extraction["reported_result"] == payload["extractions"][0][
        "reported_result"
    ]


@pytest.mark.parametrize(
    ("variable_name", "endpoint"),
    (
        ("scan speed", ""),
        ("scan speed", []),
        ("scan speed", {}),
        ("", "fixed"),
    ),
)
def test_objective_evidence_does_not_normalize_invalid_fixed_endpoints(
    variable_name,
    endpoint,
):
    payload = {
        "extractions": [
            {
                "changed_variables": [
                    {
                        "name": variable_name,
                        "baseline_value": endpoint,
                        "target_value": endpoint,
                    }
                ],
                "comparison": {"axis_names": [variable_name]},
                "attribution_scope": "joint_effect",
            }
        ]
    }

    normalized = _normalize_objective_evidence_payload(payload)

    assert normalized == payload


def test_objective_evidence_repair_prompt_requires_role_result_consistency():
    repair_prompt = _objective_evidence_repair_instruction(
        repair_detail=(
            "extractions.0: Value error, context evidence cannot report an "
            "experimental result"
        ),
        invalid_extraction={
            "evidence_role": "mechanism_context",
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": "density",
                "value": 98.05,
                "unit": "%",
                "direction": "increase",
                "result_text": "the average density was found to be 98.05%",
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
    )

    assert (
        "If `reported_result` is non-null, use `direct_result` or "
        "`contradictory_result` as `evidence_role`" in repair_prompt
    )
    assert (
        "If keeping a context role, set `reported_result` to null" in repair_prompt
    )
    assert (
        "`isolated_effect` and `joint_effect` require distinct baseline and target "
        "values" in repair_prompt
    )
    assert (
        "`comparison.axis_names` must exactly match the distinct "
        "`changed_variables` names" in repair_prompt
    )
    assert (
        "If `comparison.comparable` is false, use `not_attributable`" in repair_prompt
    )
    assert (
        "Remove each fixed parameter from `changed_variables` and "
        "`comparison.axis_names`" in repair_prompt
    )
    assert "A fixed control does not make the comparison incomparable" in repair_prompt


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
        extractor = StructuredResponseClient(client=_FakeOpenAIClient("{}"), model="fake-model")

    assert extractor.extraction_mode == "provider_parse"
    assert "Invalid CORE_LLM_EXTRACTION_MODE=not-a-mode" in caplog.text
