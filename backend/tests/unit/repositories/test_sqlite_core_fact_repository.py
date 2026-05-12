from __future__ import annotations

from domain.core import (
    BaselineReference,
    CharacterizationObservation,
    CollectionComparableResult,
    ComparableResult,
    ComparisonRowRecord,
    CoreFactSet,
    DocumentProfile,
    EvidenceAnchor,
    MeasurementResult,
    MethodFact,
    ObjectiveContext,
    PaperSkim,
    ResearchObjective,
    SampleVariant,
    StructureFeature,
    TestCondition as CoreTestCondition,
)
from infra.persistence.sqlite import SqliteCoreFactRepository


def test_sqlite_core_fact_repository_round_trips_core_fact_set(tmp_path):
    repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    facts = CoreFactSet(
        document_profiles=(
            DocumentProfile(
                document_id="doc-1",
                collection_id="col_test",
                title="LPBF 316L",
                source_filename="paper.pdf",
                doc_type="experimental",
                parsing_warnings=("table fragmented",),
                confidence=0.88,
            ),
        ),
        evidence_anchors=(
            EvidenceAnchor(
                anchor_id="anc-1",
                document_id="doc-1",
                locator_type="table",
                locator_confidence="high",
                source_type="table",
                section_id="results",
                char_range={"start": 10, "end": 24},
                bbox={"x0": 1.0, "y0": 2.0, "x1": 3.0, "y1": 4.0},
                page=3,
                quote="YS 620 MPa",
                deep_link=None,
                block_id="blk-1",
                snippet_id=None,
                figure_or_table="tbl-1",
                quote_span="YS 620 MPa",
            ),
        ),
        method_facts=(
            MethodFact(
                method_id="met-1",
                document_id="doc-1",
                collection_id="col_test",
                domain_profile="core_neutral",
                method_role="process",
                method_name="LPBF",
                method_payload={"process": "LPBF"},
                evidence_anchor_ids=("anc-1",),
                confidence=0.91,
                epistemic_status="directly_observed",
            ),
        ),
        sample_variants=(
            SampleVariant(
                variant_id="var-1",
                document_id="doc-1",
                collection_id="col_test",
                domain_profile="core_neutral",
                variant_label="HT-SLM",
                host_material_system={"family": "316L stainless steel"},
                composition=None,
                variable_axis_type="heat_treatment",
                variable_value="HT",
                process_context={"temperature_c": 1050},
                profile_payload={"source_kind": "table_row"},
                structure_feature_ids=("feat-1",),
                source_anchor_ids=("anc-1",),
                confidence=0.9,
                epistemic_status="normalized_from_evidence",
            ),
        ),
        test_conditions=(
            CoreTestCondition(
                test_condition_id="tc-1",
                document_id="doc-1",
                collection_id="col_test",
                domain_profile="core_neutral",
                property_type="yield_strength",
                template_type="mechanical",
                scope_level="variant",
                condition_payload={"temperature_c": 25},
                condition_completeness="complete",
                missing_fields=(),
                evidence_anchor_ids=("anc-1",),
                confidence=0.82,
                epistemic_status="directly_observed",
            ),
        ),
        baseline_references=(
            BaselineReference(
                baseline_id="base-1",
                document_id="doc-1",
                collection_id="col_test",
                domain_profile="core_neutral",
                variant_id="var-1",
                baseline_type="control",
                baseline_label="as-built",
                baseline_scope="document",
                evidence_anchor_ids=("anc-1",),
                confidence=0.8,
                epistemic_status="directly_observed",
            ),
        ),
        measurement_results=(
            MeasurementResult(
                result_id="res-1",
                document_id="doc-1",
                collection_id="col_test",
                domain_profile="core_neutral",
                variant_id="var-1",
                property_normalized="yield_strength",
                result_type="scalar",
                claim_scope="current_work",
                value_payload={"numeric_value": 620},
                unit="MPa",
                test_condition_id="tc-1",
                baseline_id="base-1",
                structure_feature_ids=("feat-1",),
                characterization_observation_ids=("obs-1",),
                evidence_anchor_ids=("anc-1",),
                traceability_status="direct",
                result_source_type="table",
                epistemic_status="directly_observed",
            ),
        ),
        characterization_observations=(
            CharacterizationObservation(
                observation_id="obs-1",
                document_id="doc-1",
                collection_id="col_test",
                variant_id="var-1",
                characterization_type="microstructure",
                observation_text="cellular structure",
                observed_value={"descriptor": "cellular"},
                observed_unit=None,
                condition_context={"method": "SEM"},
                evidence_anchor_ids=("anc-1",),
                confidence=0.7,
                epistemic_status="directly_observed",
            ),
        ),
        structure_features=(
            StructureFeature(
                feature_id="feat-1",
                document_id="doc-1",
                collection_id="col_test",
                variant_id="var-1",
                feature_type="grain_size",
                feature_value=12,
                feature_unit="um",
                qualitative_descriptor=None,
                source_observation_ids=("obs-1",),
                confidence=0.7,
                epistemic_status="normalized_from_evidence",
            ),
        ),
        comparable_results=(_comparable_result(),),
        collection_comparable_results=(_collection_comparable_result(),),
        comparison_rows=(_comparison_row(),),
    )

    repository.replace_collection_facts("col_test", facts)
    restored = repository.read_collection_facts("col_test")

    assert restored.paper_facts_ready is True
    assert restored.comparison_artifacts_ready is True
    assert restored.document_profiles[0].parsing_warnings == ("table fragmented",)
    assert restored.evidence_anchors[0].bbox == {
        "x0": 1.0,
        "y0": 2.0,
        "x1": 3.0,
        "y1": 4.0,
    }
    assert restored.method_facts[0].method_payload == {"process": "LPBF"}
    assert restored.sample_variants[0].host_material_system["family"] == (
        "316L stainless steel"
    )
    assert restored.measurement_results[0].value_payload["numeric_value"] == 620
    assert restored.characterization_observations[0].observed_value == {
        "descriptor": "cellular"
    }
    assert restored.structure_features[0].source_observation_ids == ("obs-1",)
    assert restored.comparable_results[0].value.numeric_value == 620.0
    assert restored.collection_comparable_results[0].included is True
    assert restored.comparison_rows[0].supporting_anchor_ids == ("anc-1",)

    repository.replace_collection_comparison_artifacts(
        "col_test",
        (_comparable_result(value=640),),
        (_collection_comparable_result(sort_order=2),),
        (_comparison_row(value=640),),
    )
    refreshed = repository.read_collection_facts("col_test")

    assert refreshed.paper_facts_ready is True
    assert refreshed.comparison_artifacts_ready is True
    assert refreshed.document_profiles[0].document_id == "doc-1"
    assert refreshed.comparable_results[0].value.numeric_value == 640.0
    assert refreshed.collection_comparable_results[0].sort_order == 2
    assert refreshed.comparison_rows[0].value == 640.0

    repository.replace_collection_comparison_artifacts("col_empty", (), (), ())
    empty_comparison = repository.read_collection_facts("col_empty")

    assert empty_comparison.paper_facts_ready is False
    assert empty_comparison.comparison_artifacts_ready is True
    assert empty_comparison.comparison_rows == ()


def test_sqlite_core_fact_repository_round_trips_research_objectives(tmp_path):
    repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "title": "LPBF 316L corrosion study",
            "source_filename": "paper.pdf",
            "doc_role": "experimental",
            "candidate_materials": ["316L stainless steel"],
            "candidate_processes": ["LPBF", "heat treatment"],
            "candidate_properties": ["corrosion"],
            "changed_variables": ["heat treatment temperature"],
            "possible_objectives": [
                "How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?"
            ],
            "evidence_density": "high",
            "confidence": 0.91,
            "warnings": [],
        }
    )
    objective = ResearchObjective.from_mapping(
        {
            "question": "How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?",
            "material_scope": ["316L stainless steel"],
            "process_axes": ["LPBF", "heat treatment"],
            "property_axes": ["corrosion"],
            "comparison_intent": "compare as-built and heat-treated corrosion behavior",
            "seed_document_ids": ["paper-1"],
            "excluded_document_ids": [],
            "confidence": 0.88,
            "reason": "paper skim points to a repeated comparison axis",
        }
    )
    objective_context = ObjectiveContext.from_mapping(
        {
            "objective_id": objective.objective_id,
            "question": objective.question,
            "material_scope": ["316L stainless steel"],
            "variable_process_axes": ["heat treatment"],
            "process_context_axes": ["LPBF"],
            "target_property_axes": ["corrosion"],
            "excluded_property_axes": [],
            "routing_hints": [
                {
                    "table_id": "table-1",
                    "role": "result_table",
                    "matched_property_axes": ["corrosion"],
                }
            ],
            "extraction_guidance": {
                "do_not_treat_as_variables": ["LPBF"],
                "do_not_treat_as_result_properties": ["heat treatment"],
            },
            "confidence": 0.88,
        }
    )

    repository.replace_collection_research_objectives(
        "col_test",
        (paper_skim,),
        (objective,),
        (objective_context,),
    )
    restored = repository.read_collection_facts("col_test")

    assert restored.research_objectives_ready is True
    assert restored.paper_facts_ready is False
    assert restored.paper_skims[0].candidate_materials == ("316L stainless steel",)
    assert restored.research_objectives[0].objective_id.startswith("obj_")
    assert restored.research_objectives[0].seed_document_ids == ("paper-1",)
    assert restored.objective_contexts[0].objective_id == objective.objective_id
    assert restored.objective_contexts[0].routing_hints[0]["table_id"] == "table-1"


def test_sqlite_core_fact_repository_preserves_research_objectives_when_replacing_facts(
    tmp_path,
):
    repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")
    paper_skim = PaperSkim.from_mapping(
        {
            "document_id": "paper-1",
            "doc_role": "experimental",
            "candidate_materials": ["316L stainless steel"],
            "possible_objectives": [
                "How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?"
            ],
        }
    )
    objective = ResearchObjective.from_mapping(
        {
            "question": "How does heat treatment affect corrosion resistance of LPBF 316L stainless steel?",
            "material_scope": ["316L stainless steel"],
        }
    )
    repository.replace_collection_research_objectives(
        "col_test",
        (paper_skim,),
        (objective,),
        (
            ObjectiveContext.from_mapping(
                {
                    "objective_id": objective.objective_id,
                    "question": objective.question,
                    "material_scope": ["316L stainless steel"],
                }
            ),
        ),
    )

    repository.replace_collection_facts(
        "col_test",
        CoreFactSet(
            document_profiles=(
                DocumentProfile(
                    document_id="doc-1",
                    collection_id="col_test",
                    title="LPBF 316L",
                    source_filename="paper.pdf",
                    doc_type="experimental",
                    parsing_warnings=(),
                    confidence=0.88,
                ),
            ),
        ),
    )
    restored = repository.read_collection_facts("col_test")

    assert restored.research_objectives_ready is True
    assert restored.paper_facts_ready is True
    assert restored.paper_skims[0].document_id == "paper-1"
    assert restored.research_objectives[0].material_scope == ("316L stainless steel",)
    assert restored.objective_contexts[0].objective_id == objective.objective_id
    assert restored.document_profiles[0].document_id == "doc-1"


def _comparable_result(value: int = 620) -> ComparableResult:
    return ComparableResult.from_mapping(
        {
            "comparable_result_id": "cres-1",
            "source_result_id": "res-1",
            "source_document_id": "doc-1",
            "binding": {
                "variant_id": "var-1",
                "baseline_id": "base-1",
                "test_condition_id": "tc-1",
            },
            "normalized_context": {
                "material_system_normalized": "316L stainless steel",
                "process_normalized": "LPBF",
                "baseline_normalized": "as-built",
                "test_condition_normalized": "room temperature tensile",
            },
            "axis": {
                "axis_name": "heat_treatment",
                "axis_value": "HT",
                "axis_unit": None,
            },
            "value": {
                "property_normalized": "yield_strength",
                "result_type": "scalar",
                "numeric_value": value,
                "unit": "MPa",
                "summary": f"{value} MPa",
            },
            "evidence": {
                "direct_anchor_ids": ["anc-1"],
                "contextual_anchor_ids": [],
                "evidence_ids": ["evi-1"],
                "structure_feature_ids": ["feat-1"],
                "characterization_observation_ids": ["obs-1"],
                "traceability_status": "direct",
            },
            "variant_label": "HT-SLM",
            "baseline_reference": "as-built",
            "result_source_type": "table",
            "epistemic_status": "normalized_from_evidence",
            "normalization_version": "comparable_result_v1",
        }
    )


def _collection_comparable_result(sort_order: int = 1) -> CollectionComparableResult:
    return CollectionComparableResult.from_mapping(
        {
            "collection_id": "col_test",
            "comparable_result_id": "cres-1",
            "assessment": {
                "missing_critical_context": [],
                "comparability_basis": ["direct_traceability"],
                "comparability_warnings": [],
                "comparability_status": "comparable",
                "requires_expert_review": False,
                "assessment_epistemic_status": "normalized_from_evidence",
            },
            "epistemic_status": "normalized_from_evidence",
            "included": True,
            "sort_order": sort_order,
            "policy_family": "default_collection_comparison_policy",
            "policy_version": "comparison_policy_v1",
            "comparable_result_normalization_version": "comparable_result_v1",
            "assessment_input_fingerprint": "fp-1",
            "reassessment_triggers": ["assessment_input_changed"],
        }
    )


def _comparison_row(value: int = 620) -> ComparisonRowRecord:
    return ComparisonRowRecord.from_mapping(
        {
            "row_id": "row-1",
            "collection_id": "col_test",
            "comparable_result_id": "cres-1",
            "source_document_id": "doc-1",
            "variant_id": "var-1",
            "variant_label": "HT-SLM",
            "variable_axis": "heat_treatment",
            "variable_value": "HT",
            "baseline_reference": "as-built",
            "result_source_type": "table",
            "result_type": "scalar",
            "result_summary": f"{value} MPa",
            "supporting_evidence_ids": ["evi-1"],
            "supporting_anchor_ids": ["anc-1"],
            "characterization_observation_ids": ["obs-1"],
            "structure_feature_ids": ["feat-1"],
            "material_system_normalized": "316L stainless steel",
            "process_normalized": "LPBF",
            "property_normalized": "yield_strength",
            "baseline_normalized": "as-built",
            "test_condition_normalized": "room temperature tensile",
            "comparability_status": "comparable",
            "comparability_warnings": [],
            "comparability_basis": ["direct_traceability"],
            "requires_expert_review": False,
            "assessment_epistemic_status": "normalized_from_evidence",
            "missing_critical_context": [],
            "value": value,
            "unit": "MPa",
        }
    )
