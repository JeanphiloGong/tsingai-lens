from __future__ import annotations

from types import SimpleNamespace

from application.core.objectives.analysis.diagnostics import (
    capture_analysis_diagnostics,
)
from application.core.objectives.analysis.evidence_materialization import (
    _analysis_contributions,
    _analysis_evidence_records,
    _canonical_objective_evidence_axes,
    _objective_detail_evidence,
    _objective_result_missing_field_families,
    _record_material_scope_exclusions,
    _record_source_coverage_ledger,
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


def test_objective_detail_evidence_keeps_context_when_result_is_not_yet_resolved() -> None:
    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser exposure"],
            "outcomes": ["porosity"],
        }
    )
    material_context = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "context-material",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods-material",
            "evidence_role": "condition_context",
            "selection_status": "extracted",
            "scientific_context": {
                "material": [{"name": "material", "value": "Ti-6Al-4V"}],
            },
            "attribution_scope": "not_attributable",
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    selected = _objective_detail_evidence(
        (material_context,),
        objective_context=objective,
    )

    assert [item.evidence_id for item in selected] == ["context-material"]


def test_changed_variable_endpoint_does_not_close_fixed_process_coverage() -> None:
    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "variables": ["temperature"],
            "outcomes": ["strength"],
        }
    )
    evidence = ObjectiveEvidence.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "evidence_id": "evidence-result",
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
            "scientific_context": {
                "sample": [{"name": "state", "value": "as-built"}],
                "process": [{"name": "temperature", "value": 500, "unit": "C"}],
                "test": [{"name": "method", "value": "tensile test"}],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    assert _objective_result_missing_field_families(
        objective=objective,
        evidence=evidence,
    ) == {"process"}


def test_materialization_does_not_mark_context_open_result_comparable() -> None:
    """A result with open same-paper process context cannot enter a Finding."""

    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "material_scope": ["316L stainless steel"],
            "variables": ["preheating temperature"],
            "outcomes": ["microstructure"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-1",
                preparation_fingerprint="fingerprint-paper-1",
            ),
        ),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    draft = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-open-process",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "source_excerpt": "The cellular structure was observed at 150 C.",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "preheating temperature",
                    "baseline_value": "NP",
                    "target_value": "150 C",
                }
            ],
            "comparison": {
                "baseline_label": "NP",
                "target_label": "150 C",
                "axis_names": ["preheating temperature"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "microstructure",
                "direction": "changed",
                "result_text": "The cellular structure was observed at 150 C.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [
                    {"name": "material", "value": "316L stainless steel"}
                ],
                "sample": [{"name": "condition", "value": "P150"}],
                "test": [{"name": "method", "value": "SEM"}],
            },
            "resolution_status": "resolved",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-1",
                }
            ],
            "confidence": 0.9,
        }
    )

    evidence_records = _analysis_evidence_records(
        collection_id=objective.collection_id,
        analysis=analysis,
        objective=objective,
        drafts=(draft,),
        blocks_by_document_id={
            "paper-1": [
                SimpleNamespace(
                    block_id="results-1",
                    text="The cellular structure was observed at 150 C.",
                    page=4,
                    heading_path="Results",
                )
            ]
        },
        tables_by_document_id={},
        figures_by_document_id={},
    )

    assert len(evidence_records) == 1
    evidence = evidence_records[0]
    assert evidence.evidence_status != "comparable"
    assert not FindingSynthesisService.is_synthesizable_result_evidence(
        objective,
        evidence,
    )


def test_source_coverage_ledger_separates_inspection_closure_and_technical_failure() -> None:
    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "variables": ["temperature"],
            "outcomes": ["strength"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-1",
                preparation_fingerprint="fingerprint-paper-1",
            ),
        ),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "source_dispositions": [
                {
                    "source_unit_id": "unit-result",
                    "source_kind": "block",
                    "source_ref": "result-1",
                    "disposition": "model_relevant",
                },
                {
                    "source_unit_id": "unit-methods",
                    "source_kind": "block",
                    "source_ref": "methods-1",
                    "disposition": "model_relevant",
                },
                {
                    "source_unit_id": "unit-failed",
                    "source_kind": "block",
                    "source_ref": "failed-1",
                    "disposition": "model_relevant",
                },
                {
                    "source_unit_id": "unit-omitted",
                    "source_kind": "table",
                    "source_ref": "table-1",
                    "disposition": "model_relevant",
                },
            ],
        }
    )
    routes = tuple(
        EvidenceCandidate.from_mapping(
            {
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": source_kind,
                "source_ref": source_ref,
                "role": role,
                "extractable": True,
            }
        )
        for source_kind, source_ref, role in (
            ("text_window", "result-1", "current_experimental_evidence"),
            ("text_window", "methods-1", "process_or_treatment"),
            ("text_window", "failed-1", "current_experimental_evidence"),
        )
    )
    result = ObjectiveEvidence.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "evidence_id": "evidence-result",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "result-1",
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
                "scientific_context": {
                    "sample": [{"name": "state", "value": "as-built"}],
                    "process": [
                        {"name": "temperature", "value": 500, "unit": "C"},
                        {"name": "hatch spacing", "value": 0.1, "unit": "mm"},
                    ],
                "test": [{"name": "method", "value": "tensile test"}],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    context = ObjectiveEvidence.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "evidence_id": "evidence-context",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods-1",
            "source_excerpt": "The specimens were prepared for tensile testing.",
            "evidence_role": "condition_context",
            "selection_status": "extracted",
            "scientific_context": {
                "sample": [{"name": "state", "value": "as-built"}],
            },
            "attribution_scope": "not_attributable",
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )
    failed = ObjectiveEvidence.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "evidence_id": "evidence-failed",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "failed-1",
            "source_excerpt": "A source that could not be parsed.",
            "evidence_role": "direct_result",
            "selection_status": "failed",
            "attribution_scope": "not_attributable",
            "resolution_status": "unknown",
            "failure_reason": "RuntimeError: provider unavailable",
            "confidence": 0.0,
        }
    )

    with capture_analysis_diagnostics() as diagnostics:
        _record_source_coverage_ledger(
            collection_id=objective.collection_id,
            analysis=analysis,
            objective=objective,
            frames=(frame,),
            routes=routes,
            evidence_records=(result, context, failed),
        )

    assert len(diagnostics.records) == 1
    ledger = diagnostics.records[0]
    assert ledger["trace_type"] == "objective_source_coverage_ledger"
    assert ledger["candidate_source_count"] == 4
    assert ledger["routed_source_count"] == 3
    assert ledger["inspected_source_count"] == 3
    assert ledger["result_source_count"] == 1
    assert ledger["context_source_count"] == 1
    assert ledger["technical_failure_count"] == 1
    assert ledger["uninspected_source_count"] == 0
    assert ledger["uninspected_source_refs"] == []
    assert ledger["missing_field_families"] == []
    assert ledger["coverage_complete"] is True
    assert ledger["closure_complete"] is False
    assert ledger["closure_basis"] == "post_materialization_same_paper_binding"


def test_objective_contribution_does_not_call_uninspected_source_scientific_absence() -> None:
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
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-1",
                preparation_fingerprint="fingerprint-paper-1",
            ),
        ),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "source_dispositions": [
                {
                    "source_unit_id": "frame-source-1",
                    "source_kind": "block",
                    "source_ref": "block-1",
                    "disposition": "model_relevant",
                },
                {
                    "source_unit_id": "frame-source-2",
                    "source_kind": "block",
                    "source_ref": "block-2",
                    "disposition": "model_relevant",
                },
            ],
        }
    )
    routed_source = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "block-1",
            "role": "current_experimental_evidence",
            "extractable": True,
            "confidence": 0.9,
        }
    )

    contribution = _analysis_contributions(
        collection_id="collection-1",
        analysis=analysis,
        objective=objective,
        paper_maps=(),
        frames=(frame,),
        routes=(routed_source,),
        evidence_records=(),
    )[0]

    assert contribution.evidence_disposition == "coverage_incomplete"
    assert contribution.uninspected_source_count == 1
    assert contribution.evidence_disposition_reason == (
        "1 selected Source(s) were not inspected for this Objective."
    )
    assert contribution.warnings == (
        "1 selected Source(s) were not inspected for this Objective.",
    )


def test_unused_framing_priors_do_not_downgrade_complete_selected_coverage() -> None:
    """Broad navigation candidates are not mandatory experiment evidence."""

    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "variables": ["temperature"],
            "outcomes": ["strength"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-1",
                preparation_fingerprint="fingerprint-paper-1",
            ),
        ),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "source_dispositions": [
                {
                    "source_unit_id": "unit-result",
                    "source_kind": "block",
                    "source_ref": "result-1",
                    "disposition": "model_relevant",
                },
                {
                    "source_unit_id": "unit-context",
                    "source_kind": "block",
                    "source_ref": "methods-1",
                    "disposition": "model_relevant",
                },
                {
                    "source_unit_id": "unit-unused-prior",
                    "source_kind": "block",
                    "source_ref": "generic-background",
                    "disposition": "model_relevant",
                },
            ],
        }
    )
    routes = tuple(
        EvidenceCandidate.from_mapping(
            {
                "objective_id": objective.objective_id,
                "document_id": "paper-1",
                "source_kind": "text_window",
                "source_ref": source_ref,
                "role": role,
                "extractable": True,
            }
        )
        for source_ref, role in (
            ("result-1", "current_experimental_evidence"),
            ("methods-1", "process_or_treatment"),
        )
    )
    result = ObjectiveEvidence.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": analysis.analysis_version,
            "evidence_id": "evidence-result",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "result-1",
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
            "scientific_context": {
                "sample": [{"name": "state", "value": "as-built"}],
                "process": [
                    {"name": "temperature", "value": 500, "unit": "C"},
                    {"name": "laser power", "value": 200, "unit": "W"},
                ],
                "test": [{"name": "method", "value": "tensile test"}],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    context = ObjectiveEvidence.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": analysis.analysis_version,
            "evidence_id": "evidence-context",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods-1",
            "source_excerpt": "Specimens were prepared for tensile testing.",
            "evidence_role": "condition_context",
            "selection_status": "extracted",
            "scientific_context": {
                "sample": [{"name": "state", "value": "as-built"}],
                "test": [{"name": "method", "value": "tensile test"}],
            },
            "attribution_scope": "not_attributable",
            "resolution_status": "resolved",
            "confidence": 0.8,
        }
    )

    contribution = _analysis_contributions(
        collection_id=objective.collection_id,
        analysis=analysis,
        objective=objective,
        paper_maps=(),
        frames=(frame,),
        routes=routes,
        evidence_records=(result, context),
    )[0]

    assert contribution.uninspected_source_count == 0
    assert contribution.evidence_disposition == "comparable_evidence"
    assert all("not inspected" not in warning for warning in contribution.warnings)


def test_materialization_persists_context_as_needs_context_evidence() -> None:
    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "material_scope": ["Ti-6Al-4V"],
            "variables": ["laser power"],
            "outcomes": ["porosity"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-1",
                preparation_fingerprint="fingerprint-paper-1",
            ),
        ),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    frame = PaperAnalysisFrame.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "relevance": "high",
            "paper_role": "primary_experiment",
        }
    )
    route = EvidenceCandidate.from_mapping(
        {
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods-material",
            "role": "process_or_treatment",
            "extractable": True,
            "reason": "Inspect same-paper material context.",
            "confidence": 0.9,
        }
    )
    draft = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "context-material",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "methods-material",
            "evidence_role": "condition_context",
            "selection_status": "extracted",
            "scientific_context": {
                "material": [{"name": "material", "value": "Ti-6Al-4V"}],
            },
            "attribution_scope": "not_attributable",
            "resolution_status": "resolved",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "methods-material",
                    "source_excerpt": "The material was Ti-6Al-4V powder.",
                }
            ],
            "confidence": 0.9,
        }
    )

    evidence_records, contributions = materialize_evidence(
        collection_id=objective.collection_id,
        analysis=analysis,
        objective=objective,
        drafts=(draft,),
        paper_maps=(),
        frames=(frame,),
        routes=(route,),
        blocks_by_document_id={
            "paper-1": [
                SimpleNamespace(
                    block_id="methods-material",
                    text="The material was Ti-6Al-4V powder.",
                    page=1,
                    heading_path="Materials and methods",
                )
            ]
        },
        tables_by_document_id={},
        figures_by_document_id={},
    )

    assert len(evidence_records) == 1
    assert evidence_records[0].evidence_status == "needs_context"
    assert not FindingSynthesisService._eligible_result_evidence(evidence_records[0])
    assert contributions[0].evidence_status_counts == (("needs_context", 1),)


def test_materialization_recovers_explicit_factor_from_result_source() -> None:
    """A missed structured factor is recovered only from the linked Source text."""

    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-fatigue",
            "material_scope": ["316L stainless steel"],
            "variables": ["volumetric energy density"],
            "outcomes": ["high cycle fatigue strength"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-p003",
                preparation_fingerprint="fingerprint-paper-p003",
            ),
        ),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    draft = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-missed-factor",
            "objective_id": objective.objective_id,
            "document_id": "paper-p003",
            "source_kind": "text_window",
            "source_ref": "results-fatigue",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": "high cycle fatigue strength",
                "direction": "improve",
                "result_text": (
                    "Increasing volumetric energy density improved high cycle fatigue strength."
                ),
            },
            "attribution_scope": "not_attributable",
            "scientific_context": {
                "material": [{"name": "material", "value": "316L stainless steel"}]
            },
            "resolution_status": "partial",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-fatigue",
                }
            ],
            "confidence": 0.8,
        }
    )

    records = _analysis_evidence_records(
        collection_id=objective.collection_id,
        analysis=analysis,
        objective=objective,
        drafts=(draft,),
        blocks_by_document_id={
            "paper-p003": [
                SimpleNamespace(
                    block_id="results-fatigue",
                    text=(
                        "Increasing volumetric energy density improved high cycle "
                        "fatigue strength."
                    ),
                    page=11,
                    heading_path="Conclusions",
                )
            ]
        },
        tables_by_document_id={},
        figures_by_document_id={},
    )

    assert len(records) == 1
    evidence = records[0]
    assert [item.name for item in evidence.changed_variables] == [
        "volumetric energy density"
    ]
    assert all(
        item.baseline_value is None and item.target_value is None
        for item in evidence.changed_variables
    )
    assert evidence.attribution_scope == "association_only"
    assert evidence.comparison is None
    assert any(
        "changed_variables" in ref.get("supports", [])
        for ref in evidence.related_source_refs
    )


def test_materialization_does_not_invent_factor_when_source_omits_it() -> None:
    """A result without an explicit factor remains unresolved, not guessed."""

    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-fatigue",
            "variables": ["volumetric energy density"],
            "outcomes": ["high cycle fatigue strength"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-p003",
                preparation_fingerprint="fingerprint-paper-p003",
            ),
        ),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    draft = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "result-without-factor",
            "objective_id": objective.objective_id,
            "document_id": "paper-p003",
            "source_kind": "text_window",
            "source_ref": "results-fatigue",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "reported_result": {
                "outcome": "high cycle fatigue strength",
                "direction": "improve",
                "result_text": "Fatigue strength improved.",
            },
            "attribution_scope": "not_attributable",
            "resolution_status": "partial",
            "source_refs": [
                {"source_kind": "text_window", "source_ref": "results-fatigue"}
            ],
            "confidence": 0.8,
        }
    )

    records = _analysis_evidence_records(
        collection_id=objective.collection_id,
        analysis=analysis,
        objective=objective,
        drafts=(draft,),
        blocks_by_document_id={
            "paper-p003": [
                SimpleNamespace(
                    block_id="results-fatigue",
                    text="Fatigue strength improved.",
                    page=11,
                    heading_path="Conclusions",
                )
            ]
        },
        tables_by_document_id={},
        figures_by_document_id={},
    )

    assert records[0].changed_variables == ()
    assert records[0].attribution_scope == "not_attributable"


def test_materialization_preserves_incomparable_observation_without_attribution() -> None:
    """Unresolved comparison groups remain usable evidence, not a hard failure."""

    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-microstructure",
            "variables": ["laser power"],
            "outcomes": ["microstructure"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-unresolved-groups",
                preparation_fingerprint="fingerprint-paper-unresolved-groups",
            ),
        ),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    draft = ExtractedEvidenceDraft.from_mapping(
        {
            "evidence_id": "incomparable-microstructure",
            "objective_id": objective.objective_id,
            "document_id": "paper-unresolved-groups",
            "source_kind": "text_window",
            "source_ref": "results-microstructure",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "comparison": {
                "baseline_label": "S1",
                "target_label": "S2",
                "axis_names": ["sample"],
                "comparable": False,
                "incomparability_reasons": [
                    "factor levels are unresolved in SOURCE"
                ],
            },
            "reported_result": {
                "outcome": "microstructure",
                "direction": "improve",
                "result_text": "S2 showed improved microstructure.",
            },
            "attribution_scope": "not_attributable",
            "resolution_status": "partial",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-microstructure",
                }
            ],
            "confidence": 0.8,
        }
    )

    records = _analysis_evidence_records(
        collection_id=objective.collection_id,
        analysis=analysis,
        objective=objective,
        drafts=(draft,),
        blocks_by_document_id={
            "paper-unresolved-groups": [
                SimpleNamespace(
                    block_id="results-microstructure",
                    text=(
                        "The laser power was varied between the groups. "
                        "S2 showed improved microstructure."
                    ),
                    page=7,
                    heading_path="Results",
                )
            ]
        },
        tables_by_document_id={},
        figures_by_document_id={},
    )

    assert len(records) == 1
    evidence = records[0]
    assert evidence.evidence_status == "non_comparable"
    assert evidence.attribution_scope == "not_attributable"
    assert evidence.comparison is not None
    assert evidence.comparison.comparable is False


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
    assert contributions[0].analysis_status == "excluded"
    assert contributions[0].evidence_disposition == "excluded"
    assert contributions[0].exclusion_reason == (
        "No Source in this paper entered Objective deep reading."
    )
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
            "paper_disposition_counts": {"excluded": 1},
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
            blocks_by_document_id={
                "paper-1": [
                    SimpleNamespace(
                        block_id="block-1",
                        text="Elongation increased to 12%.",
                        page=1,
                        heading_path="Results",
                    )
                ]
            },
            tables_by_document_id={},
            figures_by_document_id={},
        )

    assert len(evidence_records) == 1
    assert evidence_records[0].reported_result is not None
    assert evidence_records[0].reported_result.outcome == "elongation"
    assert evidence_records[0].evidence_status == "descriptive"
    assert "outside" in (evidence_records[0].selection_reason or "").casefold()
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
        "selected_draft_count": 1,
        "evidence_record_count": 1,
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
                "test": [{"name": "method", "value": "tensile test"}],
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
