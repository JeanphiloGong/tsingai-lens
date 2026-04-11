from __future__ import annotations

import asyncio

import pytest

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from application.artifact_registry_service import ArtifactRegistryService
from application.collection_service import CollectionService
from application.documents.service import DocumentProfileService
from controllers import documents as documents_controller


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
