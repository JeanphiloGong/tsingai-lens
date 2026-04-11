from __future__ import annotations

import pytest

try:
    from fastapi import HTTPException
except ImportError:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

from controllers import protocol as protocol_controller
from application.artifact_registry_service import ArtifactRegistryService
from application.collection_service import CollectionService


@pytest.fixture()
def protocol_readiness_services(monkeypatch, tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")

    monkeypatch.setattr(protocol_controller, "collection_service", collection_service)
    monkeypatch.setattr(protocol_controller, "artifact_registry_service", artifact_registry)

    return collection_service, artifact_registry


def test_protocol_ready_guard_returns_409_when_registry_is_missing(protocol_readiness_services, monkeypatch, tmp_path):
    collection_service, _ = protocol_readiness_services
    record = collection_service.create_collection(name="Pending Collection")
    output_dir = tmp_path / "collections" / record["collection_id"] / "output"
    monkeypatch.setattr(
        protocol_controller.graph_service,
        "resolve_collection_output_dir",
        lambda collection_id: output_dir,
    )

    with pytest.raises(HTTPException) as exc_info:
        protocol_controller._ensure_collection_protocol_ready(record["collection_id"])

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "protocol_artifacts_not_ready"
    assert exc.detail["collection_id"] == record["collection_id"]
    assert exc.detail["artifacts"]["protocol_steps_ready"] is False


def test_protocol_ready_guard_returns_409_when_steps_are_not_ready(protocol_readiness_services, monkeypatch, tmp_path):
    collection_service, artifact_registry = protocol_readiness_services
    record = collection_service.create_collection(name="Pending Collection")
    output_dir = tmp_path / "collections" / record["collection_id"] / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_registry.upsert(record["collection_id"], output_dir)
    monkeypatch.setattr(
        protocol_controller.graph_service,
        "resolve_collection_output_dir",
        lambda collection_id: output_dir,
    )

    with pytest.raises(HTTPException) as exc_info:
        protocol_controller._ensure_collection_protocol_ready(record["collection_id"])

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail["code"] == "protocol_artifacts_not_ready"
    assert exc.detail["artifacts"]["documents_ready"] is False
    assert exc.detail["artifacts"]["protocol_steps_ready"] is False


def test_protocol_ready_guard_returns_output_dir_when_steps_exist(protocol_readiness_services, monkeypatch, tmp_path):
    collection_service, artifact_registry = protocol_readiness_services
    record = collection_service.create_collection(name="Ready Collection")
    output_dir = tmp_path / "collections" / record["collection_id"] / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "documents.parquet").write_text("[]", encoding="utf-8")
    (output_dir / "protocol_steps.parquet").write_text("[]", encoding="utf-8")
    artifact_registry.upsert(record["collection_id"], output_dir)
    monkeypatch.setattr(
        protocol_controller.graph_service,
        "resolve_collection_output_dir",
        lambda collection_id: output_dir,
    )

    resolved = protocol_controller._ensure_collection_protocol_ready(record["collection_id"])

    assert resolved == output_dir.resolve()


def test_protocol_ready_guard_returns_404_for_missing_collection(protocol_readiness_services):
    _collection_service, _artifact_registry = protocol_readiness_services

    with pytest.raises(HTTPException) as exc_info:
        protocol_controller._ensure_collection_protocol_ready("col_missing")

    exc = exc_info.value
    assert exc.status_code == 404
    assert "collection not found" in str(exc.detail)
