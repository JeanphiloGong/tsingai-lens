from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from application.source.artifact_registry_service import ArtifactRegistryService
from infra.persistence.memory import MemoryBuildRepository


def _registry(*, source_documents: tuple[object, ...] = ()) -> ArtifactRegistryService:
    source_repository = Mock()
    source_repository.read_collection_documents.return_value = source_documents
    return ArtifactRegistryService(
        MemoryBuildRepository(),
        source_artifact_repository=source_repository,
    )


def test_artifact_registry_marks_absent_source_artifacts_not_ready(tmp_path):
    payload = _registry().build_registry("col_demo", tmp_path / "output")

    assert payload["documents_ready"] is False
    assert payload["blocks_ready"] is False
    assert payload["figures_ready"] is False
    assert payload["table_rows_ready"] is False
    assert payload["table_cells_ready"] is False


def test_artifact_registry_reports_available_source_artifacts(tmp_path):
    source_document = SimpleNamespace(
        blocks=(object(),),
        figures=(object(),),
        table_rows=(object(),),
        table_cells=(object(),),
    )

    payload = _registry(source_documents=(source_document,)).build_registry(
        "col_demo",
        tmp_path / "output",
    )

    assert payload["documents_ready"] is True
    assert payload["blocks_ready"] is True
    assert payload["figures_ready"] is True
    assert payload["table_rows_ready"] is True
    assert payload["table_cells_ready"] is True
