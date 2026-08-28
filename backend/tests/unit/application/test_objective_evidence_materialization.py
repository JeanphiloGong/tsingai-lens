from __future__ import annotations

from application.core.objectives.analysis.diagnostics import (
    capture_analysis_diagnostics,
)
from application.core.objectives.analysis.evidence_materialization import (
    _analysis_contributions,
    _canonical_objective_evidence_axes,
    _record_material_scope_exclusions,
    materialize_evidence,
)
from application.core.objectives.analysis.evidence_routing import EvidenceCandidate
from application.core.objectives.analysis.finding_synthesis import (
    FindingSynthesisService,
)
from application.core.objectives.analysis.source_extraction import (
    ExtractedEvidenceDraft,
)
from application.core.objectives.analysis.source_screening import PaperAnalysisFrame
from domain.core import ObjectiveAnalysis, ObjectiveEvidence, PreparedDocumentInput
from tests.support.research_objective_service import research_objective


def test_empty_evidence_materialization_records_bounded_abstention_trace() -> None:
    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "variables": ["temperature"],
            "outcomes": ["strength"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "objective-1",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
        }
    )

    with capture_analysis_diagnostics() as diagnostics:
        evidence_records, contributions = materialize_evidence(
            collection_id="collection-1",
            analysis=analysis,
            objective=objective,
            drafts=(),
            paper_maps=(),
            frames=(frame,),
            routes=(),
            blocks_by_document_id={},
            tables_by_document_id={},
            figures_by_document_id={},
        )

    assert evidence_records == ()
    assert contributions[0].evidence_disposition == "no_routable_evidence"
    assert diagnostics.records == (
        {
            "trace_type": "objective_evidence_materialization",
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "draft_count": 0,
            "failed_draft_count": 0,
            "target_outcome_match_count": 0,
            "selected_draft_count": 0,
            "evidence_record_count": 0,
            "paper_disposition_counts": {"no_routable_evidence": 1},
        },
    )


def test_out_of_scope_result_records_bounded_no_comparable_evidence_trace() -> None:
    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "variables": ["temperature"],
            "outcomes": ["strength"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "objective-1",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "objective-1",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-1",
            "role": "current_experimental_evidence",
            "extractable": True,
            "reason": "Inspect a reported material response.",
            "confidence": 0.9,
        }
    )
    draft = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "draft-1",
            "objective_id": "objective-1",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "temperature",
                    "baseline_value": 500,
                    "target_value": 600,
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "500 C",
                "target_label": "600 C",
                "axis_names": ["temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "elongation",
                "value": 12,
                "unit": "%",
                "direction": "increase",
                "result_text": "Elongation increased to 12%.",
            },
            "attribution_scope": "isolated_effect",
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    with capture_analysis_diagnostics() as diagnostics:
        evidence_records, contributions = materialize_evidence(
            collection_id="collection-1",
            analysis=analysis,
            objective=objective,
            drafts=(draft,),
            paper_maps=(),
            frames=(frame,),
            routes=(route,),
            blocks_by_document_id={},
            tables_by_document_id={},
            figures_by_document_id={},
        )

    assert evidence_records == ()
    assert contributions[0].analysis_status == "analyzed"
    assert contributions[0].evidence_disposition == "no_comparable_evidence"
    assert diagnostics.records[0] == {
        "trace_type": "objective_evidence_materialization",
        "collection_id": "collection-1",
        "objective_id": "objective-1",
        "analysis_version": 1,
        "draft_count": 1,
        "failed_draft_count": 0,
        "target_outcome_match_count": 0,
        "selected_draft_count": 0,
        "evidence_record_count": 0,
        "paper_disposition_counts": {"no_comparable_evidence": 1},
    }


def test_materialization_canonicalizes_elongation_to_ductility_objective() -> None:
    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-energy-ductility",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["energy input"],
            "outcomes": ["ductility"],
        }
    )
    draft = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "draft-energy-ductility",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "result-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "Laser power, P",
                    "baseline_value": "1000 W",
                    "target_value": "850 W",
                }
            ],
            "comparison": {
                "baseline_label": "200-1000",
                "target_label": "200-850",
                "axis_names": ["Laser power, P"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "elongation",
                "baseline_value": 20.1,
                "target_value": 17.0,
                "value": 17.0,
                "unit": "%",
                "direction": "decrease",
                "result_text": "elongation decreased from 20.1% to 17.0%",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [{"name": "material", "value": "Ti-6Al-4V"}],
                "process": [
                    {
                        "name": "Input current (induction heater), I",
                        "value": "200 A",
                    }
                ],
            },
            "resolution_status": "partial",
            "confidence": 0.9,
        }
    )

    canonical = _canonical_objective_evidence_axes(draft, objective=objective)
    evidence = ObjectiveEvidence.from_mapping(
        {
            **canonical.to_record(),
            "collection_id": objective.collection_id,
            "analysis_version": 1,
            "source_excerpt": "elongation decreased from 20.1% to 17.0%",
        }
    )

    assert canonical.reported_result is not None
    assert canonical.reported_result.outcome == "ductility"
    assert FindingSynthesisService.is_comparable_result_evidence(
        objective,
        evidence,
    )


def test_material_scope_exclusion_records_source_decision_trace() -> None:
    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-ti64-porosity",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser exposure condition"],
            "outcomes": ["porosity"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    evidence = ObjectiveEvidence.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "evidence_id": "evidence-steel-porosity",
            "document_id": "paper-scanning-review",
            "source_kind": "text_window",
            "source_ref": "block-review-17-4ph",
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
            "reported_result": {
                "outcome": "porosity",
                "direction": "decrease",
                "result_text": "Scan X produced smaller porosity than Scan O.",
            },
            "comparison": {
                "baseline_label": "Scan O",
                "target_label": "Scan X",
                "axis_names": ["scanning strategy"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [
                    {"name": "material", "value": "17-4PH stainless steel"}
                ]
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    with capture_analysis_diagnostics() as diagnostics:
        _record_material_scope_exclusions(
            collection_id=objective.collection_id,
            analysis=analysis,
            objective=objective,
            evidence_records=(evidence,),
        )

    assert diagnostics.records == (
        {
            "trace_type": "objective_material_scope_decision",
            "collection_id": "collection-1",
            "objective_id": "objective-ti64-porosity",
            "analysis_version": 1,
            "document_id": "paper-scanning-review",
            "source_kind": "text_window",
            "source_ref": "block-review-17-4ph",
            "objective_material_scope": ["Ti-6Al-4V"],
            "evidence_material_scope": ["17-4PH stainless steel"],
            "scope_status": "mismatched",
            "disposition": "excluded_from_comparison",
        },
    )

    out_of_axis_objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-ti64-strength",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser exposure condition"],
            "outcomes": ["yield strength"],
        }
    )
    with capture_analysis_diagnostics() as diagnostics:
        _record_material_scope_exclusions(
            collection_id=out_of_axis_objective.collection_id,
            analysis=analysis,
            objective=out_of_axis_objective,
            evidence_records=(evidence,),
        )

    assert diagnostics.records == ()


def test_material_scope_exclusion_trace_is_bounded() -> None:
    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-ti64-porosity",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["scanning strategy"],
            "outcomes": ["porosity"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    evidence = ObjectiveEvidence.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "evidence_id": "evidence-steel-porosity",
            "document_id": "paper-steel",
            "source_kind": "text_window",
            "source_ref": "block-steel",
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
            "reported_result": {
                "outcome": "porosity",
                "direction": "decrease",
                "result_text": "Scan X produced smaller porosity than Scan O.",
            },
            "comparison": {
                "baseline_label": "Scan O",
                "target_label": "Scan X",
                "axis_names": ["scanning strategy"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [
                    {"name": "material", "value": "17-4PH stainless steel"}
                ]
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    with capture_analysis_diagnostics() as diagnostics:
        _record_material_scope_exclusions(
            collection_id=objective.collection_id,
            analysis=analysis,
            objective=objective,
            evidence_records=(evidence,) * 102,
        )

    assert len(diagnostics.records) == 101
    assert diagnostics.records[-1] == {
        "trace_type": "objective_material_scope_decision_summary",
        "collection_id": "collection-1",
        "objective_id": "objective-ti64-porosity",
        "analysis_version": 1,
        "recorded_count": 100,
        "omitted_count": 2,
        "omitted_scope_status_counts": {"mismatched": 2},
    }


def test_paper_contribution_summary_comes_from_grounded_evidence() -> None:
    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "variables": ["temperature"],
            "outcomes": ["strength"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id="collection-1",
        objective_id="objective-1",
        analysis_version=1,
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fingerprint-paper-1"),),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": "objective-1",
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "screening_note": "This local batch may discuss strength.",
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": "objective-1",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "role": "current_experimental_evidence",
            "extractable": True,
        }
    )
    evidence = ObjectiveEvidence.from_mapping(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "evidence_id": "evidence-1",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "source_excerpt": "Strength increased from 800 MPa to 900 MPa.",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "temperature",
                    "baseline_value": 500,
                    "target_value": 600,
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "500 C",
                "target_label": "600 C",
                "axis_names": ["temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "strength",
                "baseline_value": 800,
                "target_value": 900,
                "unit": "MPa",
                "direction": "increase",
                "result_text": "Strength increased from 800 MPa to 900 MPa.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {},
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    contributions = _analysis_contributions(
        collection_id="collection-1",
        analysis=analysis,
        objective=objective,
        paper_maps=(),
        frames=(frame,),
        routes=(route,),
        evidence_records=(evidence,),
    )

    assert contributions[0].contribution_summary == (
        "Strength increased from 800 MPa to 900 MPa."
    )
    assert contributions[0].contribution_summary != frame.screening_note
