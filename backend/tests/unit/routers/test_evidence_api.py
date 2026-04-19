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

from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.collection_service import CollectionService
from application.core.document_profile_service import DocumentProfileService
from application.core.evidence_card_service import EvidenceCardService
from controllers.core import evidence as evidence_controller
from infra.source.runtime.source_evidence import build_sections, build_table_cells


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


def _write_source_artifacts(
    output_dir: Path,
    documents: pd.DataFrame,
    text_units: pd.DataFrame | None = None,
) -> None:
    build_sections(documents, text_units).to_parquet(output_dir / "sections.parquet", index=False)
    build_table_cells(documents, text_units).to_parquet(output_dir / "table_cells.parquet", index=False)


@pytest.fixture()
def evidence_services(monkeypatch, tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    evidence_card_service = EvidenceCardService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )

    monkeypatch.setattr(evidence_controller, "evidence_card_service", evidence_card_service)

    return collection_service, artifact_registry, evidence_card_service


def test_evidence_route_returns_409_when_cards_are_not_ready(evidence_services):
    collection_service, _artifact_registry, _evidence_card_service = evidence_services
    record = collection_service.create_collection(name="Pending Collection")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(evidence_controller.list_collection_evidence_cards(record["collection_id"]))

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "evidence_cards_not_ready"
    assert exc.detail["collection_id"] == record["collection_id"]


def test_evidence_route_returns_404_for_missing_collection(evidence_services):
    _collection_service, _artifact_registry, _evidence_card_service = evidence_services

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(evidence_controller.list_collection_evidence_cards("col_missing"))

    exc = exc_info.value
    assert exc.status_code == 404
    assert "collection not found" in str(exc.detail)


def test_evidence_route_returns_200_with_empty_cards_after_stage_generated(
    evidence_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _evidence_card_service = evidence_services
    record = collection_service.create_collection(name="Empty Evidence Collection")
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
    _write_source_artifacts(
        output_dir,
        pd.DataFrame(
            [
                {
                    "id": "doc-1",
                    "title": "Review of Composite Fillers",
                    "text": "This review summarizes recent advances in composite filler systems.",
                }
            ]
        ),
        None,
    )
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        evidence_controller.list_collection_evidence_cards(collection_id)
    )

    assert payload.collection_id == collection_id
    assert payload.total == 0
    assert payload.count == 0


def test_evidence_card_route_returns_single_card(evidence_services, monkeypatch):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _evidence_card_service = evidence_services
    record = collection_service.create_collection(name="Single Evidence Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    pd.DataFrame(
        [
            {
                "evidence_id": "ev-1",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "claim_text": "Conductivity improved after annealing.",
                "claim_type": "property",
                "evidence_source_type": "text",
                "evidence_anchors": [],
                "material_system": {"family": "oxide cathode"},
                "condition_context": {"process": {}, "baseline": {}, "test": {}},
                "confidence": 0.83,
                "traceability_status": "direct",
            }
        ]
    ).to_parquet(output_dir / "evidence_cards.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        evidence_controller.get_collection_evidence_card(collection_id, "ev-1")
    )

    assert payload.evidence_id == "ev-1"
    assert payload.collection_id == collection_id
    assert payload.claim_type == "property"
