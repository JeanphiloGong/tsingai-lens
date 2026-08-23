from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from httpx import Request, Response
from openai import APIConnectionError, BadRequestError

from application.core.objectives.analysis import (
    evidence_materialization,
    finding_synthesis,
    paper_experiment,
    source_extraction,
)
from application.core.objectives.analysis.evidence_routing import EvidenceCandidate
from application.core.objectives.analysis.source_extraction import (
    ExtractedEvidenceDraft,
    StructuredEvidenceExtraction,
    StructuredEvidenceExtractions,
    extract_and_validate_source_facts,
)
from application.core.objectives.analysis.source_screening import PaperAnalysisFrame
from domain.core import ObjectiveAnalysis, ObjectiveEvidence
from tests.support.research_objective_service import (
    research_objective as _research_objective,
)


def test_theme_objective_keeps_exact_interventions_in_separate_result_sets():
    objective = _research_objective(
        {
            "objective_id": "obj-thermal-elongation",
            "question": (
                "How does thermal post-processing condition affect elongation?"
            ),
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["thermal post-processing condition"],
            "outcomes": ["elongation"],
        }
    )

    def evidence(
        *,
        evidence_id: str,
        document_id: str,
        factor: str,
        baseline: int,
        target: int,
    ) -> ObjectiveEvidence:
        return ObjectiveEvidence.from_mapping(
            {
                "collection_id": objective.collection_id,
                "objective_id": objective.objective_id,
                "analysis_version": 1,
                "evidence_id": evidence_id,
                "document_id": document_id,
                "source_kind": "table_row",
                "source_ref": f"{document_id}-result-row",
                "source_excerpt": (
                    f"{factor} changed from {baseline} C to {target} C and "
                    "elongation increased."
                ),
                "evidence_role": "direct_result",
                "selection_status": "extracted",
                "changed_variables": [
                    {
                        "name": factor,
                        "baseline_value": baseline,
                        "target_value": target,
                        "unit": "C",
                    }
                ],
                "comparison": {
                    "baseline_label": f"{baseline} C",
                    "target_label": f"{target} C",
                    "axis_names": [factor],
                    "comparable": True,
                },
                "reported_result": {
                    "outcome": "elongation",
                    "value": 12.0,
                    "unit": "%",
                    "direction": "increase",
                    "result_text": "Elongation increased.",
                },
                "attribution_scope": "isolated_effect",
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    evidence_records = (
        evidence(
            evidence_id="evidence-annealing",
            document_id="paper-annealing",
            factor="annealing temperature",
            baseline=700,
            target=850,
        ),
        evidence(
            evidence_id="evidence-hip",
            document_id="paper-hip",
            factor="HIP temperature",
            baseline=850,
            target=920,
        ),
    )
    service = finding_synthesis.FindingSynthesisService()

    assert all(
        service.is_comparable_result_evidence(objective, item)
        for item in evidence_records
    )
    result_sets = service._result_sets(objective, evidence_records)
    assert len(result_sets) == 2
    assert {tuple(item["factors"]) for item in result_sets} == {
        ("annealing temperature",),
        ("HIP temperature",),
    }


def test_objective_evidence_document_state_is_typed_and_document_scoped():
    class RecordingExtractor:
        def __init__(self) -> None:
            self.payloads: list[dict[str, Any]] = []

        def extract_source(
            self,
            payload: dict[str, Any],
        ) -> StructuredEvidenceExtractions:
            self.payloads.append(payload)
            source_ref = payload["evidence_route"]["source_ref"]
            if source_ref == "paper-1-methods":
                return StructuredEvidenceExtractions(
                    extractions=[
                        StructuredEvidenceExtraction(
                            evidence_role="condition_context",
                            attribution_scope="descriptive_only",
                            scientific_context={
                                "process": [
                                    {
                                        "name": "laser power",
                                        "value": 150,
                                        "unit": "W",
                                    }
                                ]
                            },
                            resolution_status="resolved",
                            confidence=0.9,
                        )
                    ]
                )
            return StructuredEvidenceExtractions(
                extractions=[
                    StructuredEvidenceExtraction(
                        evidence_role="direct_result",
                        changed_variables=[
                            {
                                "name": "laser power",
                                "baseline_value": 150,
                                "target_value": 200,
                                "unit": "W",
                            }
                        ],
                        comparison={
                            "baseline_label": "150 W",
                            "target_label": "200 W",
                            "axis_names": ["laser power"],
                            "comparable": True,
                            "incomparability_reasons": [],
                        },
                        reported_result={
                            "outcome": "relative density",
                            "value": 99.2,
                            "unit": "%",
                            "direction": "increase",
                            "result_text": (
                                "Relative density increased from 96.1% to 99.2%."
                            ),
                        },
                        attribution_scope="isolated_effect",
                        resolution_status="resolved",
                        confidence=0.9,
                    )
                ]
            )

    extractor = RecordingExtractor()
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    routes = tuple(
        EvidenceCandidate.from_mapping(
            {
                "objective_id": "obj-density",
                "document_id": document_id,
                "source_kind": "text_window",
                "source_ref": source_ref,
                "role": "current_experimental_evidence",
                "extractable": True,
                "confidence": 0.9,
            }
        )
        for document_id, source_ref in (
            ("paper-1", "paper-1-methods"),
            ("paper-1", "paper-1-results"),
            ("paper-2", "paper-2-results"),
        )
    )
    blocks = {
        document_id: [
                SimpleNamespace(
                    block_id=source_ref,
                    text=(
                        "Laser power was 150 W in the methods."
                        if source_ref == "paper-1-methods"
                        else (
                            "Laser power increased from 150 W to 200 W, and relative "
                            "density increased from 96.1% to 99.2%."
                        )
                    ),
                page=1,
                block_type="paragraph",
                heading_path="Results",
            )
            for route_document_id, source_ref in (
                ("paper-1", "paper-1-methods"),
                ("paper-1", "paper-1-results"),
                ("paper-2", "paper-2-results"),
            )
            if route_document_id == document_id
        ]
        for document_id in ("paper-1", "paper-2")
    }

    units = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=routes,
        blocks_by_document_id=blocks,
        tables_by_document_id={},
        document_trees_by_document_id={},
    )

    assert len(units) == 3
    states_by_source_ref = {
        payload["evidence_route"]["source_ref"]: payload["document_state"]
        for payload in extractor.payloads
    }
    empty_state = source_extraction._empty_objective_document_state()
    assert states_by_source_ref["paper-1-methods"] == empty_state
    assert states_by_source_ref["paper-2-results"] == empty_state
    paper_1_result_state = states_by_source_ref["paper-1-results"]
    assert paper_1_result_state["schema_version"] == "objective_document_state.v2"
    assert paper_1_result_state["evidence_counts_by_role"] == {
        "condition_context": 1
    }
    prior = paper_1_result_state["prior_evidence"][0]
    assert prior["source_refs"][0]["source_ref"] == "paper-1-methods"
    assert not {
        "changed_variables",
        "comparison",
        "reported_result",
        "scientific_context",
    } & prior.keys()
    units_by_source_ref = {unit.source_ref: unit for unit in units}
    paper_1_result = units_by_source_ref["paper-1-results"]
    assert paper_1_result.document_id == "paper-1"
    assert paper_1_result.source_refs[0]["source_ref"] == "paper-1-results"


def test_objective_evidence_continues_after_one_route_format_failure():
    class RecoveringExtractor:
        def __init__(self) -> None:
            self.calls = 0

        def extract_source(
            self,
            payload: dict[str, Any],
        ) -> StructuredEvidenceExtractions:
            self.calls += 1
            if self.calls == 1:
                raise ValueError("invalid structured response")
            return StructuredEvidenceExtractions(
                extractions=[
                    StructuredEvidenceExtraction(
                        evidence_role="condition_context",
                        attribution_scope="descriptive_only",
                        scientific_context={
                            "test": [{"name": "temperature", "value": 25, "unit": "C"}]
                        },
                        resolution_status="resolved",
                        confidence=0.8,
                    )
                ]
            )

    extractor = RecoveringExtractor()
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    routes = tuple(
        EvidenceCandidate.from_mapping(
            {
                "objective_id": "obj-density",
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": source_ref,
                "role": "current_experimental_evidence",
                "extractable": True,
                "confidence": 0.9,
            }
        )
        for source_ref in ("block-failed", "block-recovered")
    )
    blocks = [
        SimpleNamespace(
            block_id=source_ref,
            text=f"Source text for {source_ref}. Test temperature was 25 C.",
            page=1,
            block_type="paragraph",
            heading_path="Results",
        )
        for source_ref in ("block-failed", "block-recovered")
    ]

    units = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=routes,
        blocks_by_document_id={"paper-1": blocks},
        tables_by_document_id={},
        document_trees_by_document_id={},
    )

    assert extractor.calls == 2
    assert len(units) == 2
    assert units[0].source_ref == "block-failed"
    assert units[0].selection_status == "failed"
    assert units[0].failure_reason == "ValueError: invalid structured response"
    assert units[1].source_ref == "block-recovered"
    assert units[1].selection_status == "extracted"


def test_objective_evidence_routes_round_robin_across_documents():
    class RecordingExtractor:
        def __init__(self) -> None:
            self.source_refs: list[str] = []

        def extract_source(
            self,
            payload: dict[str, Any],
        ) -> StructuredEvidenceExtractions:
            self.source_refs.append(payload["evidence_route"]["source_ref"])
            return StructuredEvidenceExtractions(extractions=[])

    extractor = RecordingExtractor()
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    route_specs = (
        ("paper-1", "paper-1-a"),
        ("paper-1", "paper-1-b"),
        ("paper-2", "paper-2-a"),
    )
    routes = tuple(
        EvidenceCandidate.from_mapping(
            {
                "objective_id": objective.objective_id,
                "document_id": document_id,
                "source_kind": "text_window",
                "source_ref": source_ref,
                "role": "current_experimental_evidence",
                "extractable": True,
                "confidence": 0.9,
            }
        )
        for document_id, source_ref in route_specs
    )
    blocks = {
        document_id: [
            SimpleNamespace(
                block_id=source_ref,
                text=f"Source text for {source_ref}.",
                page=1,
                block_type="paragraph",
                heading_path="Results",
            )
            for route_document_id, source_ref in route_specs
            if route_document_id == document_id
        ]
        for document_id in ("paper-1", "paper-2")
    }

    extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=routes,
        blocks_by_document_id=blocks,
        tables_by_document_id={},
        document_trees_by_document_id={},
    )

    assert extractor.source_refs == ["paper-1-a", "paper-2-a", "paper-1-b"]


def test_objective_evidence_provider_failure_is_scoped_to_one_document():
    class RecoveringExtractor:
        def __init__(self) -> None:
            self.source_refs: list[str] = []

        def extract_source(
            self,
            payload: dict[str, Any],
        ) -> StructuredEvidenceExtractions:
            source_ref = payload["evidence_route"]["source_ref"]
            self.source_refs.append(source_ref)
            if source_ref == "paper-1-a-results":
                raise APIConnectionError(
                    message="provider failure",
                    request=Request("POST", "http://llm.test/v1/chat/completions"),
                )
            return StructuredEvidenceExtractions(
                extractions=[
                    StructuredEvidenceExtraction(
                        evidence_role="condition_context",
                        attribution_scope="descriptive_only",
                        scientific_context={
                            "test": [
                                {"name": "temperature", "value": 25, "unit": "C"}
                            ]
                        },
                        resolution_status="resolved",
                        confidence=0.8,
                    )
                ]
            )

    extractor = RecoveringExtractor()
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    route_specs = (
        ("paper-1", "paper-1-a-results"),
        ("paper-1", "paper-1-b-followup"),
        ("paper-2", "paper-2-results"),
    )
    routes = tuple(
        EvidenceCandidate.from_mapping(
            {
                "objective_id": objective.objective_id,
                "document_id": document_id,
                "source_kind": "text_window",
                "source_ref": source_ref,
                "role": "current_experimental_evidence",
                "extractable": True,
                "confidence": 0.9,
            }
        )
        for document_id, source_ref in route_specs
    )
    blocks = {
        document_id: [
            SimpleNamespace(
                block_id=source_ref,
                text=f"Source text for {source_ref}. Test temperature was 25 C.",
                page=1,
                block_type="paragraph",
                heading_path="Results",
            )
            for route_document_id, source_ref in route_specs
            if route_document_id == document_id
        ]
        for document_id in ("paper-1", "paper-2")
    }

    units = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=routes,
        blocks_by_document_id=blocks,
        tables_by_document_id={},
        document_trees_by_document_id={},
    )

    assert extractor.source_refs == ["paper-1-a-results", "paper-2-results"]
    assert {
        unit.source_ref
        for unit in units
        if unit.document_id == "paper-1" and unit.selection_status == "failed"
    } == {"paper-1-a-results", "paper-1-b-followup"}
    assert any(
        unit.document_id == "paper-2" and unit.selection_status == "extracted"
        for unit in units
    )


def test_objective_evidence_bad_request_does_not_suppress_later_document_route(
):
    class RecoveringExtractor:
        def __init__(self) -> None:
            self.source_refs: list[str] = []

        def extract_source(
            self,
            payload: dict[str, Any],
        ) -> StructuredEvidenceExtractions:
            source_ref = payload["evidence_route"]["source_ref"]
            self.source_refs.append(source_ref)
            if source_ref == "paper-1-invalid":
                request = Request("POST", "http://llm.test/v1/chat/completions")
                raise BadRequestError(
                    "invalid route payload",
                    response=Response(400, request=request),
                    body=None,
                )
            return StructuredEvidenceExtractions(
                extractions=[
                    StructuredEvidenceExtraction(
                        evidence_role="condition_context",
                        attribution_scope="descriptive_only",
                        scientific_context={
                            "test": [
                                {"name": "temperature", "value": 25, "unit": "C"}
                            ]
                        },
                        resolution_status="resolved",
                        confidence=0.8,
                    )
                ]
            )

    extractor = RecoveringExtractor()
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    source_refs = ("paper-1-invalid", "paper-1-valid")
    routes = tuple(
        EvidenceCandidate.from_mapping(
            {
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": source_ref,
                "role": "current_experimental_evidence",
                "extractable": True,
                "confidence": 0.9,
            }
        )
        for source_ref in source_refs
    )
    blocks = [
        SimpleNamespace(
            block_id=source_ref,
            text=f"Source text for {source_ref}. Test temperature was 25 C.",
            page=1,
            block_type="paragraph",
            heading_path="Results",
        )
        for source_ref in source_refs
    ]

    units = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=extractor,
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=routes,
        blocks_by_document_id={"paper-1": blocks},
        tables_by_document_id={},
        document_trees_by_document_id={},
    )

    assert extractor.source_refs == list(source_refs)
    assert [unit.selection_status for unit in units] == ["failed", "extracted"]


def test_objective_evidence_rejects_selected_route_without_source():
    class UnexpectedExtractor:
        def extract_source(self, _payload):
            raise AssertionError("missing Source must fail before model extraction")

    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "missing-block",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )

    with pytest.raises(RuntimeError, match="selected Evidence Source is missing"):
        extract_and_validate_source_facts(
            collection_id="col-test",
            source_extractor=UnexpectedExtractor(),
            objectives=(objective,),
            objective_paper_frames=(),
            objective_evidence_routes=(route,),
            blocks_by_document_id={"paper-1": []},
            tables_by_document_id={},
            document_trees_by_document_id={},
        )


def test_analysis_contributions_report_each_paper_evidence_disposition():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["relative density"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id="col-test",
        objective_id=objective.objective_id,
        analysis_version=1,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name=None,
        prompt_versions={},
    )
    document_ids = (
        "paper-excluded",
        "paper-no-route",
        "paper-failed",
        "paper-context",
        "paper-comparable",
    )
    frames = tuple(
        PaperAnalysisFrame.from_mapping(
            {
                "objective_id": objective.objective_id,
                "document_id": document_id,
                "relevance": (
                    "irrelevant" if document_id == "paper-excluded" else "high"
                ),
                "paper_role": (
                    "irrelevant"
                    if document_id == "paper-excluded"
                    else "primary_experiment"
                ),
                "screening_note": (
                    "Outside the Objective scope."
                    if document_id == "paper-excluded"
                    else "Relevant experiment."
                ),
                "changed_variables": ["laser power"],
                "measured_property_scope": ["relative density"],
            }
        )
        for document_id in document_ids
    )
    routed_documents = ("paper-failed", "paper-context", "paper-comparable")
    routes = tuple(
        EvidenceCandidate.from_mapping(
            {
                "objective_id": objective.objective_id,
                "document_id": document_id,
                "source_kind": "text_window",
                "source_ref": f"block-{document_id}",
                "role": "current_experimental_evidence",
                "extractable": True,
                "confidence": 0.9,
            }
        )
        for document_id in routed_documents
    )

    def evidence(document_id: str, *, kind: str) -> ObjectiveEvidence:
        failed = kind == "failed"
        direct = kind == "direct"
        payload = {
            "collection_id": "col-test",
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "evidence_id": f"evidence-{document_id}",
            "document_id": document_id,
            "source_kind": "text_window",
            "source_ref": f"block-{document_id}",
            "source_excerpt": f"Source excerpt for {document_id}.",
            "evidence_role": (
                "irrelevant" if failed else "direct_result" if direct else "condition_context"
            ),
            "selection_status": "failed" if failed else "extracted",
            "changed_variables": (
                [
                    {
                        "name": "laser power",
                        "baseline_value": 150,
                        "target_value": 200,
                        "unit": "W",
                    }
                ]
                if direct
                else []
            ),
            "comparison": (
                {
                    "baseline_label": "150 W",
                    "target_label": "200 W",
                    "axis_names": ["laser power"],
                    "comparable": True,
                }
                if direct
                else None
            ),
            "reported_result": (
                {
                    "outcome": "relative density",
                    "value": 99.2,
                    "unit": "%",
                    "direction": "increase",
                    "result_text": "Relative density increased.",
                }
                if direct
                else None
            ),
            "attribution_scope": "isolated_effect" if direct else "not_attributable",
            "scientific_context": (
                {}
                if failed
                else {"test": [{"name": "temperature", "value": 25, "unit": "C"}]}
            ),
            "resolution_status": "unknown" if failed else "resolved",
            "failure_reason": "OpenAIError: provider unavailable" if failed else None,
            "confidence": 0.0 if failed else 0.9,
        }
        return ObjectiveEvidence.from_mapping(payload)

    evidence_records = (
        evidence("paper-failed", kind="failed"),
        evidence("paper-context", kind="context"),
        evidence("paper-comparable", kind="direct"),
    )

    contributions = evidence_materialization._analysis_contributions(
        collection_id="col-test",
        analysis=analysis,
        objective=objective,
        paper_skims=(),
        frames=frames,
        routes=routes,
        evidence_records=evidence_records,
    )

    by_document = {item.document_id: item for item in contributions}
    assert by_document["paper-excluded"].evidence_disposition == "excluded"
    assert by_document["paper-no-route"].evidence_disposition == (
        "no_routable_evidence"
    )
    assert by_document["paper-failed"].analysis_status == "failed"
    assert by_document["paper-failed"].evidence_disposition == "extraction_failed"
    assert by_document["paper-failed"].failed_source_count == 1
    assert by_document["paper-context"].evidence_disposition == (
        "no_comparable_evidence"
    )
    assert by_document["paper-context"].extracted_source_count == 1
    assert by_document["paper-comparable"].evidence_disposition == (
        "comparable_evidence"
    )
    assert by_document["paper-comparable"].comparable_evidence_count == 1


def test_objective_context_drops_model_changed_variable_without_values():
    class ContextExtractor:
        def extract_source(
            self,
            payload: dict[str, Any],
        ) -> StructuredEvidenceExtractions:
            return StructuredEvidenceExtractions(
                extractions=[
                    StructuredEvidenceExtraction(
                        evidence_role="condition_context",
                        changed_variables=[
                            {"name": "build platform preheating temperature"}
                        ],
                        attribution_scope="descriptive_only",
                        scientific_context={
                            "process": [
                                {
                                    "name": "build platform preheating temperature",
                                    "value": 150,
                                    "unit": "C",
                                }
                            ]
                        },
                        resolution_status="resolved",
                        confidence=0.8,
                    )
                ]
            )

    objective = _research_objective(
        {
            "objective_id": "obj-preheating",
            "variables": ["build platform preheating temperature"],
            "outcomes": ["microstructure"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-context",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    block = SimpleNamespace(
        block_id="block-context",
        text="The build platform preheating temperature was 150 C.",
        page=2,
        block_type="paragraph",
        heading_path="Methods",
    )

    units = extract_and_validate_source_facts(
        collection_id="col-test",
        source_extractor=ContextExtractor(),
        objectives=(objective,),
        objective_paper_frames=(),
        objective_evidence_routes=(route,),
        blocks_by_document_id={"paper-1": [block]},
        tables_by_document_id={},
        document_trees_by_document_id={},
    )

    assert len(units) == 1
    assert units[0].changed_variables == ()
    assert units[0].comparison is None
    assert units[0].scientific_context.process[0].value == 150


def test_pairwise_comparison_retains_every_changed_process_axis():

    def result(evidence_id: str, values: dict[str, float], density: float):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-density",
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-density",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "relative density",
                    "value": density,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"Relative density = {density}%.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "process": [
                        {"name": name, "value": value}
                        for name, value in values.items()
                    ]
                },
                "source_refs": [
                    {"source_kind": "table", "source_ref": "table-density"}
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        (
            result(
                "row-a",
                {"scan speed": 800, "hatch spacing": 0.12, "VED": 100},
                96.1,
            ),
            result(
                "row-b",
                {"scan speed": 700, "hatch spacing": 0.10, "VED": 120},
                99.2,
            ),
        ),
        objectives=(),
    )

    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert comparison.attribution_scope == "joint_effect"
    assert {item.name for item in comparison.changed_variables} == {
        "scan speed",
        "hatch spacing",
        "VED",
    }
    assert comparison.comparison is not None
    assert comparison.comparison.comparable


def test_pairwise_comparison_joins_process_and_result_tables_by_sample_label(
):

    def process_context(
        evidence_id: str,
        sample_label: str,
        *,
        ved: float,
        laser_power: int,
        scanning_speed: int,
        hatch_spacing: int,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-defect",
                "document_id": "paper-ved",
                "source_kind": "table",
                "source_ref": "table-process",
                "evidence_role": "condition_context",
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "sample": [{"name": "ID", "value": sample_label}],
                    "process": [
                        {
                            "name": "volumetric energy density",
                            "value": ved,
                            "unit": "J/mm3",
                        },
                        {"name": "laser power", "value": laser_power, "unit": "W"},
                        {
                            "name": "scanning speed",
                            "value": scanning_speed,
                            "unit": "mm/s",
                        },
                        {
                            "name": "hatch spacing",
                            "value": hatch_spacing,
                            "unit": "um",
                        },
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-process",
                        "source_excerpt": f"ID: {sample_label} | VED: {ved}",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    def defect_result(
        evidence_id: str,
        sample_label: str,
        defect_length: int,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-defect",
                "document_id": "paper-ved",
                "source_kind": "table",
                "source_ref": "table-defect",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "max defect length",
                    "value": defect_length,
                    "unit": "um",
                    "direction": "unknown",
                    "result_text": f"Max defect length = {defect_length} um.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "sample": [
                        {"name": "Printed 316L", "value": sample_label}
                    ]
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-defect",
                        "source_excerpt": (
                            f"Printed 316L: {sample_label} | Max defect length: "
                            f"{defect_length}"
                        ),
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    units = (
        process_context(
            "process-low",
            "L-VED",
            ved=50.8,
            laser_power=160,
            scanning_speed=875,
            hatch_spacing=120,
        ),
        process_context(
            "process-high",
            "H-VED",
            ved=84.3,
            laser_power=220,
            scanning_speed=725,
            hatch_spacing=120,
        ),
        defect_result("defect-low", "L-VED", 394),
        defect_result("defect-high", "H-VED", 86),
    )

    bound_units = paper_experiment._bind_objective_result_process_context(units)
    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        bound_units,
        objectives=(),
    )

    assert {
        item.name for item in bound_units[2].scientific_context.process
    } == {
        "volumetric energy density",
        "laser power",
        "scanning speed",
        "hatch spacing",
    }
    assert {ref["source_ref"] for ref in bound_units[2].source_refs} == {
        "table-process",
        "table-defect",
    }
    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert comparison.attribution_scope == "joint_effect"
    assert {item.name for item in comparison.changed_variables} == {
        "volumetric energy density",
        "laser power",
        "scanning speed",
    }


def test_text_result_process_binding_requires_exact_groups_and_expands_axes(
):

    def process_context(
        evidence_id: str,
        sample_label: str,
        *,
        ved: float,
        laser_power: int,
        scanning_speed: int,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-defect",
                "document_id": "paper-ved",
                "source_kind": "table",
                "source_ref": "table-process",
                "evidence_role": "condition_context",
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "sample": [{"name": "ID", "value": sample_label}],
                    "process": [
                        {
                            "name": "volumetric energy density",
                            "value": ved,
                            "unit": "J/mm3",
                        },
                        {"name": "laser power", "value": laser_power, "unit": "W"},
                        {
                            "name": "scanning speed",
                            "value": scanning_speed,
                            "unit": "mm/s",
                        },
                        {"name": "hatch spacing", "value": 120, "unit": "um"},
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-process",
                        "source_excerpt": f"ID: {sample_label} | VED: {ved}",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    def text_result(
        evidence_id: str,
        baseline_label: str,
        target_label: str,
        source_excerpt: str,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-defect",
                "document_id": "paper-ved",
                "source_kind": "text_window",
                "source_ref": evidence_id,
                "evidence_role": "direct_result",
                "changed_variables": [
                    {
                        "name": "volumetric energy density",
                        "baseline_value": baseline_label,
                        "target_value": target_label,
                    }
                ],
                "comparison": {
                    "baseline_label": baseline_label,
                    "target_label": target_label,
                    "axis_names": ["volumetric energy density"],
                    "comparable": True,
                },
                "reported_result": {
                    "outcome": "defect structure",
                    "value": None,
                    "unit": None,
                    "direction": "decrease",
                    "result_text": "Maximum defect sizes decrease with increasing VED.",
                },
                "attribution_scope": "isolated_effect",
                "source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": evidence_id,
                        "source_excerpt": source_excerpt,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.95,
            }
        )

    units = paper_experiment._bind_objective_result_process_context(
        (
            process_context(
                "process-low",
                "L-VED",
                ved=50.8,
                laser_power=160,
                scanning_speed=875,
            ),
            process_context(
                "process-high",
                "H-VED",
                ved=84.3,
                laser_power=220,
                scanning_speed=725,
            ),
            text_result(
                "block-defects",
                "L-VED",
                "H-VED",
                "Maximum defect sizes decrease from L-VED to H-VED.",
            ),
            text_result(
                "block-fatigue",
                "high",
                "low",
                (
                    "The high VED structure had the largest defect. All structures "
                    "exhibited a low fatigue limit."
                ),
            ),
        )
    )

    grounded = units[2]
    assert grounded.attribution_scope == "joint_effect"
    assert {
        item.name for item in grounded.changed_variables
    } == {
        "volumetric energy density",
        "laser power",
        "scanning speed",
    }
    assert grounded.comparison is not None
    assert set(grounded.comparison.axis_names) == {
        "volumetric energy density",
        "laser power",
        "scanning speed",
    }
    assert {
        item.name for item in grounded.scientific_context.process
    } == {"hatch spacing"}
    assert {ref["source_ref"] for ref in grounded.source_refs} == {
        "block-defects",
        "table-process",
    }

    ungrounded = units[3]
    assert ungrounded.attribution_scope == "not_attributable"
    assert ungrounded.changed_variables == ()
    assert ungrounded.comparison is not None
    assert not ungrounded.comparison.comparable
    assert ungrounded.comparison.incomparability_reasons == (
        "comparison groups do not bind to source process conditions",
    )


def test_total_elongation_column_is_result_not_process_context():
    objective = _research_objective(
        {
            "objective_id": "obj-hip-elongation",
            "question": "How does cooling rate after HIP affect elongation?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["cooling rate after HIP"],
            "outcomes": ["elongation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-hip",
            "source_kind": "table",
            "source_ref": "table-tensile-properties",
            "role": "process_or_treatment",
            "extractable": True,
            "column_roles": {
                "Condition": "sample condition",
                "TE (%)": "process variable",
            },
            "confidence": 0.95,
        }
    )

    records = source_extraction._objective_table_matrix_evidence_records(
        route=route,
        objective_context=objective,
        source={
            "source_kind": "table",
            "source_ref": route.source_ref,
            "caption_text": (
                "Tensile properties of laser powder bed fusion Ti-6Al-4V "
                "after HIP treatments. TE = total elongation."
            ),
            "column_headers": ["Condition", "TE (%)"],
            "table_matrix": [
                ["Condition", "TE (%)"],
                ["800 FC", "27.56 +/- 2.57"],
                ["800 RQ", "28.86 +/- 0.92"],
            ],
        },
    )

    results = [record for record in records if record["reported_result"]]
    contexts = [record for record in records if not record["reported_result"]]
    assert [record["reported_result"]["outcome"] for record in results] == [
        "elongation",
        "elongation",
    ]
    assert all(
        attribute["name"] != "TE (%)"
        for record in contexts
        for attribute in record["scientific_context"]["process"]
    )


def test_source_reported_hip_cooling_comparison_remains_an_association():
    objective = _research_objective(
        {
            "objective_id": "obj-hip-elongation",
            "question": "How does cooling rate after HIP affect elongation?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["cooling rate after HIP"],
            "outcomes": ["elongation"],
        }
    )

    def condition_context(evidence_id: str, label: str) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-hip-elongation",
                "document_id": "paper-hip",
                "source_kind": "table",
                "source_ref": "table-tensile-properties",
                "evidence_role": "condition_context",
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "sample": [{"name": "Condition", "value": label}],
                    "process": [
                        {
                            "name": "manufacturing process",
                            "value": "laser powder bed fusion",
                        }
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-tensile-properties",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.95,
            }
        )

    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-hip-elongation",
            "objective_id": "obj-hip-elongation",
            "document_id": "paper-hip",
            "source_kind": "text_window",
            "source_ref": "results-cooling-rate",
            "evidence_role": "direct_result",
            "changed_variables": [],
            "comparison": {
                "baseline_label": "800 FC",
                "target_label": "800 RQ",
                "axis_names": ["cooling rate"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "elongation",
                "direction": "no_change",
                "result_text": (
                    "With increased cooling rate, elongation of the 800 C HIP "
                    "treatments remained relatively unchanged."
                ),
            },
            "attribution_scope": "association_only",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-cooling-rate",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    bound = paper_experiment._bind_objective_result_process_context(
        (
            condition_context("condition-800-fc", "800 FC"),
            condition_context("condition-800-rq", "800 RQ"),
            result,
        )
    )[2]

    assert bound.attribution_scope == "association_only"
    assert [item.name for item in bound.changed_variables] == ["cooling rate"]
    assert bound.comparison is not None
    assert bound.comparison.comparable
    assert {ref["source_ref"] for ref in bound.source_refs} == {
        "results-cooling-rate",
        "table-tensile-properties",
    }

    canonical = evidence_materialization._canonical_objective_evidence_axes(
        bound,
        objective=objective,
    )
    evidence = ObjectiveEvidence.from_mapping(
        {
            **canonical.to_record(),
            "collection_id": objective.collection_id,
            "analysis_version": 1,
            "source_excerpt": (
                "With increased cooling rate, elongation of the 800 C HIP "
                "treatments remained relatively unchanged."
            ),
        }
    )

    assert [item.name for item in evidence.changed_variables] == ["cooling rate"]
    assert finding_synthesis.FindingSynthesisService.is_comparable_result_evidence(
        objective,
        evidence,
    )


def test_hip_cooling_groups_bind_across_repeated_condition_tables():
    objective = _research_objective(
        {
            "objective_id": "obj-hip-elongation",
            "question": "How does cooling rate after HIP affect elongation?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["cooling rate after HIP"],
            "outcomes": ["elongation"],
        }
    )
    tensile_route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-hip",
            "source_kind": "table",
            "source_ref": "table-tensile-properties",
            "role": "process_or_treatment",
            "extractable": True,
            "column_roles": {
                "Condition": "sample condition",
                "TE (%)": "process variable",
            },
            "confidence": 0.95,
        }
    )
    table_records = source_extraction._objective_table_matrix_evidence_records(
        route=tensile_route,
        objective_context=objective,
        source={
            "source_kind": "table",
            "source_ref": tensile_route.source_ref,
            "caption_text": (
                "Tensile properties of laser powder bed fusion Ti-6Al-4V "
                "after HIP treatments. TE = total elongation."
            ),
            "column_headers": ["Condition", "TE (%)"],
            "table_matrix": [
                ["Condition", "TE (%)"],
                ["800 FC", "27.56 +/- 2.57"],
                ["800 RQ", "28.86 +/- 0.92"],
            ],
        },
    )
    condition_contexts = tuple(
        ExtractedEvidenceDraft.from_mapping(record)
        for record in table_records
        if record["reported_result"] is None
    )

    def repeated_context(evidence_id: str, label: str) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
                "document_id": "paper-hip",
                "source_kind": "table",
                "source_ref": "table-microstructure",
                "evidence_role": "condition_context",
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "sample": [{"name": "Condition", "value": label}],
                    "process": [
                        {
                            "name": "manufacturing process",
                            "value": "laser powder bed fusion",
                        }
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-microstructure",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-hip-elongation",
            "objective_id": objective.objective_id,
            "document_id": "paper-hip",
            "source_kind": "text_window",
            "source_ref": "results-cooling-rate",
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "cooling rate after HIP",
                    "baseline_value": "800 FC",
                    "target_value": "800 RQ",
                }
            ],
            "comparison": {
                "baseline_label": "800 FC",
                "target_label": "800 RQ",
                "axis_names": ["cooling rate after HIP"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "elongation",
                "direction": "no_change",
                "result_text": (
                    "With increased cooling rate, elongation of the 800 C HIP "
                    "treatments remained relatively unchanged."
                ),
            },
            "attribution_scope": "isolated_effect",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-cooling-rate",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    bound = paper_experiment._bind_objective_result_process_context(
        (
            *condition_contexts,
            repeated_context("condition-800-fc", "800 FC"),
            repeated_context("condition-800-rq", "800 RQ"),
            result,
        )
    )[-1]

    assert bound.attribution_scope == "association_only"
    assert [item.name for item in bound.changed_variables] == [
        "cooling rate after HIP"
    ]
    assert bound.comparison is not None
    assert bound.comparison.comparable
    assert bound.reported_result is not None
    assert bound.reported_result.direction == "no_change"
    assert {ref["source_ref"] for ref in bound.source_refs} == {
        "results-cooling-rate",
        "table-tensile-properties",
    }


def test_process_result_table_join_rejects_conflicting_sample_context():
    context_payload = {
        "objective_id": "obj-defect",
        "document_id": "paper-ved",
        "source_kind": "table",
        "evidence_role": "condition_context",
        "attribution_scope": "not_attributable",
        "scientific_context": {
            "sample": [{"name": "ID", "value": "L-VED"}],
        },
        "source_refs": [{"source_kind": "table", "source_ref": "table-process"}],
        "resolution_status": "resolved",
    }
    first_context = ExtractedEvidenceDraft.from_mapping(
        {
            **context_payload,
            "evidence_id": "process-low-a",
            "scientific_context": {
                **context_payload["scientific_context"],
                "process": [{"name": "laser power", "value": 160, "unit": "W"}],
            },
        }
    )
    conflicting_context = ExtractedEvidenceDraft.from_mapping(
        {
            **context_payload,
            "evidence_id": "process-low-b",
            "scientific_context": {
                **context_payload["scientific_context"],
                "process": [{"name": "laser power", "value": 190, "unit": "W"}],
            },
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "defect-low",
            "objective_id": "obj-defect",
            "document_id": "paper-ved",
            "source_kind": "table",
            "source_ref": "table-defect",
            "evidence_role": "direct_result",
            "reported_result": {
                "outcome": "max defect length",
                "value": 394,
                "unit": "um",
                "direction": "unknown",
                "result_text": "Max defect length = 394 um.",
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": {
                "sample": [{"name": "Printed 316L", "value": "L-VED"}]
            },
            "source_refs": [{"source_kind": "table", "source_ref": "table-defect"}],
            "resolution_status": "resolved",
        }
    )

    bound = paper_experiment._bind_objective_result_process_context(
        (first_context, conflicting_context, result)
    )

    assert bound[2] == result


def test_pairwise_comparison_isolated_effect_requires_one_changed_axis():

    def result(evidence_id: str, scan_speed: int, density: float):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-density",
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-density",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "relative density",
                    "value": density,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"Relative density = {density}%.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "process": [
                        {"name": "scan speed", "value": scan_speed, "unit": "mm/s"},
                        {"name": "laser power", "value": 200, "unit": "W"},
                    ]
                },
                "source_refs": [
                    {"source_kind": "table", "source_ref": "table-density"}
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    comparison = paper_experiment._build_objective_pairwise_comparison_units(
        (result("row-a", 800, 96.1), result("row-b", 700, 99.2)),
        objectives=(),
    )[0]

    assert comparison.attribution_scope == "isolated_effect"
    assert [item.name for item in comparison.changed_variables] == ["scan speed"]
    assert comparison.comparison is not None
    assert comparison.comparison.axis_names == ("scan speed",)
    assert comparison.scientific_context.to_record() == {
        "material": [],
        "sample": [],
        "process": [{"name": "laser power", "value": 200, "unit": "W"}],
        "test": [],
    }


def test_pairwise_comparison_marks_sample_state_change_incomparable():

    def result(
        evidence_id: str,
        *,
        energy_density: int,
        sample_state: str,
        yield_strength: float,
    ):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-strength",
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-strength",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "yield strength",
                    "value": yield_strength,
                    "unit": "MPa",
                    "direction": "unknown",
                    "result_text": f"Yield strength = {yield_strength} MPa.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "sample": [{"name": "sample state", "value": sample_state}],
                    "process": [
                        {
                            "name": "energy density",
                            "value": energy_density,
                            "unit": "J/mm3",
                        }
                    ],
                },
                "source_refs": [
                    {"source_kind": "table", "source_ref": "table-strength"}
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    comparison = paper_experiment._build_objective_pairwise_comparison_units(
        (
            result(
                "as-slm",
                energy_density=194,
                sample_state="as-SLM",
                yield_strength=426.7,
            ),
            result(
                "hip-slm",
                energy_density=167,
                sample_state="HIP-SLM",
                yield_strength=265.1,
            ),
        ),
        objectives=(),
    )[0]

    assert comparison.attribution_scope == "not_attributable"
    assert comparison.comparison is not None
    assert not comparison.comparison.comparable
    assert any(
        "sample condition differs for sample state" in reason
        for reason in comparison.comparison.incomparability_reasons
    )


def test_pairwise_comparison_keeps_semantic_values_from_generic_sample_column(
):

    def result(evidence_id: str, sample: str, energy_density: int, strength: float):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-strength",
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-strength",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "yield strength",
                    "value": strength,
                    "unit": "MPa",
                    "direction": "unknown",
                    "result_text": f"Yield strength = {strength} MPa.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "sample": [{"name": "Sample", "value": sample}],
                    "process": [
                        {
                            "name": "energy density",
                            "value": energy_density,
                            "unit": "J/mm3",
                        }
                    ],
                },
                "source_refs": [
                    {"source_kind": "table", "source_ref": "table-strength"}
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    comparison = paper_experiment._build_objective_pairwise_comparison_units(
        (
            result("as-slm", "as-SLM", 194, 426.7),
            result("hip-slm", "HIP-SLM", 167, 265.1),
        ),
        objectives=(),
    )[0]

    assert comparison.attribution_scope == "not_attributable"
    assert comparison.comparison is not None
    assert any(
        "sample condition differs for Sample" in reason
        for reason in comparison.comparison.incomparability_reasons
    )


def test_pairwise_comparison_marks_sparse_process_axis_incomparable():

    def result(evidence_id: str, process: list[dict[str, Any]], value: float):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-density",
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-density",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "relative density",
                    "value": value,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"Relative density = {value}%.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {"process": process},
                "source_refs": [
                    {"source_kind": "table", "source_ref": "table-density"}
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    comparison = paper_experiment._build_objective_pairwise_comparison_units(
        (
            result("row-a", [{"name": "scan speed", "value": 800}], 96.1),
            result(
                "row-b",
                [
                    {"name": "scan speed", "value": 700},
                    {"name": "hatch spacing", "value": 0.1},
                ],
                99.2,
            ),
        ),
        objectives=(),
    )[0]

    assert comparison.attribution_scope == "not_attributable"
    assert comparison.comparison is not None
    assert not comparison.comparison.comparable
    assert any(
        "missing one group value for hatch spacing" in reason
        for reason in comparison.comparison.incomparability_reasons
    )


def test_pairwise_comparison_is_bounded_per_objective_document():
    measurements = tuple(
        ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": f"row-{index}",
                "objective_id": "obj-density",
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-density",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "relative density",
                    "value": 90 + index / 10,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"Relative density = {90 + index / 10}%.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "process": [{"name": "scan speed", "value": 500 + index}]
                },
                "source_refs": [
                    {"source_kind": "table", "source_ref": "table-density"}
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )
        for index in range(100)
    )

    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        measurements,
        objectives=(),
    )

    assert len(comparisons) == 48


def test_table_material_and_cell_locators_bound_comparison_source():
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-density",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-density",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Material": "material",
                "Scan speed": "process_variable",
                "Relative density [%]": "result_property",
            },
            "confidence": 0.9,
        }
    )
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "material_scope": ["316L", "Ti-6Al-4V"],
            "variables": ["scan speed"],
            "outcomes": ["relative density"],
        }
    )
    source = {
        "page": 4,
        "column_headers": ["Material", "Scan speed", "Relative density [%]"],
        "table_matrix": [
            ["Material", "Scan speed", "Relative density [%]"],
            ["316L", "800", "96.1"],
            ["Ti-6Al-4V", "700", "99.2"],
        ],
    }
    measurements = tuple(
        ExtractedEvidenceDraft.from_mapping(record)
        for record in source_extraction._objective_table_matrix_evidence_records(
            route=route,
            source=source,
            objective_context=objective,
        )
    )

    assert [item.value for item in measurements[0].scientific_context.material] == [
        "316L"
    ]
    assert measurements[0].source_refs[0]["row_index"] == 1
    assert measurements[0].source_refs[0]["col_index"] == 2
    assert measurements[0].source_refs[0]["header_path"] == "Relative density [%]"
    comparison = paper_experiment._build_objective_pairwise_comparison_units(
        measurements,
        objectives=(objective,),
    )[0]
    assert comparison.attribution_scope == "not_attributable"
    assert comparison.comparison is not None
    assert any(
        "material condition differs for Material" in reason
        for reason in comparison.comparison.incomparability_reasons
    )

    analysis = ObjectiveAnalysis(
        collection_id="col-test",
        objective_id="obj-density",
        analysis_version=1,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name=None,
        prompt_versions={},
    )
    table = SimpleNamespace(
        table_id="table-density",
        page=4,
        to_record=lambda: {"table_markdown": "full table"},
    )
    evidence = evidence_materialization._analysis_evidence_records(
        collection_id="col-test",
        analysis=analysis,
        objective=objective,
        drafts=(comparison,),
        blocks_by_document_id={},
        tables_by_document_id={"paper-1": [table]},
        figures_by_document_id={},
    )[0]
    assert "Material: 316L" in evidence.source_excerpt
    assert "Material: Ti-6Al-4V" in evidence.source_excerpt
    assert {ref["row_index"] for ref in evidence.related_source_refs} == {1, 2}


def test_analysis_evidence_preserves_distinct_claims_from_one_table_source():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["scan speed"],
            "outcomes": ["relative density"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id="col-test",
        objective_id=objective.objective_id,
        analysis_version=1,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name=None,
        prompt_versions={},
    )
    drafts = tuple(
        ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-density",
                "evidence_role": "direct_result",
                "selection_status": "extracted",
                "changed_variables": [
                    {
                        "name": "scan speed",
                        "target_value": scan_speed,
                        "unit": "mm/s",
                    }
                ],
                "reported_result": {
                    "outcome": "relative density",
                    "value": density,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"Relative density was {density}%.",
                },
                "attribution_scope": "descriptive_only",
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-density",
                        "row_index": row_index,
                        "col_index": 2,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )
        for evidence_id, row_index, scan_speed, density in (
            ("evidence-row-1", 1, 700, 98.1),
            ("evidence-row-2", 2, 900, 99.2),
        )
    )
    table = SimpleNamespace(
        table_id="table-density",
        page=4,
        to_record=lambda: {
            "table_markdown": (
                "| Scan speed (mm/s) | Relative density (%) |\n"
                "| --- | --- |\n"
                "| 700 | 98.1 |\n"
                "| 900 | 99.2 |"
            )
        },
    )

    evidence = evidence_materialization._analysis_evidence_records(
        collection_id="col-test",
        analysis=analysis,
        objective=objective,
        drafts=drafts,
        blocks_by_document_id={},
        tables_by_document_id={"paper-1": [table]},
        figures_by_document_id={},
    )

    assert {item.evidence_id for item in evidence} == {
        "evidence-row-1",
        "evidence-row-2",
    }
    assert {
        item.related_source_refs[0]["row_index"] for item in evidence
    } == {1, 2}


@pytest.mark.parametrize(
    ("baseline_phase", "target_phase", "expected_direction"),
    (
        ("alpha-prime", "alpha+beta", "changed"),
        ("alpha+beta", "alpha+beta", "no_change"),
    ),
)
def test_pairwise_comparison_preserves_categorical_result_transition(
    baseline_phase: str,
    target_phase: str,
    expected_direction: str,
):
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-phase",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-phase",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Heat treatment": "process_variable",
                "Phase composition": "result_property",
            },
            "confidence": 0.9,
        }
    )
    objective = _research_objective(
        {
            "objective_id": "obj-phase",
            "variables": ["heat treatment"],
            "outcomes": ["phase composition"],
        }
    )
    measurements = tuple(
        ExtractedEvidenceDraft.from_mapping(record)
        for record in source_extraction._objective_table_matrix_evidence_records(
            route=route,
            source={
                "page": 6,
                "column_headers": ["Heat treatment", "Phase composition"],
                "table_matrix": [
                    ["Heat treatment", "Phase composition"],
                    ["as-built", baseline_phase],
                    ["annealed", target_phase],
                ],
            },
            objective_context=objective,
        )
    )

    assert [item.reported_result.value for item in measurements] == [
        baseline_phase,
        target_phase,
    ]
    comparison = paper_experiment._build_objective_pairwise_comparison_units(
        measurements,
        objectives=(objective,),
    )[0]

    assert comparison.reported_result is not None
    assert comparison.reported_result.baseline_value == baseline_phase
    assert comparison.reported_result.target_value == target_phase
    assert comparison.reported_result.direction == expected_direction
    assert comparison.comparison is not None
    assert comparison.comparison.comparable is True
    assert comparison.attribution_scope == "isolated_effect"


def test_pairwise_categorical_result_keeps_context_conflict_incomparable():
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "obj-phase",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-phase",
            "role": "current_experimental_evidence",
            "extractable": True,
            "column_roles": {
                "Material": "material",
                "Heat treatment": "process_variable",
                "Phase composition": "result_property",
            },
            "confidence": 0.9,
        }
    )
    objective = _research_objective(
        {
            "objective_id": "obj-phase",
            "variables": ["heat treatment"],
            "outcomes": ["phase composition"],
        }
    )
    measurements = tuple(
        ExtractedEvidenceDraft.from_mapping(record)
        for record in source_extraction._objective_table_matrix_evidence_records(
            route=route,
            source={
                "page": 6,
                "column_headers": [
                    "Material",
                    "Heat treatment",
                    "Phase composition",
                ],
                "table_matrix": [
                    ["Material", "Heat treatment", "Phase composition"],
                    ["Ti-6Al-4V", "as-built", "alpha-prime"],
                    ["316L", "annealed", "alpha+beta"],
                ],
            },
            objective_context=objective,
        )
    )

    comparison = paper_experiment._build_objective_pairwise_comparison_units(
        measurements,
        objectives=(objective,),
    )[0]

    assert comparison.reported_result is not None
    assert comparison.reported_result.direction == "changed"
    assert comparison.comparison is not None
    assert comparison.comparison.comparable is False
    assert comparison.attribution_scope == "not_attributable"
    assert any(
        "material condition differs" in reason
        for reason in comparison.comparison.incomparability_reasons
    )


def test_pairwise_mixed_result_value_types_are_incomparable():
    objective = _research_objective(
        {
            "objective_id": "obj-phase",
            "variables": ["heat treatment"],
            "outcomes": ["phase composition"],
        }
    )
    measurements = tuple(
        ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": f"phase-{index}",
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": "table-phase",
                "evidence_role": "direct_result",
                "selection_status": "extracted",
                "reported_result": {
                    "outcome": "phase composition",
                    "value": value,
                    "direction": "unknown",
                    "result_text": f"Phase composition = {value}",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "process": [{"name": "heat treatment", "value": treatment}]
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-phase",
                        "row_index": index,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )
        for index, treatment, value in (
            (1, "as-built", 1),
            (2, "annealed", "alpha+beta"),
        )
    )

    comparison = paper_experiment._build_objective_pairwise_comparison_units(
        measurements,
        objectives=(objective,),
    )[0]

    assert comparison.reported_result is not None
    assert comparison.reported_result.direction == "unknown"
    assert comparison.comparison is not None
    assert comparison.comparison.comparable is False
    assert any(
        "result value types differ" in reason
        for reason in comparison.comparison.incomparability_reasons
    )


def test_analysis_evidence_uses_confirmed_objective_axis_names():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power", "base plate preheating temperature"],
            "outcomes": ["density"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id="col-test",
        objective_id=objective.objective_id,
        analysis_version=1,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name=None,
        prompt_versions={},
    )
    draft = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "evidence-unit-qualified-axes",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-results",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "Laser power (W)",
                    "baseline_value": 100,
                    "target_value": 120,
                },
                {
                    "name": "preheating",
                    "baseline_value": 25,
                    "target_value": 200,
                    "unit": "C",
                },
                {
                    "name": "layer thickness",
                    "baseline_value": 30,
                    "target_value": 50,
                    "unit": "um",
                },
            ],
            "comparison": {
                "baseline_label": "condition A",
                "target_label": "condition B",
                "axis_names": [
                    "Laser power (W)",
                    "preheating",
                    "layer thickness",
                ],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "Density (%)",
                "value": 98.7,
                "unit": "%",
                "direction": "increase",
                "result_text": "Density increased to 98.7%.",
            },
            "attribution_scope": "joint_effect",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "block-results",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    block = SimpleNamespace(
        block_id="block-results",
        text=(
            "Laser power and preheating were varied, and density increased to "
            "98.7%."
        ),
        page=3,
        block_type="paragraph",
        heading_path="Results",
    )

    evidence = evidence_materialization._analysis_evidence_records(
        collection_id="col-test",
        analysis=analysis,
        objective=objective,
        drafts=(draft,),
        blocks_by_document_id={"paper-1": [block]},
        tables_by_document_id={},
        figures_by_document_id={},
    )[0]

    assert tuple(item.name for item in evidence.changed_variables) == (
        "laser power",
        "base plate preheating temperature",
        "layer thickness",
    )
    assert evidence.comparison is not None
    assert evidence.comparison.axis_names == (
        "laser power",
        "base plate preheating temperature",
        "layer thickness",
    )
    assert evidence.reported_result is not None
    assert evidence.reported_result.outcome == "density"


def test_analysis_evidence_merges_duplicate_aliases_for_one_objective_axis():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["density"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id="col-test",
        objective_id=objective.objective_id,
        analysis_version=1,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name=None,
        prompt_versions={},
    )
    draft = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "evidence-duplicate-axis-alias",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-results",
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "laser power",
                    "baseline_value": 100,
                    "target_value": 120,
                    "unit": "W",
                },
                {
                    "name": "Laser power (W)",
                    "baseline_value": 100,
                    "target_value": 120,
                },
            ],
            "comparison": {
                "baseline_label": "100 W",
                "target_label": "120 W",
                "axis_names": ["laser power", "Laser power (W)"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "Density (%)",
                "value": 98.7,
                "unit": "%",
                "direction": "increase",
                "result_text": "Density increased to 98.7%.",
            },
            "attribution_scope": "joint_effect",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "block-results",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    block = SimpleNamespace(
        block_id="block-results",
        text="Laser power increased from 100 W to 120 W.",
        page=3,
    )

    evidence = evidence_materialization._analysis_evidence_records(
        collection_id="col-test",
        analysis=analysis,
        objective=objective,
        drafts=(draft,),
        blocks_by_document_id={"paper-1": [block]},
        tables_by_document_id={},
        figures_by_document_id={},
    )[0]

    assert [item.to_record() for item in evidence.changed_variables] == [
        {
            "name": "laser power",
            "baseline_value": 100,
            "target_value": 120,
            "unit": "W",
        }
    ]
    assert evidence.comparison is not None
    assert evidence.comparison.axis_names == ("laser power",)
    assert evidence.attribution_scope == "isolated_effect"


def test_analysis_evidence_marks_conflicting_axis_aliases_failed():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["density"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id="col-test",
        objective_id=objective.objective_id,
        analysis_version=1,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name=None,
        prompt_versions={},
    )
    draft = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "evidence-conflicting-axis-alias",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-results",
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "laser power",
                    "baseline_value": 100,
                    "target_value": 120,
                    "unit": "W",
                },
                {
                    "name": "Laser power (W)",
                    "baseline_value": 100,
                    "target_value": 140,
                    "unit": "W",
                },
            ],
            "comparison": {
                "baseline_label": "100 W",
                "target_label": "reported target",
                "axis_names": ["laser power", "Laser power (W)"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "density",
                "value": 98.7,
                "unit": "%",
                "direction": "increase",
                "result_text": "Density increased to 98.7%.",
            },
            "attribution_scope": "joint_effect",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "block-results",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    block = SimpleNamespace(
        block_id="block-results",
        text="The source reports inconsistent laser-power endpoints.",
        page=3,
    )

    evidence = evidence_materialization._analysis_evidence_records(
        collection_id="col-test",
        analysis=analysis,
        objective=objective,
        drafts=(draft,),
        blocks_by_document_id={"paper-1": [block]},
        tables_by_document_id={},
        figures_by_document_id={},
    )[0]

    assert evidence.selection_status == "failed"
    assert evidence.failure_reason is not None
    assert "conflicting values for Objective axis laser power" in evidence.failure_reason
    assert evidence.changed_variables == ()
    assert evidence.comparison is None
    assert evidence.reported_result is None


def test_analysis_evidence_rejects_draft_without_resolvable_source():
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power"],
            "outcomes": ["density"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id="col-test",
        objective_id=objective.objective_id,
        analysis_version=1,
        source_build_id="build-1",
        pipeline_version="test.v1",
        model_name=None,
        prompt_versions={},
    )
    draft = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "evidence-missing-source",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "missing-block",
            "evidence_role": "condition_context",
            "attribution_scope": "descriptive_only",
            "scientific_context": {
                "test": [{"name": "temperature", "value": 25, "unit": "C"}]
            },
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )

    with pytest.raises(RuntimeError, match="Evidence Source cannot be resolved"):
        evidence_materialization._analysis_evidence_records(
            collection_id="col-test",
            analysis=analysis,
            objective=objective,
            drafts=(draft,),
            blocks_by_document_id={"paper-1": []},
            tables_by_document_id={},
            figures_by_document_id={},
        )


def test_real_hip_multilevel_condition_table_reconstructs_experiment_conditions():
    objective = _research_objective(
        {
            "objective_id": "obj-hip-elongation",
            "question": "How does cooling rate after HIP affect elongation?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["cooling rate after HIP"],
            "outcomes": ["elongation"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-hip",
            "source_kind": "table",
            "source_ref": "table-hip-conditions",
            "role": "process_or_treatment",
            "extractable": True,
            "column_roles": {
                "Nomenclature": "sample_condition",
                "Heat Treatment": "process_context",
                "Temper": "process_context",
            },
            "confidence": 0.95,
        }
    )

    records = source_extraction._objective_table_matrix_evidence_records(
        route=route,
        objective_context=objective,
        source={
            "source_kind": "table",
            "source_ref": route.source_ref,
            "caption_text": (
                "Nominal HIP conditions. Heating/cooling rates are in C/min. "
                "Up and down arrows refer to the nominal heating rates and "
                "cooling rates, respectively."
            ),
            "column_headers": [
                "Nomenclature",
                "Heat Treatment",
                "Heat Treatment",
                "Heat Treatment",
                "Heat Treatment",
                "Heat Treatment",
                "Temper",
                "Temper",
                "Temper",
                "Temper",
                "Temper",
                "Temper",
            ],
            "table_matrix": [
                [
                    "Nomenclature",
                    "Heat Treatment",
                    "Heat Treatment",
                    "Heat Treatment",
                    "Heat Treatment",
                    "Heat Treatment",
                    "Temper",
                    "Temper",
                    "Temper",
                    "Temper",
                    "Temper",
                    "Temper",
                ],
                [
                    "HT",
                    "Color",
                    "up",
                    "T (C)",
                    "P (MPa)",
                    "t (hr)",
                    "down",
                    "up",
                    "T (C)",
                    "P (MPa)",
                    "t (hr)",
                    "down",
                ],
                [
                    "800 SC",
                    "black",
                    "12",
                    "800",
                    "200",
                    "2",
                    "12",
                    "-",
                    "-",
                    "-",
                    "-",
                    "-",
                ],
                [
                    "800 FC",
                    "black",
                    "12",
                    "800",
                    "200",
                    "2",
                    "100",
                    "-",
                    "-",
                    "-",
                    "-",
                    "-",
                ],
                [
                    "800 RQ",
                    "black",
                    "12",
                    "800",
                    "200",
                    "2",
                    "2000",
                    "-",
                    "-",
                    "-",
                    "-",
                    "-",
                ],
            ],
        },
    )

    conditions = tuple(
        ExtractedEvidenceDraft.from_mapping(record)
        for record in records
        if record["evidence_role"] == "condition_context"
    )
    assert len(conditions) == 3
    assert [
        paper_experiment._objective_explicit_sample_identity(item)
        for item in conditions
    ] == [
        "800 sc",
        "800 fc",
        "800 rq",
    ]
    process_by_label = {
        paper_experiment._objective_explicit_sample_identity(item): {
            attribute.name: (attribute.value, attribute.unit)
            for attribute in item.scientific_context.process
        }
        for item in conditions
    }
    assert process_by_label["800 sc"] == {
        "heating rate": ("12", "C/min"),
        "heat treatment temperature": ("800", "C"),
        "heat treatment pressure": ("200", "MPa"),
        "heat treatment duration": ("2", "hr"),
        "cooling rate": ("12", "C/min"),
    }
    assert process_by_label["800 rq"]["cooling rate"] == ("2000", "C/min")


def test_real_hip_result_uses_condition_registry_when_model_omits_comparison():
    objective = _research_objective(
        {
            "objective_id": "obj-hip-elongation",
            "question": "How does cooling rate after HIP affect elongation?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["cooling rate after HIP"],
            "outcomes": ["elongation"],
        }
    )

    def condition(
        label: str,
        cooling_rate: str,
        row_index: int,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": f"condition-{label.casefold().replace(' ', '-')}",
                "objective_id": objective.objective_id,
                "document_id": "paper-hip",
                "source_kind": "table",
                "source_ref": "table-hip-conditions",
                "evidence_role": "condition_context",
                "attribution_scope": "not_attributable",
                "scientific_context": {
                    "material": [{"name": "material", "value": "Ti-6Al-4V"}],
                    "sample": [{"name": "condition", "value": label}],
                    "process": [
                        {"name": "heating rate", "value": "12", "unit": "C/min"},
                        {
                            "name": "heat treatment temperature",
                            "value": "800",
                            "unit": "C",
                        },
                        {
                            "name": "heat treatment pressure",
                            "value": "200",
                            "unit": "MPa",
                        },
                        {"name": "heat treatment duration", "value": "2", "unit": "hr"},
                        {
                            "name": "cooling rate",
                            "value": cooling_rate,
                            "unit": "C/min",
                        },
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-hip-conditions",
                        "row_index": row_index,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.95,
            }
        )

    result_source = (
        "The 800 SC condition had the highest strength compared to the 800 FC "
        "and 800 RQ conditions, which had progressively lower strengths as a "
        "result of the increased cooling rate. While the decrease in strength "
        "was observed for the faster cooling rates, the elongation of the "
        "800 C HIP treatments remained relatively unchanged."
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-hip-elongation",
            "objective_id": objective.objective_id,
            "document_id": "paper-hip",
            "source_kind": "text_window",
            "source_ref": "results-800-cooling",
            "evidence_role": "direct_result",
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": "elongation",
                "direction": "no_change",
                "result_text": (
                    "the elongation of the 800 C HIP treatments remained "
                    "relatively unchanged"
                ),
            },
            "attribution_scope": "descriptive_only",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-800-cooling",
                    "source_excerpt": result_source,
                }
            ],
            "resolution_status": "partial",
            "confidence": 0.9,
        }
    )

    bound = paper_experiment._bind_objective_result_process_context(
        (
            condition("800SC", "12", 3),
            condition("800FC", "100", 4),
            condition("800RQ", "2000", 5),
            result,
        )
    )[-1]

    assert bound.attribution_scope == "isolated_effect"
    assert [item.to_record() for item in bound.changed_variables] == [
        {
            "name": "cooling rate",
            "baseline_value": "12",
            "target_value": "2000",
            "unit": "C/min",
        }
    ]
    assert bound.comparison is not None
    assert bound.comparison.to_record() == {
        "baseline_label": "800SC",
        "target_label": "800RQ",
        "axis_names": ["cooling rate"],
        "comparable": True,
        "incomparability_reasons": [],
    }
    assert {
        item.name: (item.value, item.unit)
        for item in bound.scientific_context.process
    } == {
        "heating rate": ("12", "C/min"),
        "heat treatment temperature": ("800", "C"),
        "heat treatment pressure": ("200", "MPa"),
        "heat treatment duration": ("2", "hr"),
    }
    assert {ref["source_ref"] for ref in bound.source_refs} == {
        "table-hip-conditions",
        "results-800-cooling",
    }


def test_condition_registry_does_not_bind_a_conflicting_condition_label():
    def condition(
        label: str,
        cooling_rate: str,
        source_ref: str,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": source_ref,
                "objective_id": "obj-hip-elongation",
                "document_id": "paper-hip",
                "source_kind": "table",
                "source_ref": source_ref,
                "evidence_role": "condition_context",
                "scientific_context": {
                    "sample": [{"name": "condition", "value": label}],
                    "process": [
                        {
                            "name": "cooling rate",
                            "value": cooling_rate,
                            "unit": "C/min",
                        }
                    ],
                },
                "source_refs": [{"source_kind": "table", "source_ref": source_ref}],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-conflicting-condition",
            "objective_id": "obj-hip-elongation",
            "document_id": "paper-hip",
            "source_kind": "text_window",
            "source_ref": "result-source",
            "evidence_role": "direct_result",
            "reported_result": {
                "outcome": "elongation",
                "direction": "no_change",
                "result_text": "elongation remained unchanged",
            },
            "attribution_scope": "descriptive_only",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "result-source",
                    "source_excerpt": (
                        "Elongation remained unchanged between 800 SC and 800 RQ."
                    ),
                }
            ],
            "resolution_status": "partial",
            "confidence": 0.9,
        }
    )

    bound = paper_experiment._bind_objective_result_process_context(
        (
            condition("800 SC", "12", "condition-source-a"),
            condition("800SC", "20", "condition-source-b"),
            condition("800 RQ", "2000", "condition-source-rq"),
            result,
        )
    )[-1]

    assert bound.comparison is None
    assert bound.changed_variables == ()
    assert bound.attribution_scope == "descriptive_only"


def test_condition_registry_does_not_bind_labels_from_a_remote_claim():
    def condition(label: str, cooling_rate: str) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": f"condition-{label}",
                "objective_id": "obj-hip-elongation",
                "document_id": "paper-hip",
                "source_kind": "table",
                "source_ref": "condition-table",
                "evidence_role": "condition_context",
                "scientific_context": {
                    "sample": [{"name": "condition", "value": label}],
                    "process": [
                        {
                            "name": "cooling rate",
                            "value": cooling_rate,
                            "unit": "C/min",
                        }
                    ],
                },
                "source_refs": [
                    {"source_kind": "table", "source_ref": "condition-table"}
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    result_text = "Elongation remained unchanged in the specimens."
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-remote-labels",
            "objective_id": "obj-hip-elongation",
            "document_id": "paper-hip",
            "source_kind": "text_window",
            "source_ref": "long-results-source",
            "evidence_role": "direct_result",
            "reported_result": {
                "outcome": "elongation",
                "direction": "no_change",
                "result_text": result_text,
            },
            "attribution_scope": "descriptive_only",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "long-results-source",
                    "source_excerpt": (
                        "800 SC and 800 RQ differed in strength. "
                        + "Unrelated discussion. " * 100
                        + result_text
                    ),
                }
            ],
            "resolution_status": "partial",
            "confidence": 0.9,
        }
    )

    bound = paper_experiment._bind_objective_result_process_context(
        (condition("800 SC", "12"), condition("800 RQ", "2000"), result)
    )[-1]

    assert bound.comparison is None
    assert bound.attribution_scope == "descriptive_only"


def _reported_build_orientation_fact(
    evidence_id: str,
    source_ref: str,
    scientific_context: dict[str, Any],
    *,
    result_value: Any = 1006.7,
) -> ExtractedEvidenceDraft:
    return ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": evidence_id,
            "objective_id": "obj-build-orientation-uts",
            "document_id": "paper-ti64",
            "source_kind": "text_window",
            "source_ref": source_ref,
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "build orientation",
                    "baseline_value": "horizontal",
                    "target_value": "vertical",
                }
            ],
            "comparison": {
                "baseline_label": "horizontal",
                "target_label": "vertical",
                "axis_names": ["build orientation"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "ultimate tensile strength",
                "value": result_value,
                "unit": "MPa",
                "direction": "increase",
                "result_text": (
                    "Ultimate tensile strength increased from 961.3 MPa "
                    "for horizontal samples to 1006.7 MPa for vertical samples."
                ),
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": scientific_context,
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": source_ref,
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )


def test_paper_reconstruction_merges_duplicate_reports_of_one_scientific_fact():
    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id="collection-ti64",
        source_facts=(
            _reported_build_orientation_fact("evidence-abstract", "abstract", {}),
            _reported_build_orientation_fact(
                "evidence-results",
                "results",
                {
                    "material": [
                        {"name": "material", "value": "Ti-6Al-4V"}
                    ],
                    "process": [
                        {"name": "condition", "value": "as-fabricated"}
                    ],
                },
            ),
        ),
        paper_skims=(),
        objectives=(),
    )

    assert len(reconstructed) == 1
    fact = reconstructed[0]
    assert fact.evidence_id == "evidence-results"
    assert fact.scientific_context.to_record() == {
        "material": [
            {"name": "material", "value": "Ti-6Al-4V", "unit": None}
        ],
        "sample": [],
        "process": [
            {"name": "condition", "value": "as-fabricated", "unit": None}
        ],
        "test": [],
    }
    assert {item["source_ref"] for item in fact.source_refs} == {
        "abstract",
        "results",
    }


def test_paper_reconstruction_does_not_bridge_conflicting_context_with_unknown():
    ambiguous = paper_experiment.reconstruct_paper_experiments(
        collection_id="collection-ti64",
        source_facts=(
            _reported_build_orientation_fact(
                "evidence-as-fabricated",
                "results-as-fabricated",
                {
                    "process": [
                        {"name": "condition", "value": "as-fabricated"}
                    ]
                },
            ),
            _reported_build_orientation_fact(
                "evidence-hip",
                "results-hip",
                {
                    "process": [
                        {"name": "condition", "value": "HIP-treated"}
                    ]
                },
            ),
            _reported_build_orientation_fact(
                "evidence-unspecified",
                "abstract",
                {},
            ),
        ),
        paper_skims=(),
        objectives=(),
    )

    assert {item.evidence_id for item in ambiguous} == {
        "evidence-as-fabricated",
        "evidence-hip",
        "evidence-unspecified",
    }


def test_paper_reconstruction_requires_one_context_to_enrich_the_other():
    complementary = paper_experiment.reconstruct_paper_experiments(
        collection_id="collection-ti64",
        source_facts=(
            _reported_build_orientation_fact(
                "evidence-material-only",
                "material-source",
                {
                    "material": [
                        {"name": "material", "value": "Ti-6Al-4V"}
                    ]
                },
            ),
            _reported_build_orientation_fact(
                "evidence-condition-only",
                "condition-source",
                {
                    "process": [
                        {"name": "condition", "value": "as-fabricated"}
                    ]
                },
            ),
        ),
        paper_skims=(),
        objectives=(),
    )

    assert {item.evidence_id for item in complementary} == {
        "evidence-material-only",
        "evidence-condition-only",
    }


def test_paper_reconstruction_preserves_distinct_reported_values():
    distinct_values = paper_experiment.reconstruct_paper_experiments(
        collection_id="collection-ti64",
        source_facts=(
            _reported_build_orientation_fact(
                "evidence-value-1",
                "value-source-1",
                {},
                result_value="1.0",
            ),
            _reported_build_orientation_fact(
                "evidence-value-10",
                "value-source-10",
                {},
                result_value="10",
            ),
        ),
        paper_skims=(),
        objectives=(),
    )

    assert {item.evidence_id for item in distinct_values} == {
        "evidence-value-1",
        "evidence-value-10",
    }
