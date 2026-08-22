from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

if "devtools" not in sys.modules:
    sys.modules["devtools"] = SimpleNamespace(pformat=lambda value: str(value))

import pytest
from infra.persistence.memory import MemoryBuildRepository
from infra.source.runtime.artifact_bundle import SourceArtifactBundle
from infra.source.runtime.source_evidence import (
    build_blocks,
    build_table_cells,
    build_table_rows,
)
from tests.support.paper_fact_repository import MemoryPaperFactRepository
from tests.support.objective_repository import MemoryObjectiveRepository
from tests.support.objective_review_repository import InMemoryObjectiveReviewRepository
from tests.support.experiment_plan_repository import (
    InMemoryExperimentPlanRepository,
)
from tests.support.chat_repository import MemoryChatRepository
from tests.support.source_artifact_repository import MemorySourceArtifactRepository

try:
    from fastapi.testclient import TestClient

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False

if not FASTAPI_AVAILABLE:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

API_V1_PREFIX = "/api/v1"


class DummyWorkflowOutput:
    def __init__(
        self,
        workflow: str = "build",
        errors: list[str] | None = None,
        result=None,  # noqa: ANN001
    ):
        self.workflow = workflow
        self.errors = errors
        self.result = result


def _wait_for_task_terminal(app_client, task_id: str, timeout_s: float = 5.0) -> dict:  # noqa: ANN001
    deadline = time.monotonic() + timeout_s
    last_body: dict | None = None
    while time.monotonic() < deadline:
        response = app_client.get(f"{API_V1_PREFIX}/tasks/{task_id}")
        assert response.status_code == 200
        last_body = response.json()
        if last_body["status"] in {"completed", "partial_success", "failed"}:
            return last_body
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not finish before timeout: {last_body}")


def _build_config(output_dir: Path, input_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        output=SimpleNamespace(base_dir=str(output_dir)),
        input=SimpleNamespace(storage=SimpleNamespace(base_dir=str(input_dir))),
        root_dir=str(output_dir.parent),
    )


def _write_source_artifact_outputs(
    output_dir: Path,
) -> SourceArtifactBundle:
    output_dir.mkdir(parents=True, exist_ok=True)
    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Composite Paper",
                "metadata": {"source_path": "paper.txt"},
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "The precursor powders were mixed in ethanol and stirred for 2 h.",
                        "The slurry was dried at 80 C and annealed at 600 C for 2 h under Ar.",
                        "Characterization",
                        "XRD and SEM were used to characterize the powders.",
                        "Flexural strength at 25 C increased to 97 MPa relative to the untreated baseline.",
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
            {
                "id": "tu-3",
                "text": "Flexural strength at 25 C increased to 97 MPa relative to the untreated baseline.",
                "document_ids": ["paper-1"],
            },
        ]
    )
    blocks = build_blocks(documents, text_units)
    tables = pd.DataFrame(
        [
            {
                "table_id": "tbl-1",
                "document_id": "paper-1",
                "table_order": 0,
                "caption_text": "Processing summary",
                "caption_block_id": None,
                "page": None,
                "heading_path": ["Experimental Section"],
                "row_count": 1,
                "col_count": 2,
                "column_headers": ["condition", "result"],
                "table_markdown": "| condition | result |\n| --- | --- |\n| annealed | 97 MPa |",
                "table_text": "condition: annealed; result: 97 MPa",
                "metadata": {},
            }
        ]
    )
    table_rows = build_table_rows(documents, text_units)
    table_cells = build_table_cells(documents, text_units)
    return SourceArtifactBundle(
        documents=documents,
        text_units=text_units,
        blocks=blocks,
        figures=pd.DataFrame(),
        tables=tables,
        table_rows=table_rows,
        table_cells=table_cells,
        figure_assets={},
    )



def _create_built_collection(
    app_client, name: str = "Composite Set"
) -> tuple[str, str]:  # noqa: ANN001
    create_resp = app_client.post(f"{API_V1_PREFIX}/collections", json={"name": name})
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    upload_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/files",
        files={
            "file": (
                "paper.txt",
                b"Experimental Section\nMix and anneal.",
                "text/plain",
            )
        },
    )
    assert upload_resp.status_code == 200

    task_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/tasks/build", json={}
    )
    assert task_resp.status_code == 200
    task_id = task_resp.json()["task_id"]
    final_task = _wait_for_task_terminal(app_client, task_id)
    assert final_task["status"] == "completed"
    active_build = app_client.portal.call(
        app_client.app.state.task_service.repository.read_active_build,
        collection_id,
    )
    assert active_build is not None
    app_client.app.state.paper_fact_repository.activate(active_build.build_id)
    return collection_id, task_id


def test_request_id_is_generated_and_echoed(app_client):
    response = app_client.get(f"{API_V1_PREFIX}/collections")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"].startswith("req_")


def test_request_id_is_echoed_and_propagated_to_background_build(
    app_client, monkeypatch
):
    import application.pipeline.collection_build.service as task_runner_module
    from utils.logger import REQUEST_ID_HEADER, get_request_id

    captured: dict[str, str | None] = {}

    async def fake_build_source_artifacts(**kwargs):  # noqa: ANN003
        captured["bound_request_id"] = get_request_id()
        output_dir = Path(kwargs["config"].output.base_dir)
        return [DummyWorkflowOutput(result=_write_source_artifact_outputs(output_dir))]

    monkeypatch.setattr(
        task_runner_module, "build_source_artifacts", fake_build_source_artifacts
    )

    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections", json={"name": "Request ID Set"}
    )
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    upload_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/files",
        files={
            "file": (
                "paper.txt",
                b"Experimental Section\nMix and anneal.",
                "text/plain",
            )
        },
    )
    assert upload_resp.status_code == 200

    request_id = "client-request-123"
    task_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/tasks/build",
        json={},
        headers={REQUEST_ID_HEADER: request_id},
    )

    assert task_resp.status_code == 200
    assert task_resp.headers[REQUEST_ID_HEADER] == request_id
    final_task = _wait_for_task_terminal(app_client, task_resp.json()["task_id"])
    assert final_task["status"] == "completed"
    assert captured["bound_request_id"] == request_id


def test_build_task_route_schedules_async_entry_without_waiting(
    app_client, monkeypatch
):
    captured: dict[str, object] = {}
    started = threading.Event()
    finished = threading.Event()

    async def fake_run_task(*args, **kwargs):  # noqa: ANN002, ANN003
        captured["args"] = args
        captured["kwargs"] = kwargs
        started.set()
        await asyncio.sleep(0.2)
        finished.set()
        return {"task_id": args[0], "collection_id": args[1], "status": "queued"}

    monkeypatch.setattr(
        app_client.app.state.build_pipeline_service,
        "run_task",
        fake_run_task,
    )

    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections", json={"name": "Blocking Entry Set"}
    )
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    upload_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/files",
        files={
            "file": (
                "paper.txt",
                b"Experimental Section\nMix and anneal.",
                "text/plain",
            )
        },
    )
    assert upload_resp.status_code == 200

    task_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/tasks/build", json={}
    )

    assert task_resp.status_code == 200
    assert started.wait(timeout=2)
    assert captured["args"][1] == collection_id
    assert not finished.is_set()
    assert finished.wait(timeout=2)


def test_legacy_index_task_route_is_not_registered(app_client):
    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections", json={"name": "Legacy Route"}
    )
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    upload_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/files",
        files={
            "file": (
                "paper.txt",
                b"Experimental Section\nMix and anneal.",
                "text/plain",
            )
        },
    )
    assert upload_resp.status_code == 200

    task_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/tasks/index", json={}
    )
    assert task_resp.status_code == 404


@pytest.mark.parametrize(
    "retired_path",
    (
        "/comparable-results",
        "/collections/{collection_id}/research-view",
        "/collections/{collection_id}/materials",
        "/collections/{collection_id}/results",
        "/collections/{collection_id}/evidence/cards",
        "/collections/{collection_id}/graph",
        "/collections/{collection_id}/graphml",
        "/collections/{collection_id}/documents/doc-1/comparison-semantics",
    ),
)
def test_retired_collection_projection_routes_are_not_registered(
    app_client,
    retired_path,
):
    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections",
        json={"name": "Maintained Objective Flow"},
    )
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    response = app_client.get(
        f"{API_V1_PREFIX}{retired_path.format(collection_id=collection_id)}"
    )

    assert response.status_code == 404



@pytest.fixture()
def app_client(monkeypatch, tmp_path, auth_session_service, collection_service):
    import application.pipeline.collection_build.service as task_runner_module
    from application.source.task_service import TaskService

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin-password")
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    from main import create_app

    monkeypatch.setattr("main.DATA_DIR", tmp_path)
    build_repository = MemoryBuildRepository()
    task_service = TaskService(build_repository)
    source_artifact_repository = MemorySourceArtifactRepository()
    paper_fact_repository = MemoryPaperFactRepository()
    objective_repository = MemoryObjectiveRepository()
    finding_review_repository = InMemoryObjectiveReviewRepository()
    experiment_plan_repository = InMemoryExperimentPlanRepository()

    async def fake_build_source_artifacts(**kwargs):  # noqa: ANN003
        output_dir = Path(kwargs["config"].output.base_dir)
        return [DummyWorkflowOutput(result=_write_source_artifact_outputs(output_dir))]

    monkeypatch.setattr(
        task_runner_module, "build_source_artifacts", fake_build_source_artifacts
    )
    with TestClient(
        create_app(
            auth_session_service=auth_session_service,
            collection_service=collection_service,
            task_service=task_service,
            source_artifact_repository=source_artifact_repository,
            paper_fact_repository=paper_fact_repository,
            objective_repository=objective_repository,
            finding_review_repository=finding_review_repository,
            experiment_plan_repository=experiment_plan_repository,
            chat_repository=MemoryChatRepository(),
        )
    ) as client:
        login_response = client.post(
            f"{API_V1_PREFIX}/auth/login",
            json={"email": "admin@example.com", "password": "admin-password"},
        )
        assert login_response.status_code == 200
        yield client


def test_objective_experiment_plan_routes_are_registered(app_client):
    openapi = app_client.get("/api/openapi.json")
    assert openapi.status_code == 200
    paths = openapi.json()["paths"]
    plan_list_path = (
        f"{API_V1_PREFIX}/collections/{{collection_id}}/objectives/{{objective_id}}/"
        "experiment-plans"
    )
    plan_detail_path = f"{plan_list_path}/{{plan_id}}"

    assert "get" in paths[plan_list_path]
    assert "post" in paths[plan_list_path]
    assert "patch" in paths[plan_detail_path]


def test_collection_task_flow(app_client):
    collection_id, task_id = _create_built_collection(app_client)

    task_status = app_client.get(f"{API_V1_PREFIX}/tasks/{task_id}")
    assert task_status.status_code == 200
    assert task_status.json()["task_type"] == "build"
    assert task_status.json()["status"] == "completed"
    assert task_status.json()["current_stage"] == "artifacts_ready"

    collection_tasks = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/tasks"
    )
    assert collection_tasks.status_code == 200
    tasks_body = collection_tasks.json()
    assert tasks_body["collection_id"] == collection_id
    assert tasks_body["count"] >= 1
    assert tasks_body["items"][0]["task_id"] == task_id
    assert tasks_body["items"][0]["task_type"] == "build"

    completed_tasks = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/tasks",
        params={"status": "completed", "limit": 5, "offset": 0},
    )
    assert completed_tasks.status_code == 200
    assert completed_tasks.json()["count"] >= 1

    artifacts = app_client.get(f"{API_V1_PREFIX}/tasks/{task_id}/artifacts")
    assert artifacts.status_code == 200
    body = artifacts.json()
    assert body["documents_generated"] is True
    assert body["documents_ready"] is True
    assert body["blocks_generated"] is True
    assert body["blocks_ready"] is True
    assert body["figures_generated"] is True
    assert body["figures_ready"] is False
    assert body["table_rows_generated"] is True
    assert body["table_rows_ready"] is False
    assert body["table_cells_generated"] is True
    assert body["table_cells_ready"] is False

    profiles = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/documents/profiles"
    )
    assert profiles.status_code == 200
    profiles_body = profiles.json()
    assert profiles_body["count"] == 1
    assert profiles_body["items"][0]["title"] == "Composite Paper"
    assert profiles_body["items"][0]["source_filename"] == "paper.txt"
    assert profiles_body["items"][0]["doc_type"] == "experimental"

    document_id = profiles_body["items"][0]["document_id"]
    profile = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/documents/{document_id}/profile"
    )
    assert profile.status_code == 200
    assert profile.json()["document_id"] == document_id


def test_goal_intake_creates_collection_and_converges_on_workspace(app_client):
    response = app_client.post(
        f"{API_V1_PREFIX}/goals/intake",
        json={
            "material_system": "Li metal",
            "target_property": "cycling stability",
            "intent": "compare",
            "constraints": {"electrolyte": "carbonate"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    collection_id = payload["seed_collection"]["collection_id"]

    assert payload["coverage_assessment"]["level"] == "direct"
    assert payload["entry_recommendation"]["recommended_mode"] == "comparison"
    assert payload["seed_collection"]["source_channels"] == ["upload"]
    assert payload["seed_collection"]["handoff_id"].startswith("handoff_")
    assert payload["seed_collection"]["handoff_status"] == "awaiting_source_material"

    workspace = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/workspace")
    assert workspace.status_code == 200
    workspace_body = workspace.json()
    assert workspace_body["collection"]["collection_id"] == collection_id
    assert workspace_body["file_count"] == 0
    assert workspace_body["status_summary"] == "empty"



def test_delete_collection_removes_app_layer_collection(app_client):
    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections", json={"name": "Delete Me"}
    )
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    get_resp = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}")
    assert get_resp.status_code == 200

    delete_resp = app_client.delete(f"{API_V1_PREFIX}/collections/{collection_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["collection_id"] == collection_id

    missing_resp = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}")
    assert missing_resp.status_code == 404

    list_resp = app_client.get(f"{API_V1_PREFIX}/collections")
    assert list_resp.status_code == 200
    assert all(
        item["collection_id"] != collection_id for item in list_resp.json()["items"]
    )


def test_collection_contract_hides_default_method_and_ignores_legacy_payload(
    app_client,
):
    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections",
        json={
            "name": "Compat Collection",
            "description": "legacy client payload",
            "default_method": "fast",
        },
    )
    assert create_resp.status_code == 200
    create_body = create_resp.json()
    collection_id = create_body["collection_id"]
    assert "default_method" not in create_body

    get_resp = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}")
    assert get_resp.status_code == 200
    assert "default_method" not in get_resp.json()

    list_resp = app_client.get(f"{API_V1_PREFIX}/collections")
    assert list_resp.status_code == 200
    created_item = next(
        item
        for item in list_resp.json()["items"]
        if item["collection_id"] == collection_id
    )
    assert "default_method" not in created_item


def test_build_task_contract_ignores_legacy_engine_fields(app_client, monkeypatch):
    import application.pipeline.collection_build.service as task_runner_module

    captured: dict[str, object] = {}

    async def capturing_build_source_artifacts(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        output_dir = Path(kwargs["config"].output.base_dir)
        return [DummyWorkflowOutput(result=_write_source_artifact_outputs(output_dir))]

    monkeypatch.setattr(
        task_runner_module,
        "build_source_artifacts",
        capturing_build_source_artifacts,
    )

    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections",
        json={"name": "Legacy Task Contract"},
    )
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    upload_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/files",
        files={
            "file": (
                "paper.txt",
                b"Experimental Section\nMix and anneal.",
                "text/plain",
            )
        },
    )
    assert upload_resp.status_code == 200

    task_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/tasks/build",
        json={
            "mode": "fast",
            "method": "fast",
            "is_update_run": True,
            "verbose": True,
            "additional_context": {"caller": "legacy-frontend"},
        },
    )
    assert task_resp.status_code == 200

    task_id = task_resp.json()["task_id"]
    task_status = _wait_for_task_terminal(app_client, task_id)
    assert task_status["task_type"] == "build"
    assert task_status["status"] == "completed"

    assert captured["method"] == task_runner_module.IndexingMethod.Fast
    build = app_client.portal.call(
        app_client.app.state.task_service.repository.read_build,
        task_id,
    )
    assert build is not None
    assert build.mode == "fast"
    assert "is_update_run" not in captured
    assert captured["verbose"] is True
    assert captured["additional_context"] == {"caller": "legacy-frontend"}


def test_build_task_contract_rejects_unknown_pipeline_mode(app_client):
    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections",
        json={"name": "Invalid Pipeline Mode"},
    )
    collection_id = create_resp.json()["collection_id"]
    app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/files",
        files={"file": ("paper.txt", b"Paper", "text/plain")},
    )

    response = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/tasks/build",
        json={"mode": "unknown"},
    )

    assert response.status_code == 422
