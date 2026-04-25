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


def _write_evidence_chain_fact_artifacts(output_dir: Path) -> None:
    pd.DataFrame(
        [
            {
                "variant_id": "var-1",
                "document_id": "paper-1",
                "collection_id": "test",
                "domain_profile": "pbf_metal",
                "variant_label": "optimized VED + HIP",
                "host_material_system": {
                    "family": "titanium alloy",
                    "composition": "Ti-6Al-4V",
                },
                "composition": "Ti-6Al-4V",
                "variable_axis_type": None,
                "variable_value": None,
                "process_context": {
                    "laser_power_w": 280,
                    "scan_speed_mm_s": 1200,
                    "layer_thickness_um": 30,
                    "hatch_spacing_um": 100,
                    "build_orientation": "vertical",
                    "post_treatment_summary": "HIP",
                },
                "profile_payload": {},
                "structure_feature_ids": ["sf-porosity"],
                "source_anchor_ids": ["anchor-process"],
                "confidence": 0.9,
                "epistemic_status": "normalized_from_evidence",
            }
        ]
    ).to_parquet(output_dir / "sample_variants.parquet", index=False)
    pd.DataFrame(
        [
            {
                "test_condition_id": "tc-25",
                "document_id": "paper-1",
                "collection_id": "test",
                "domain_profile": "pbf_metal",
                "property_type": "yield_strength",
                "template_type": "mechanical",
                "scope_level": "result",
                "condition_payload": {
                    "method": "tensile",
                    "test_temperature_c": 25.0,
                    "strain_rate_s-1": 0.001,
                    "loading_direction": "vertical",
                    "sample_orientation": "vertical",
                },
                "condition_completeness": "complete",
                "missing_fields": [],
                "evidence_anchor_ids": ["anchor-test-25"],
                "confidence": 0.9,
                "epistemic_status": "normalized_from_evidence",
            },
            {
                "test_condition_id": "tc-200",
                "document_id": "paper-1",
                "collection_id": "test",
                "domain_profile": "pbf_metal",
                "property_type": "yield_strength",
                "template_type": "mechanical",
                "scope_level": "result",
                "condition_payload": {
                    "method": "tensile",
                    "test_temperature_c": 200.0,
                    "strain_rate_s-1": 0.001,
                    "loading_direction": "vertical",
                    "sample_orientation": "vertical",
                },
                "condition_completeness": "complete",
                "missing_fields": [],
                "evidence_anchor_ids": ["anchor-test-200"],
                "confidence": 0.9,
                "epistemic_status": "normalized_from_evidence",
            },
        ]
    ).to_parquet(output_dir / "test_conditions.parquet", index=False)
    pd.DataFrame(
        [
            {
                "baseline_id": "base-1",
                "document_id": "paper-1",
                "collection_id": "test",
                "domain_profile": "pbf_metal",
                "variant_id": "var-1",
                "baseline_type": "same_paper_control",
                "baseline_label": "optimized VED without HIP",
                "baseline_scope": "current_paper",
                "evidence_anchor_ids": ["anchor-baseline"],
                "confidence": 0.9,
                "epistemic_status": "normalized_from_evidence",
            }
        ]
    ).to_parquet(output_dir / "baseline_references.parquet", index=False)
    pd.DataFrame(
        [
            {
                "result_id": "res-detail-25",
                "document_id": "paper-1",
                "collection_id": "test",
                "domain_profile": "pbf_metal",
                "variant_id": "var-1",
                "property_normalized": "yield_strength",
                "result_type": "scalar",
                "claim_scope": "current_work",
                "value_payload": {
                    "value": 940.0,
                    "source_value_text": "940",
                    "source_unit_text": "MPa",
                    "value_origin": "reported",
                },
                "unit": "MPa",
                "test_condition_id": "tc-25",
                "baseline_id": "base-1",
                "structure_feature_ids": ["sf-porosity"],
                "characterization_observation_ids": ["obs-porosity"],
                "evidence_anchor_ids": ["anchor-1"],
                "traceability_status": "direct",
                "result_source_type": "text",
                "epistemic_status": "normalized_from_evidence",
            },
            {
                "result_id": "res-detail-200",
                "document_id": "paper-1",
                "collection_id": "test",
                "domain_profile": "pbf_metal",
                "variant_id": "var-1",
                "property_normalized": "yield_strength",
                "result_type": "scalar",
                "claim_scope": "current_work",
                "value_payload": {
                    "value": 820.0,
                    "source_value_text": "820",
                    "source_unit_text": "MPa",
                    "value_origin": "reported",
                },
                "unit": "MPa",
                "test_condition_id": "tc-200",
                "baseline_id": "base-1",
                "structure_feature_ids": [],
                "characterization_observation_ids": [],
                "evidence_anchor_ids": ["anchor-3"],
                "traceability_status": "direct",
                "result_source_type": "text",
                "epistemic_status": "normalized_from_evidence",
            },
        ]
    ).to_parquet(output_dir / "measurement_results.parquet", index=False)
    pd.DataFrame(
        [
            {
                "observation_id": "obs-porosity",
                "document_id": "paper-1",
                "collection_id": "test",
                "variant_id": "var-1",
                "characterization_type": "porosity",
                "observation_text": "Porosity decreased to 0.1%.",
                "observed_value": 0.1,
                "observed_unit": "%",
                "condition_context": {"process": {"temperatures_c": []}},
                "evidence_anchor_ids": ["anchor-porosity"],
                "confidence": 0.9,
                "epistemic_status": "normalized_from_evidence",
            }
        ]
    ).to_parquet(output_dir / "characterization_observations.parquet", index=False)
    pd.DataFrame(
        [
            {
                "feature_id": "sf-porosity",
                "document_id": "paper-1",
                "collection_id": "test",
                "variant_id": "var-1",
                "feature_type": "porosity",
                "feature_value": 0.1,
                "feature_unit": "%",
                "qualitative_descriptor": "Porosity 0.1%",
                "source_observation_ids": ["obs-porosity"],
                "confidence": 0.9,
                "epistemic_status": "normalized_from_evidence",
            }
        ]
    ).to_parquet(output_dir / "structure_features.parquet", index=False)


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


def test_result_detail_route_returns_evidence_chain_additive_fields(
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
                "document_id": "paper-1",
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
    first_result, first_scope = _build_semantic_result_record(
        collection_id=collection_id,
        comparable_result_id="cres-detail-25",
        source_document_id="paper-1",
        property_normalized="yield_strength",
        numeric_value=940.0,
    )
    first_result["source_result_id"] = "res-detail-25"
    first_result["binding"]["test_condition_id"] = "tc-25"
    first_result["normalized_context"]["material_system_normalized"] = "Ti-6Al-4V"
    first_result["normalized_context"]["process_normalized"] = "LPBF optimized VED + HIP"
    first_result["normalized_context"]["test_condition_normalized"] = "tensile"
    first_result["value"]["summary"] = "YS 940 MPa"
    first_result["evidence"]["structure_feature_ids"] = ["sf-porosity"]
    first_result["evidence"]["characterization_observation_ids"] = ["obs-porosity"]
    first_result["variant_label"] = "optimized VED + HIP"
    first_result["baseline_reference"] = "optimized VED without HIP"
    second_result, second_scope = _build_semantic_result_record(
        collection_id=collection_id,
        comparable_result_id="cres-detail-200",
        source_document_id="paper-1",
        property_normalized="yield_strength",
        numeric_value=820.0,
        sort_order=1,
    )
    second_result["source_result_id"] = "res-detail-200"
    second_result["binding"]["test_condition_id"] = "tc-200"
    second_result["normalized_context"]["material_system_normalized"] = "Ti-6Al-4V"
    second_result["normalized_context"]["process_normalized"] = "LPBF optimized VED + HIP"
    second_result["normalized_context"]["test_condition_normalized"] = "tensile"
    second_result["value"]["summary"] = "YS 820 MPa"
    second_result["variant_label"] = "optimized VED + HIP"
    second_result["baseline_reference"] = "optimized VED without HIP"
    _write_semantic_comparison_artifacts(
        output_dir,
        [first_result, second_result],
        [first_scope, second_scope],
    )
    _write_evidence_chain_fact_artifacts(output_dir)
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        results_controller.get_collection_result(collection_id, "cres-detail-25")
    )

    assert payload.variant_dossier is not None
    assert payload.variant_dossier.variant_id == "var-1"
    assert payload.variant_dossier.variant_label == "optimized VED + HIP"
    assert payload.variant_dossier.material.composition == "Ti-6Al-4V"
    assert payload.variant_dossier.shared_process_state["laser_power_w"] == 280
    assert payload.test_condition_detail is not None
    assert payload.test_condition_detail.test_method == "tensile"
    assert payload.test_condition_detail.test_temperature_c == 25.0
    assert payload.test_condition_detail.strain_rate_s_1 == 0.001
    assert payload.baseline_detail is not None
    assert payload.baseline_detail.reference == "optimized VED without HIP"
    assert payload.baseline_detail.baseline_type == "same_paper_control"
    assert payload.baseline_detail.baseline_scope == "current_paper"
    assert payload.structure_support[0].support_id == "sf-porosity"
    assert payload.structure_support[0].summary == "Porosity 0.1%"
    assert payload.value_provenance is not None
    assert payload.value_provenance.value_origin == "reported"
    assert payload.value_provenance.source_value_text == "940"
    assert payload.series_navigation is not None
    assert payload.series_navigation.series_key == "yield_strength:test_temperature_c"
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
