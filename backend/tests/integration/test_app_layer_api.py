from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

if "devtools" not in sys.modules:
    sys.modules["devtools"] = SimpleNamespace(pformat=lambda value: str(value))

import pytest
from infra.source.runtime.source_evidence import build_blocks, build_table_cells, build_table_rows

try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False

if not FASTAPI_AVAILABLE:  # pragma: no cover
    pytest.skip("fastapi not installed", allow_module_level=True)

API_V1_PREFIX = "/api/v1"


class DummyWorkflowOutput:
    def __init__(self, workflow: str = "build", errors: list[str] | None = None):
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


def _write_source_artifact_outputs(output_dir: Path) -> None:
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
                        "Flexural strength increased to 97 MPa relative to the untreated baseline.",
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
                "text": "Flexural strength increased to 97 MPa relative to the untreated baseline.",
                "document_ids": ["paper-1"],
            },
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    build_blocks(documents, text_units).to_parquet(output_dir / "blocks.parquet", index=False)
    pd.DataFrame(columns=["figure_id"]).to_parquet(output_dir / "figures.parquet", index=False)
    build_table_rows(documents, text_units).to_parquet(output_dir / "table_rows.parquet", index=False)
    build_table_cells(documents, text_units).to_parquet(output_dir / "table_cells.parquet", index=False)


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


def _create_built_collection(app_client, name: str = "Composite Set") -> tuple[str, str]:  # noqa: ANN001
    create_resp = app_client.post(f"{API_V1_PREFIX}/collections", json={"name": name})
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    upload_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/files",
        files={"file": ("paper.txt", b"Experimental Section\nMix and anneal.", "text/plain")},
    )
    assert upload_resp.status_code == 200

    task_resp = app_client.post(f"{API_V1_PREFIX}/collections/{collection_id}/tasks/build", json={})
    assert task_resp.status_code == 200
    task_id = task_resp.json()["task_id"]
    return collection_id, task_id


def test_request_id_is_generated_and_echoed(app_client):
    response = app_client.get(f"{API_V1_PREFIX}/collections")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"].startswith("req_")


def test_request_id_is_echoed_and_propagated_to_background_build(app_client, monkeypatch):
    import application.source.collection_build_task_runner as task_runner_module
    from utils.logger import REQUEST_ID_HEADER, get_request_id

    captured: dict[str, str | None] = {}

    async def fake_build_source_artifacts(**kwargs):  # noqa: ANN003
        captured["bound_request_id"] = get_request_id()
        output_dir = Path(kwargs["config"].output.base_dir)
        _write_source_artifact_outputs(output_dir)
        return [DummyWorkflowOutput()]

    monkeypatch.setattr(task_runner_module, "build_source_artifacts", fake_build_source_artifacts)

    create_resp = app_client.post(f"{API_V1_PREFIX}/collections", json={"name": "Request ID Set"})
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    upload_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/files",
        files={"file": ("paper.txt", b"Experimental Section\nMix and anneal.", "text/plain")},
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
    assert captured["bound_request_id"] == request_id


def test_legacy_index_task_route_is_not_registered(app_client):
    create_resp = app_client.post(f"{API_V1_PREFIX}/collections", json={"name": "Legacy Route"})
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    upload_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/files",
        files={"file": ("paper.txt", b"Experimental Section\nMix and anneal.", "text/plain")},
    )
    assert upload_resp.status_code == 200

    task_resp = app_client.post(f"{API_V1_PREFIX}/collections/{collection_id}/tasks/index", json={})
    assert task_resp.status_code == 404


@pytest.fixture()
def app_client(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    from controllers.source import collections as collections_controller
    from controllers.core import comparisons as comparisons_controller
    from controllers.core import documents as documents_controller
    from controllers.core import evidence as evidence_controller
    from controllers.goal import intake as goals_controller
    from controllers.derived import graph as graph_controller
    from controllers.derived import protocol as protocol_controller
    from controllers.derived import reports as reports_controller
    from controllers.source import tasks as tasks_controller
    from controllers.core import workspace as workspace_controller
    from controllers.schemas.derived.report import (
        ReportCommunityDetailResponse,
        ReportCommunityListResponse,
        ReportPatternsResponse,
    )
    import application.derived.graph_service as graph_service_module
    import application.source.collection_build_task_runner as task_runner_module
    import application.derived.report_service as report_service_module
    from application.source.artifact_registry_service import ArtifactRegistryService
    from application.source.collection_service import CollectionService
    from application.core.comparison_service import ComparisonService
    from application.core.document_profile_service import DocumentProfileService
    from application.core.paper_facts_service import PaperFactsService
    from application.goal.brief_service import GoalService
    from application.source.collection_build_task_runner import CollectionBuildTaskRunner
    from application.source.task_service import TaskService
    from application.core.workspace_overview_service import WorkspaceService
    from main import create_app

    collection_service = CollectionService(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    document_profile_service = DocumentProfileService(collection_service, artifact_registry)
    paper_facts_service = PaperFactsService(
        collection_service,
        artifact_registry,
        document_profile_service,
    )
    comparison_service = ComparisonService(
        collection_service,
        artifact_registry,
        paper_facts_service,
    )
    runner = CollectionBuildTaskRunner(
        collection_service,
        task_service,
        artifact_registry,
        document_profile_service,
        paper_facts_service,
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

    async def fake_build_source_artifacts(**kwargs):  # noqa: ANN003
        output_dir = Path(kwargs["config"].output.base_dir)
        _write_source_artifact_outputs(output_dir)
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
    monkeypatch.setattr(tasks_controller, "build_task_runner", runner)
    monkeypatch.setattr(task_runner_module, "CONFIG_DIR", default_config.parent)
    monkeypatch.setattr(task_runner_module, "load_config", lambda *args, **kwargs: _build_config(Path("placeholder-output"), Path("placeholder-input")))
    monkeypatch.setattr(task_runner_module, "build_source_artifacts", fake_build_source_artifacts)
    monkeypatch.setattr(graph_service_module, "collection_service", collection_service)
    monkeypatch.setattr(graph_service_module, "artifact_registry_service", artifact_registry)
    monkeypatch.setattr(workspace_controller, "workspace_service", workspace_service)
    monkeypatch.setattr(documents_controller, "document_profile_service", document_profile_service)
    monkeypatch.setattr(evidence_controller, "paper_facts_service", paper_facts_service)
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

    return TestClient(create_app())


def test_collection_task_flow(app_client):
    collection_id, task_id = _create_built_collection(app_client)

    task_status = app_client.get(f"{API_V1_PREFIX}/tasks/{task_id}")
    assert task_status.status_code == 200
    assert task_status.json()["task_type"] == "build"
    assert task_status.json()["status"] == "completed"
    assert task_status.json()["current_stage"] == "artifacts_ready"

    collection_tasks = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/tasks")
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
    assert body["document_profiles_generated"] is True
    assert body["document_profiles_ready"] is True
    assert body["evidence_cards_generated"] is True
    assert body["evidence_cards_ready"] is True
    assert body["characterization_observations_generated"] is True
    assert body["characterization_observations_ready"] is True
    assert body["structure_features_generated"] is True
    assert body["structure_features_ready"] is False
    assert body["test_conditions_generated"] is True
    assert body["test_conditions_ready"] is False
    assert body["baseline_references_generated"] is True
    assert body["baseline_references_ready"] is True
    assert body["sample_variants_generated"] is True
    assert body["sample_variants_ready"] is True
    assert body["measurement_results_generated"] is True
    assert body["measurement_results_ready"] is True
    assert body["comparison_rows_generated"] is True
    assert body["comparison_rows_ready"] is True
    assert body["graph_generated"] is True
    assert body["graph_ready"] is True
    assert body["blocks_generated"] is True
    assert body["blocks_ready"] is True
    assert body["figures_generated"] is True
    assert body["figures_ready"] is False
    assert body["table_rows_generated"] is True
    assert body["table_rows_ready"] is False
    assert body["table_cells_generated"] is True
    assert body["table_cells_ready"] is False
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
    assert comparisons_body["items"][0]["assessment"]["comparability_status"] in {
        "comparable",
        "limited",
        "not_comparable",
        "insufficient",
    }
    assert "display" in comparisons_body["items"][0]
    assert "evidence_bundle" in comparisons_body["items"][0]
    assert "assessment" in comparisons_body["items"][0]
    assert "uncertainty" in comparisons_body["items"][0]
    assert "variant_id" in comparisons_body["items"][0]["display"]
    assert "variant_label" in comparisons_body["items"][0]["display"]
    assert "variable_axis" in comparisons_body["items"][0]["display"]
    assert "variable_value" in comparisons_body["items"][0]["display"]
    assert "baseline_reference" in comparisons_body["items"][0]["display"]
    assert "result_source_type" in comparisons_body["items"][0]["evidence_bundle"]

    document_id = profiles_body["items"][0]["document_id"]
    profile = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/documents/{document_id}/profile"
    )
    assert profile.status_code == 200
    assert profile.json()["document_id"] == document_id

    evidence_id = evidence_body["items"][0]["evidence_id"]
    evidence_detail = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/evidence/{evidence_id}"
    )
    assert evidence_detail.status_code == 200
    assert evidence_detail.json()["evidence_id"] == evidence_id

    row_id = comparisons_body["items"][0]["row_id"]
    comparison_detail = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/comparisons/{row_id}"
    )
    assert comparison_detail.status_code == 200
    assert comparison_detail.json()["row_id"] == row_id


def test_comparisons_endpoint_supports_graph_drilldown_filters(app_client):
    from controllers.core import comparisons as comparisons_controller

    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections",
        json={"name": "Filtered Comparisons"},
    )
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    workspace = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/workspace")
    assert workspace.status_code == 200
    output_dir = Path(workspace.json()["artifacts"]["output_path"])
    output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "row_id": "cmp-1",
                "collection_id": collection_id,
                "source_document_id": "paper-1",
                "variant_id": "var-1",
                "variant_label": "A1",
                "variable_axis": "anneal_temp",
                "variable_value": 700,
                "baseline_reference": "as-prepared",
                "result_source_type": "table",
                "result_type": "scalar",
                "result_summary": "12 mS/cm",
                "supporting_evidence_ids": ["ev-1"],
                "supporting_anchor_ids": ["anchor-1"],
                "characterization_observation_ids": [],
                "structure_feature_ids": [],
                "material_system_normalized": "oxide cathode",
                "process_normalized": "700 C",
                "property_normalized": "conductivity",
                "baseline_normalized": "as-prepared",
                "test_condition_normalized": "EIS",
                "comparability_status": "comparable",
                "comparability_warnings": [],
                "comparability_basis": ["baseline_resolved"],
                "requires_expert_review": False,
                "assessment_epistemic_status": "normalized_from_evidence",
                "missing_critical_context": [],
                "value": 12.0,
                "unit": "mS/cm",
            },
            {
                "row_id": "cmp-2",
                "collection_id": collection_id,
                "source_document_id": "paper-2",
                "variant_id": "var-2",
                "variant_label": "B1",
                "variable_axis": "atmosphere",
                "variable_value": "air",
                "baseline_reference": "air annealed",
                "result_source_type": "text",
                "result_type": "trend",
                "result_summary": "Trend reported",
                "supporting_evidence_ids": ["ev-2"],
                "supporting_anchor_ids": ["anchor-2"],
                "characterization_observation_ids": [],
                "structure_feature_ids": [],
                "material_system_normalized": "layered oxide",
                "process_normalized": "air anneal",
                "property_normalized": "cycle retention",
                "baseline_normalized": "air annealed",
                "test_condition_normalized": "cycling",
                "comparability_status": "limited",
                "comparability_warnings": [],
                "comparability_basis": ["baseline_partial"],
                "requires_expert_review": True,
                "assessment_epistemic_status": "provisional",
                "missing_critical_context": [],
                "value": None,
                "unit": None,
            },
        ]
    ).to_parquet(output_dir / "comparison_rows.parquet", index=False)
    comparisons_controller.comparison_service.artifact_registry_service.upsert(
        collection_id,
        output_dir,
    )

    response = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/comparisons",
        params={
            "material_system_normalized": "oxide cathode",
            "property_normalized": "conductivity",
            "test_condition_normalized": "EIS",
            "baseline_normalized": "as-prepared",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["total"] == 1
    assert payload["items"][0]["row_id"] == "cmp-1"


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


def test_graph_endpoints_serve_core_projection_without_legacy_graph_outputs(
    app_client,
):
    from controllers.derived import graph as graph_controller

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
    assert len(payload["nodes"]) == 7
    assert len(payload["edges"]) == 6
    assert {item["type"] for item in payload["nodes"]} == {
        "document",
        "evidence",
        "comparison",
        "material",
        "property",
        "test_condition",
        "baseline",
    }
    assert set(payload["nodes"][0]) == {"id", "label", "type", "degree"}
    assert set(payload["edges"][0]) == {
        "id",
        "source",
        "target",
        "weight",
        "edge_description",
    }

    neighbors = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/graph/nodes/evi:ev-1/neighbors"
    )
    assert neighbors.status_code == 200
    neighbors_body = neighbors.json()
    assert neighbors_body["center_node_id"] == "evi:ev-1"
    assert len(neighbors_body["nodes"]) == 3
    assert len(neighbors_body["edges"]) == 2

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


def test_build_task_contract_ignores_legacy_engine_fields(app_client, monkeypatch):
    import application.source.collection_build_task_runner as task_runner_module

    captured: dict[str, object] = {}

    async def capturing_build_source_artifacts(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        output_dir = Path(kwargs["config"].output.base_dir)
        _write_source_artifact_outputs(output_dir)
        return [DummyWorkflowOutput()]

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
        files={"file": ("paper.txt", b"Experimental Section\nMix and anneal.", "text/plain")},
    )
    assert upload_resp.status_code == 200

    task_resp = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/tasks/build",
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
    assert task_status.json()["task_type"] == "build"
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
    from controllers.derived import protocol as protocol_controller

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
