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

from application.artifact_registry_service import ArtifactRegistryService
from application.collection_service import CollectionService
from application.documents.service import DocumentProfileService
from controllers import documents as documents_controller


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
def document_services(monkeypatch, tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)

    monkeypatch.setattr(documents_controller, "document_profile_service", document_profile_service)
    monkeypatch.setattr(documents_controller.lens_v1_mock_service, "is_enabled", lambda: False)

    return collection_service, artifact_registry, document_profile_service


def test_documents_route_returns_409_when_profiles_are_not_ready(document_services):
    collection_service, _artifact_registry, _document_profile_service = document_services
    record = collection_service.create_collection(name="Pending Collection")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            documents_controller.list_collection_document_profiles(record["collection_id"])
        )

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "document_profiles_not_ready"
    assert exc.detail["collection_id"] == record["collection_id"]


def test_documents_route_returns_404_for_missing_collection(document_services):
    _collection_service, _artifact_registry, _document_profile_service = document_services

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            documents_controller.list_collection_document_profiles("col_missing")
        )

    exc = exc_info.value
    assert exc.status_code == 404
    assert "collection not found" in str(exc.detail)


def test_documents_route_returns_200_with_empty_profiles_after_stage_generated(
    document_services,
    monkeypatch,
):
    _patch_parquet(monkeypatch)

    collection_service, artifact_registry, _document_profile_service = document_services
    record = collection_service.create_collection(name="Empty Profiles Collection")
    collection_id = record["collection_id"]
    output_dir = collection_service.get_paths(collection_id).output_dir

    pd.DataFrame(columns=["id", "title", "text"]).to_parquet(
        output_dir / "documents.parquet",
        index=False,
    )
    artifact_registry.upsert(collection_id, output_dir)

    payload = asyncio.run(
        documents_controller.list_collection_document_profiles(collection_id)
    )

    assert payload.collection_id == collection_id
    assert payload.total == 0
    assert payload.count == 0
