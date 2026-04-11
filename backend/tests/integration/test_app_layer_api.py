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

API_V1_PREFIX = "/api/v1"


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
    entities = pd.DataFrame(
        [
            {
                "id": "ent-1",
                "title": "epoxy",
                "type": "material",
                "description": "matrix",
                "degree": 3,
                "frequency": 2,
                "x": 0.1,
                "y": 0.2,
            },
            {
                "id": "ent-2",
                "title": "SiO2",
                "type": "material",
                "description": "filler",
                "degree": 2,
                "frequency": 1,
                "x": 0.3,
                "y": 0.4,
            },
        ]
    )
    relationships = pd.DataFrame(
        [
            {
                "id": "rel-1",
                "source": "epoxy",
                "target": "SiO2",
                "weight": 1.0,
                "description": "composite relation",
                "rank": 1,
            }
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    entities.to_parquet(output_dir / "entities.parquet", index=False)
    relationships.to_parquet(output_dir / "relationships.parquet", index=False)


@pytest.fixture()
def app_client(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)
    monkeypatch.setenv("LENS_ENABLE_MOCK_API", "1")

    from fastapi import FastAPI
    from controllers import collections as collections_controller
    from controllers import comparisons as comparisons_controller
    from controllers import documents as documents_controller
    from controllers import evidence as evidence_controller
    from controllers import graph as graph_controller
    from controllers import protocol as protocol_controller
    from controllers import query as query_controller
    from controllers import reports as reports_controller
    from controllers import tasks as tasks_controller
    from controllers import workspace as workspace_controller
    from controllers.schemas import (
        QueryResponse,
        ReportCommunityDetailResponse,
        ReportCommunityListResponse,
        ReportPatternsResponse,
    )
    import application.graph_service as graph_service_module
    import application.index_task_runner as task_runner_module
    import application.query_service as query_service_module
    import application.report_service as report_service_module
    from application.artifact_registry_service import ArtifactRegistryService
    from application.collection_service import CollectionService
    from application.comparisons.service import ComparisonService
    from application.documents.service import DocumentProfileService
    from application.evidence.service import EvidenceCardService
    from application.index_task_runner import IndexTaskRunner
    from application.task_service import TaskService
    from application.workspace_service import WorkspaceService

    collection_service = CollectionService(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
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
    runner = IndexTaskRunner(
        collection_service,
        task_service,
        artifact_registry,
        document_profile_service,
        evidence_card_service,
        comparison_service,
    )
    workspace_service = WorkspaceService(
        collection_service,
        task_service,
        artifact_registry,
        document_profile_service,
    )

    default_config = tmp_path / "configs" / "default.yaml"
    default_config.parent.mkdir(parents=True, exist_ok=True)
    default_config.write_text("dummy: true\n", encoding="utf-8")

    async def fake_build_index(**kwargs):  # noqa: ANN003
        output_dir = Path(kwargs["config"].output.base_dir)
        _write_index_outputs(output_dir)
        return [DummyWorkflowOutput()]

    async def fake_query_index(payload):  # noqa: ANN001
        return QueryResponse(
            answer="stub-answer",
            method=str(payload.method),
            collection_id=payload.collection_id or "default",
            output_path=str(tmp_path / "output"),
            context_data=None,
        )

    def fake_list_community_reports(  # noqa: ANN001
        collection_id, level, limit, offset, min_size, sort
    ):
        return ReportCommunityListResponse(
            collection_id=collection_id,
            level=level,
            total=0,
            count=0,
            items=[],
        )

    def fake_get_community_report_detail(  # noqa: ANN001
        collection_id, community_id, level, entity_limit, relationship_limit, document_limit
    ):
        parsed_community_id = int(community_id) if str(community_id).isdigit() else None
        return ReportCommunityDetailResponse(
            collection_id=collection_id,
            community_id=parsed_community_id,
            human_readable_id=parsed_community_id,
            level=level,
            parent=None,
            children=None,
            title=None,
            summary=None,
            findings=None,
            rating=None,
            size=None,
            document_count=0,
            text_unit_count=0,
            entities=[],
            relationships=[],
            documents=[],
        )

    def fake_list_patterns(collection_id, level, limit, sort):  # noqa: ANN001
        return ReportPatternsResponse(
            collection_id=collection_id,
            level=level,
            total_communities=0,
            total_entities=0,
            total_relationships=0,
            total_documents=0,
            count=0,
            items=[],
        )

    monkeypatch.setattr(collections_controller, "collection_service", collection_service)
    monkeypatch.setattr(graph_controller.graph_service, "collection_service", collection_service)
    monkeypatch.setattr(graph_controller.graph_service, "artifact_registry_service", artifact_registry)
    monkeypatch.setattr(protocol_controller, "collection_service", collection_service)
    monkeypatch.setattr(protocol_controller, "artifact_registry_service", artifact_registry)
    monkeypatch.setattr(tasks_controller, "collection_service", collection_service)
    monkeypatch.setattr(tasks_controller, "task_service", task_service)
    monkeypatch.setattr(tasks_controller, "artifact_registry_service", artifact_registry)
    monkeypatch.setattr(tasks_controller, "index_task_runner", runner)
    monkeypatch.setattr(task_runner_module, "CONFIG_DIR", default_config.parent)
    monkeypatch.setattr(task_runner_module, "load_config", lambda *args, **kwargs: _build_config(Path("placeholder-output"), Path("placeholder-input")))
    monkeypatch.setattr(task_runner_module, "build_index", fake_build_index)
    monkeypatch.setattr(graph_service_module, "collection_service", collection_service)
    monkeypatch.setattr(graph_service_module, "artifact_registry_service", artifact_registry)
    monkeypatch.setattr(workspace_controller, "workspace_service", workspace_service)
    monkeypatch.setattr(documents_controller, "document_profile_service", document_profile_service)
    monkeypatch.setattr(evidence_controller, "evidence_card_service", evidence_card_service)
    monkeypatch.setattr(comparisons_controller, "comparison_service", comparison_service)
    monkeypatch.setattr(query_service_module, "query_index", fake_query_index)
    monkeypatch.setattr(
        report_service_module,
        "list_community_reports",
        fake_list_community_reports,
    )
    monkeypatch.setattr(
        report_service_module,
        "get_community_report_detail",
        fake_get_community_report_detail,
    )
    monkeypatch.setattr(report_service_module, "list_patterns", fake_list_patterns)

    app = FastAPI()
    app.include_router(query_controller.router, prefix=API_V1_PREFIX)
    app.include_router(reports_controller.router, prefix=API_V1_PREFIX)
    app.include_router(collections_controller.router, prefix=API_V1_PREFIX)
    app.include_router(graph_controller.router, prefix=API_V1_PREFIX)
    app.include_router(protocol_controller.router, prefix=API_V1_PREFIX)
    app.include_router(tasks_controller.router, prefix=API_V1_PREFIX)
    app.include_router(workspace_controller.router, prefix=API_V1_PREFIX)
    app.include_router(documents_controller.router, prefix=API_V1_PREFIX)
    app.include_router(evidence_controller.router, prefix=API_V1_PREFIX)
    app.include_router(comparisons_controller.router, prefix=API_V1_PREFIX)
    return TestClient(app)


def test_collection_task_and_query_flow(app_client):
    create_resp = app_client.post(f"{API_V1_PREFIX}/collections", json={"name": "Composite Set"})
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    upload_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/files",
        files={"file": ("paper.txt", b"Experimental Section\nMix and anneal.", "text/plain")},
    )
    assert upload_resp.status_code == 200

    task_resp = app_client.post(f"{API_V1_PREFIX}/collections/{collection_id}/tasks/index", json={})
    assert task_resp.status_code == 200
    task_id = task_resp.json()["task_id"]

    task_status = app_client.get(f"{API_V1_PREFIX}/tasks/{task_id}")
    assert task_status.status_code == 200
    assert task_status.json()["status"] == "completed"
    assert task_status.json()["current_stage"] == "artifacts_ready"

    collection_tasks = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/tasks")
    assert collection_tasks.status_code == 200
    tasks_body = collection_tasks.json()
    assert tasks_body["collection_id"] == collection_id
    assert tasks_body["count"] >= 1
    assert tasks_body["items"][0]["task_id"] == task_id

    completed_tasks = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/tasks",
        params={"status": "completed", "limit": 5, "offset": 0},
    )
    assert completed_tasks.status_code == 200
    assert completed_tasks.json()["count"] >= 1

    artifacts = app_client.get(f"{API_V1_PREFIX}/tasks/{task_id}/artifacts")
    assert artifacts.status_code == 200
    body = artifacts.json()
    assert body["documents_ready"] is True
    assert body["document_profiles_ready"] is True
    assert body["evidence_cards_ready"] is True
    assert body["comparison_rows_ready"] is True
    assert body["graph_ready"] is True
    assert body["sections_ready"] is True
    assert body["protocol_steps_ready"] is True

    graph = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/graph")
    assert graph.status_code == 200
    graph_body = graph.json()
    assert len(graph_body["nodes"]) == 2
    assert len(graph_body["edges"]) == 1

    graphml = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/graphml")
    assert graphml.status_code == 200
    assert graphml.headers["content-type"].startswith("application/graphml+xml")

    steps = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/protocol/steps")
    assert steps.status_code == 200
    assert steps.json()["count"] >= 1

    profiles = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/documents/profiles")
    assert profiles.status_code == 200
    profiles_body = profiles.json()
    assert profiles_body["count"] == 1
    assert profiles_body["items"][0]["doc_type"] == "experimental"
    assert profiles_body["items"][0]["protocol_extractable"] == "yes"

    evidence = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/evidence/cards")
    assert evidence.status_code == 200
    evidence_body = evidence.json()
    assert evidence_body["count"] >= 2
    assert evidence_body["items"][0]["traceability_status"] in {"direct", "partial"}

    comparisons = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/comparisons")
    assert comparisons.status_code == 200
    comparisons_body = comparisons.json()
    assert comparisons_body["count"] >= 1
    assert comparisons_body["items"][0]["comparability_status"] in {
        "comparable",
        "limited",
        "not_comparable",
        "insufficient",
    }


def test_mock_collection_resources_are_available_for_frontend_integration(app_client):
    collections = app_client.get(f"{API_V1_PREFIX}/collections")
    assert collections.status_code == 200
    collection_ids = {item["collection_id"] for item in collections.json()["items"]}
    assert "col_mock_empty" in collection_ids
    assert "col_mock_processing" in collection_ids
    assert "col_mock_ready" in collection_ids
    assert "col_mock_limited" in collection_ids

    workspace = app_client.get(f"{API_V1_PREFIX}/collections/col_mock_ready/workspace")
    assert workspace.status_code == 200
    workspace_body = workspace.json()
    assert workspace_body["workflow"]["documents"]["status"] == "ready"
    assert workspace_body["workflow"]["comparisons"]["status"] == "ready"
    assert workspace_body["links"]["comparisons"] == "/api/v1/collections/col_mock_ready/comparisons"

    profiles = app_client.get(f"{API_V1_PREFIX}/collections/col_mock_ready/documents/profiles")
    assert profiles.status_code == 200
    profiles_body = profiles.json()
    assert profiles_body["count"] == 3
    assert profiles_body["summary"]["by_doc_type"]["experimental"] == 2

    evidence = app_client.get(f"{API_V1_PREFIX}/collections/col_mock_ready/evidence/cards")
    assert evidence.status_code == 200
    evidence_body = evidence.json()
    assert evidence_body["count"] == 3
    assert evidence_body["items"][0]["traceability_status"] == "direct"

    comparisons = app_client.get(f"{API_V1_PREFIX}/collections/col_mock_ready/comparisons")
    assert comparisons.status_code == 200
    comparisons_body = comparisons.json()
    assert comparisons_body["count"] == 2
    assert comparisons_body["items"][0]["comparability_status"] == "comparable"

    tasks = app_client.get(f"{API_V1_PREFIX}/collections/col_mock_processing/tasks")
    assert tasks.status_code == 200
    tasks_body = tasks.json()
    assert tasks_body["count"] == 1
    assert tasks_body["items"][0]["status"] == "running"

    task_detail = app_client.get(f"{API_V1_PREFIX}/tasks/task_mock_limited_index")
    assert task_detail.status_code == 200
    assert task_detail.json()["status"] == "partial_success"

    task_artifacts = app_client.get(f"{API_V1_PREFIX}/tasks/task_mock_ready_index/artifacts")
    assert task_artifacts.status_code == 200
    assert task_artifacts.json()["documents_ready"] is True
    assert steps.json()["items"][0]["paper_title"] == "Composite Paper"

    search = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/protocol/search",
        params={"q": "anneal Ar", "limit": 5},
    )
    assert search.status_code == 200
    assert search.json()["count"] >= 1
    assert search.json()["items"][0]["paper_title"] == "Composite Paper"

    sop = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/protocol/sop",
        json={"goal": "Design a composite SOP", "target_properties": ["mechanical", "thermal"]},
    )
    assert sop.status_code == 200
    sop_body = sop.json()
    assert sop_body["collection_id"] == collection_id
    assert sop_body["sop_draft"]["objective"] == "Design a composite SOP"
    assert sop_body["sop_draft"]["steps"][0]["paper_title"] == "Composite Paper"

    workspace = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/workspace")
    assert workspace.status_code == 200
    workspace_body = workspace.json()
    assert workspace_body["collection"]["collection_id"] == collection_id
    assert workspace_body["status_summary"] == "ready"
    assert workspace_body["workflow"]["documents"]["status"] == "ready"
    assert workspace_body["workflow"]["evidence"]["status"] == "ready"
    assert workspace_body["workflow"]["comparisons"]["status"] == "ready"
    assert workspace_body["capabilities"]["can_view_graph"] is True
    assert workspace_body["capabilities"]["can_generate_sop"] is True
    assert workspace_body["latest_task"]["task_id"] == task_id


def test_delete_collection_removes_app_layer_collection(app_client):
    create_resp = app_client.post(f"{API_V1_PREFIX}/collections", json={"name": "Delete Me"})
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


def test_collection_protocol_endpoints_return_readiness_error_until_artifacts_exist(app_client):
    create_resp = app_client.post(f"{API_V1_PREFIX}/collections", json={"name": "Pending Collection"})
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    upload_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/files",
        files={"file": ("paper.txt", b"Experimental Section\nMix and anneal.", "text/plain")},
    )
    assert upload_resp.status_code == 200

    workspace = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/workspace")
    assert workspace.status_code == 200
    workspace_body = workspace.json()
    assert workspace_body["artifacts"]["protocol_steps_ready"] is False
    assert workspace_body["capabilities"]["can_view_protocol_steps"] is False

    steps = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/protocol/steps")
    assert steps.status_code == 409
    steps_detail = steps.json()["detail"]
    assert steps_detail["code"] == "protocol_artifacts_not_ready"
    assert steps_detail["collection_id"] == collection_id
    assert steps_detail["artifacts"]["protocol_steps_ready"] is False

    search = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/protocol/search",
        params={"q": "anneal", "limit": 5},
    )
    assert search.status_code == 409
    assert search.json()["detail"]["code"] == "protocol_artifacts_not_ready"

    sop = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/protocol/sop",
        json={"goal": "Build a draft SOP"},
    )
    assert sop.status_code == 409
    assert sop.json()["detail"]["code"] == "protocol_artifacts_not_ready"


def test_public_query_and_reports_routes_are_exposed(app_client):
    query_resp = app_client.post(f"{API_V1_PREFIX}/query", json={"query": "status"})
    assert query_resp.status_code == 200
    assert query_resp.json()["answer"] == "stub-answer"

    reports_resp = app_client.get(f"{API_V1_PREFIX}/collections/demo/reports/communities")
    assert reports_resp.status_code == 200
    assert reports_resp.json()["collection_id"] == "demo"

    detail_resp = app_client.get(
        f"{API_V1_PREFIX}/collections/demo/reports/communities/42"
    )
    assert detail_resp.status_code == 200
    assert detail_resp.json()["community_id"] == 42

    patterns_resp = app_client.get(f"{API_V1_PREFIX}/collections/demo/reports/patterns")
    assert patterns_resp.status_code == 200
    assert patterns_resp.json()["collection_id"] == "demo"
