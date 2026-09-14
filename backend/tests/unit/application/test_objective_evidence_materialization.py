from __future__ import annotations

from types import SimpleNamespace

from application.core.objectives.analysis.diagnostics import (
    capture_analysis_diagnostics,
)
from application.core.objectives.analysis.evidence_materialization import (
    _analysis_contributions,
    _analysis_evidence_records,
    _canonical_evidence_source,
    _canonical_objective_evidence_axes,
    _objective_detail_evidence,
    _recover_source_explicit_objective_factors,
    _objective_result_missing_field_families,
    _record_material_scope_exclusions,
    _researcher_decision_packet_audit,
    _record_researcher_information_parity_snapshot,
    _record_source_coverage_ledger,
    materialize_evidence,
    rebind_persisted_contribution,
    rebind_persisted_evidence,
)
from application.core.objectives.analysis.evidence_routing import EvidenceCandidate
from application.core.objectives.analysis.finding_synthesis import (
    FindingSynthesisService,
)
from application.core.objectives.analysis.source_screening import PaperAnalysisFrame
from application.core.objectives.analysis.source_extraction import SourceReadAudit
from domain.core import (
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
    PreparedDocumentInput,
    SourceObservation,
)
from domain.source import SourceTable
from tests.support.research_objective_service import research_objective


def test_grounding_rejection_remains_retryable_not_a_scientific_absence() -> None:
    objective = research_objective({"variables": ["laser power"], "outcomes": ["porosity"]})
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id, objective_id=objective.objective_id,
        analysis_version=1, total_document_count=1,
        document_inputs=(PreparedDocumentInput(document_id="paper-1", preparation_fingerprint="fixture"),),
        pipeline_version="test", model_name=None, prompt_versions={},
    )
    route = EvidenceCandidate.from_mapping({
        "objective_id": objective.objective_id, "document_id": "paper-1",
        "source_kind": "text_window", "source_ref": "result-1",
        "role": "current_experimental_evidence", "extractable": True,
    })
    records, contributions = materialize_evidence(
        collection_id=objective.collection_id, objective=objective, analysis=analysis,
        observations=(), technical_audits=(SourceReadAudit(
            collection_id=objective.collection_id, objective_id=objective.objective_id,
            document_id="paper-1", source_kind="text_window", source_ref="result-1",
            disposition="grounding_rejected", reason="Source grounding failed: unsupported result value",
        ),), paper_maps=(), frames=(PaperAnalysisFrame.from_mapping({
            "objective_id": objective.objective_id, "document_id": "paper-1",
            "relevance": "high", "paper_role": "primary_experiment",
        }),), routes=(route,), blocks_by_document_id={}, tables_by_document_id={}, figures_by_document_id={},
    )
    assert records == ()
    assert contributions[0].failed_source_count == 1
    assert contributions[0].analysis_status == "failed"
    assert contributions[0].uninspected_source_count == 0
    assert contributions[0].warnings


def test_unaccepted_observation_keeps_its_value_without_entering_synthesis() -> None:
    objective = research_objective(
        {"variables": ["preheating"], "outcomes": ["elongation"]}
    )
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=1,
        total_document_count=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="p002", preparation_fingerprint="fixture"
            ),
        ),
        pipeline_version="test",
        model_name=None,
        prompt_versions={},
    )
    table = SourceTable(
        table_id="table-2",
        document_id="p002",
        table_order=2,
        caption_block_id=None,
        page=8,
        caption_text="Elongation (%)",
        heading_path="Results",
        column_headers=("Condition", "Elongation (%)"),
        table_matrix=(("P150", "82"),),
    )
    for state, expected in (("uncertain", "candidate"), ("rejected", "rejected")):
        observation = SourceObservation.from_mapping(
            {
                "observation_id": "p150",
                "objective_id": objective.objective_id,
                "document_id": "p002",
                "source_kind": "table",
                "source_ref": "table-2",
                "observation_role": "direct_result",
                "status": state,
                "source_excerpt": "P150 82",
                "selection_status": "extracted",
                "reported_result": {
                    "outcome": "elongation",
                    "value": 82,
                    "unit": "%",
                    "direction": "unknown",
                    "result_text": "P150 82",
                },
            }
        )
        evidence = _analysis_evidence_records(
            collection_id=objective.collection_id,
            analysis=analysis,
            objective=objective,
            drafts=(observation,),
            blocks_by_document_id={},
            tables_by_document_id={"p002": [table]},
            figures_by_document_id={},
        )[0]
        assert evidence.reported_result.value == 82
        assert evidence.selection_status == expected
        assert not FindingSynthesisService.is_synthesizable_result_evidence(
            objective, evidence
        )


def test_factor_recovery_does_not_promote_treatment_mediated_porosity() -> None:
    objective = research_objective(
        {
            "objective_id": "objective-porosity-elongation",
            "question": "How does porosity affect elongation?",
            "variables": ["porosity"],
            "outcomes": ["elongation"],
        }
    )
    draft = SourceObservation.from_mapping(
        {
            "evidence_id": "heat-treatment-elongation",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "abstract-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": "elongation",
                "direction": "improve",
                "result_text": "The heat treatments improved elongation.",
            },
            "attribution_scope": "descriptive_only",
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )

    recovered = _recover_source_explicit_objective_factors(
        draft,
        objective=objective,
        source_excerpt=(
            "The heat treatments induced the removal of porosity. "
            "The heat treatments improved elongation."
        ),
        source_kind="text_window",
        source_ref="abstract-1",
    )

    assert recovered.changed_variables == ()
    assert recovered.attribution_scope == "descriptive_only"


def test_factor_recovery_keeps_explicit_porosity_elongation_association() -> None:
    objective = research_objective(
        {
            "objective_id": "objective-porosity-elongation",
            "question": "How does porosity affect elongation?",
            "variables": ["porosity"],
            "outcomes": ["elongation"],
        }
    )
    result_text = "Higher porosity was associated with lower elongation."
    draft = SourceObservation.from_mapping(
        {
            "evidence_id": "porosity-elongation-association",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [],
            "comparison": None,
            "reported_result": {
                "outcome": "elongation",
                "direction": "decrease",
                "result_text": result_text,
            },
            "attribution_scope": "descriptive_only",
            "resolution_status": "partial",
            "confidence": 0.8,
        }
    )

    recovered = _recover_source_explicit_objective_factors(
        draft,
        objective=objective,
        source_excerpt=result_text,
        source_kind="text_window",
        source_ref="results-1",
    )

    assert [item.name for item in recovered.changed_variables] == ["porosity"]


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
    material_context = SourceObservation.from_mapping(
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
    draft = SourceObservation.from_mapping(
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


def test_materialization_deduplicates_identical_source_grounded_fact() -> None:
    """A repeated model extraction is one scientific fact, not two Evidence rows."""

    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "material_scope": ["alloy"],
            "variables": ["temperature"],
            "outcomes": ["grain structure"],
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
    source_text = "At 600 C the grain structure changed compared with 500 C."
    common = {
        "objective_id": objective.objective_id,
        "document_id": "paper-1",
        "source_kind": "text_window",
        "source_ref": "results-1",
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
            "outcome": "grain structure",
            "direction": "changed",
            "result_text": source_text,
        },
        "attribution_scope": "isolated_effect",
        "scientific_context": {
            "material": [{"name": "material", "value": "alloy"}],
            "process": [{"name": "process", "value": "heat treatment"}],
            "test": [{"name": "method", "value": "microscopy"}],
        },
        "resolution_status": "resolved",
        "confidence": 0.9,
    }
    drafts = tuple(
        SourceObservation.from_mapping(
            {**common, "evidence_id": evidence_id}
        )
        for evidence_id in ("model-pass-1", "model-pass-2")
    )

    records = _analysis_evidence_records(
        collection_id=objective.collection_id,
        analysis=analysis,
        objective=objective,
        drafts=drafts,
        blocks_by_document_id={
            "paper-1": [
                SimpleNamespace(
                    block_id="results-1",
                    text=source_text,
                    page=4,
                    heading_path="Results",
                )
            ]
        },
        tables_by_document_id={},
        figures_by_document_id={},
    )

    assert len(records) == 1


def test_materialization_keeps_same_value_from_distinct_table_rows() -> None:
    """A repeated scalar in two specimen rows remains two Source-local facts."""

    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "material_scope": ["alloy"],
            "variables": ["temperature"],
            "outcomes": ["elongation"],
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
    table = SourceTable(
        table_id="table-1",
        document_id="paper-1",
        table_order=1,
        caption_text="Elongation by specimen.",
        caption_block_id=None,
        page=5,
        heading_path="Results",
        column_headers=("Specimen", "Elongation (%)"),
        table_matrix=(
            ("Specimen", "Elongation (%)"),
            ("A", "12"),
            ("B", "12"),
        ),
    )
    common = {
        "objective_id": objective.objective_id,
        "document_id": "paper-1",
        "source_kind": "table",
        "source_ref": "table-1",
        "evidence_role": "direct_result",
        "selection_status": "extracted",
        "reported_result": {
            "outcome": "elongation",
            "value": 12,
            "unit": "%",
            "direction": "unchanged",
            "result_text": "Elongation was 12%.",
        },
        "attribution_scope": "descriptive_only",
        "resolution_status": "partial",
        "confidence": 0.8,
    }
    drafts = tuple(
        SourceObservation.from_mapping(
            {
                **common,
                "evidence_id": f"row-{row_index}",
                "scientific_context": {
                    "material": [{"name": "material", "value": "alloy"}],
                    "sample": [{"name": "specimen", "value": specimen}],
                },
                "source_refs": [
                    {
                        "source_kind": "table",
                        "source_ref": "table-1",
                        "page": 5,
                        "row_index": row_index,
                        "col_index": 1,
                        "source_excerpt": (
                            f"Specimen: {specimen} | Elongation (%): 12"
                        ),
                    }
                ],
            }
        )
        for row_index, specimen in ((1, "A"), (2, "B"))
    )

    records = _analysis_evidence_records(
        collection_id=objective.collection_id,
        analysis=analysis,
        objective=objective,
        drafts=drafts,
        blocks_by_document_id={},
        tables_by_document_id={"paper-1": [table]},
        figures_by_document_id={},
    )

    assert len(records) == 2
    assert {record.evidence_id for record in records} == {"row-1", "row-2"}
    assert {record.source_excerpt for record in records} == {
        "Specimen: A | Elongation (%): 12",
        "Specimen: B | Elongation (%): 12",
    }


def test_materialization_coalesces_replayed_fact_with_different_context_lineage() -> None:
    """A reread may resolve context differently without creating a second fact."""

    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "material_scope": ["316L"],
            "variables": ["volumetric energy density"],
            "outcomes": ["fatigue strength"],
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
    result_text = "Fatigue strength decreased from 470 MPa to 340 MPa."
    common = {
        "objective_id": objective.objective_id,
        "document_id": "paper-1",
        "source_kind": "text_window",
        "source_ref": "results-1",
        "evidence_role": "direct_result",
        "selection_status": "extracted",
        "changed_variables": [
            {
                "name": "volumetric energy density",
                "baseline_value": 84.3,
                "target_value": 50.8,
                "unit": "J/mm3",
            }
        ],
        "comparison": {
            "baseline_label": "H-VED",
            "target_label": "L-VED",
            "axis_names": ["volumetric energy density"],
            "comparable": True,
        },
        "reported_result": {
            "outcome": "fatigue strength",
            "value": 340,
            "baseline_value": 470,
            "target_value": 340,
            "unit": "MPa",
            "direction": "decrease",
            "result_text": result_text,
            "result_kind": "measured",
        },
        "attribution_scope": "isolated_effect",
        "resolution_status": "resolved",
        "confidence": 0.9,
    }
    first = SourceObservation.from_mapping(
        {
            **common,
            "evidence_id": "model-pass-1",
            "scientific_context": {
                "material": [{"name": "material", "value": "AISI 316L"}],
            },
            "source_refs": [
                {"source_kind": "text_window", "source_ref": "results-1"},
                {"source_kind": "text_window", "source_ref": "methods-1"},
            ],
        }
    )
    replay = SourceObservation.from_mapping(
        {
            **common,
            "evidence_id": "model-pass-2",
            "scientific_context": {
                "material": [{"name": "316L stainless steel", "value": "316L"}],
            },
            "source_refs": [
                {"source_kind": "text_window", "source_ref": "results-1"},
                {"source_kind": "text_window", "source_ref": "methods-2"},
            ],
        }
    )

    records = _analysis_evidence_records(
        collection_id=objective.collection_id,
        analysis=analysis,
        objective=objective,
        drafts=(first, replay),
        blocks_by_document_id={
            "paper-1": [
                SimpleNamespace(
                    block_id="results-1",
                    text=result_text,
                    page=4,
                    heading_path="Results",
                ),
                SimpleNamespace(
                    block_id="methods-1",
                    text="The material was AISI 316L.",
                    page=2,
                    heading_path="Methods",
                ),
                SimpleNamespace(
                    block_id="methods-2",
                    text="The material was 316L stainless steel.",
                    page=2,
                    heading_path="Methods",
                ),
            ]
        },
        tables_by_document_id={},
        figures_by_document_id={},
    )

    assert len(records) == 1
    assert records[0].evidence_id == "model-pass-1"
    assert {item["source_ref"] for item in records[0].related_source_refs} >= {
        "results-1",
        "methods-1",
        "methods-2",
    }


def test_text_evidence_excerpt_stays_bound_to_its_primary_source() -> None:
    """Same-paper context is lineage, not text appended to the result Source."""

    result_text = "P150 developed a cellular structure compared with NP."
    methods_text = (
        "NP and P150 denote non-preheated and 150 C preheated specimens, "
        "respectively."
    )
    draft = SourceObservation.from_mapping(
        {
            "evidence_id": "microstructure-result",
            "objective_id": "objective-1",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "reported_result": {
                "outcome": "microstructure",
                "direction": "changed",
                "result_text": result_text,
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-1",
                    "source_excerpt": f"{result_text}\n{methods_text}\nMethods",
                },
                {
                    "source_kind": "text_window",
                    "source_ref": "methods-1",
                    "source_excerpt": f"{methods_text}\nMethods",
                    "supports": ["changed_variables", "comparison.axis_names"],
                },
            ],
            "confidence": 0.9,
        }
    )

    source = _canonical_evidence_source(
        draft,
        blocks_by_document_id={
            "paper-1": [
                SimpleNamespace(block_id="results-1", text=result_text, page=6),
                SimpleNamespace(block_id="methods-1", text=methods_text, page=3),
            ]
        },
        tables_by_document_id={},
        figures_by_document_id={},
    )

    assert source is not None
    assert source["source_ref"] == "results-1"
    assert source["source_excerpt"] == result_text
    assert {item["source_ref"] for item in source["related_source_refs"]} == {
        "results-1",
        "methods-1",
    }


def test_materialization_uses_same_paper_definition_to_resolve_source_axis() -> None:
    """A paper-defined condition mapping may resolve a different source label.

    The Objective asks about the intervention ``build platform preheating``;
    the model called the extracted process field ``preheating temperature``.
    Those labels are not interchangeable by vocabulary alone.  The paper's
    Methods passage defines both comparison groups and the intervention, so
    the late canonicalization step may safely bind the source field to the
    confirmed Objective axis.
    """

    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-preheating",
            "material_scope": ["316L stainless steel"],
            "variables": ["build platform preheating"],
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
    result_text = (
        "Comparing the microstructure obtained for P150 with NP condition, "
        "the cellular structure is seen in the former condition."
    )
    methods_text = (
        "Specimens fabricated without preheating the build platform and with "
        "preheating the build platform to 150 C were designated NP and P150."
    )
    draft = SourceObservation.from_mapping(
        {
            "evidence_id": "source-specific-axis",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "source_excerpt": result_text,
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "preheating temperature",
                    "baseline_value": "NP",
                    "target_value": 150,
                    "unit": "C",
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
                "result_text": result_text,
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [
                    {"name": "material", "value": "316L stainless steel"}
                ]
            },
            "resolution_status": "resolved",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-1",
                    "source_excerpt": result_text,
                    "supports": ["comparison.labels", "reported_result"],
                },
                {
                    "source_kind": "text_window",
                    "source_ref": "methods-1",
                    "source_excerpt": methods_text,
                    "supports": ["changed_variables", "comparison.axis_names"],
                },
            ],
            "confidence": 0.9,
        }
    )

    records = _analysis_evidence_records(
        collection_id=objective.collection_id,
        analysis=analysis,
        objective=objective,
        drafts=(draft,),
        blocks_by_document_id={
            "paper-1": [
                SimpleNamespace(
                    block_id="results-1",
                    text=result_text,
                    page=6,
                    heading_path="Results",
                ),
                SimpleNamespace(
                    block_id="methods-1",
                    text=methods_text,
                    page=3,
                    heading_path="Methods",
                ),
            ]
        },
        tables_by_document_id={},
        figures_by_document_id={},
    )

    assert len(records) == 1
    assert records[0].changed_variables[0].name == "build platform preheating"
    assert records[0].comparison is not None
    assert records[0].comparison.axis_names == ("build platform preheating",)


def test_materialization_resolves_source_axis_from_locator_only_refs() -> None:
    """The production-shaped payload keeps excerpts in the Source store.

    Extraction responses normally return stable Source locators, while the
    materializer receives the authoritative block text separately.  Axis
    binding must inspect that text before deciding whether a Source-local label
    is in Objective scope.
    """

    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-preheating-locator-only",
            "material_scope": ["316L stainless steel"],
            "variables": ["build platform preheating"],
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
    result_text = (
        "Comparing the microstructure obtained for P150 with NP condition, "
        "the cellular structure is seen in the former condition."
    )
    methods_text = (
        "Specimens fabricated without preheating the build platform and with "
        "preheating the build platform to 150 C were designated NP and P150."
    )
    draft = SourceObservation.from_mapping(
        {
            "evidence_id": "source-specific-axis-locator-only",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "preheating temperature",
                    "baseline_value": "NP",
                    "target_value": 150,
                    "unit": "C",
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
                "result_text": result_text,
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "material": [
                    {"name": "material", "value": "316L stainless steel"}
                ]
            },
            "resolution_status": "resolved",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-1",
                    "supports": ["comparison.labels", "reported_result"],
                },
                {
                    "source_kind": "text_window",
                    "source_ref": "methods-1",
                    "supports": ["changed_variables", "comparison.axis_names"],
                },
            ],
            "confidence": 0.9,
        }
    )

    records = _analysis_evidence_records(
        collection_id=objective.collection_id,
        analysis=analysis,
        objective=objective,
        drafts=(draft,),
        blocks_by_document_id={
            "paper-1": [
                SimpleNamespace(
                    block_id="results-1",
                    text=result_text,
                    page=6,
                    heading_path="Results",
                ),
                SimpleNamespace(
                    block_id="methods-1",
                    text=methods_text,
                    page=3,
                    heading_path="Methods",
                ),
            ]
        },
        tables_by_document_id={},
        figures_by_document_id={},
    )

    assert len(records) == 1
    assert records[0].changed_variables[0].name == "build platform preheating"
    assert records[0].comparison is not None
    assert records[0].comparison.axis_names == ("build platform preheating",)


def test_locator_only_source_axis_binding_is_domain_agnostic() -> None:
    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-catalyst-loading",
            "variables": ["catalyst loading"],
            "outcomes": ["conversion"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-catalysis",
                preparation_fingerprint="fingerprint-paper-catalysis",
            ),
        ),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    result_text = "Conversion was higher for C2 than for C1."
    methods_text = (
        "Runs C1 and C2 used catalyst loading values of 1 wt% and 2 wt%, "
        "respectively."
    )
    draft = SourceObservation.from_mapping(
        {
            "evidence_id": "catalyst-loading-result",
            "objective_id": objective.objective_id,
            "document_id": "paper-catalysis",
            "source_kind": "text_window",
            "source_ref": "results-catalysis",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "loading level",
                    "baseline_value": "C1",
                    "target_value": "C2",
                }
            ],
            "comparison": {
                "baseline_label": "C1",
                "target_label": "C2",
                "axis_names": ["loading level"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "conversion",
                "direction": "increase",
                "result_text": result_text,
            },
            "attribution_scope": "isolated_effect",
            "resolution_status": "resolved",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-catalysis",
                    "supports": ["comparison.labels", "reported_result"],
                },
                {
                    "source_kind": "text_window",
                    "source_ref": "methods-catalysis",
                    "supports": ["changed_variables", "comparison.axis_names"],
                },
            ],
            "confidence": 0.9,
        }
    )

    records = _analysis_evidence_records(
        collection_id=objective.collection_id,
        analysis=analysis,
        objective=objective,
        drafts=(draft,),
        blocks_by_document_id={
            "paper-catalysis": [
                SimpleNamespace(
                    block_id="results-catalysis",
                    text=result_text,
                    page=5,
                ),
                SimpleNamespace(
                    block_id="methods-catalysis",
                    text=methods_text,
                    page=2,
                ),
            ]
        },
        tables_by_document_id={},
        figures_by_document_id={},
    )

    assert records[0].changed_variables[0].name == "catalyst loading"
    assert records[0].comparison is not None
    assert records[0].comparison.axis_names == ("catalyst loading",)


def test_locator_only_source_axis_binding_rejects_unrelated_condition() -> None:
    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-catalyst-loading",
            "variables": ["catalyst loading"],
            "outcomes": ["conversion"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=1,
        document_inputs=(
            PreparedDocumentInput(
                document_id="paper-catalysis",
                preparation_fingerprint="fingerprint-paper-catalysis",
            ),
        ),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    result_text = "Conversion was higher for C2 than for C1."
    temperature_text = (
        "Runs C1 and C2 used reaction temperatures of 300 K and 350 K, "
        "respectively."
    )
    draft = SourceObservation.from_mapping(
        {
            "evidence_id": "reaction-temperature-result",
            "objective_id": objective.objective_id,
            "document_id": "paper-catalysis",
            "source_kind": "text_window",
            "source_ref": "results-catalysis",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "reaction temperature",
                    "baseline_value": "C1",
                    "target_value": "C2",
                }
            ],
            "comparison": {
                "baseline_label": "C1",
                "target_label": "C2",
                "axis_names": ["reaction temperature"],
                "comparable": True,
            },
            "reported_result": {
                "outcome": "conversion",
                "direction": "increase",
                "result_text": result_text,
            },
            "attribution_scope": "isolated_effect",
            "resolution_status": "resolved",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-catalysis",
                    "supports": ["comparison.labels", "reported_result"],
                },
                {
                    "source_kind": "text_window",
                    "source_ref": "methods-temperature",
                    "supports": ["changed_variables", "comparison.axis_names"],
                },
            ],
            "confidence": 0.9,
        }
    )

    records = _analysis_evidence_records(
        collection_id=objective.collection_id,
        analysis=analysis,
        objective=objective,
        drafts=(draft,),
        blocks_by_document_id={
            "paper-catalysis": [
                SimpleNamespace(
                    block_id="results-catalysis",
                    text=result_text,
                    page=5,
                ),
                SimpleNamespace(
                    block_id="methods-temperature",
                    text=temperature_text,
                    page=2,
                ),
            ]
        },
        tables_by_document_id={},
        figures_by_document_id={},
    )

    assert records[0].changed_variables[0].name == "reaction temperature"
    assert records[0].comparison is not None
    assert records[0].comparison.axis_names == ("reaction temperature",)
    assert not FindingSynthesisService.evidence_matches_objective_axes(
        objective,
        records[0],
    )


def test_materialization_does_not_resolve_axis_from_vocabulary_alone() -> None:
    """A related label without a source definition remains source-specific."""

    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-preheating",
            "variables": ["build platform preheating"],
            "outcomes": ["microstructure"],
        }
    )
    draft = SourceObservation.from_mapping(
        {
            "evidence_id": "unproven-axis",
            "objective_id": objective.objective_id,
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "source_excerpt": "The microstructure changed at a preheating temperature.",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "preheating temperature",
                    "baseline_value": "low",
                    "target_value": "high",
                }
            ],
            "comparison": {
                "baseline_label": "low",
                "target_label": "high",
                "axis_names": ["preheating temperature"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "microstructure",
                "direction": "mixed",
                "result_text": "The microstructure changed at a preheating temperature.",
            },
            "attribution_scope": "isolated_effect",
            "resolution_status": "resolved",
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-1",
                    "source_excerpt": "The microstructure changed at a preheating temperature.",
                    "supports": ["changed_variables", "comparison.axis_names"],
                }
            ],
            "confidence": 0.9,
        }
    )

    canonical = _canonical_objective_evidence_axes(draft, objective=objective)

    assert canonical.changed_variables[0].name == "preheating temperature"
    assert canonical.comparison is not None
    assert canonical.comparison.axis_names == ("preheating temperature",)


def test_pageless_filename_context_yields_primary_source_to_paged_scientific_text() -> None:
    """A researcher must be sent to the paper passage, not its imported filename."""

    filename = "P005-Influence of porosity on 316L stainless steel.pdf"
    abstract = "This study investigates porosity in SLM 316L stainless steel."
    draft = SourceObservation.from_mapping(
        {
            "evidence_id": "material-context",
            "objective_id": "objective-1",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "title-1",
            "evidence_role": "condition_context",
            "selection_status": "extracted",
            "scientific_context": {
                "material": [{"name": "material", "value": "316L stainless steel"}]
            },
            "source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "title-1",
                    "supports": ["scientific_context.material"],
                },
                {
                    "source_kind": "text_window",
                    "source_ref": "abstract-1",
                    "page": 1,
                    "heading_path": "Abstract",
                    "supports": ["scientific_context.material"],
                },
            ],
            "confidence": 0.9,
        }
    )

    source = _canonical_evidence_source(
        draft,
        blocks_by_document_id={
            "paper-1": [
                SimpleNamespace(block_id="title-1", text=filename, page=None),
                SimpleNamespace(block_id="abstract-1", text=abstract, page=1),
            ]
        },
        tables_by_document_id={},
        figures_by_document_id={},
    )

    assert source is not None
    assert source["source_ref"] == "abstract-1"
    assert source["source_excerpt"] == abstract
    assert source["page_numbers"] == (1,)
    assert {item["source_ref"] for item in source["related_source_refs"]} == {
        "title-1",
        "abstract-1",
    }


def test_table_evidence_excerpt_stays_bound_to_its_primary_table() -> None:
    """Related tables provide lineage without contaminating the result Source."""

    result_table = SourceTable(
        table_id="result-table",
        document_id="paper-1",
        table_order=2,
        caption_text="Yield strength by specimen.",
        caption_block_id=None,
        page=5,
        heading_path="Results",
        column_headers=("Specimen", "Yield strength (MPa)"),
        table_matrix=(
            ("Specimen", "Yield strength (MPa)"),
            ("A", "300"),
            ("B", "340"),
        ),
    )
    process_table = SourceTable(
        table_id="process-table",
        document_id="paper-1",
        table_order=1,
        caption_text="Process parameters by specimen.",
        caption_block_id=None,
        page=4,
        heading_path="Methods",
        column_headers=("Specimen", "Scan speed (mm/s)"),
        table_matrix=(
            ("Specimen", "Scan speed (mm/s)"),
            ("A", "700"),
            ("B", "800"),
        ),
    )
    draft = SourceObservation.from_mapping(
        {
            "evidence_id": "yield-strength-result",
            "objective_id": "objective-1",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "result-table",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "reported_result": {
                "outcome": "yield strength",
                "direction": "increase",
                "result_text": "Yield strength increased from 300 to 340 MPa.",
            },
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "result-table",
                    "page": 5,
                    "row_index": 1,
                    "source_excerpt": "Specimen: A | Yield strength (MPa): 300",
                },
                {
                    "source_kind": "table",
                    "source_ref": "result-table",
                    "page": 5,
                    "row_index": 2,
                    "source_excerpt": "Specimen: B | Yield strength (MPa): 340",
                },
                {
                    "source_kind": "table",
                    "source_ref": "process-table",
                    "page": 4,
                    "row_index": 1,
                    "source_excerpt": "Specimen: A | Scan speed (mm/s): 700",
                    "supports": ["changed_variables"],
                },
                {
                    "source_kind": "table",
                    "source_ref": "process-table",
                    "page": 4,
                    "row_index": 2,
                    "source_excerpt": "Specimen: B | Scan speed (mm/s): 800",
                    "supports": ["changed_variables"],
                },
            ],
            "confidence": 0.9,
        }
    )

    source = _canonical_evidence_source(
        draft,
        blocks_by_document_id={},
        tables_by_document_id={"paper-1": [result_table, process_table]},
        figures_by_document_id={},
    )

    assert source is not None
    assert source["source_ref"] == "result-table"
    assert source["source_excerpt"] == (
        "Specimen: A | Yield strength (MPa): 300\n"
        "Specimen: B | Yield strength (MPa): 340"
    )
    assert "Scan speed" not in source["source_excerpt"]
    assert {item["source_ref"] for item in source["related_source_refs"]} == {
        "result-table",
        "process-table",
    }


def test_table_result_excerpt_excludes_same_table_context_rows() -> None:
    """A scalar result cites its row, not every context row from the table."""

    result_table = SourceTable(
        table_id="result-table",
        document_id="paper-1",
        table_order=1,
        caption_text="Yield strength by specimen.",
        caption_block_id=None,
        page=5,
        heading_path="Results",
        column_headers=("Specimen", "Yield strength (MPa)"),
        table_matrix=(
            ("Specimen", "Yield strength (MPa)"),
            ("A", "300"),
            ("B", "340"),
        ),
    )
    result_excerpt = "Specimen: A | Yield strength (MPa): 300"
    context_excerpt = "Specimen: B | Yield strength (MPa): 340"
    draft = SourceObservation.from_mapping(
        {
            "evidence_id": "yield-strength-result",
            "objective_id": "objective-1",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "result-table",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "reported_result": {
                "outcome": "yield strength",
                "value": 300,
                "unit": "MPa",
                "direction": "unknown",
                "result_text": "Yield strength was 300 MPa.",
            },
            "source_refs": [
                {
                    "source_kind": "table",
                    "source_ref": "result-table",
                    "page": 5,
                    "row_index": 1,
                    "col_index": 1,
                    "source_excerpt": result_excerpt,
                },
                {
                    "source_kind": "table",
                    "source_ref": "result-table",
                    "page": 5,
                    "row_index": 2,
                    "source_excerpt": context_excerpt,
                    "supports": ["scientific_context.process"],
                },
            ],
            "confidence": 0.9,
        }
    )

    source = _canonical_evidence_source(
        draft,
        blocks_by_document_id={},
        tables_by_document_id={"paper-1": [result_table]},
        figures_by_document_id={},
    )

    assert source is not None
    assert source["source_excerpt"] == result_excerpt
    assert context_excerpt not in source["source_excerpt"]


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
    packet_audit = _researcher_decision_packet_audit((result, context, failed))
    assert ledger["decision_packet_sha256"] == packet_audit["decision_packet_sha256"]
    assert len(ledger["decision_packet_sha256"]) == 64
    assert ledger["decision_packet_evidence_ids"] == [
        "evidence-result",
        "evidence-context",
        "evidence-failed",
    ]
    assert ledger["decision_packet_source_refs"] == [
        {
            "source_kind": "text_window",
            "source_ref": "result-1",
        },
        {
            "source_kind": "text_window",
            "source_ref": "methods-1",
        },
        {
            "source_kind": "text_window",
            "source_ref": "failed-1",
        },
    ]
    changed_result = ObjectiveEvidence.from_mapping(
        {
            **result.to_record(),
            "source_excerpt": "Strength did not change.",
        }
    )
    assert _researcher_decision_packet_audit((changed_result, context, failed))[
        "decision_packet_sha256"
    ] != ledger["decision_packet_sha256"]


def test_researcher_information_parity_snapshot_exposes_context_and_disposition() -> None:
    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "question": "How does temperature affect strength?",
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

    with capture_analysis_diagnostics() as diagnostics:
        _record_researcher_information_parity_snapshot(
            collection_id=objective.collection_id,
            analysis=analysis,
            objective=objective,
            ledger_records=(
                {
                    "document_id": "paper-1",
                    "paper_role": "primary_experiment",
                    "candidate_source_refs": [
                        {"source_kind": "text_window", "source_ref": "result-1"},
                        {"source_kind": "text_window", "source_ref": "methods-1"},
                    ],
                    "inspected_source_refs": [
                        {"source_kind": "text_window", "source_ref": "result-1"}
                    ],
                    "uninspected_source_refs": [
                        {"source_kind": "text_window", "source_ref": "methods-1"}
                    ],
                    "missing_field_families": ["process", "test"],
                    "technical_failure_details": [],
                    "result_count": 1,
                    "closed_result_count": 0,
                    "closure_complete": False,
                    "coverage_complete": False,
                    "technical_failure_count": 0,
                    "decision_packet_sha256": "a" * 64,
                    "decision_packet_evidence_count": 1,
                    "decision_packet_evidence_ids": ["evidence-result"],
                    "decision_packet_evidence_ids_truncated": False,
                    "decision_packet_source_count": 1,
                    "decision_packet_source_refs": [
                        {"source_kind": "text_window", "source_ref": "result-1"}
                    ],
                    "decision_packet_source_refs_truncated": False,
                },
            ),
        )

    assert diagnostics.records == (
        {
            "trace_type": "researcher_information_parity",
            "collection_id": "collection-1",
            "objective_id": "objective-1",
            "analysis_version": 1,
            "objective": "How does temperature affect strength?",
            "papers": [
                {
                    "document_id": "paper-1",
                    "paper_role": "primary_experiment",
                    "visible_source_refs": [
                        {"source_kind": "text_window", "source_ref": "result-1"},
                        {"source_kind": "text_window", "source_ref": "methods-1"},
                    ],
                    "inspected_source_refs": [
                        {"source_kind": "text_window", "source_ref": "result-1"}
                    ],
                    "uninspected_candidate_refs": [
                        {"source_kind": "text_window", "source_ref": "methods-1"}
                    ],
                    "field_coverage": {
                        "material": True,
                        "variables": True,
                        "comparison": True,
                        "outcome": True,
                        "process": False,
                        "sample": True,
                        "test": False,
                    },
                    "missing_field_families": ["process", "test"],
                    "technical_failures": [],
                    "result_count": 1,
                    "closed_result_count": 0,
                    "closure_complete": False,
                    "final_disposition": "needs_context",
                    "decision_packet_sha256": "a" * 64,
                    "decision_packet_evidence_count": 1,
                    "decision_packet_evidence_ids": ["evidence-result"],
                    "decision_packet_evidence_ids_truncated": False,
                    "decision_packet_source_count": 1,
                    "decision_packet_source_refs": [
                        {"source_kind": "text_window", "source_ref": "result-1"}
                    ],
                    "decision_packet_source_refs_truncated": False,
                }
            ],
            "paper_count": 1,
            "final_disposition": "needs_context",
            "scientific_conclusion_allowed": False,
            "technical_failure_count": 0,
        },
    )


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
    draft = SourceObservation.from_mapping(
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
        observations=(draft,),
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
    draft = SourceObservation.from_mapping(
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
    draft = SourceObservation.from_mapping(
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
    draft = SourceObservation.from_mapping(
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
            observations=(),
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
            "experiment_count": 0,
            "bound_experiment_count": 0,
            "measurement_count": 0,
            "comparison_assessment_counts": {},
            "grounding_rejection_count": 0,
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
    draft = SourceObservation.from_mapping(
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
            observations=(draft,),
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
        "experiment_count": 0,
        "bound_experiment_count": 0,
        "measurement_count": 0,
        "comparison_assessment_counts": {},
        "grounding_rejection_count": 0,
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
    draft = SourceObservation.from_mapping(
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
            "scientific_context": {
                "process": [{"name": "process", "value": "LPBF"}],
                "test": [{"name": "method", "value": "metallography"}],
            },
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


def test_rebind_persisted_evidence_rechecks_source_defined_axis() -> None:
    """A reused checkpoint must not bypass current Source-backed binding."""

    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-preheating",
            "variables": ["build platform preheating"],
            "outcomes": ["microstructure"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=2,
        document_inputs=(
            PreparedDocumentInput("paper-1", "fingerprint-paper-1"),
        ),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    result_text = (
        "The cellular structure was observed for P150 compared with NP."
    )
    methods_text = (
        "Specimens without build platform preheating (NP) and with build "
        "platform preheating to 150 C (P150) were compared."
    )
    checkpoint_evidence = ObjectiveEvidence.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "evidence_id": "cached-preheating-result",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "source_excerpt": result_text,
            "related_source_refs": [
                {
                    "source_kind": "text_window",
                    "source_ref": "results-1",
                    "supports": ["comparison.labels", "reported_result"],
                },
                {
                    "source_kind": "text_window",
                    "source_ref": "methods-1",
                    "supports": ["changed_variables", "comparison.axis_names"],
                },
            ],
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "preheating temperature",
                    "baseline_value": "NP",
                    "target_value": 150,
                    "unit": "C",
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
                "result_text": result_text,
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "process": [{"name": "process", "value": "LPBF"}],
                "test": [{"name": "method", "value": "metallography"}],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )

    rebound = rebind_persisted_evidence(
        collection_id=objective.collection_id,
        analysis=analysis,
        objective=objective,
        evidence_records=(checkpoint_evidence,),
        blocks_by_document_id={
            "paper-1": [
                SimpleNamespace(block_id="results-1", text=result_text, page=6),
                SimpleNamespace(block_id="methods-1", text=methods_text, page=3),
            ]
        },
        tables_by_document_id={},
        figures_by_document_id={},
    )

    assert len(rebound) == 1
    assert rebound[0].analysis_version == 2
    assert [item.name for item in rebound[0].changed_variables] == [
        "build platform preheating"
    ]
    assert rebound[0].comparison is not None
    assert rebound[0].comparison.axis_names == ("build platform preheating",)
    assert rebound[0].source_ref == "results-1"


def test_rebind_persisted_contribution_recomputes_axis_dependent_accounting() -> None:
    """A reused paper contribution must agree with rebound Evidence."""

    objective = research_objective(
        {
            "collection_id": "collection-1",
            "objective_id": "objective-preheating",
            "variables": ["build platform preheating"],
            "outcomes": ["microstructure"],
        }
    )
    analysis = ObjectiveAnalysis(
        collection_id=objective.collection_id,
        objective_id=objective.objective_id,
        analysis_version=2,
        document_inputs=(
            PreparedDocumentInput("paper-1", "fingerprint-paper-1"),
        ),
        total_document_count=1,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    evidence = ObjectiveEvidence.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": 2,
            "evidence_id": "rebound-result",
            "document_id": "paper-1",
            "source_kind": "text_window",
            "source_ref": "results-1",
            "source_excerpt": "Microstructure changed from NP to P150.",
            "evidence_role": "direct_result",
            "selection_status": "extracted",
            "changed_variables": [
                {
                    "name": "build platform preheating",
                    "baseline_value": "NP",
                    "target_value": 150,
                    "unit": "C",
                }
            ],
            "comparison": {
                "baseline_label": "NP",
                "target_label": "P150",
                "axis_names": ["build platform preheating"],
                "comparable": True,
                "incomparability_reasons": [],
            },
            "reported_result": {
                "outcome": "microstructure",
                "direction": "mixed",
                "result_kind": "observed",
                "result_text": "Microstructure changed from NP to P150.",
            },
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "process": [{"name": "process", "value": "LPBF"}],
                "test": [{"name": "method", "value": "metallography"}],
            },
            "resolution_status": "resolved",
            "confidence": 0.9,
        }
    )
    stale_contribution = PaperContribution.from_mapping(
        {
            "collection_id": objective.collection_id,
            "objective_id": objective.objective_id,
            "analysis_version": 1,
            "document_id": "paper-1",
            "analysis_status": "analyzed",
            "relevance": "high",
            "paper_role": "primary_experiment",
            "contribution_summary": "Microstructure changed from NP to P150.",
            "material_match": [],
            "changed_variables": ["preheating temperature"],
            "measured_property_scope": ["microstructure"],
            "test_environment_scope": [],
            "warnings": [],
            "confidence": 0.9,
            "evidence_disposition": "no_comparable_evidence",
            "routed_source_count": 1,
            "extracted_source_count": 1,
            "comparable_evidence_count": 0,
            "failed_source_count": 0,
            "evidence_disposition_reason": (
                "Selected sources produced no comparable direct result for this Objective."
            ),
            "evidence_status_counts": {"descriptive": 1},
        }
    )

    rebound = rebind_persisted_contribution(
        contribution=stale_contribution,
        analysis=analysis,
        objective=objective,
        evidence_records=(evidence,),
    )

    assert rebound.analysis_version == 2
    assert rebound.evidence_disposition == "comparable_evidence"
    assert rebound.comparable_evidence_count == 1
    assert rebound.evidence_disposition_reason is None
    assert rebound.evidence_status_counts == (("comparable", 1),)
