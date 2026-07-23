from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from application.core.comparison_service import ComparisonService
from application.core.semantic_build.document_profile_service import (
    DocumentProfileService,
)
from infra.persistence.sqlite import SqliteSourceArtifactRepository
from tests.support.collection_service import build_test_collection_service
from tests.support.paper_fact_repository import MemoryPaperFactRepository
from tests.support.objective_repository import MemoryObjectiveRepository
from controllers.core import results as results_controller
from domain.core import (
    BaselineReference,
    CharacterizationObservation,
    CollectionComparableResult,
    ComparableResult,
    ComparisonFactSet,
    DocumentProfile,
    MeasurementResult,
    SampleVariant,
    StructureFeature,
    TestCondition as CoreTestCondition,
)
from domain.core.paper_fact import PaperFactSet
from domain.core.comparison import (
    build_collection_assessment_input_fingerprint,
)
from tests.support.pbf_acceptance_fixture import (
    PBF_BASELINE_LABEL,
    PBF_DOCUMENT_ID,
    PBF_S3_VARIANT_ID,
    PBF_YIELD_25_COMPARABLE_ID,
    PBF_YIELD_SERIES_KEY,
    pbf_acceptance_baseline_references,
    pbf_acceptance_characterization_observations,
    pbf_acceptance_comparison_records,
    pbf_acceptance_measurement_results,
    pbf_acceptance_sample_variants,
    pbf_acceptance_structure_features,
    pbf_acceptance_test_conditions,
)
from tests.support.comparison_repository import MemoryComparisonRepository


def _build_semantic_result_record(
    *,
    collection_id: str,
    comparable_result_id: str,
    source_document_id: str,
    property_normalized: str = "flexural_strength",
    numeric_value: float = 97.0,
    unit: str = "MPa",
    traceability_status: str = "direct",
    comparability_status: str = "comparable",
    sort_order: int = 0,
) -> tuple[dict, dict]:
    comparable_result = {
        "comparable_result_id": comparable_result_id,
        "source_result_id": f"res-{comparable_result_id}",
        "source_document_id": source_document_id,
        "binding": {
            "variant_id": "var-1",
            "baseline_id": "base-1",
            "test_condition_id": "tc-1",
        },
        "normalized_context": {
            "material_system_normalized": "epoxy composite",
            "process_normalized": "80 C, 2 h, under Ar",
            "baseline_normalized": "untreated baseline",
            "test_condition_normalized": "SEM",
        },
        "axis": {
            "axis_name": None,
            "axis_value": None,
            "axis_unit": None,
        },
        "value": {
            "property_normalized": property_normalized,
            "result_type": "scalar",
            "numeric_value": numeric_value,
            "unit": unit,
            "summary": "Flexural strength increased to 97 MPa.",
            "statistic_type": None,
            "uncertainty": None,
        },
        "evidence": {
            "direct_anchor_ids": ["anchor-1"],
            "contextual_anchor_ids": ["anchor-2"],
            "evidence_ids": ["ev-1"],
            "structure_feature_ids": [],
            "characterization_observation_ids": [],
            "traceability_status": traceability_status,
        },
        "variant_label": "Sample A",
        "baseline_reference": "untreated baseline",
        "result_source_type": "text",
        "epistemic_status": "normalized_from_evidence",
        "normalization_version": "comparable_result_v1",
    }
    comparable_record = ComparableResult.from_mapping(comparable_result)
    scoped_result = {
        "collection_id": collection_id,
        "comparable_result_id": comparable_result_id,
        "assessment": {
            "missing_critical_context": [],
            "comparability_basis": [
                "variant_linked",
                "baseline_resolved",
                "test_condition_resolved",
                "direct_traceability",
                "numeric_value_available",
                "result_type:scalar",
            ],
            "comparability_warnings": [],
            "comparability_status": comparability_status,
            "requires_expert_review": False,
            "assessment_epistemic_status": "normalized_from_evidence",
        },
        "epistemic_status": "normalized_from_evidence",
        "included": True,
        "sort_order": sort_order,
        "policy_family": "default_collection_comparison_policy",
        "policy_version": "comparison_policy_v1",
        "comparable_result_normalization_version": "comparable_result_v1",
        "assessment_input_fingerprint": build_collection_assessment_input_fingerprint(
            comparable_record
        ),
        "reassessment_triggers": [
            "policy_family_changed",
            "policy_version_changed",
            "comparable_result_normalization_version_changed",
            "assessment_input_fingerprint_changed",
        ],
    }
    return comparable_result, scoped_result


def _store_core_result_facts(
    comparison_service: ComparisonService,
    collection_id: str,
    *,
    document_profiles: list[dict] | None = None,
    comparable_results: list[dict] | None = None,
    scoped_results: list[dict] | None = None,
    sample_variants: list[dict] | None = None,
    test_conditions: list[dict] | None = None,
    baseline_references: list[dict] | None = None,
    measurement_results: list[dict] | None = None,
    characterization_observations: list[dict] | None = None,
    structure_features: list[dict] | None = None,
) -> None:
    comparison_service.paper_fact_repository.replace_document_profiles(
        collection_id,
        "build_test",
        tuple(DocumentProfile.from_mapping(row) for row in (document_profiles or [])),
    )
    comparison_service.paper_fact_repository.replace_paper_facts(
        collection_id,
        "build_test",
        PaperFactSet(
            paper_facts_ready=True,
            sample_variants=tuple(
                SampleVariant.from_mapping(row) for row in (sample_variants or [])
            ),
            test_conditions=tuple(
                CoreTestCondition.from_mapping(row) for row in (test_conditions or [])
            ),
            baseline_references=tuple(
                BaselineReference.from_mapping(row)
                for row in (baseline_references or [])
            ),
            measurement_results=tuple(
                MeasurementResult.from_mapping(row)
                for row in (measurement_results or [])
            ),
            characterization_observations=tuple(
                CharacterizationObservation.from_mapping(row)
                for row in (characterization_observations or [])
            ),
            structure_features=tuple(
                StructureFeature.from_mapping(row) for row in (structure_features or [])
            ),
        ),
    )
    comparison_service.comparison_repository.replace(
        collection_id,
        "build_test",
        ComparisonFactSet(
            comparison_artifacts_ready=True,
            comparable_results=tuple(
                ComparableResult.from_mapping(row) for row in (comparable_results or [])
            ),
            collection_comparable_results=tuple(
                CollectionComparableResult.from_mapping(row)
                for row in (scoped_results or [])
            ),
        ),
    )


@pytest.fixture()
def result_services(tmp_path):
    collection_service = build_test_collection_service(tmp_path / "collections")
    source_repository = SqliteSourceArtifactRepository(tmp_path / "lens.sqlite")
    paper_fact_repository = MemoryPaperFactRepository()
    comparison_service = ComparisonService(
        collection_service,
        paper_fact_repository=paper_fact_repository,
        comparison_repository=MemoryComparisonRepository(),
        document_profile_service=DocumentProfileService(
            collection_service,
            source_artifact_repository=source_repository,
            paper_fact_repository=paper_fact_repository,
        ),
    )

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(comparison_service=comparison_service),
        )
    )
    return collection_service, comparison_service, request


def test_results_route_returns_409_when_semantic_artifacts_are_not_ready(
    result_services,
):
    collection_service, _comparison_service, request = result_services
    record = collection_service.create_collection(name="Pending Results Collection")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            results_controller.list_collection_results(record["collection_id"], request)
        )

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "results_not_ready"
    assert exc.detail["collection_id"] == record["collection_id"]


def test_results_route_returns_product_projection_without_row_cache(result_services):
    collection_service, comparison_service, request = result_services
    collection = collection_service.create_collection(
        name="Results Projection Collection"
    )
    collection_id = collection["collection_id"]

    document_profile = {
        "document_id": "paper-1",
        "collection_id": collection_id,
        "title": "Flexural Strength Study",
        "source_filename": "paper.txt",
        "doc_type": "experimental",
        "parsing_warnings": [],
        "confidence": 0.93,
    }
    comparable_result, scoped_result = _build_semantic_result_record(
        collection_id=collection_id,
        comparable_result_id="cres-route-1",
        source_document_id="paper-1",
    )
    _store_core_result_facts(
        comparison_service,
        collection_id,
        document_profiles=[document_profile],
        comparable_results=[comparable_result],
        scoped_results=[scoped_result],
    )

    payload = asyncio.run(
        results_controller.list_collection_results(
            collection_id,
            request,
            comparability_status="comparable",
        )
    )

    assert payload.collection_id == collection_id
    assert payload.total == 1
    assert payload.count == 1
    item = payload.items[0]
    assert item.result_id == "cres-route-1"
    assert item.document_id == "paper-1"
    assert item.document_title == "Flexural Strength Study"
    assert item.material_label == "epoxy composite"
    assert item.variant_label == "Sample A"
    assert item.property == "flexural_strength"
    assert item.value == 97.0
    assert item.unit == "MPa"
    assert item.summary == "Flexural strength increased to 97 MPa."
    assert item.baseline == "untreated baseline"
    assert item.test_condition == "SEM"
    assert item.process == "80 C, 2 h, under Ar"
    assert item.traceability_status == "direct"
    assert item.comparability_status == "comparable"
    assert item.requires_expert_review is False


def test_result_detail_route_returns_document_assessment_evidence_and_actions(
    result_services,
):
    collection_service, comparison_service, request = result_services
    collection = collection_service.create_collection(name="Results Detail Collection")
    collection_id = collection["collection_id"]

    document_profile = {
        "document_id": "paper-1",
        "collection_id": collection_id,
        "title": "Flexural Strength Study",
        "source_filename": "paper.txt",
        "doc_type": "experimental",
        "parsing_warnings": [],
        "confidence": 0.93,
    }
    comparable_result, scoped_result = _build_semantic_result_record(
        collection_id=collection_id,
        comparable_result_id="cres-detail-1",
        source_document_id="paper-1",
    )
    _store_core_result_facts(
        comparison_service,
        collection_id,
        document_profiles=[document_profile],
        comparable_results=[comparable_result],
        scoped_results=[scoped_result],
    )

    payload = asyncio.run(
        results_controller.get_collection_result(
            collection_id,
            "cres-detail-1",
            request,
        )
    )

    assert payload.result_id == "cres-detail-1"
    assert payload.document.document_id == "paper-1"
    assert payload.document.title == "Flexural Strength Study"
    assert payload.document.source_filename == "paper.txt"
    assert payload.material.label == "epoxy composite"
    assert payload.material.variant_id == "var-1"
    assert payload.material.variant_label == "Sample A"
    assert payload.measurement.property == "flexural_strength"
    assert payload.measurement.value == 97.0
    assert payload.measurement.unit == "MPa"
    assert payload.measurement.summary == "Flexural strength increased to 97 MPa."
    assert payload.measurement.statistic_type is None
    assert payload.measurement.uncertainty is None
    assert payload.context.baseline == "untreated baseline"
    assert payload.context.baseline_reference == "untreated baseline"
    assert payload.context.test_condition == "SEM"
    assert payload.context.process == "80 C, 2 h, under Ar"
    assert payload.context.axis_name is None
    assert payload.context.axis_value is None
    assert payload.context.axis_unit is None
    assert payload.assessment.comparability_status == "comparable"
    assert payload.assessment.warnings == []
    assert payload.assessment.basis[-1] == "result_type:scalar"
    assert payload.evidence[0].evidence_id == "ev-1"
    assert payload.evidence[0].traceability_status == "direct"
    assert payload.evidence[0].source_type == "text"
    assert payload.evidence[0].anchor_ids == ["anchor-1", "anchor-2"]
    assert (
        payload.actions.open_document
        == f"/collections/{collection_id}/documents/paper-1"
    )
    assert payload.actions.open_comparisons.startswith(
        f"/collections/{collection_id}/comparisons?"
    )
    assert payload.actions.open_evidence == f"/collections/{collection_id}/evidence"


def test_result_detail_route_returns_pbf_acceptance_chain_fields(result_services):
    collection_service, comparison_service, request = result_services
    collection = collection_service.create_collection(name="Result Evidence Chain")
    collection_id = collection["collection_id"]
    document_profile = {
        "document_id": PBF_DOCUMENT_ID,
        "collection_id": collection_id,
        "title": "Ti64 Tensile Study",
        "source_filename": "ti64.txt",
        "doc_type": "experimental",
        "parsing_warnings": [],
        "confidence": 0.93,
    }
    sample_variants = pbf_acceptance_sample_variants(collection_id)
    test_conditions = pbf_acceptance_test_conditions(collection_id)
    baseline_references = pbf_acceptance_baseline_references(collection_id)
    measurement_results = pbf_acceptance_measurement_results(collection_id)
    characterization_observations = pbf_acceptance_characterization_observations(
        collection_id
    )
    structure_features = pbf_acceptance_structure_features(collection_id)
    comparable_results, scoped_results = pbf_acceptance_comparison_records(
        collection_id,
        sample_variants=sample_variants,
        test_conditions=test_conditions,
        baseline_references=baseline_references,
        measurement_results=measurement_results,
    )
    _store_core_result_facts(
        comparison_service,
        collection_id,
        document_profiles=[document_profile],
        sample_variants=sample_variants,
        test_conditions=test_conditions,
        baseline_references=baseline_references,
        measurement_results=measurement_results,
        characterization_observations=characterization_observations,
        structure_features=structure_features,
        comparable_results=comparable_results,
        scoped_results=scoped_results,
    )

    payload = asyncio.run(
        results_controller.get_collection_result(
            collection_id,
            PBF_YIELD_25_COMPARABLE_ID,
            request,
        )
    )

    assert payload.variant_dossier is not None
    assert payload.variant_dossier.variant_id == PBF_S3_VARIANT_ID
    assert payload.variant_dossier.variant_label == "S3 optimized VED + HIP"
    assert payload.variant_dossier.material.composition == "Ti-6Al-4V"
    assert payload.variant_dossier.shared_process_state["laser_power_w"] == 280
    assert payload.variant_dossier.shared_process_state["scan_speed_mm_s"] == 1200
    assert payload.variant_dossier.shared_process_state["hatch_spacing_um"] == 100
    assert payload.variant_dossier.shared_process_state["layer_thickness_um"] == 30
    assert payload.variant_dossier.shared_process_state["energy_density_j_mm3"] == 78
    assert (
        payload.variant_dossier.shared_process_state["energy_density_origin"]
        == "reported"
    )
    assert (
        payload.variant_dossier.shared_process_state["build_orientation"] == "vertical"
    )
    assert payload.test_condition_detail is not None
    assert payload.test_condition_detail.test_method == "tensile"
    assert payload.test_condition_detail.test_temperature_c == 25.0
    assert payload.test_condition_detail.strain_rate_s_1 == 0.001
    assert payload.test_condition_detail.loading_direction == "vertical"
    assert payload.test_condition_detail.sample_orientation == "vertical"
    assert payload.baseline_detail is not None
    assert payload.baseline_detail.reference == PBF_BASELINE_LABEL
    assert payload.baseline_detail.baseline_type == "same_paper_control"
    assert payload.baseline_detail.baseline_scope == "current_paper"
    support_by_id = {
        support.support_id: support for support in payload.structure_support
    }
    assert support_by_id["sf-porosity"].summary == "Porosity 0.1%"
    assert (
        support_by_id["sf-residual-stress"].summary == "Residual stress lower after HIP"
    )
    assert payload.value_provenance is not None
    assert payload.value_provenance.value_origin == "reported"
    assert payload.value_provenance.source_value_text == "940"
    assert payload.series_navigation is not None
    assert payload.series_navigation.series_key == PBF_YIELD_SERIES_KEY
    assert [sibling.axis_value for sibling in payload.series_navigation.siblings] == [
        25.0,
        200.0,
    ]


def test_result_detail_route_returns_404_when_missing(result_services):
    collection_service, comparison_service, request = result_services
    collection = collection_service.create_collection(name="Missing Result Collection")
    collection_id = collection["collection_id"]

    comparable_result, scoped_result = _build_semantic_result_record(
        collection_id=collection_id,
        comparable_result_id="cres-existing-1",
        source_document_id="paper-1",
    )
    _store_core_result_facts(
        comparison_service,
        collection_id,
        comparable_results=[comparable_result],
        scoped_results=[scoped_result],
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            results_controller.get_collection_result(
                collection_id,
                "cres-missing",
                request,
            )
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "result_not_found"
    assert exc.detail["collection_id"] == collection_id
    assert exc.detail["result_id"] == "cres-missing"
