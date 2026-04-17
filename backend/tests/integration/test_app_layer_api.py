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


def _write_community_outputs(output_dir: Path) -> None:
    communities = pd.DataFrame(
        [
            {
                "id": "community-1",
                "human_readable_id": 1,
                "community": 1,
                "level": 1,
                "title": "Community 1",
                "entity_ids": ["ent-1", "ent-2"],
            }
        ]
    )
    communities.to_parquet(output_dir / "communities.parquet", index=False)


def _write_core_graph_outputs(output_dir: Path, collection_id: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "document_id": "paper-1",
                "collection_id": collection_id,
                "title": "Core Projection Paper",
                "source_filename": "paper.txt",
                "doc_type": "experimental",
                "protocol_extractable": "yes",
                "protocol_extractability_signals": ["methods_section_detected"],
                "parsing_warnings": [],
                "confidence": 0.91,
            }
        ]
    ).to_parquet(output_dir / "document_profiles.parquet", index=False)
    pd.DataFrame(
        [
            {
                "evidence_id": "ev-1",
                "document_id": "paper-1",
                "collection_id": collection_id,
                "claim_text": "Conductivity increased to 12 mS/cm after annealing.",
                "claim_type": "property",
                "evidence_source_type": "text",
                "evidence_anchors": [
                    {
                        "anchor_id": "anchor-1",
                        "source_type": "text",
                        "section_id": None,
                        "block_id": None,
                        "snippet_id": "tu-1",
                        "figure_or_table": None,
                        "quote_span": "Conductivity increased to 12 mS/cm after annealing.",
                    }
                ],
                "material_system": {"family": "oxide cathode", "composition": None},
                "condition_context": {
                    "process": {"temperatures_c": [700.0]},
                    "baseline": {"control": "as-prepared"},
                    "test": {"method": "EIS"},
                },
                "confidence": 0.83,
                "traceability_status": "direct",
            }
        ]
    ).to_parquet(output_dir / "evidence_cards.parquet", index=False)
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


def _create_indexed_collection(app_client, name: str = "Composite Set") -> tuple[str, str]:  # noqa: ANN001
    create_resp = app_client.post(f"{API_V1_PREFIX}/collections", json={"name": name})
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
    return collection_id, task_id


@pytest.fixture()
def app_client(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from fastapi import FastAPI
    from controllers import collections as collections_controller
    from controllers import comparisons as comparisons_controller
    from controllers import documents as documents_controller
    from controllers import evidence as evidence_controller
    from controllers import goals as goals_controller
    from controllers import graph as graph_controller
    from controllers import protocol as protocol_controller
    from controllers import reports as reports_controller
    from controllers import tasks as tasks_controller
    from controllers import workspace as workspace_controller
    from controllers.schemas import (
        ReportCommunityDetailResponse,
        ReportCommunityListResponse,
        ReportPatternsResponse,
    )
    import application.graph.service as graph_service_module
    import application.indexing.index_task_runner as task_runner_module
    import application.reports.service as report_service_module
    from application.workspace.artifact_registry_service import ArtifactRegistryService
    from application.collections.service import CollectionService
    from application.comparisons.service import ComparisonService
    from application.documents.service import DocumentProfileService
    from application.evidence.service import EvidenceCardService
    from application.goals.service import GoalService
    from application.indexing.index_task_runner import IndexTaskRunner
    from application.indexing.task_service import TaskService
    from application.workspace.service import WorkspaceService

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
    goal_service = GoalService(collection_service)

    default_config = tmp_path / "configs" / "default.yaml"
    default_config.parent.mkdir(parents=True, exist_ok=True)
    default_config.write_text("dummy: true\n", encoding="utf-8")

    async def fake_build_index(**kwargs):  # noqa: ANN003
        output_dir = Path(kwargs["config"].output.base_dir)
        _write_index_outputs(output_dir)
        return [DummyWorkflowOutput()]

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
    monkeypatch.setattr(goals_controller, "goal_service", goal_service)
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
    app.include_router(reports_controller.router, prefix=API_V1_PREFIX)
    app.include_router(collections_controller.router, prefix=API_V1_PREFIX)
    app.include_router(goals_controller.router, prefix=API_V1_PREFIX)
    app.include_router(graph_controller.router, prefix=API_V1_PREFIX)
    app.include_router(protocol_controller.router, prefix=API_V1_PREFIX)
    app.include_router(tasks_controller.router, prefix=API_V1_PREFIX)
    app.include_router(workspace_controller.router, prefix=API_V1_PREFIX)
    app.include_router(documents_controller.router, prefix=API_V1_PREFIX)
    app.include_router(evidence_controller.router, prefix=API_V1_PREFIX)
    app.include_router(comparisons_controller.router, prefix=API_V1_PREFIX)
    return TestClient(app)


def test_collection_task_flow(app_client):
    collection_id, task_id = _create_indexed_collection(app_client)

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
    assert body["documents_generated"] is True
    assert body["documents_ready"] is True
    assert body["document_profiles_generated"] is True
    assert body["document_profiles_ready"] is True
    assert body["evidence_cards_generated"] is True
    assert body["evidence_cards_ready"] is True
    assert body["comparison_rows_generated"] is True
    assert body["comparison_rows_ready"] is True
    assert body["graph_generated"] is True
    assert body["graph_ready"] is True
    assert body["sections_generated"] is True
    assert body["sections_ready"] is True
    assert body["protocol_steps_generated"] is True
    assert body["protocol_steps_ready"] is True

    graph = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/graph")
    assert graph.status_code == 200
    graph_body = graph.json()
    assert graph_body["collection_id"] == collection_id
    assert len(graph_body["nodes"]) >= 3
    assert len(graph_body["edges"]) >= 2
    assert {item["type"] for item in graph_body["nodes"]} >= {
        "document",
        "evidence",
        "comparison",
    }

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
    assert profiles_body["items"][0]["title"] == "Composite Paper"
    assert profiles_body["items"][0]["source_filename"] == "paper.txt"
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


def test_graph_endpoint_returns_collection_not_found_error(app_client):
    graph = app_client.get(f"{API_V1_PREFIX}/collections/col_missing/graph")
    assert graph.status_code == 404
    detail = graph.json()["detail"]
    assert detail["code"] == "collection_not_found"
    assert detail["collection_id"] == "col_missing"


def test_graph_endpoints_return_readiness_error_until_artifacts_exist(app_client):
    create_resp = app_client.post(f"{API_V1_PREFIX}/collections", json={"name": "Pending Graph"})
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    graph = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/graph")
    assert graph.status_code == 409
    graph_detail = graph.json()["detail"]
    assert graph_detail["code"] == "graph_not_ready"
    assert graph_detail["collection_id"] == collection_id
    assert "document_profiles.parquet" in graph_detail["missing_artifacts"]
    assert "evidence_cards.parquet" in graph_detail["missing_artifacts"]
    assert "comparison_rows.parquet" in graph_detail["missing_artifacts"]

    graphml = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/graphml")
    assert graphml.status_code == 409
    graphml_detail = graphml.json()["detail"]
    assert graphml_detail["code"] == "graph_not_ready"
    assert graphml_detail["collection_id"] == collection_id


def test_graph_endpoint_rejects_legacy_community_filter(app_client):
    collection_id, _task_id = _create_indexed_collection(app_client, name="Community Graph")
    graph = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/graph",
        params={"community_id": "999"},
    )
    assert graph.status_code == 400
    detail = graph.json()["detail"]
    assert detail["code"] == "graph_filter_not_supported"
    assert detail["collection_id"] == collection_id
    assert detail["filter_name"] == "community_id"

def test_graph_endpoints_serve_core_projection_without_legacy_graph_outputs(
    app_client,
):
    from controllers import graph as graph_controller

    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections",
        json={"name": "Core Graph Only"},
    )
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    workspace = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/workspace")
    assert workspace.status_code == 200
    output_dir = Path(workspace.json()["artifacts"]["output_path"])

    _write_core_graph_outputs(output_dir, collection_id)
    graph_controller.graph_service.artifact_registry_service.upsert(
        collection_id,
        output_dir,
    )

    graph = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/graph")
    assert graph.status_code == 200
    payload = graph.json()
    assert payload["collection_id"] == collection_id
    assert payload["community"] is None
    assert len(payload["nodes"]) == 3
    assert len(payload["edges"]) == 2
    assert {item["type"] for item in payload["nodes"]} == {
        "document",
        "evidence",
        "comparison",
    }

    graphml = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/graphml")
    assert graphml.status_code == 200
    assert graphml.headers["content-type"].startswith("application/graphml+xml")
    assert b"<graphml" in graphml.content


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


def test_collection_contract_hides_default_method_and_ignores_legacy_payload(app_client):
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
        item for item in list_resp.json()["items"] if item["collection_id"] == collection_id
    )
    assert "default_method" not in created_item


def test_index_task_contract_ignores_legacy_engine_fields(app_client, monkeypatch):
    import application.indexing.index_task_runner as task_runner_module

    captured: dict[str, object] = {}

    async def capturing_build_index(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        output_dir = Path(kwargs["config"].output.base_dir)
        _write_index_outputs(output_dir)
        return [DummyWorkflowOutput()]

    monkeypatch.setattr(task_runner_module, "build_index", capturing_build_index)

    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections",
        json={"name": "Legacy Task Contract"},
    )
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    upload_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/files",
        files={"file": ("paper.txt", b"Experimental Section\nMix and anneal.", "text/plain")},
    )
    assert upload_resp.status_code == 200

    task_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/tasks/index",
        json={
            "method": "fast",
            "is_update_run": True,
            "verbose": True,
            "additional_context": {"caller": "legacy-frontend"},
        },
    )
    assert task_resp.status_code == 200

    task_id = task_resp.json()["task_id"]
    task_status = app_client.get(f"{API_V1_PREFIX}/tasks/{task_id}")
    assert task_status.status_code == 200
    assert task_status.json()["status"] == "completed"

    assert captured["method"] == task_runner_module.IndexingMethod.Standard
    assert "is_update_run" not in captured
    assert captured["verbose"] is True
    assert captured["additional_context"] == {"caller": "legacy-frontend"}


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
    assert workspace_body["artifacts"]["protocol_steps_generated"] is False
    assert workspace_body["artifacts"]["protocol_steps_ready"] is False
    assert workspace_body["capabilities"]["can_view_protocol_steps"] is False

    steps = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/protocol/steps")
    assert steps.status_code == 409
    steps_detail = steps.json()["detail"]
    assert steps_detail["code"] == "protocol_artifacts_not_ready"
    assert steps_detail["collection_id"] == collection_id
    assert steps_detail["artifacts"]["protocol_steps_generated"] is False
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


def test_collection_protocol_steps_returns_empty_list_when_generated_but_not_ready(
    app_client,
):
    from controllers import protocol as protocol_controller

    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections",
        json={"name": "Generated But Empty Protocol"},
    )
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    workspace = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/workspace")
    assert workspace.status_code == 200
    output_dir = Path(workspace.json()["artifacts"]["output_path"])
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame().to_parquet(output_dir / "protocol_steps.parquet", index=False)
    protocol_controller.artifact_registry_service.upsert(collection_id, output_dir)

    workspace_after = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/workspace"
    )
    assert workspace_after.status_code == 200
    artifacts = workspace_after.json()["artifacts"]
    assert artifacts["protocol_steps_generated"] is True
    assert artifacts["protocol_steps_ready"] is False
    assert workspace_after.json()["capabilities"]["can_view_protocol_steps"] is True

    steps = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/protocol/steps")
    assert steps.status_code == 200
    payload = steps.json()
    assert payload["total"] == 0
    assert payload["count"] == 0
    assert payload["items"] == []


def test_reports_routes_are_exposed(app_client):
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
