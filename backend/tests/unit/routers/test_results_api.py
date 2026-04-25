from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pandas as pd
import pytest

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from application.core.comparison_service import ComparisonService
from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.collection_service import CollectionService
from controllers.core import results as results_controller
from domain.core.comparison import (
    ComparableResult,
    build_collection_assessment_input_fingerprint,
)
from tests.support.pbf_acceptance_fixture import (
    PBF_BASELINE_LABEL,
    PBF_DOCUMENT_ID,
    PBF_S3_VARIANT_ID,
    PBF_YIELD_25_COMPARABLE_ID,
    PBF_YIELD_SERIES_KEY,
    write_pbf_acceptance_artifacts,
)


def _patch_parquet(monkeypatch) -> None:  # noqa: ANN001
    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        frame = self.reset_index(drop=True) if index else self
        payload = {
            "columns": list(frame.columns),
            "records": frame.to_dict(orient="records"),
        }
        Path(path).write_text(json.dumps(payload), encoding="utf-8")

    def fake_read_parquet(path, *args, **kwargs):  # noqa: ANN001, ARG001
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return pd.DataFrame(payload["records"], columns=payload["columns"])

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet, raising=False)
    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)


def _write_semantic_comparison_artifacts(
    output_dir: Path,
    comparable_results: list[dict],
    scoped_results: list[dict],
) -> None:
    pd.DataFrame(comparable_results).to_parquet(
        output_dir / "comparable_results.parquet",
        index=False,
    )
    pd.DataFrame(scoped_results).to_parquet(
        output_dir / "collection_comparable_results.parquet",
        index=False,
    )


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


@pytest.fixture()
def result_services(monkeypatch, tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    comparison_service = ComparisonService(collection_service, artifact_registry)

    monkeypatch.setattr(results_controller, "comparison_service", comparison_service)

    return collection_service, artifact_registry, comparison_service


def test_results_route_returns_409_when_semantic_artifacts_are_not_ready(result_services):
    collection_service, _artifact_registry, _comparison_service = result_services
    record = collection_service.create_collection(name="Pending Results Collection")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(results_controller.list_collection_results(record["collection_id"]))

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "results_not_ready"
    assert exc.detail["collection_id"] == record["collection_id"]


def test_results_route_returns_product_projection_without_row_cache(
    result_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _comparison_service = result_services
    collection = collection_service.create_collection(name="Results Projection Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Flexural Strength Study",
                "source_filename": "paper.txt",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": [],
                "parsing_warnings": [],
                "confidence": 0.93,
            }
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    pd.DataFrame(
        [
            {
                "evidence_id": "ev-1",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "claim_text": "Flexural strength increased to 97 MPa.",
                "claim_type": "property",
                "evidence_source_type": "text",
                "evidence_anchors": [],
                "material_system": {"family": "epoxy composite"},
                "condition_context": {"process": {}, "baseline": {}, "test": {}},
                "confidence": 0.84,
                "traceability_status": "direct",
            }
        ]
    ).to_parquet(output_dir / "evidence_cards.parquet", index=False)
    comparable_result, scoped_result = _build_semantic_result_record(
        collection_id=collection_id,
        comparable_result_id="cres-route-1",
        source_document_id="paper-1",
    )
    _write_semantic_comparison_artifacts(
        output_dir,
        [comparable_result],
        [scoped_result],
    )
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        results_controller.list_collection_results(
            collection_id,
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
    assert not (output_dir / "comparison_rows.parquet").exists()


def test_result_detail_route_returns_document_assessment_evidence_and_actions(
    result_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _comparison_service = result_services
    collection = collection_service.create_collection(name="Results Detail Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Flexural Strength Study",
                "source_filename": "paper.txt",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": [],
                "parsing_warnings": [],
                "confidence": 0.93,
            }
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    pd.DataFrame(
        [
            {
                "evidence_id": "ev-1",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "claim_text": "Flexural strength increased to 97 MPa.",
                "claim_type": "property",
                "evidence_source_type": "text",
                "evidence_anchors": [],
                "material_system": {"family": "epoxy composite"},
                "condition_context": {"process": {}, "baseline": {}, "test": {}},
                "confidence": 0.84,
                "traceability_status": "direct",
            }
        ]
    ).to_parquet(output_dir / "evidence_cards.parquet", index=False)
    comparable_result, scoped_result = _build_semantic_result_record(
        collection_id=collection_id,
        comparable_result_id="cres-detail-1",
        source_document_id="paper-1",
    )
    _write_semantic_comparison_artifacts(
        output_dir,
        [comparable_result],
        [scoped_result],
    )
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        results_controller.get_collection_result(collection_id, "cres-detail-1")
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


def test_result_detail_route_returns_pbf_acceptance_chain_fields(
    result_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _comparison_service = result_services
    collection = collection_service.create_collection(name="Result Evidence Chain")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "document_id": PBF_DOCUMENT_ID,
                "collection_id": collection_id,
                "title": "Ti64 Tensile Study",
                "source_filename": "ti64.txt",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": [],
                "parsing_warnings": [],
                "confidence": 0.93,
            }
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    write_pbf_acceptance_artifacts(output_dir, collection_id=collection_id)
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        results_controller.get_collection_result(collection_id, PBF_YIELD_25_COMPARABLE_ID)
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
    assert payload.variant_dossier.shared_process_state["energy_density_origin"] == "reported"
    assert payload.variant_dossier.shared_process_state["build_orientation"] == "vertical"
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
    support_by_id = {support.support_id: support for support in payload.structure_support}
    assert support_by_id["sf-porosity"].summary == "Porosity 0.1%"
    assert support_by_id["sf-residual-stress"].summary == "Residual stress lower after HIP"
    assert payload.value_provenance is not None
    assert payload.value_provenance.value_origin == "reported"
    assert payload.value_provenance.source_value_text == "940"
    assert payload.series_navigation is not None
    assert payload.series_navigation.series_key == PBF_YIELD_SERIES_KEY
    assert [sibling.axis_value for sibling in payload.series_navigation.siblings] == [
        25.0,
        200.0,
    ]


def test_result_detail_route_returns_404_when_missing(
    result_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _comparison_service = result_services
    collection = collection_service.create_collection(name="Missing Result Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    comparable_result, scoped_result = _build_semantic_result_record(
        collection_id=collection_id,
        comparable_result_id="cres-existing-1",
        source_document_id="paper-1",
    )
    _write_semantic_comparison_artifacts(
        output_dir,
        [comparable_result],
        [scoped_result],
    )
    artifact_registry.upsert(collection_id, output_dir)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            results_controller.get_collection_result(collection_id, "cres-missing")
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "result_not_found"
    assert exc.detail["collection_id"] == collection_id
    assert exc.detail["result_id"] == "cres-missing"
