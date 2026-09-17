from __future__ import annotations

import json
from time import monotonic

import pytest

from application.core.objectives.discovery.paper_understanding.paper_map_outputs import (
    ExperimentalPaperMapModelOutput,
)
from application.core.objectives.discovery.paper_understanding.paper_map_results import (
    StructuredPaperResearchMap,
)
from application.core.objectives.discovery.paper_understanding.workflow import (
    PaperResearchMapExtractor,
    _normalize_experimental_paper_map_payload,
)
from application.core.objectives.llm.structured_response import StructuredResponseClient
from application.core.objectives.paper_map_extraction import (
    PaperMapExtractionBudget,
    PaperMapExtractionService,
)
from application.core.objectives.paper_map_sources import PaperMapSourceSelector
from infra.llm.usage import capture_llm_usage
from tests.unit.application.test_paper_research_map_service import (
    _artifacts,
    _build_skims,
    _paragraph,
    _study,
)
from tests.unit.services.test_domain_model_extractors import _FakeOpenAIClient


class _ContextReader:
    def __init__(self, respond=None):
        self.payloads = []
        self.respond = respond

    def estimate_prompt_tokens(self, payload):
        return sum(len(str(unit["content"])) // 4 for unit in payload["source_units"])

    def extract(self, payload, *, before_request=None):
        if before_request is not None:
            before_request()
        self.payloads.append(payload)
        if self.respond is not None:
            return self.respond(payload)
        return StructuredPaperResearchMap()


def _selected_payloads(blocks, *, reader=None):
    documents, tree = _artifacts(blocks=blocks)
    document = documents[0]
    return PaperMapSourceSelector(
        PaperMapExtractionService().fit_payload_to_prompt_limit
    ).build_payloads(
        collection_id="context-reading",
        document=document,
        profile=None,
        blocks=list(document.blocks),
        tables=[],
        table_rows=[],
        figures=[],
        document_tree=tree,
        paper_map_extractor=reader or _ContextReader(),
    )


def test_summary_sections_are_read_together_without_source_count_partitioning():
    blocks = [
        _paragraph("abstract-power", "We varied laser power in LPBF 316L.", 1, "Abstract"),
        *[
            _paragraph(f"conclusion-{index}", text, index + 2, "Conclusions")
            for index, text in enumerate(
                [
                    "Relative density was compared across those laser-power conditions.",
                    "Lack-of-fusion pores occurred at the lowest power.",
                    "Scan speed was held constant.",
                    "A separate experiment compared annealing temperatures.",
                    "Tensile strength was measured for the annealed samples.",
                ]
            )
        ],
    ]

    payloads = _selected_payloads(blocks)

    assert len(payloads) == 1
    units = payloads[0]["source_units"]
    assert {unit["source_ref"] for unit in units} == {block["block_id"] for block in blocks}
    assert {unit["section_path"] for unit in units} == {"Abstract", "Conclusions"}
    assert [unit["content"] for unit in units] == [block["text"] for block in blocks]


def test_a_complete_passage_is_not_fragmented_when_it_fits_the_prompt_budget():
    text = "Prior work provides the following context. " * 130
    text += "In this work, laser power was varied and relative density was measured."

    payloads = _selected_payloads([_paragraph("abstract", text, 1, "Abstract")])

    assert len(payloads) == 1
    assert len(payloads[0]["source_units"]) == 1
    assert payloads[0]["source_units"][0]["content"] == text


def _signal(label, kind, unit, **fields):
    return {
        "label": label,
        "signal_type": kind,
        "variable_role": "varied" if kind == "variable" else "not_applicable",
        "claim_scope": "current_work",
        "material_scope": ["316L stainless steel"],
        "process_context": ["LPBF"],
        "source_unit_ids": [unit["source_unit_id"]],
        **fields,
    }


def test_targeted_reading_includes_full_original_context_and_binds_both_sources():
    abstract = "Motivation and prior work. " * 50
    abstract += "In this work laser power was varied in LPBF 316L."
    artifacts, tree = _artifacts(blocks=[
        _paragraph("abstract", abstract, 1, "Abstract"),
        _paragraph("density", "Relative density was measured for those power groups.", 2, "Results"),
    ])

    def respond(payload):
        units = {unit["source_ref"]: unit for unit in payload["source_units"]}
        assert units["abstract"]["content"] == abstract
        if "density" not in units:
            return StructuredPaperResearchMap(unresolved_signals=[
                _signal("laser power", "variable", units["abstract"]),
            ])
        return StructuredPaperResearchMap(studies=[_study(
            varied_factors=["laser power"], outcome="relative density",
            source_unit_ids=[unit["source_unit_id"] for unit in units.values()],
            confidence=0.9,
        )])

    reader = _ContextReader(respond)
    paper_map = _build_skims(artifacts, tree, reader)[0]

    assert len(reader.payloads) == 2
    assert paper_map.map_status == "sufficient"
    assert paper_map.unresolved_signals == ()
    assert {source.source_ref for source in paper_map.studies[0].relationships[0].source_refs} == {"abstract", "density"}
    assert len(paper_map.source_unit_coverage) == 2


@pytest.mark.parametrize("variable_role", ["varied", "fixed", "context"])
def test_separate_experiment_or_ineligible_factor_remains_unlinked(variable_role):
    artifacts, tree = _artifacts(blocks=[
        _paragraph("power", "The power study used LPBF 316L.", 1, "Abstract"),
        _paragraph("annealing", "A separate annealing experiment measured hardness.", 2, "Conclusions"),
    ])

    def respond(payload):
        units = {unit["source_ref"]: unit for unit in payload["source_units"]}
        return StructuredPaperResearchMap(unresolved_signals=[
            _signal("laser power", "variable", units["power"], variable_role=variable_role, experiment_label="power study"),
            _signal("hardness", "outcome", units["annealing"], experiment_label="annealing study"),
        ])

    reader = _ContextReader(respond)
    paper_map = _build_skims(artifacts, tree, reader)[0]

    assert len(reader.payloads) == 1
    assert paper_map.studies == ()
    assert len(paper_map.unresolved_signals) == 2
    assert paper_map.map_status == "insufficient_map"


def test_no_rereading_subset_of_context_that_was_already_read_together():
    artifacts, tree = _artifacts(blocks=[
        _paragraph("overview", "This paper describes the current LPBF investigation.", 1, "Abstract"),
        _paragraph("gap", "The specific microstructure metric is not identified.", 2, "Conclusions"),
    ])
    reader = _ContextReader(lambda payload: StructuredPaperResearchMap(
        unresolved_signals=[_signal("microstructure", "outcome", payload["source_units"][-1])],
    ))

    paper_map = _build_skims(artifacts, tree, reader)[0]

    assert len(reader.payloads) == 1
    assert paper_map.map_status == "insufficient_map"
    assert "outcome_too_broad" in paper_map.map_limitations


def test_valid_initial_relationship_survives_failed_contextual_reading():
    artifacts, tree = _artifacts(blocks=[
        _paragraph("abstract", "Laser power changed relative density and microstructure.", 1, "Abstract"),
        _paragraph("results", "The microstructure was characterized.", 2, "Results"),
    ])

    def respond(payload):
        if payload.get("reading_round"):
            raise TimeoutError("provider timed out")
        unit = payload["source_units"][0]
        return StructuredPaperResearchMap(
            studies=[_study(varied_factors=["laser power"], outcome="relative density", source_unit_ids=[unit["source_unit_id"]], confidence=0.9)],
            unresolved_signals=[_signal("microstructure", "outcome", unit)],
        )

    reader = _ContextReader(respond)
    paper_map = _build_skims(artifacts, tree, reader)[0]

    assert len(reader.payloads) == 3
    assert reader.payloads[1] == reader.payloads[2]
    assert paper_map.studies[0].relationships[0].outcome == "relative density"
    assert not paper_map.coverage_complete
    assert "source_extraction_incomplete" in paper_map.map_limitations


def test_model_declared_overflow_retains_valid_relationship_without_retry_fanout():
    artifacts, tree = _artifacts(blocks=[
        _paragraph("abstract", "Laser power changed relative density.", 1, "Abstract"),
    ])
    reader = _ContextReader(lambda payload: StructuredPaperResearchMap(
        studies=[_study(varied_factors=["laser power"], outcome="relative density", source_unit_ids=[payload["source_units"][0]["source_unit_id"]], confidence=0.9)],
        output_saturated=True,
    ))

    paper_map = _build_skims(artifacts, tree, reader)[0]

    assert len(reader.payloads) == 1
    assert len(paper_map.studies) == 1
    assert not paper_map.coverage_complete
    assert paper_map.map_status == "insufficient_map"


def test_oversized_input_splits_losslessly_with_distinct_fragment_lineage():
    text = ("The original experimental passage is retained. " * 1300).strip()
    payloads = _selected_payloads([_paragraph("long", text, 1, "Abstract")])
    units = [unit for payload in payloads for unit in payload["source_units"]]

    assert len(payloads) > 1
    assert "".join(unit["content"] for unit in units) == text
    assert len({unit["source_unit_id"] for unit in units}) == len(units)
    assert {unit["source_ref"] for unit in units} == {"long"}
    assert all(_ContextReader().estimate_prompt_tokens(payload) <= 12_288 for payload in payloads)


@pytest.mark.parametrize("mode", ["json_text", "provider_parse"])
@pytest.mark.parametrize("allowed_recovery", [0, 1])
def test_actual_provider_attempts_share_budget_and_do_not_count_unsent_calls(mode, allowed_recovery):
    class BudgetClient(_FakeOpenAIClient):
        def __init__(self):
            super().__init__("not JSON", parse_error=RuntimeError("invalid provider response"))
            self.options = []

        def with_options(self, **kwargs):
            self.options.append(kwargs)
            return self

    client = BudgetClient()
    reader = PaperResearchMapExtractor(StructuredResponseClient(
        client=client, model="fake-model", extraction_mode=mode,
    ))
    payloads = _selected_payloads([_paragraph("abstract", "Laser power changed relative density.", 1, "Abstract")])
    budget = PaperMapExtractionBudget(deadline=monotonic() + 30, max_calls=1 + allowed_recovery, max_recovery_calls=allowed_recovery)

    with capture_llm_usage() as usage:
        results = PaperMapExtractionService().extract_window_payloads(
            collection_id="test", document_id="paper-1", payloads=payloads,
            paper_map_extractor=reader, extraction_budget=budget,
        )

    actual_calls = len(client.chat.completions.calls) + len(client.beta.chat.completions.calls)
    assert actual_calls == budget.calls == 1 + allowed_recovery
    assert usage.execution_stats().model_usage[0].request_count == actual_calls
    assert len(client.options) == actual_calls
    assert all(option["max_retries"] == 0 and 0 < option["timeout"] <= 30 for option in client.options)
    assert not results[0][0][0].coverage_complete


def test_expired_document_budget_sends_no_model_request():
    reader = _ContextReader()
    payloads = _selected_payloads([_paragraph("abstract", "Current study.", 1, "Abstract")])
    budget = PaperMapExtractionBudget(deadline=monotonic() - 1, max_calls=2, max_recovery_calls=1)

    results = PaperMapExtractionService().extract_window_payloads(
        collection_id="test", document_id="paper-1", payloads=payloads,
        paper_map_extractor=reader, extraction_budget=budget,
    )

    assert budget.calls == 0
    assert reader.payloads == []
    assert not results[0][0][0].coverage_complete


def test_source_citations_follow_supplied_input_instead_of_four_source_cap():
    labels = [f"S{position}" for position in range(1, 7)]
    output = {"studies": [{
        "claim_scope": "current_work",
        "relationships": [{
            "factor_assertions": [{"label": "laser power", "role": "varied", "source_labels": labels}],
            "outcome": "relative density", "source_labels": labels,
        }],
    }]}
    client = _FakeOpenAIClient(json.dumps(output))
    reader = PaperResearchMapExtractor(StructuredResponseClient(client=client, model="fake-model", extraction_mode="json_text"))
    payloads = _selected_payloads([
        _paragraph(f"abstract-{position}", "Part of the current study.", position, "Abstract")
        for position in range(6)
    ])

    result = reader.extract(payloads[0])

    assert len(result.studies[0].relationships[0].source_unit_ids) == 6


def test_factor_overflow_never_turns_a_joint_design_into_a_smaller_factor_set():
    payload = {"studies": [{"relationships": [{
        "factor_assertions": [{"label": label, "role": "varied", "source_labels": ["S1"]} for label in ("power", "speed", "spacing", "thickness", "temperature", "pressure", "flow")],
        "outcome": "relative density", "source_labels": ["S1"],
    }]}]}

    result = ExperimentalPaperMapModelOutput.model_validate(_normalize_experimental_paper_map_payload(payload))

    assert result.output_saturated
    assert result.studies == []


def test_failed_fragment_does_not_mark_the_original_source_fully_read():
    source_text = "A" * 30_000 + "\n" + "B" * 30_000
    artifacts, tree = _artifacts(blocks=[_paragraph("long-source", source_text, 1, "Abstract")])

    def respond(payload):
        unit = payload["source_units"][0]
        if unit["content"].startswith("B"):
            raise ValueError("invalid scope response")
        return StructuredPaperResearchMap(studies=[_study(
            varied_factors=["laser power"], outcome="relative density",
            source_unit_ids=[unit["source_unit_id"]], confidence=0.9,
        )])

    paper_map = _build_skims(artifacts, tree, _ContextReader(respond))[0]

    assert len(paper_map.studies) == 1
    assert len(paper_map.source_unit_coverage) == 2
    assert {item.source_ref for item in paper_map.source_unit_coverage} == {"long-source"}
    assert {item.status.value for item in paper_map.source_unit_coverage} == {"relationship_emitted", "extraction_failed"}
    assert not paper_map.coverage_complete


def test_other_window_budget_failure_does_not_mask_this_window_parse_failure():
    def respond(payload):
        raise json.JSONDecodeError("invalid JSON", "{", 1)

    payloads = _selected_payloads([_paragraph("abstract", "Current study.", 1, "Abstract")])
    budget = PaperMapExtractionBudget(
        deadline=monotonic() + 30, max_calls=2, max_recovery_calls=0,
        failure_kind="recovery_budget_exhausted",
    )

    results = PaperMapExtractionService().extract_window_payloads(
        collection_id="test", document_id="paper-1", payloads=payloads,
        paper_map_extractor=_ContextReader(respond), extraction_budget=budget,
    )

    coverage = results[0][0][0].source_unit_coverage[0]
    assert "malformed_json" in coverage.reason
    assert "recovery_budget_exhausted" not in coverage.reason
