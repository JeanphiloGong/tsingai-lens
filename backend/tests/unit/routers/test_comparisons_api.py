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

from application.workspace.artifact_registry_service import ArtifactRegistryService
from application.collections.service import CollectionService
from application.comparisons.service import ComparisonService
from application.documents.service import DocumentProfileService
from application.evidence.service import EvidenceCardService
from controllers import comparisons as comparisons_controller


def _patch_parquet(monkeypatch) -> None:  # noqa: ANN001
    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        frame = self.reset_index(drop=True) if index else self
        Path(path).write_text(frame.to_json(orient="records"), encoding="utf-8")

    def fake_read_parquet(path, *args, **kwargs):  # noqa: ANN001, ARG001
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return pd.DataFrame(payload)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet, raising=False)
    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)


@pytest.fixture()
def comparison_services(monkeypatch, tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    evidence_card_service = EvidenceCardService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )
    comparison_service = ComparisonService(
        collection_service,
        artifact_registry,
        evidence_card_service,
    )

    monkeypatch.setattr(comparisons_controller, "comparison_service", comparison_service)

    return collection_service, artifact_registry, comparison_service


def test_comparisons_route_returns_409_when_rows_are_not_ready(comparison_services):
    collection_service, _artifact_registry, _comparison_service = comparison_services
    record = collection_service.create_collection(name="Pending Collection")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(comparisons_controller.list_collection_comparisons(record["collection_id"]))

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "comparison_rows_not_ready"
    assert exc.detail["collection_id"] == record["collection_id"]


def test_comparisons_route_returns_404_for_missing_collection(comparison_services):
    _collection_service, _artifact_registry, _comparison_service = comparison_services

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(comparisons_controller.list_collection_comparisons("col_missing"))

    exc = exc_info.value
    assert exc.status_code == 404
    assert "collection not found" in str(exc.detail)


def test_comparisons_route_returns_200_with_empty_rows_after_stage_generated(
    comparison_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _comparison_service = comparison_services
    record = collection_service.create_collection(name="Empty Comparisons Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    pd.DataFrame(
        [
            {
                "id": "doc-1",
                "title": "Review of Composite Fillers",
                "text": "This review summarizes recent advances in composite filler systems.",
            }
        ]
    ).to_parquet(output_dir / "documents.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        comparisons_controller.list_collection_comparisons(collection_id)
    )

    assert payload.collection_id == collection_id
    assert payload.total == 0
    assert payload.count == 0


def test_comparisons_route_exposes_v2_contract_fields_for_existing_rows(
    comparison_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _comparison_service = comparison_services
    record = collection_service.create_collection(name="Existing Comparisons Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    pd.DataFrame(
        [
            {
                "row_id": "cmp-1",
                "collection_id": collection_id,
                "source_document_id": "paper-1",
                "supporting_evidence_ids": ["ev-1"],
                "material_system_normalized": "oxide cathode",
                "process_normalized": "700 C",
                "property_normalized": "conductivity",
                "baseline_normalized": "as-prepared",
                "test_condition_normalized": "EIS",
                "comparability_status": "comparable",
                "comparability_warnings": [],
                "value": 12.0,
                "unit": "mS/cm",
            }
        ]
    ).to_parquet(output_dir / "comparison_rows.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        comparisons_controller.list_collection_comparisons(collection_id)
    )

    assert payload.count == 1
    item = payload.items[0]
    assert item.row_id == "cmp-1"
    assert item.variant_id is None
    assert item.variant_label is None
    assert item.variable_axis is None
    assert item.variable_value is None
    assert item.baseline_reference is None
    assert item.result_source_type is None
