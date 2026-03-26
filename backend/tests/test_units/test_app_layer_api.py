from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

if "devtools" not in sys.modules:
    sys.modules["devtools"] = SimpleNamespace(pformat=lambda value: str(value))
import pytest

try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False

if not FASTAPI_AVAILABLE:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)


class DummyWorkflowOutput:
    def __init__(self, workflow: str = "index", errors: list[str] | None = None):
        self.workflow = workflow
        self.errors = errors


def _patch_parquet(monkeypatch) -> None:  # noqa: ANN001
    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        frame = self.reset_index(drop=True) if index else self
        Path(path).write_text(frame.to_json(orient="records"), encoding="utf-8")

    def fake_read_parquet(path, *args, **kwargs):  # noqa: ANN001, ARG001
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return pd.DataFrame(payload)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet, raising=False)
    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)


def _build_config(output_dir: Path, input_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        output=SimpleNamespace(base_dir=str(output_dir)),
        input=SimpleNamespace(storage=SimpleNamespace(base_dir=str(input_dir))),
        root_dir=str(output_dir.parent),
    )


def _write_index_outputs(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Composite Paper",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "The precursor powders were mixed in ethanol and stirred for 2 h.",
                        "The slurry was dried at 80 C and annealed at 600 C for 2 h under Ar.",
                        "Characterization",
                        "XRD and SEM were used to characterize the powders.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "The precursor powders were mixed in ethanol and stirred for 2 h.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-2",
                "text": "The slurry was dried at 80 C and annealed at 600 C for 2 h under Ar.",
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


@pytest.fixture()
def app_client(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from fastapi import FastAPI
    from controllers import collections as collections_controller
    from controllers import tasks as tasks_controller
    from services.artifact_registry_service import ArtifactRegistryService
    from services.collection_service import CollectionService
    from services.index_task_runner import IndexTaskRunner
    from services.task_service import TaskService
    import services.index_task_runner as task_runner_module

    collection_service = CollectionService(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    runner = IndexTaskRunner(collection_service, task_service, artifact_registry)

    default_config = tmp_path / "configs" / "default.yaml"
    default_config.parent.mkdir(parents=True, exist_ok=True)
    default_config.write_text("dummy: true\n", encoding="utf-8")

    async def fake_build_index(**kwargs):  # noqa: ANN003
        output_dir = Path(kwargs["config"].output.base_dir)
        _write_index_outputs(output_dir)
        return [DummyWorkflowOutput()]

    monkeypatch.setattr(collections_controller, "collection_service", collection_service)
    monkeypatch.setattr(tasks_controller, "collection_service", collection_service)
    monkeypatch.setattr(tasks_controller, "task_service", task_service)
    monkeypatch.setattr(tasks_controller, "artifact_registry_service", artifact_registry)
    monkeypatch.setattr(tasks_controller, "index_task_runner", runner)
    monkeypatch.setattr(task_runner_module, "CONFIG_DIR", default_config.parent)
    monkeypatch.setattr(task_runner_module, "load_config", lambda *args, **kwargs: _build_config(Path("placeholder-output"), Path("placeholder-input")))
    monkeypatch.setattr(task_runner_module, "build_index", fake_build_index)

    app = FastAPI()
    app.include_router(collections_controller.router)
    app.include_router(tasks_controller.router)
    return TestClient(app)


def test_collection_task_flow(app_client):
    create_resp = app_client.post("/collections", json={"name": "Composite Set"})
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    upload_resp = app_client.post(
        f"/collections/{collection_id}/files",
        files={"file": ("paper.txt", b"Experimental Section\nMix and anneal.", "text/plain")},
    )
    assert upload_resp.status_code == 200

    task_resp = app_client.post(f"/collections/{collection_id}/tasks/index", json={})
    assert task_resp.status_code == 200
    task_id = task_resp.json()["task_id"]

    task_status = app_client.get(f"/tasks/{task_id}")
    assert task_status.status_code == 200
    assert task_status.json()["status"] == "completed"
    assert task_status.json()["current_stage"] == "artifacts_ready"

    artifacts = app_client.get(f"/tasks/{task_id}/artifacts")
    assert artifacts.status_code == 200
    body = artifacts.json()
    assert body["documents_ready"] is True
    assert body["graph_ready"] is True
    assert body["sections_ready"] is True
    assert body["protocol_steps_ready"] is True
