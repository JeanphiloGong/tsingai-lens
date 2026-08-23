from __future__ import annotations

from application.core.objectives.analysis.diagnostics import (
    capture_analysis_diagnostics,
)
from application.core.objectives.analysis.evidence_materialization import (
    materialize_evidence,
)
from application.core.objectives.analysis.evidence_routing import EvidenceCandidate
from application.core.objectives.analysis.source_extraction import (
    ExtractedEvidenceDraft,
)
from application.core.objectives.analysis.source_screening import PaperAnalysisFrame
from domain.core import ObjectiveAnalysis
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
        source_build_id="build-1",
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
            paper_skims=(),
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
        source_build_id="build-1",
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
            paper_skims=(),
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
