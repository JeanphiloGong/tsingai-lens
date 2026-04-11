from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from application.artifact_registry_service import ArtifactRegistryService
from application.collection_service import CollectionService
from application.task_service import TaskService
from application.workspace_service import WorkspaceService


def _patch_parquet(monkeypatch) -> None:  # noqa: ANN001
    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        frame = self.reset_index(drop=True) if index else self
        Path(path).write_text(frame.to_json(orient="records"), encoding="utf-8")

    def fake_read_parquet(path, *args, **kwargs):  # noqa: ANN001, ARG001
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return pd.DataFrame(payload)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet, raising=False)
    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)


def test_workspace_service_builds_collection_overview(tmp_path):
    collection_service = CollectionService(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    workspace_service = WorkspaceService(collection_service, task_service, artifact_registry)

    collection = collection_service.create_collection("Composite Workspace")
    collection_id = collection["collection_id"]
    collection_service.add_file(collection_id, "paper.txt", b"Experimental Section\nMix and anneal.")

    task_service.create_task(collection_id, "index")
    task_service.update_task(
        task_service.list_tasks(collection_id=collection_id, limit=1)[0]["task_id"],
        status="running",
        current_stage="graphrag_index_started",
        progress_percent=35,
    )
    artifact_registry.upsert(collection_id, collection_service.get_paths(collection_id).output_dir)

    overview = workspace_service.get_workspace_overview(collection_id)

    assert overview["collection"]["collection_id"] == collection_id
    assert overview["file_count"] == 1
    assert overview["status_summary"] == "processing"
    assert overview["latest_task"]["current_stage"] == "graphrag_index_started"
    assert overview["capabilities"]["can_view_graph"] is False
    assert overview["capabilities"]["can_generate_sop"] is False


def test_workspace_service_includes_document_summary_and_links(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    collection_service = CollectionService(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    workspace_service = WorkspaceService(collection_service, task_service, artifact_registry)

    collection = collection_service.create_collection("Profiled Workspace")
    collection_id = collection["collection_id"]
    collection_service.add_file(
        collection_id,
        "paper.txt",
        b"Experimental Section\nPowders were mixed and annealed.",
    )

    output_dir = collection_service.get_paths(collection_id).output_dir
    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Profiled Paper",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "Powders were mixed in ethanol and stirred for 2 h.",
                        "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "Powders were mixed in ethanol and stirred for 2 h.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-2",
                "text": "The slurry was dried at 80 C and annealed at 600 C under Ar.",
                "document_ids": ["paper-1"],
            },
        ]
    )
    entities = pd.DataFrame([{"id": "ent-1", "title": "epoxy"}])
    relationships = pd.DataFrame([{"source": "epoxy", "target": "SiO2", "weight": 1.0}])
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    entities.to_parquet(output_dir / "entities.parquet", index=False)
    relationships.to_parquet(output_dir / "relationships.parquet", index=False)
    artifact_registry.upsert(collection_id, output_dir)

    overview = workspace_service.get_workspace_overview(collection_id)

    assert overview["status_summary"] == "document_profiled"
    assert overview["workflow"]["documents"]["status"] == "ready"
    assert overview["workflow"]["protocol"]["status"] == "limited"
    assert overview["artifacts"]["document_profiles_ready"] is True
    assert overview["artifacts"]["evidence_cards_ready"] is False
    assert overview["artifacts"]["comparison_rows_ready"] is False
    assert overview["document_summary"]["total_documents"] == 1
    assert overview["document_summary"]["by_doc_type"]["experimental"] == 1
    assert overview["links"]["documents_profiles"] == f"/api/v1/collections/{collection_id}/documents/profiles"
    assert overview["links"]["comparisons"] == f"/api/v1/collections/{collection_id}/comparisons"
