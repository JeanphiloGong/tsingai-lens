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
    source_validation,
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
from domain.core import (
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
    PreparedDocumentInput,
)
from tests.support.research_objective_service import (
    research_objective as _research_objective,
)


def _material_scope_evidence(
    objective: Any,
    evidence_id: str,
    material_attributes: list[dict[str, str]],
) -> ObjectiveEvidence:
    return ObjectiveEvidence.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "evidence_id": evidence_id,
            "document_id": f"paper-{evidence_id}",
            "source_kind": "text_window",
            "source_ref": f"source-{evidence_id}",
            "source_excerpt": "Scan X produced smaller porosity than Scan O.",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "scanning strategy",
                    "baseline_value": "Scan O",
                    "target_value": "Scan X",
                }
            ],
            "comparison": {
                "baseline_label": "Scan O",
                "target_label": "Scan X",
                "axis_names": ["scanning strategy"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "porosity",
                "direction": "decrease",
                "result_text": "Scan X produced smaller porosity than Scan O.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": material_attributes,
                "process": [{"name": "manufacturing process", "value": "LPBF"}],
                "test": [{"name": "method", "value": "porosity measurement"}],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )


def test_source_grounded_qualitative_result_survives_full_evidence_to_finding_chain():
    """A researcher-readable qualitative result must not disappear at synthesis."""

    objective = _research_objective(
        {
            "objective_id": "obj-ved-fatigue",
            "question": (
                "How does volumetric energy density affect low cycle fatigue strength?"
            ),
            "variables": ["volumetric energy density"],
            "outcomes": ["low cycle fatigue strength"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-lcf",
            "source_kind": "text_window",
            "source_ref": "results-lcf",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    source_text = (
        "Low cycle fatigue strength was enhanced for medium VED structures "
        "and high VED structures."
    )
    validated = source_extraction.validate_source_fact(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": route.source_ref,
            "text": source_text,
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [],
            "comparison": {
                "baseline_label": "medium VED",
                "target_label": "high VED",
                "axis_names": ["sample"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "low cycle fatigue strength",
                "value": None,
                "unit": None,
                "direction": "improve",
                "result_text": source_text,
            },
            "attribution_scope": "association_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        },
    )
    assert len(validated) == 1
    draft = ExtractedEvidenceDraft.from_mapping(validated[0])
    assert [item.name for item in draft.changed_variables] == [
        "volumetric energy density"
    ]

    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id=objective.collection_id,
        source_facts=(draft,),
        objectives=(objective,),
    )
    result_draft = next(item for item in reconstructed if item.evidence_id == draft.evidence_id)
    assert [item.name for item in result_draft.changed_variables] == [
        "volumetric energy density"
    ]
    assert result_draft.attribution_scope == "association_only"

    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-lcf",
                preparation_fingerprint="fingerprint-paper-lcf",
            ),
        ),
        pipeline_version="objective-analysis.v2",
        model_name="test-model",
        prompt_versions={},
        status="running",
        phase="finding_synthesis",
        total_document_count=1,
    )
    block = SimpleNamespace(block_id="results-lcf", text=source_text, page=1)
    evidence_records = evidence_materialization._analysis_evidence_records(
        collection_id=objective.collection_id,
        analysis=analysis,
        objective=objective,
        drafts=(result_draft,),
        blocks_by_document_id={"paper-lcf": [block]},
        tables_by_document_id={},
        figures_by_document_id={},
    )
    assert len(evidence_records) == 1
    evidence = evidence_records[0]
    assert evidence.evidence_status == "association_only"
    assert evidence.changed_variables[0].name == "volumetric energy density"

    contribution = PaperContribution.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "document_id": "paper-lcf",
            "analysis_status": "analyzed",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "contribution_summary": "Low cycle fatigue result.",
            "material_match": [],
            "changed_variables": ["volumetric energy density"],
            "measured_property_scope": ["low cycle fatigue strength"],
            "test_environment_scope": [],
            "warnings": [],
            "confidence": 0.9,
        }
    )
    findings = finding_synthesis.FindingSynthesisService().synthesize(
        collection_id=objective.collection_id,
        objective=objective,
        analysis=analysis,
        contributions=(contribution,),
        evidence_records=evidence_records,
    )
    assert len(findings) == 1
    assert findings[0].attribution_scope == "association_only"
    assert findings[0].assertion_strength == "descriptive"
    assert findings[0].supporting_evidence_ids == (evidence.evidence_id,)


def test_finding_synthesis_requires_complete_endpoints_for_cross_paper_comparison():
    """Association evidence remains paper-scoped until both endpoints exist."""

    objective = _research_objective(
        {
            "objective_id": "obj-ved-strength",
            "variables": ["volumetric energy density"],
            "outcomes": ["yield strength"],
        }
    )
    evidence = ObjectiveEvidence.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "evidence_id": "qualitative-ved-strength",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "source_excerpt": "Yield strength improved at high VED.",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {"name": "volumetric energy density"},
            ],
            "comparison": None,
            "reported_result": {
                "outcome": "yield strength",
                "direction": "improve",
                "result_text": "Yield strength improved at high VED.",
            },
            "attribution_scope": "association_only",
            "scientific_context": {},
            "resolution_status": "partial",
            "confidence": 0.9,
        }
    )
    service = finding_synthesis.FindingSynthesisService()
    assert service._result_sets(objective, (evidence,)) == ()
    qualified = service._qualified_result_sets(objective, (evidence,))
    assert len(qualified) == 1
    assert qualified[0]["document_id"] == "paper-1"


def test_broad_objective_keeps_source_specific_result_as_paper_scoped_finding():
    """A broad question must retain a grounded narrower result for review."""

    objective = _research_objective(
        {
            "objective_id": "obj-ved-fatigue-behaviour",
            "question": "How does volumetric energy density affect fatigue behaviour?",
            "material_scope": ["316L stainless steel"],
            "variables": ["volumetric energy density"],
            "outcomes": ["fatigue behaviour"],
        }
    )
    evidence = ObjectiveEvidence.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "evidence_id": "paper-fatigue-life-result",
            "document_id": "paper-fatigue",
            "source_kind": "text_window",
            "source_ref": "fatigue-results",
            "source_excerpt": (
                "Fatigue life decreased as volumetric energy density decreased."
            ),
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "volumetric energy density",
                    "baseline_value": None,
                    "target_value": None,
                    "unit": "J/mm3",
                }
            ],
            "comparison": None,
            "reported_result": {
                "outcome": "fatigue life",
                "direction": "decrease",
                "result_text": (
                    "Fatigue life decreased as volumetric energy density decreased."
                ),
            },
            "attribution_scope": "association_only",
            "scientific_context": {
                "material": [{"name": "material", "value": "316L stainless steel"}]
            },
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-fatigue",
                preparation_fingerprint="fingerprint-paper-fatigue",
            ),
        ),
        pipeline_version="objective-analysis.v2",
        model_name="test-model",
        prompt_versions={},
        status="running",
        phase="finding_synthesis",
        total_document_count=1,
    )
    contribution = PaperContribution.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "document_id": "paper-fatigue",
            "analysis_status": "analyzed",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "contribution_summary": "The paper reports a fatigue-life result.",
            "material_match": ["316L stainless steel"],
            "changed_variables": ["volumetric energy density"],
            "measured_property_scope": ["fatigue behaviour"],
            "test_environment_scope": [],
            "warnings": [],
            "confidence": 0.8,
        }
    )

    findings = finding_synthesis.FindingSynthesisService().synthesize(
        collection_id=objective.collection_id,
        objective=objective,
        analysis=analysis,
        contributions=(contribution,),
        evidence_records=(evidence,),
    )

    assert len(findings) == 1
    assert findings[0].outcome == "fatigue life"
    assert findings[0].assertion_strength == "descriptive"
    assert findings[0].attribution_scope == "association_only"
    assert findings[0].supporting_evidence_ids == (evidence.evidence_id,)


def test_umbrella_outcome_is_consistent_during_source_validation() -> None:
    """A broad Objective must retain its concrete source measurement end to end."""

    objective = _research_objective(
        {
            "objective_id": "obj-ved-fatigue-validation",
            "question": "How does volumetric energy density affect fatigue behaviour?",
            "material_scope": ["316L stainless steel"],
            "variables": ["volumetric energy density"],
            "outcomes": ["fatigue behaviour"],
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-fatigue-validation",
            "source_kind": "text_window",
            "source_ref": "fatigue-results",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )
    source_text = (
        "For low VED and high VED, fatigue life decreased from 120000 cycles "
        "to 80000 cycles as volumetric energy density decreased."
    )
    records = source_validation.validate_source_fact(
        route=route,
        source={
            "source_kind": "text_window",
            "source_ref": route.source_ref,
            "text": source_text,
        },
        objective_context=objective,
        extracted_record={
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "volumetric energy density",
                    "baseline_value": "high VED",
                    "target_value": "low VED",
                    "unit": None,
                }
            ],
            "comparison": {
                "baseline_label": "high VED",
                "target_label": "low VED",
                "axis_names": ["volumetric energy density"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "fatigue life",
                "value": 80000,
                "baseline_value": 120000,
                "target_value": 80000,
                "unit": "cycles",
                "direction": "decrease",
                "result_text": (
                    "fatigue life decreased from 120000 cycles to 80000 cycles"
                ),
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [
                    {"name": "material", "value": "316L stainless steel"}
                ]
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        },
    )

    assert len(records) == 1
    record = records[0]
    assert record["reported_result"]["outcome"] == "fatigue life"
    assert record["comparison"]["comparable"] is True
    assert record["attribution_scope"] == "isolated_effect"


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
                "scientific_context": {
                    "material": [
                        {"name": "material", "value": "Ti-6Al-4V"}
                    ],
                    "process": [
                        {"name": "manufacturing process", "value": "LPBF"}
                    ],
                    "test": [{"name": "method", "value": "tensile test"}],
                },
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


def test_comparable_result_requires_resolved_objective_material_scope() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-ti64-porosity",
            "question": "How does scanning strategy affect porosity?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser exposure condition"],
            "outcomes": ["porosity"],
        }
    )

    def evidence(evidence_id: str, material: str | None) -> ObjectiveEvidence:
        return ObjectiveEvidence.from_mapping(
            {
                "collection_id": objective.collection_id,
                "objective_id": objective.objective_id,
                "analysis_version": 1,
                "evidence_id": evidence_id,
                "document_id": f"paper-{evidence_id}",
                "source_kind": "text_window",
                "source_ref": f"source-{evidence_id}",
                "source_excerpt": (
                    "Scan X produced smaller porosity than Scan O."
                ),
                "evidence_role": "direct_result",
                "selection_status": "extracted",
                "changed_variables": [
                    {
                        "name": "scanning strategy",
                        "baseline_value": "Scan O",
                        "target_value": "Scan X",
                    }
                ],
                "comparison": {
                    "baseline_label": "Scan O",
                    "target_label": "Scan X",
                    "axis_names": ["scanning strategy"],
                    "comparable": True,
                    "incomparability_reasons": [],
                },
                "reported_result": {
                    "outcome": "porosity",
                    "direction": "decrease",
                    "result_text": (
                        "Scan X produced smaller porosity than Scan O."
                    ),
                },
                "attribution_scope": "isolated_effect",
                "scientific_context": {
                    "material": (
                        [{"name": "material", "value": material}]
                        if material is not None
                        else []
                    ),
                    "process": [
                        {"name": "manufacturing process", "value": "LPBF"}
                    ],
                    "test": [{"name": "method", "value": "porosity measurement"}],
                },
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    service = finding_synthesis.FindingSynthesisService()

    assert service.is_comparable_result_evidence(
        objective,
        evidence("matching", "TiAl6V4"),
    )
    assert not service.is_comparable_result_evidence(
        objective,
        evidence("missing", None),
    )
    assert not service.is_comparable_result_evidence(
        objective,
        evidence("conflicting", "17-4PH stainless steel"),
    )
    assert service.material_scope_status(
        objective,
        evidence("broad", "titanium alloy"),
    ) == "unresolved"
    assert service.material_scope_status(
        objective,
        evidence("other-grade", "316L"),
    ) == "mismatched"


def test_material_scope_ignores_supporting_substrate_identity() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-316l-porosity",
            "question": "How does scanning strategy affect porosity?",
            "material_scope": ["316L stainless steel"],
            "variables": ["scanning strategy"],
            "outcomes": ["porosity"],
        }
    )
    scoped = _material_scope_evidence(
        objective,
        "substrate-context",
        [
            {"name": "material", "value": "316L stainless steel"},
            {"name": "substrate", "value": "carbon steel"},
        ],
    )

    assert finding_synthesis.FindingSynthesisService.material_scope_status(
        objective,
        scoped,
    ) == "matched"


def test_material_scope_stays_unresolved_when_only_substrate_is_known() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-316l-porosity-substrate-only",
            "question": "How does scanning strategy affect porosity?",
            "material_scope": ["316L stainless steel"],
            "variables": ["scanning strategy"],
            "outcomes": ["porosity"],
        }
    )
    scoped = _material_scope_evidence(
        objective,
        "substrate-only",
        [{"name": "substrate", "value": "carbon steel"}],
    )

    assert finding_synthesis.FindingSynthesisService.material_scope_status(
        objective,
        scoped,
    ) == "unresolved"


def test_result_without_condition_pair_is_not_cross_paper_comparable() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-porosity",
            "question": "How does laser power affect porosity?",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    evidence = ObjectiveEvidence.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "evidence_id": "association-without-pair",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "source_excerpt": "Porosity decreased as laser power increased.",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "laser power",
                    "baseline_value": None,
                    "target_value": None,
                    "unit": "W",
                }
            ],
            "reported_result": {
                "outcome": "porosity",
                "value": None,
                "direction": "decrease",
                "result_text": "Porosity decreased as laser power increased.",
            },
            "comparison": None,
            "attribution_scope": "association_only",
            "scientific_context": {
                "material": [{"name": "material", "value": "Ti-6Al-4V"}]
            },
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )

    service = finding_synthesis.FindingSynthesisService()

    assert evidence.evidence_status == "association_only"
    assert not service.is_comparable_result_evidence(objective, evidence)


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
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
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
                else {
                    "process": [
                        {"name": "manufacturing process", "value": "LPBF"}
                    ],
                    "test": [{"name": "temperature", "value": 25, "unit": "C"}],
                }
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
        paper_maps=(),
        frames=frames,
        routes=routes,
        evidence_records=evidence_records,
    )

    by_document = {item.document_id: item for item in contributions}
    assert by_document["paper-excluded"].evidence_disposition == "excluded"
    assert by_document["paper-no-route"].evidence_disposition == "excluded"
    assert by_document["paper-failed"].analysis_status == "failed"
    assert by_document["paper-failed"].evidence_disposition == "extraction_failed"
    assert by_document["paper-failed"].failed_source_count == 1
    assert by_document["paper-context"].evidence_disposition == (
        "no_comparable_evidence"
    )
    assert by_document["paper-context"].extracted_source_count == 1
    assert by_document["paper-context"].evidence_status_counts == (
        ("needs_context", 1),
    )
    assert by_document["paper-comparable"].evidence_disposition == (
        "comparable_evidence"
    )
    assert by_document["paper-comparable"].comparable_evidence_count == 1
    assert by_document["paper-comparable"].evidence_status_counts == (
        ("comparable", 1),
    )


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


def test_pairwise_comparison_does_not_infer_multi_axis_effect_from_result_rows():

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

    assert comparisons == ()


def test_pairwise_comparison_keeps_joint_row_contrast_as_association():
    """Row values remain usable without being promoted to a causal effect."""

    objective = _research_objective(
        {
            "objective_id": "obj-joint-process-yield",
            "question": (
                "How do scan strategy rotation angle and build orientation "
                "affect yield strength?"
            ),
            "variables": ["scan strategy rotation angle", "build orientation"],
            "outcomes": ["yield strength"],
        }
    )

    def result(
        evidence_id: str,
        sample: str,
        rotation: int,
        orientation: int,
        value: int,
        row_index: int,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
                "document_id": "paper-joint",
                "source_kind": "table",
                "source_ref": "table-yield",
                "evidence_role": "direct_result",
                "changed_variables": [],
                "comparison": None,
                "reported_result": {
                    "outcome": "yield strength",
                    "value": value,
                    "unit": "MPa",
                    "direction": "unknown",
                    "result_text": f"Yield strength for {sample}: {value} MPa.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "sample": [{"name": "sample", "value": sample}],
                    "process": [
                        {
                            "name": "scan strategy rotation angle",
                            "value": rotation,
                            "unit": "deg",
                        },
                        {
                            "name": "build orientation",
                            "value": orientation,
                            "unit": "deg",
                        },
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-yield",
                        "row_index": row_index,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id=objective.collection_id,
        source_facts=(
            result("joint-a", "A", 0, 0, 600, 1),
            result("joint-b", "B", 45, 90, 650, 2),
        ),
        objectives=(objective,),
    )

    comparisons = tuple(
        item for item in reconstructed if item.evidence_id.startswith("oeu_cmp_")
    )
    assert len(comparisons) == 1
    assert comparisons[0].attribution_scope == "association_only"
    assert comparisons[0].comparison is not None
    assert comparisons[0].comparison.comparable is True
    assert {
        variable.name for variable in comparisons[0].changed_variables
    } == {"scan strategy rotation angle", "build orientation"}
    assert sum(item.reported_result is not None for item in reconstructed) == 3


def test_pairwise_comparison_uses_source_grounded_contrast_to_resolve_generic_row_axis():
    objective = _research_objective(
        {
            "objective_id": "obj-surface-response",
            "question": "How does surface preparation affect response magnitude?",
            "variables": ["surface preparation"],
            "outcomes": ["response magnitude"],
        }
    )

    def result(
        evidence_id: str,
        *,
        row_number: int,
        condition: str,
        value: float,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
                "document_id": "paper-contrast",
                "source_kind": "table",
                "source_ref": "table-response",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "response magnitude",
                    "value": value,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"response magnitude = {value} %",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "sample": [{"name": "sample_number", "value": row_number}],
                    "process": [
                        {"name": "Specimen condition", "value": condition},
                        {
                            "name": "surface preparation",
                            "value": "without polishing versus mechanically polished",
                        },
                    ],
                    "test": [{"name": "method", "value": "response test"}],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-response",
                        "row_index": row_number,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        (
            result(
                "response-row-1",
                row_number=1,
                condition="Non-polished",
                value=72.0,
            ),
            result(
                "response-row-2",
                row_number=2,
                condition="Polished",
                value=82.0,
            ),
        ),
        objectives=(objective,),
    )

    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert [item.name for item in comparison.changed_variables] == [
        "surface preparation"
    ]
    assert comparison.reported_result is not None
    assert comparison.reported_result.baseline_value == 72.0
    assert comparison.reported_result.target_value == 82.0
    assert comparison.reported_result.direction == "increase"
    assert comparison.comparison is not None
    assert comparison.comparison.baseline_label == "Non-polished"
    assert comparison.comparison.target_label == "Polished"
    assert comparison.comparison.comparable is True


def test_pairwise_comparison_resolves_numeric_treatment_level_from_compact_contrast():
    objective = _research_objective(
        {
            "objective_id": "obj-preheating-elongation",
            "question": "How does build platform preheating affect elongation?",
            "variables": ["build platform preheating"],
            "outcomes": ["elongation"],
        }
    )

    def result(
        evidence_id: str,
        *,
        row_number: int,
        condition: str,
        value: float,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
                "document_id": "paper-preheating",
                "source_kind": "table",
                "source_ref": "table-tensile-properties",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "elongation",
                    "value": value,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"elongation = {value} %",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "sample": [{"name": "sample_number", "value": row_number}],
                    "process": [
                        {"name": "Build platform conditions", "value": condition},
                        {
                            "name": "build platform preheating",
                            "value": "without preheating / 150 C",
                        },
                    ],
                    "test": [{"name": "method", "value": "tensile testing"}],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-tensile-properties",
                        "row_index": row_number,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        (
            result(
                "elongation-non-preheated",
                row_number=1,
                condition="Non-preheated",
                value=72.0,
            ),
            result(
                "elongation-preheated",
                row_number=2,
                condition="Preheated",
                value=82.0,
            ),
        ),
        objectives=(objective,),
    )

    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert [item.name for item in comparison.changed_variables] == [
        "build platform preheating"
    ]
    assert comparison.reported_result is not None
    assert comparison.reported_result.baseline_value == 72.0
    assert comparison.reported_result.target_value == 82.0
    assert comparison.reported_result.direction == "increase"
    assert comparison.comparison is not None
    assert comparison.comparison.baseline_label == "Non-preheated"
    assert comparison.comparison.target_label == "Preheated"
    assert comparison.comparison.comparable is True


def test_pairwise_comparison_resolves_objective_axis_from_table_header_and_endpoints():
    """A complete result table does not depend on repeated Methods extraction."""

    objective = _research_objective(
        {
            "objective_id": "obj-preheating-elongation-table",
            "question": "How does build platform preheating affect elongation?",
            "variables": ["build platform preheating"],
            "outcomes": ["elongation"],
        }
    )

    def result(
        evidence_id: str,
        *,
        row_number: int,
        condition: str,
        value: float,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
                "document_id": "paper-preheating",
                "source_kind": "table",
                "source_ref": "table-tensile-properties",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "elongation",
                    "value": value,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"elongation = {value} %",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "material": [
                        {"name": "material", "value": "316L stainless steel"}
                    ],
                    "sample": [
                        {"name": "sample_number", "value": row_number},
                        {
                            "name": "specimen geometry",
                            "value": "sub-sized ASTM E8 tensile specimen",
                        },
                    ],
                    "process": [
                        {"name": "Build platform conditions", "value": condition}
                    ],
                    "test": [{"name": "method", "value": "tensile testing"}],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-tensile-properties",
                        "row_index": row_number,
                    }
                ],
                "resolution_status": "partial",
                "confidence": 0.9,
            }
        )

    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id="collection-test",
        source_facts=(
            result(
                "elongation-non-preheated",
                row_number=1,
                condition="Non-preheated",
                value=72.0,
            ),
            result(
                "elongation-preheated",
                row_number=2,
                condition="Preheated",
                value=82.0,
            ),
        ),
        objectives=(objective,),
    )
    comparisons = tuple(
        item
        for item in reconstructed
        if item.evidence_id.startswith("oeu_cmp_")
    )

    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert [item.name for item in comparison.changed_variables] == [
        "build platform preheating"
    ]
    assert comparison.reported_result is not None
    assert comparison.reported_result.baseline_value == 72.0
    assert comparison.reported_result.target_value == 82.0
    assert comparison.reported_result.direction == "increase"
    assert comparison.comparison is not None
    assert comparison.comparison.baseline_label == "Non-preheated"
    assert comparison.comparison.target_label == "Preheated"
    assert comparison.comparison.comparable is True


@pytest.mark.parametrize(
    ("axis_name", "objective_variable"),
    (
        ("Specimen condition", "surface preparation"),
        ("Build platform conditions", "surface preparation"),
    ),
)
def test_pairwise_comparison_does_not_guess_objective_axis_from_unrelated_endpoints(
    axis_name: str,
    objective_variable: str,
):
    objective = _research_objective(
        {
            "objective_id": "obj-unrelated-endpoint-axis",
            "question": f"How does {objective_variable} affect response magnitude?",
            "variables": [objective_variable],
            "outcomes": ["response magnitude"],
        }
    )

    def result(evidence_id: str, condition: str, value: float):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
                "document_id": "paper-unrelated-axis",
                "source_kind": "table",
                "source_ref": "table-response",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "response magnitude",
                    "value": value,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"response magnitude = {value} %",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "process": [{"name": axis_name, "value": condition}],
                    "test": [{"name": "method", "value": "response test"}],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-response",
                        "row_index": 1 if value == 1.0 else 2,
                    }
                ],
                "resolution_status": "partial",
                "confidence": 0.9,
            }
        )

    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        (
            result("response-non-preheated", "Non-preheated", 1.0),
            result("response-preheated", "Preheated", 2.0),
        ),
        objectives=(objective,),
    )

    assert comparisons == ()


@pytest.mark.parametrize(
    "axis_description",
    (
        "surface preparation used during specimen preparation",
        "without polishing versus another preparation route",
    ),
)
def test_pairwise_comparison_does_not_resolve_generic_row_axis_without_explicit_endpoint_contrast(
    axis_description: str,
):
    objective = _research_objective(
        {
            "objective_id": "obj-surface-response",
            "question": "How does surface preparation affect response magnitude?",
            "variables": ["surface preparation"],
            "outcomes": ["response magnitude"],
        }
    )

    def result(
        evidence_id: str,
        *,
        row_number: int,
        condition: str,
        value: float,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
                "document_id": "paper-contrast",
                "source_kind": "table",
                "source_ref": "table-response",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "response magnitude",
                    "value": value,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"response magnitude = {value} %",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "sample": [{"name": "sample_number", "value": row_number}],
                    "process": [
                        {"name": "Specimen condition", "value": condition},
                        {
                            "name": "surface preparation",
                            "value": axis_description,
                        },
                    ],
                    "test": [{"name": "method", "value": "response test"}],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-response",
                        "row_index": row_number,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        (
            result(
                "response-row-1",
                row_number=1,
                condition="Non-polished",
                value=72.0,
            ),
            result(
                "response-row-2",
                row_number=2,
                condition="Polished",
                value=82.0,
            ),
        ),
        objectives=(objective,),
    )

    assert comparisons == ()


def test_pairwise_comparison_uses_confirmed_objective_axes() -> None:
    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["volumetric energy density"],
            "outcomes": ["relative density"],
        }
    )

    def result(evidence_id: str, scan_speed: int, density: float):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
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
                        {"name": "scan speed", "value": scan_speed},
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
            result("row-a", 800, 96.1),
            result("row-b", 700, 99.2),
        ),
        objectives=(objective,),
    )

    assert comparisons == ()


def test_pairwise_comparison_does_not_infer_joint_effect_from_result_rows() -> None:
    """A multi-axis row contrast is retained as association, never joint causation."""

    objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["laser power", "scan speed"],
            "outcomes": ["relative density"],
        }
    )

    def result(evidence_id: str, laser_power: int, scan_speed: int, density: float):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
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
                        {"name": "laser power", "value": laser_power, "unit": "W"},
                        {"name": "scan speed", "value": scan_speed, "unit": "mm/s"},
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
            result("row-a", 100, 500, 96.1),
            result("row-b", 200, 900, 99.2),
        ),
        objectives=(objective,),
    )

    assert len(comparisons) == 1
    assert comparisons[0].attribution_scope == "association_only"
    assert comparisons[0].comparison is not None
    assert comparisons[0].comparison.comparable is True


def test_pairwise_comparison_uses_the_objective_for_each_result_group() -> None:
    density_objective = _research_objective(
        {
            "objective_id": "obj-density",
            "variables": ["volumetric energy density"],
            "outcomes": ["relative density"],
        }
    )
    strength_objective = _research_objective(
        {
            "objective_id": "obj-strength",
            "variables": ["scan speed"],
            "outcomes": ["yield strength"],
        }
    )

    def result(
        evidence_id: str,
        objective_id: str,
        outcome: str,
        process_name: str,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective_id,
                "document_id": "paper-1",
                "source_kind": "table",
                "source_ref": f"table-{objective_id}",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": outcome,
                    "value": 96.1 if evidence_id.endswith("a") else 99.2,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": f"{outcome} is reported.",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "process": [
                        {
                            "name": process_name,
                            "value": 800 if evidence_id.endswith("a") else 700,
                        }
                    ],
                },
                "source_refs": [
                    {"source_kind": "table", "source_ref": f"table-{objective_id}"}
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        (
            result("density-a", "obj-density", "relative density", "scan speed"),
            result("density-b", "obj-density", "relative density", "scan speed"),
            result("strength-a", "obj-strength", "yield strength", "scan speed"),
            result("strength-b", "obj-strength", "yield strength", "scan speed"),
        ),
        objectives=(density_objective, strength_objective),
    )

    assert len(comparisons) == 1
    assert comparisons[0].objective_id == "obj-strength"


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
    assert comparisons == ()


def test_sample_condition_row_overrides_paper_wide_process_list() -> None:
    """A joined sample row, not a paper-level list, defines changed factors."""

    def condition(
        evidence_id: str,
        sample_label: str,
        *,
        energy_density: int,
        scanning_speed: int,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-density",
                "document_id": "paper-split-tables",
                "source_kind": "table",
                "source_ref": "process-table",
                "evidence_role": "condition_context",
                "scientific_context": {
                    "sample": [{"name": "sample number", "value": sample_label}],
                    "process": [
                        {
                            "name": "energy density",
                            "value": energy_density,
                            "unit": "J/mm3",
                        },
                        {
                            "name": "scanning speed",
                            "value": scanning_speed,
                            "unit": "mm/s",
                        },
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "process-table",
                        "row_index": int(sample_label),
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    def result(
        evidence_id: str,
        sample_label: str,
        yield_strength: int,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-density",
                "document_id": "paper-split-tables",
                "source_kind": "table",
                "source_ref": "result-table",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "yield strength",
                    "value": yield_strength,
                    "unit": "MPa",
                    "direction": "unknown",
                    "result_text": f"Yield strength = {yield_strength} MPa.",
                    "result_kind": "measured",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "sample": [{"name": "sample number", "value": sample_label}],
                    "process": [
                        {
                            "name": "scanning speed",
                            "value": "700, 900",
                            "unit": "mm/s",
                        }
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "result-table",
                        "row_index": int(sample_label),
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    bound = paper_experiment._bind_objective_result_process_context(
        (
            condition("condition-1", "1", energy_density=70, scanning_speed=900),
            condition("condition-2", "2", energy_density=100, scanning_speed=700),
            result("result-1", "1", 300),
            result("result-2", "2", 340),
        )
    )

    bound_results = tuple(item for item in bound if item.reported_result is not None)
    assert [
        {
            attribute.name: attribute.value
            for attribute in item.scientific_context.process
        }
        for item in bound_results
    ] == [
        {"energy density": 70, "scanning speed": 900},
        {"energy density": 100, "scanning speed": 700},
    ]

    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        bound,
        objectives=(
            _research_objective(
                {
                    "objective_id": "obj-density",
                    "question": "How does energy density affect yield strength?",
                    "variables": ["energy density"],
                    "outcomes": ["yield strength"],
                }
            ),
        ),
    )

    assert len(comparisons) == 1
    assert {item.name for item in comparisons[0].changed_variables} == {
        "energy density",
        "scanning speed",
    }
    assert comparisons[0].attribution_scope == "association_only"


def test_result_table_without_sample_id_joins_condition_table_by_shared_values():
    """A result row can be bound through the paper's shared condition key."""

    def condition(sample: str, theta: str, alpha: str, beta: str):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": f"condition-{sample}",
                "objective_id": "obj-yield",
                "document_id": "paper-p006",
                "source_kind": "table",
                "source_ref": "table-samples",
                "evidence_role": "condition_context",
                "scientific_context": {
                    "sample": [{"name": "Sample #", "value": sample}],
                    "process": [
                        {"name": "theta", "value": theta, "unit": "degree"},
                        {"name": "alpha", "value": alpha, "unit": "degree"},
                        {"name": "beta", "value": beta, "unit": "degree"},
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-samples",
                        "source_excerpt": f"{sample} | {theta} | {alpha} | {beta}",
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-row",
            "objective_id": "obj-yield",
            "document_id": "paper-p006",
            "source_kind": "table",
            "source_ref": "table-results",
            "evidence_role": "direct_result",
            "reported_result": {
                "outcome": "yield strength",
                "value": 342.5,
                "unit": "MPa",
                "direction": "unknown",
                "result_text": "Yield strength experiment = 342.5 MPa.",
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": {
                "process": [
                    {"name": "theta", "value": 30, "unit": "degree"},
                    {"name": "alpha", "value": 0, "unit": "degree"},
                    {"name": "beta", "value": 0, "unit": "degree"},
                ]
            },
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-results",
                    "source_excerpt": "0 | 0 | 30 | 342.5",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    bound = paper_experiment._bind_objective_result_process_context(
        (condition("2", "30", "0", "0"), condition("3", "45", "0", "0"), result)
    )

    joined = bound[-1]
    assert {item.name: item.value for item in joined.scientific_context.sample} == {
        "Sample #": "2"
    }
    assert {ref["source_ref"] for ref in joined.source_refs} == {
        "table-results",
        "table-samples",
    }


def test_group_scoped_context_is_not_promoted_to_document_wide_result_context():
    """A local sample description must not become a paper-wide condition."""

    context = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "first-sample-context",
            "objective_id": "obj-yield",
            "document_id": "paper-p006",
            "source_kind": "text_window",
            "source_ref": "methods-first-sample",
            "evidence_role": "condition_context",
            "scientific_context": {
                "sample": [{"name": "sample", "value": "first sample"}],
                "process": [
                    {"name": "alpha", "value": 22.5, "unit": "degree"},
                ],
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "methods-first-sample",
                    "source_excerpt": "The first sample used alpha = 22.5 degree.",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-without-context",
            "objective_id": "obj-yield",
            "document_id": "paper-p006",
            "source_kind": "table",
            "source_ref": "table-results",
            "evidence_role": "direct_result",
            "reported_result": {
                "outcome": "yield strength",
                "value": 342.5,
                "unit": "MPa",
                "direction": "unknown",
                "result_text": "Yield strength = 342.5 MPa.",
            },
            "scientific_context": {},
            "source_refs": [
                {"source_kind": "table", "source_ref": "table-results"}
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    bound = paper_experiment._bind_unambiguous_document_context((context, result))

    assert bound[-1].scientific_context.process == ()


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
                    "material": [
                        {"name": "material", "value": "Ti-6Al-4V"}
                    ],
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
    assert evidence.evidence_status == "association_only"
    assert not finding_synthesis.FindingSynthesisService.is_comparable_result_evidence(
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

    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
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
    )

    assert comparisons == ()


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

    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        (
            result("as-slm", "as-SLM", 194, 426.7),
            result("hip-slm", "HIP-SLM", 167, 265.1),
        ),
        objectives=(),
    )

    assert comparisons == ()


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

    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
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
    )

    assert comparisons == ()


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


def test_result_table_builds_adjacent_controlled_series_instead_of_all_pairs():
    """A researcher compares neighboring levels under fixed conditions."""

    objective = _research_objective(
        {
            "objective_id": "obj-orientation-yield",
            "question": (
                "How do scan rotation and specimen orientation affect yield strength?"
            ),
            "variables": [
                "scan rotation",
                "orientation alpha",
                "orientation beta",
            ],
            "outcomes": ["yield strength"],
        }
    )
    rows = (
        (0, 0, 0, 334.2),
        (0, 0, 30, 342.5),
        (0, 0, 45, 351.9),
        (0, 22.5, 0, 295.1),
        (45, 22.5, 0, 363.1),
        (45, 22.5, 30, 356.9),
        (45, 22.5, 45, 365.6),
    )

    def measurement(
        row_index: int,
        alpha: float,
        beta: float,
        theta: float,
        strength: float,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": f"row-{row_index}",
                "objective_id": objective.objective_id,
                "document_id": "paper-orientation",
                "source_kind": "table",
                "source_ref": "result-table",
                "evidence_role": "direct_result",
                "reported_result": {
                    "outcome": "yield strength",
                    "value": strength,
                    "unit": "MPa",
                    "direction": "unknown",
                    "result_text": f"Yield strength = {strength} MPa.",
                    "result_kind": "measured",
                },
                "attribution_scope": "descriptive_only",
                "scientific_context": {
                    "process": [
                        {"name": "orientation alpha", "value": alpha, "unit": "deg"},
                        {"name": "orientation beta", "value": beta, "unit": "deg"},
                        {"name": "scan rotation", "value": theta, "unit": "deg"},
                    ]
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "result-table",
                        "row_index": row_index,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.95,
            }
        )

    measurements = tuple(
        measurement(index, *row)
        for index, row in enumerate(rows, start=1)
    )
    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        measurements,
        objectives=(objective,),
    )

    assert len(comparisons) == 6
    intervals = {
        (
            comparison.changed_variables[0].name,
            comparison.changed_variables[0].baseline_value,
            comparison.changed_variables[0].target_value,
            comparison.reported_result.baseline_value,
            comparison.reported_result.target_value,
        )
        for comparison in comparisons
        if len(comparison.changed_variables) == 1
        and comparison.reported_result is not None
    }
    assert intervals == {
        ("scan rotation", 0, 30, 334.2, 342.5),
        ("scan rotation", 30, 45, 342.5, 351.9),
        ("orientation beta", 0, 22.5, 334.2, 295.1),
        ("orientation alpha", 0, 45, 295.1, 363.1),
        ("scan rotation", 0, 30, 363.1, 356.9),
        ("scan rotation", 30, 45, 356.9, 365.6),
    }
    assert all(
        len(comparison.changed_variables) == 1 for comparison in comparisons
    )


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

    result_measurements = tuple(
        item for item in measurements if item.reported_result is not None
    )
    assert [item.value for item in result_measurements[0].scientific_context.material] == [
        "316L"
    ]
    assert result_measurements[0].source_refs[0]["row_index"] == 1
    assert result_measurements[0].source_refs[0]["col_index"] == 2
    assert result_measurements[0].source_refs[0]["header_path"] == "Relative density [%]"
    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        measurements,
        objectives=(objective,),
    )
    assert comparisons == ()

    analysis = ObjectiveAnalysis(
        collection_id="col-test",
        objective_id="obj-density",
        analysis_version=1,
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
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
        drafts=measurements,
        blocks_by_document_id={},
        tables_by_document_id={"paper-1": [table]},
        figures_by_document_id={},
    )
    assert len(evidence) == 4
    result_evidence = tuple(
        item for item in evidence if item.reported_result is not None
    )
    assert len(result_evidence) == 2
    assert {item.source_excerpt.split(" | ")[0] for item in result_evidence} == {
        "Material: 316L",
        "Material: Ti-6Al-4V",
    }
    assert {
        ref["row_index"]
        for item in evidence
        for ref in item.related_source_refs
    } == {1, 2}


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
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
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

    result_measurements = tuple(
        item for item in measurements if item.reported_result is not None
    )
    assert [item.reported_result.value for item in result_measurements] == [
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

    comparisons = paper_experiment._build_objective_pairwise_comparison_units(
        measurements,
        objectives=(objective,),
    )

    assert comparisons == ()


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
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
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
            "scientific_context": {
                "process": [{"name": "manufacturing process", "value": "LPBF"}],
                "test": [{"name": "method", "value": "density measurement"}],
            },
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
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
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
            "scientific_context": {
                "process": [{"name": "manufacturing process", "value": "LPBF"}],
                "test": [{"name": "method", "value": "density measurement"}],
            },
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
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
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
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
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


def test_condition_registry_merges_missing_process_fields_into_partial_result_context():
    """A researcher can join a result table to a parameter table by sample id."""

    objective = _research_objective(
        {
            "objective_id": "obj-scan-strategy-yield-strength",
            "question": "How does scanning strategy affect yield strength?",
            "material_scope": ["316L stainless steel"],
            "variables": ["scanning strategy"],
            "outcomes": ["yield strength"],
        }
    )

    def condition(sample_number: str, strategy: str) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": f"condition-{sample_number}",
                "objective_id": objective.objective_id,
                "document_id": "paper-p001",
                "source_kind": "table",
                "source_ref": "table-processing-parameters",
                "evidence_role": "condition_context",
                "scientific_context": {
                    "sample": [
                        {"name": "Condition number", "value": "4"},
                        {"name": "Sample number", "value": sample_number},
                    ],
                    "process": [
                        {"name": "Scan strategy", "value": strategy},
                        {"name": "Scanning speed", "value": "0.239", "unit": "m/s"},
                        {"name": "Energy density", "value": "70", "unit": "J/mm3"},
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-processing-parameters",
                        "row_index": int(sample_number),
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.95,
            }
        )

    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-sample-9",
            "objective_id": objective.objective_id,
            "document_id": "paper-p001",
            "source_kind": "table",
            "source_ref": "table-mechanical-properties",
            "evidence_role": "direct_result",
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": "yield strength",
                "value": 148.36,
                "unit": "MPa",
                "direction": "unknown",
                "result_text": "Yield strength was 148.36 MPa for sample 9.",
            },
            "attribution_scope": "descriptive_only",
            "scientific_context": {
                "material": [
                    {"name": "material", "value": "316L stainless steel"}
                ],
                "sample": [{"name": "Sample number", "value": "9"}],
                "process": [
                    {"name": "laser power", "value": 100, "unit": "W"}
                ],
            },
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-mechanical-properties",
                    "row_index": 9,
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    bound = paper_experiment._bind_objective_result_process_context(
        (condition("9", "B"), result)
    )[-1]

    assert {
        item.name: (item.value, item.unit)
        for item in bound.scientific_context.process
    } == {
        "laser power": (100, "W"),
        "Scan strategy": ("B", None),
        "Scanning speed": ("0.239", "m/s"),
        "Energy density": ("70", "J/mm3"),
    }
    assert {ref["source_ref"] for ref in bound.source_refs} == {
        "table-mechanical-properties",
        "table-processing-parameters",
    }


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


def test_paper_reconstruction_merges_duplicate_qualitative_claims_from_windows():
    claim = "Heat treatment increased density in the SLM samples."

    def qualitative(evidence_id: str, source_ref: str):
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": "obj-density",
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": source_ref,
                "evidence_role": "direct_result",
                "changed_variables": [
                    {
                        "name": "heat treatment type",
                        "baseline_value": None,
                        "target_value": None,
                    }
                ],
                "comparison": None,
                "reported_result": {
                    "outcome": "density",
                    "value": None,
                    "direction": "increase",
                    "result_text": claim,
                },
                "attribution_scope": "descriptive_only",
                "source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": source_ref,
                        "source_excerpt": claim,
                    }
                ],
                "resolution_status": "partial",
                "confidence": 0.8,
            }
        )

    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id="collection-test",
        source_facts=(
            qualitative("claim-results", "results-window"),
            qualitative("claim-conclusion", "conclusion-window"),
        ),
        objectives=(),
    )

    assert len(reconstructed) == 1
    assert reconstructed[0].reported_result is not None
    assert {
        ref["source_ref"] for ref in reconstructed[0].source_refs
    } == {"results-window", "conclusion-window"}


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
        objectives=(),
    )

    assert {item.evidence_id for item in distinct_values} == {
        "evidence-value-1",
        "evidence-value-10",
    }


def _source_grounded_material_context(
    *,
    evidence_id: str,
    material: str,
) -> ExtractedEvidenceDraft:
    return ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": evidence_id,
            "objective_id": "obj-ti64-strength",
            "document_id": "paper-ti64",
            "source_kind": "text_window",
            "source_ref": evidence_id,
            "evidence_role": "condition_context",
            "selection_status": "extracted",
            "attribution_scope": "not_attributable",
            "scientific_context": {
                "material": [{"name": "material", "value": material}],
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": evidence_id,
                    "supports": ["scientific_context.material"],
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.95,
        }
    )


def _source_grounded_strength_result() -> ExtractedEvidenceDraft:
    return ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "strength-result",
            "objective_id": "obj-ti64-strength",
            "document_id": "paper-ti64",
            "source_kind": "table",
            "source_ref": "table-strength",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "heat treatment temperature",
                    "baseline_value": 800,
                    "target_value": 900,
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "800 C",
                "target_label": "900 C",
                "axis_names": ["heat treatment temperature"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "tensile strength",
                "baseline_value": 980,
                "target_value": 1040,
                "value": 1040,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "tensile strength increased from 980 to 1040 MPa",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-strength",
                    "supports": [
                        "changed_variables",
                        "comparison.labels",
                        "reported_result",
                    ],
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )


def test_paper_reconstruction_binds_one_source_grounded_material_to_result():
    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id="collection-ti64",
        source_facts=(
            _source_grounded_material_context(
                evidence_id="methods-material",
                material="Ti-6Al-4V",
            ),
            _source_grounded_strength_result(),
        ),
        objectives=(),
    )

    result = next(item for item in reconstructed if item.evidence_id == "strength-result")
    assert [item.to_record() for item in result.scientific_context.material] == [
        {"name": "material", "value": "Ti-6Al-4V", "unit": None}
    ]
    material_ref = next(
        ref for ref in result.source_refs if ref["source_ref"] == "methods-material"
    )
    assert "scientific_context.material" in material_ref["supports"]


def test_paper_reconstruction_does_not_guess_between_multiple_materials():
    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id="collection-mixed",
        source_facts=(
            _source_grounded_material_context(
                evidence_id="methods-ti64",
                material="Ti-6Al-4V",
            ),
            _source_grounded_material_context(
                evidence_id="methods-316l",
                material="316L stainless steel",
            ),
            _source_grounded_strength_result(),
        ),
        objectives=(),
    )

    result = next(item for item in reconstructed if item.evidence_id == "strength-result")
    assert result.scientific_context.material == ()
    assert {ref["source_ref"] for ref in result.source_refs} == {"table-strength"}


def test_source_local_factor_comparison_survives_unrelated_condition_registry():
    unrelated_condition = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "condition-s1",
            "objective_id": "obj-residual-stress",
            "document_id": "paper-rescan",
            "source_kind": "table",
            "source_ref": "conditions",
            "evidence_role": "condition_context",
            "scientific_context": {
                "sample": [{"name": "sample", "value": "S1"}],
                "process": [{"name": "laser power", "value": 200, "unit": "W"}],
            },
            "source_refs": [{"source_kind": "table", "source_ref": "conditions"}],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "residual-stress-result",
            "objective_id": "obj-residual-stress",
            "document_id": "paper-rescan",
            "source_kind": "text_window",
            "source_ref": "abstract-result",
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "scanning strategy",
                    "baseline_value": "SLMed",
                    "target_value": "Re-SLMed",
                }
            ],
            "comparison": {
                "baseline_label": "SLMed",
                "target_label": "Re-SLMed",
                "axis_names": ["scanning strategy"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "residual stress",
                "baseline_value": 322,
                "target_value": 254,
                "value": 254,
                "unit": "MPa",
                "direction": "decrease",
                "result_text": (
                    "the average residual stress of the Re-SLMed sample was "
                    "reduced from 322 MPa to 254 MPa"
                ),
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [{"name": "alloy", "value": "Ti6Al4V"}],
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "abstract-result",
                    "supports": [
                        "changed_variables",
                        "comparison.labels",
                        "reported_result",
                        "scientific_context.material",
                    ],
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    bound = paper_experiment._bind_objective_result_process_context(
        (unrelated_condition, result)
    )[-1]

    assert [item.to_record() for item in bound.changed_variables] == [
        {
            "name": "scanning strategy",
            "baseline_value": "SLMed",
            "target_value": "Re-SLMed",
            "unit": None,
        }
    ]
    assert bound.comparison is not None
    assert bound.comparison.comparable is True
    assert bound.attribution_scope == "association_only"


def test_paper_reconstruction_binds_material_from_source_grounded_document_context():
    objective = _research_objective(
        {
            "objective_id": "obj-strength",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["heat treatment temperature"],
            "outcomes": ["tensile strength"],
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "table-strength",
            "objective_id": objective.objective_id,
            "document_id": "paper-ti64",
            "source_kind": "table",
            "source_ref": "table-5",
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "heat treatment temperature",
                    "baseline_value": 800,
                    "target_value": 900,
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "800 C",
                "target_label": "900 C",
                "axis_names": ["heat treatment temperature"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "tensile strength",
                "baseline_value": 980,
                "target_value": 1040,
                "value": 1040,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "tensile strength increased from 980 to 1040 MPa",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-5",
                    "supports": [
                        "changed_variables",
                        "comparison.labels",
                        "reported_result",
                    ],
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id=objective.collection_id,
        source_facts=(result,),
        objectives=(objective,),
        document_contexts={
            "paper-ti64": (
                {
                    "source_kind": "text_window",
                    "source_ref": "title-block",
                    "text": "Effect of heat treatment on Ti-6Al-4V tensile strength",
                },
            )
        },
    )

    bound = next(item for item in reconstructed if item.evidence_id == result.evidence_id)
    assert [item.to_record() for item in bound.scientific_context.material] == [
        {"name": "material", "value": "Ti-6Al-4V", "unit": None}
    ]
    assert any(
        ref.get("source_ref") == "title-block"
        and "scientific_context.material" in ref.get("supports", ())
        for ref in bound.source_refs
    )


def test_paper_reconstruction_binds_context_when_one_result_already_has_material():
    objective = _research_objective(
        {
            "objective_id": "obj-strength-mixed-material",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["heat treatment temperature"],
            "outcomes": ["tensile strength"],
        }
    )

    def result(evidence_id: str, value: int, material: bool) -> ExtractedEvidenceDraft:
        scientific_context = (
            {"material": [{"name": "material", "value": "Ti-6Al-4V"}]}
            if material
            else {}
        )
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
                "document_id": "paper-ti64",
                "source_kind": "table",
                "source_ref": f"table-{evidence_id}",
                "evidence_role": "direct_result",
                "changed_variables": [
                    {
                        "name": "heat treatment temperature",
                        "baseline_value": 800,
                        "target_value": 900,
                        "unit": "C",
                    }
                ],
                "comparison": {
                    "baseline_label": "800 C",
                    "target_label": "900 C",
                    "axis_names": ["heat treatment temperature"],
                    "comparable": True,
                },
                "reported_result": {
                    "outcome": "tensile strength",
                    "baseline_value": value - 50,
                    "target_value": value,
                    "value": value,
                    "unit": "MPa",
                    "direction": "increase",
                    "result_text": f"tensile strength increased to {value} MPa",
                },
                "attribution_scope": "isolated_effect",
                "scientific_context": scientific_context,
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": f"table-{evidence_id}",
                        "supports": [
                            "changed_variables",
                            "comparison.labels",
                            "reported_result",
                        ],
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id=objective.collection_id,
        source_facts=(
            result("with-material", 1040, True),
            result("without-material", 1060, False),
        ),
        objectives=(objective,),
        document_contexts={
            "paper-ti64": (
                {
                    "source_kind": "text_window",
                    "source_ref": "title-block",
                    "text": "Effect of heat treatment on Ti-6Al-4V tensile strength",
                },
            )
        },
    )

    without_material = next(
        item for item in reconstructed if item.evidence_id == "without-material"
    )
    assert [item.to_record() for item in without_material.scientific_context.material] == [
        {"name": "material", "value": "Ti-6Al-4V", "unit": None}
    ]


def test_paper_reconstruction_binds_unambiguous_same_paper_context_fields():
    """A result inherits only one source-grounded value per context field."""

    objective = _research_objective(
        {
            "objective_id": "obj-strength-context",
            "material_scope": ["316L stainless steel"],
            "variables": ["heat treatment temperature"],
            "outcomes": ["tensile strength"],
        }
    )
    context = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "methods-context",
            "objective_id": objective.objective_id,
            "document_id": "paper-316l",
            "source_kind": "text_window",
            "source_ref": "methods-context",
            "evidence_role": "condition_context",
            "selection_status": "extracted",
            "scientific_context": {
                "material": [{"name": "alloy", "value": "316L stainless steel"}],
                "sample": [{"name": "orientation", "value": "vertical"}],
                "process": [{"name": "layer thickness", "value": 0.03, "unit": "mm"}],
                "test": [{"name": "standard", "value": "ASTM E8"}],
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "methods-context",
                    "source_excerpt": "316L vertical samples, 0.03 mm layers, ASTM E8.",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.95,
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-context",
            "objective_id": objective.objective_id,
            "document_id": "paper-316l",
            "source_kind": "table",
            "source_ref": "table-strength",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "heat treatment temperature",
                    "baseline_value": 800,
                    "target_value": 900,
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "800 C",
                "target_label": "900 C",
                "axis_names": ["heat treatment temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "tensile strength",
                "baseline_value": 980,
                "target_value": 1040,
                "value": 1040,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "tensile strength increased from 980 to 1040 MPa",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "table-strength",
                    "source_excerpt": "800 C: 980 MPa; 900 C: 1040 MPa",
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id=objective.collection_id,
        source_facts=(context, result),
        objectives=(objective,),
    )

    bound = next(item for item in reconstructed if item.evidence_id == result.evidence_id)
    assert bound.scientific_context.to_record() == {
        "material": [{"name": "alloy", "value": "316L stainless steel", "unit": None}],
        "sample": [{"name": "orientation", "value": "vertical", "unit": None}],
        "process": [{"name": "layer thickness", "value": 0.03, "unit": "mm"}],
        "test": [{"name": "standard", "value": "ASTM E8", "unit": None}],
    }
    context_ref = next(
        ref for ref in bound.source_refs if ref["source_ref"] == "methods-context"
    )
    assert {
        "scientific_context.material",
        "scientific_context.sample",
        "scientific_context.process",
        "scientific_context.test",
    } <= set(context_ref["supports"])


def test_paper_reconstruction_joins_explicit_group_aliases_to_fixed_context():
    """NP/P150 labels must bind to the paper's descriptive condition Sources."""

    objective = _research_objective(
        {
            "objective_id": "obj-preheating-context",
            "question": "How does build platform preheating affect microstructure?",
            "variables": ["build platform preheating"],
            "outcomes": ["microstructure"],
        }
    )
    alias_text = (
        "Specimens fabricated without preheating the build platform, and the "
        "ones fabricated with preheating the build platform to 150 C are "
        "designated by NP and P150, respectively."
    )

    def condition(
        evidence_id: str,
        sample: str,
        process_value: str,
    ) -> ExtractedEvidenceDraft:
        return ExtractedEvidenceDraft.from_mapping(
            {
                "evidence_id": evidence_id,
                "objective_id": objective.objective_id,
                "document_id": "paper-preheating",
                "source_kind": "text_window",
                "source_ref": evidence_id,
                "evidence_role": "condition_context",
                "selection_status": "extracted",
                "scientific_context": {
                    "sample": [{"name": "specimen set", "value": sample}],
                    "process": [
                        {"name": "build platform preheating", "value": process_value},
                        {"name": "process", "value": "LB-PBF"},
                    ],
                },
                "source_refs": [
                    {
                        "source_kind": "text_window",
                        "source_ref": evidence_id,
                        "source_excerpt": alias_text,
                    }
                ],
                "resolution_status": "resolved",
                "confidence": 0.9,
            }
        )

    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "preheating-result-context",
            "objective_id": objective.objective_id,
            "document_id": "paper-preheating",
            "source_kind": "text_window",
            "source_ref": "results",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "preheating temperature",
                    "baseline_value": "NP",
                    "target_value": "P150",
                }
            ],
            "comparison": {
                "baseline_label": "NP",
                "target_label": "P150",
                "axis_names": ["preheating temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "microstructure",
                "direction": "mixed",
                "result_text": "The microstructure differed between NP and P150.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results",
                    "source_excerpt": "The microstructure differed between NP and P150.",
                    "supports": [
                        "changed_variables",
                        "comparison.labels",
                        "reported_result",
                    ],
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id=objective.collection_id,
        source_facts=(
            condition("condition-np", "non-preheated build platform", "non-preheated"),
            condition("condition-p150", "build platform preheated to 150 C", "150 C"),
            result,
        ),
        objectives=(objective,),
        document_contexts={
            "paper-preheating": (
                {
                    "source_kind": "text_window",
                    "source_ref": "group-aliases",
                    "text": alias_text,
                },
            )
        },
    )

    bound = next(item for item in reconstructed if item.evidence_id == result.evidence_id)
    assert bound.changed_variables[0].name == "build platform preheating"
    assert [item.to_record() for item in bound.scientific_context.process] == [
        {"name": "process", "value": "LB-PBF", "unit": None}
    ]


def test_paper_reconstruction_binds_qualitative_result_with_missing_endpoints():
    objective = _research_objective(
        {
            "objective_id": "obj-preheating-qualitative",
            "question": "How does build platform preheating affect microstructure?",
            "variables": ["build platform preheating"],
            "outcomes": ["microstructure"],
        }
    )
    alias_text = (
        "Specimens fabricated without preheating the build platform, and the "
        "ones fabricated with preheating the build platform to 150 C are "
        "designated by NP and P150, respectively."
    )
    result_source = (
        "Comparing the microstructure obtained for P150 with NP condition, "
        "the cellular structure is seen in the former condition."
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "preheating-qualitative-result",
            "objective_id": objective.objective_id,
            "document_id": "paper-preheating",
            "source_kind": "text_window",
            "source_ref": "results",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "build platform preheating",
                    "baseline_value": None,
                    "target_value": None,
                }
            ],
            "comparison": None,
            "reported_result": {
                "outcome": "microstructure",
                "direction": "mixed",
                "result_text": "the cellular structure is seen in the former condition",
            },
            "attribution_scope": "not_attributable",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results",
                    "source_excerpt": result_source,
                    "supports": ["reported_result"],
                }
            ],
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )

    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id=objective.collection_id,
        source_facts=(result,),
        objectives=(objective,),
        document_contexts={
            "paper-preheating": (
                {
                    "source_kind": "text_window",
                    "source_ref": "group-aliases",
                    "text": alias_text,
                },
            )
        },
    )

    bound = next(item for item in reconstructed if item.evidence_id == result.evidence_id)
    assert [variable.to_record() for variable in bound.changed_variables] == [
        {
            "name": "build platform preheating",
            "baseline_value": "with preheating the build platform to 150 C",
            "target_value": "without preheating the build platform",
            "unit": None,
        }
    ]
    assert bound.comparison is not None and bound.comparison.comparable
    assert bound.comparison.baseline_label == "P150"
    assert bound.comparison.target_label == "NP"
    assert bound.attribution_scope == "isolated_effect"
    assert {ref["source_ref"] for ref in bound.source_refs} == {
        "results",
        "group-aliases",
    }


def test_group_alias_binding_preserves_grounded_paper_wide_process_context():
    objective = _research_objective(
        {
            "objective_id": "obj-preheating-fixed-process",
            "question": "How does build platform preheating affect microstructure?",
            "variables": ["build platform preheating"],
            "outcomes": ["microstructure"],
        }
    )
    alias_text = (
        "Specimens fabricated without preheating the build platform, and the "
        "ones fabricated with preheating the build platform to 150 C are "
        "designated by NP and P150, respectively."
    )
    fixed_process = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "paper-wide-process",
            "objective_id": objective.objective_id,
            "document_id": "paper-preheating",
            "source_kind": "text_window",
            "source_ref": "methods-process",
            "evidence_role": "condition_context",
            "scientific_context": {
                "process": [
                    {"name": "manufacturing process", "value": "LB-PBF"},
                    {"name": "shielding gas", "value": "argon"},
                ]
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "methods-process",
                    "source_excerpt": (
                        "All specimens were fabricated by LB-PBF under argon."
                    ),
                }
            ],
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    result = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "preheating-result",
            "objective_id": objective.objective_id,
            "document_id": "paper-preheating",
            "source_kind": "text_window",
            "source_ref": "results",
            "evidence_role": "direct_result",
            "changed_variables": [
                {
                    "name": "build platform preheating",
                    "baseline_value": None,
                    "target_value": None,
                }
            ],
            "reported_result": {
                "outcome": "microstructure",
                "direction": "mixed",
                "result_text": "the cellular structure is seen in the former condition",
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results",
                    "source_excerpt": (
                        "Comparing the microstructure obtained for P150 with NP "
                        "condition, the cellular structure is seen in the former "
                        "condition."
                    ),
                    "supports": ["reported_result"],
                }
            ],
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )

    reconstructed = paper_experiment.reconstruct_paper_experiments(
        collection_id=objective.collection_id,
        source_facts=(fixed_process, result),
        objectives=(objective,),
        document_contexts={
            "paper-preheating": (
                {
                    "source_kind": "text_window",
                    "source_ref": "group-aliases",
                    "text": alias_text,
                },
            )
        },
    )

    bound = next(item for item in reconstructed if item.evidence_id == result.evidence_id)
    assert [item.to_record() for item in bound.scientific_context.process] == [
        {"name": "manufacturing process", "value": "LB-PBF", "unit": None},
        {"name": "shielding gas", "value": "argon", "unit": None},
    ]
    assert bound.comparison is not None and bound.comparison.comparable
    assert bound.attribution_scope == "isolated_effect"
