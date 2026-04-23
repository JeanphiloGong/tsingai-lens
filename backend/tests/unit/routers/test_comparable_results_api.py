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
from controllers.core import comparable_results as comparable_results_controller
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


@pytest.fixture()
def comparable_result_services(monkeypatch, tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    comparison_service = ComparisonService(collection_service, artifact_registry)

    monkeypatch.setattr(
        comparable_results_controller,
        "comparison_service",
        comparison_service,
    )

    return collection_service, artifact_registry, comparison_service


def test_comparable_results_route_returns_200_without_row_cache(
    comparable_result_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _comparison_service = comparable_result_services
    collection = collection_service.create_collection(name="Comparable Results Collection")
    collection_id = collection["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    comparable_result, scoped_result = _build_semantic_comparison_record(
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
        comparable_results_controller.list_comparable_results(collection_id=collection_id)
    )

    assert payload.collection_id == collection_id
    assert payload.total == 1
    assert payload.count == 1
    assert payload.items[0].comparable_result_id == "cres-route-1"
    assert payload.items[0].observed_collection_ids == [collection_id]
    assert payload.items[0].collection_overlays[0].collection_id == collection_id
    assert not (output_dir / "comparison_rows.parquet").exists()


def test_comparable_result_detail_route_returns_404_when_missing(
    comparable_result_services,
):
    _collection_service, _artifact_registry, _comparison_service = comparable_result_services

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            comparable_results_controller.get_comparable_result("cres-missing")
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail["code"] == "comparable_result_not_found"
    assert exc.detail["comparable_result_id"] == "cres-missing"
