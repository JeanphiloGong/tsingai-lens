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
from infra.persistence.sqlite import SqliteCoreFactRepository, SqliteSourceArtifactRepository
from tests.support.collection_service import build_test_collection_service
from tests.support.paper_fact_repository import MemoryPaperFactRepository
from tests.support.objective_repository import MemoryObjectiveRepository
from controllers.core import comparable_results as comparable_results_controller
from domain.core import (
    CollectionComparableResult,
    ComparableResult,
)
from domain.core.comparison import (
    build_collection_assessment_input_fingerprint,
)


def _build_semantic_comparison_record(
    *,
    collection_id: str,
    comparable_result_id: str,
    source_document_id: str,
    property_normalized: str = "flexural_strength",
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
            "numeric_value": 97.0,
            "unit": "MPa",
            "summary": "Flexural strength increased to 97 MPa.",
            "statistic_type": None,
            "uncertainty": None,
        },
        "evidence": {
            "direct_anchor_ids": ["anchor-1"],
            "contextual_anchor_ids": ["anchor-2"],
            "evidence_ids": ["ev-result-1"],
            "structure_feature_ids": [],
            "characterization_observation_ids": [],
            "traceability_status": "direct",
        },
        "variant_label": "epoxy composite",
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


def _store_core_comparable_result_facts(
    comparison_service: ComparisonService,
    collection_id: str,
    *,
    comparable_results: list[dict],
    scoped_results: list[dict],
) -> None:
    comparison_service.core_fact_repository.replace_collection_comparison_artifacts(
        collection_id,
        tuple(ComparableResult.from_mapping(row) for row in comparable_results),
        tuple(
            CollectionComparableResult.from_mapping(row) for row in scoped_results
        ),
        (),
    )


@pytest.fixture()
def comparable_result_services(tmp_path):
    collection_service = build_test_collection_service(tmp_path / "collections")
    source_repository = SqliteSourceArtifactRepository(tmp_path / "lens.sqlite")
    paper_fact_repository = MemoryPaperFactRepository()
    comparison_service = ComparisonService(
        collection_service,
        paper_fact_repository=paper_fact_repository,
        objective_repository=MemoryObjectiveRepository(),
        core_fact_repository=SqliteCoreFactRepository(tmp_path / "lens.sqlite"),
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


def test_comparable_results_route_returns_200_without_row_cache(
    comparable_result_services,
):
    collection_service, comparison_service, request = comparable_result_services
    collection = collection_service.create_collection(name="Comparable Results Collection")
    collection_id = collection["collection_id"]

    comparable_result, scoped_result = _build_semantic_comparison_record(
        collection_id=collection_id,
        comparable_result_id="cres-route-1",
        source_document_id="paper-1",
    )
    _store_core_comparable_result_facts(
        comparison_service,
        collection_id,
        comparable_results=[comparable_result],
        scoped_results=[scoped_result],
    )

    payload = asyncio.run(
        comparable_results_controller.list_comparable_results(
            request,
            collection_id=collection_id,
        )
    )

    assert payload.collection_id == collection_id
    assert payload.total == 1
    assert payload.count == 1
    assert payload.items[0].comparable_result_id == "cres-route-1"
    assert payload.items[0].observed_collection_ids == [collection_id]
    assert payload.items[0].collection_overlays[0].collection_id == collection_id


def test_comparable_result_detail_route_returns_404_when_missing(
    comparable_result_services,
):
    _collection_service, _comparison_service, request = comparable_result_services

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            comparable_results_controller.get_comparable_result(
                "cres-missing",
                request,
            )
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "comparable_result_not_found"
    assert exc.detail["comparable_result_id"] == "cres-missing"
