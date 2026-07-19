from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

if "devtools" not in sys.modules:
    sys.modules["devtools"] = SimpleNamespace(pformat=lambda value: str(value))

import pytest
from domain.core.comparison import (
    CollectionComparableResult,
    ComparableResult,
    ComparisonFactSet,
    build_collection_assessment_input_fingerprint,
    build_comparison_row_id,
)
from domain.core.document_profile import DocumentProfile
from domain.core.evidence_backbone import EvidenceAnchor, MeasurementResult
from domain.core.paper_fact import PaperFactSet
from domain.source import (
    SourceArtifactSet,
    SourceReferenceSet,
    build_source_document_tree,
)
from infra.persistence.sqlite import (
    SqliteCoreFactRepository,
)
from infra.persistence.memory import MemoryBuildRepository
from infra.source.runtime.artifact_bundle import SourceArtifactBundle
from infra.source.runtime.source_evidence import (
    build_blocks,
    build_table_cells,
    build_table_rows,
)
from tests.support.paper_fact_repository import MemoryPaperFactRepository
from tests.support.objective_repository import MemoryObjectiveRepository
from tests.support.comparison_repository import MemoryComparisonRepository

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


class MemorySourceArtifactRepository:
    def __init__(self) -> None:
        self._artifacts: dict[tuple[str, str], SourceArtifactSet] = {}
        self._references: dict[tuple[str, str], SourceReferenceSet] = {}

    def replace_collection_artifacts(
        self,
        collection_id: str,
        build_id: str,
        artifacts: SourceArtifactSet,
    ) -> None:
        self._artifacts[(collection_id, build_id)] = artifacts

    def read_collection_artifacts(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> SourceArtifactSet:
        if build_id is None:
            return SourceArtifactSet()
        return self._artifacts.get((collection_id, build_id), SourceArtifactSet())

    def replace_collection_references(
        self,
        collection_id: str,
        build_id: str,
        references: SourceReferenceSet,
    ) -> None:
        self._references[(collection_id, build_id)] = references

    def read_collection_references(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> SourceReferenceSet:
        if build_id is None:
            return SourceReferenceSet()
        return self._references.get((collection_id, build_id), SourceReferenceSet())

    def read_document_tree(
        self,
        collection_id: str,
        document_id: str,
        build_id: str | None = None,
    ):
        artifacts = self.read_collection_artifacts(
            collection_id,
            build_id=build_id,
        )
        document = next(
            item for item in artifacts.documents if item.document_id == document_id
        )
        return build_source_document_tree(
            collection_id=collection_id,
            document=document,
            blocks=tuple(
                item for item in artifacts.blocks if item.document_id == document_id
            ),
            tables=tuple(
                item for item in artifacts.tables if item.document_id == document_id
            ),
            figures=tuple(
                item for item in artifacts.figures if item.document_id == document_id
            ),
            references=self.read_collection_references(
                collection_id,
                build_id=build_id,
            ),
        )


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


def _collection_output_dir(app_client, collection_id: str) -> Path:  # noqa: ANN001
    return app_client.app.state.collection_service.get_paths(collection_id).output_dir


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
                "bbox": None,
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


def _write_core_graph_outputs(comparison_service, collection_id: str) -> None:  # noqa: ANN001
    comparable_result, scoped_result, _row_id = _build_semantic_comparison_record(
        collection_id=collection_id,
        comparable_result_id="cres-graph-1",
        source_document_id="paper-1",
        variant_id=None,
        variant_label=None,
        variable_axis=None,
        variable_value=None,
        baseline_reference="as-prepared",
        result_source_type="text",
        result_type="scalar",
        result_summary="12 mS/cm",
        supporting_evidence_ids=["ev_result_res-graph-1"],
        supporting_anchor_ids=["anchor-1"],
        characterization_observation_ids=[],
        structure_feature_ids=[],
        material_system_normalized="oxide cathode",
        process_normalized="700 C",
        property_normalized="conductivity",
        baseline_normalized="as-prepared",
        test_condition_normalized="EIS",
        comparability_status="comparable",
        comparability_warnings=[],
        comparability_basis=["baseline_resolved"],
        requires_expert_review=False,
        assessment_epistemic_status="normalized_from_evidence",
        missing_critical_context=[],
        value=12.0,
        unit="mS/cm",
        sort_order=0,
    )
    comparison_service.paper_fact_repository.replace_document_profiles(
        collection_id,
        "build_test",
        (
            DocumentProfile.from_mapping(
                {
                    "document_id": "paper-1",
                    "collection_id": collection_id,
                    "title": "Core Projection Paper",
                    "source_filename": "paper.txt",
                    "doc_type": "experimental",
                    "confidence": 0.91,
                }
            ),
        ),
    )
    comparison_service.paper_fact_repository.replace_paper_facts(
        collection_id,
        "build_test",
        PaperFactSet(
            paper_facts_ready=True,
            evidence_anchors=(
                EvidenceAnchor.from_mapping(
                    {
                        "anchor_id": "anchor-1",
                        "document_id": "paper-1",
                        "source_type": "text",
                        "quote": "Conductivity increased to 12 mS/cm after annealing.",
                    }
                ),
            ),
            measurement_results=(
                MeasurementResult.from_mapping(
                    {
                        "result_id": "res-graph-1",
                        "document_id": "paper-1",
                        "collection_id": collection_id,
                        "property_normalized": "conductivity",
                        "result_type": "scalar",
                        "value_payload": {"value": 12.0},
                        "unit": "mS/cm",
                        "evidence_anchor_ids": ["anchor-1"],
                        "traceability_status": "direct",
                        "result_source_type": "text",
                    }
                ),
            ),
        ),
    )
    comparison_service.comparison_repository.replace(
        collection_id,
        "build_test",
        ComparisonFactSet(
            comparison_artifacts_ready=True,
            comparable_results=(ComparableResult.from_mapping(comparable_result),),
            collection_comparable_results=(
                CollectionComparableResult.from_mapping(scoped_result),
            ),
        ),
    )


def _build_semantic_comparison_record(
    *,
    collection_id: str,
    comparable_result_id: str,
    source_document_id: str,
    variant_id: str | None,
    variant_label: str | None,
    variable_axis: str | None,
    variable_value,
    baseline_reference: str | None,
    result_source_type: str | None,
    result_type: str,
    result_summary: str,
    supporting_evidence_ids: list[str],
    supporting_anchor_ids: list[str],
    characterization_observation_ids: list[str],
    structure_feature_ids: list[str],
    material_system_normalized: str,
    process_normalized: str,
    property_normalized: str,
    baseline_normalized: str,
    test_condition_normalized: str,
    comparability_status: str,
    comparability_warnings: list[str],
    comparability_basis: list[str],
    requires_expert_review: bool,
    assessment_epistemic_status: str,
    missing_critical_context: list[str],
    value: float | None,
    unit: str | None,
    sort_order: int,
) -> tuple[dict, dict, str]:
    comparable_result = {
        "comparable_result_id": comparable_result_id,
        "source_result_id": f"res-{comparable_result_id}",
        "source_document_id": source_document_id,
        "binding": {
            "variant_id": variant_id,
            "baseline_id": f"base-{comparable_result_id}"
            if baseline_reference
            else None,
            "test_condition_id": (
                f"tc-{comparable_result_id}" if test_condition_normalized else None
            ),
        },
        "normalized_context": {
            "material_system_normalized": material_system_normalized,
            "process_normalized": process_normalized,
            "baseline_normalized": baseline_normalized,
            "test_condition_normalized": test_condition_normalized,
        },
        "axis": {
            "axis_name": variable_axis,
            "axis_value": variable_value,
            "axis_unit": None,
        },
        "value": {
            "property_normalized": property_normalized,
            "result_type": result_type,
            "numeric_value": value,
            "unit": unit,
            "summary": result_summary,
            "statistic_type": None,
            "uncertainty": None,
        },
        "evidence": {
            "direct_anchor_ids": supporting_anchor_ids,
            "contextual_anchor_ids": [],
            "evidence_ids": supporting_evidence_ids,
            "structure_feature_ids": structure_feature_ids,
            "characterization_observation_ids": characterization_observation_ids,
            "traceability_status": "direct",
        },
        "variant_label": variant_label,
        "baseline_reference": baseline_reference,
        "result_source_type": result_source_type,
        "epistemic_status": assessment_epistemic_status,
        "normalization_version": "comparable_result_v1",
    }
    comparable_record = ComparableResult.from_mapping(comparable_result)
    scoped_result = {
        "collection_id": collection_id,
        "comparable_result_id": comparable_result_id,
        "assessment": {
            "missing_critical_context": missing_critical_context,
            "comparability_basis": comparability_basis,
            "comparability_warnings": comparability_warnings,
            "comparability_status": comparability_status,
            "requires_expert_review": requires_expert_review,
            "assessment_epistemic_status": assessment_epistemic_status,
        },
        "epistemic_status": assessment_epistemic_status,
        "included": True,
        "sort_order": sort_order,
        "policy_family": "default_collection_comparison_policy",
        "policy_version": "comparison_policy_v1",
        "comparable_result_normalization_version": "comparable_result_v1",
        "assessment_input_fingerprint": build_collection_assessment_input_fingerprint(
            comparable_record
        ),
        "reassessment_triggers": [
            "policy_family_changed",
            "policy_version_changed",
            "comparable_result_normalization_version_changed",
            "assessment_input_fingerprint_changed",
        ],
    }
    row_id = build_comparison_row_id(
        collection_id=collection_id,
        comparable_result_id=comparable_result_id,
    )
    return comparable_result, scoped_result, row_id


def _store_core_comparison_facts(
    comparison_service,
    collection_id: str,
    *,
    comparable_results: list[dict],
    scoped_results: list[dict],
    document_profiles: list[dict] | None = None,
) -> None:  # noqa: ANN001
    comparison_service.paper_fact_repository.replace_document_profiles(
        collection_id,
        "build_test",
        tuple(DocumentProfile.from_mapping(row) for row in (document_profiles or [])),
    )
    comparison_service.paper_fact_repository.replace_paper_facts(
        collection_id,
        "build_test",
        PaperFactSet(paper_facts_ready=True),
    )
    comparison_service.comparison_repository.replace(
        collection_id,
        "build_test",
        ComparisonFactSet(
            comparison_artifacts_ready=True,
            comparable_results=tuple(
                ComparableResult.from_mapping(row) for row in comparable_results
            ),
            collection_comparable_results=tuple(
                CollectionComparableResult.from_mapping(row) for row in scoped_results
            ),
        ),
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
    active_build = app_client.app.state.task_service.repository.read_active_build(
        collection_id
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


def test_build_task_route_schedules_blocking_entry_without_waiting(
    app_client, monkeypatch
):
    captured: dict[str, object] = {}
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def fake_run_task_blocking(*args, **kwargs):  # noqa: ANN002, ANN003
        captured["args"] = args
        captured["kwargs"] = kwargs
        started.set()
        release.wait(timeout=5)
        finished.set()
        return {"task_id": args[0], "collection_id": args[1], "status": "queued"}

    def fail_run_task(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("async build entry should not be scheduled directly")

    monkeypatch.setattr(
        app_client.app.state.build_pipeline_service,
        "run_task_blocking",
        fake_run_task_blocking,
    )
    monkeypatch.setattr(
        app_client.app.state.build_pipeline_service,
        "run_task",
        fail_run_task,
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

    try:
        task_resp = app_client.post(
            f"{API_V1_PREFIX}/collections/{collection_id}/tasks/build", json={}
        )

        assert task_resp.status_code == 200
        assert started.wait(timeout=2)
        assert captured["args"][1] == collection_id
        assert not finished.is_set()
    finally:
        release.set()
        finished.wait(timeout=2)


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


def test_research_view_endpoint_returns_empty_state_for_empty_collection(app_client):
    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections",
        json={"name": "Research View Empty"},
    )
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    response = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/research-view"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["collection_id"] == collection_id
    assert body["state"] == "empty"
    assert body["materials"] == []
    assert body["paper_coverage"] == []
    assert body["comparable_groups"] == []

    materials = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/materials")
    assert materials.status_code == 200
    assert materials.json()["materials"] == []

    workspace = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/workspace")
    assert workspace.status_code == 200
    workspace_body = workspace.json()
    assert workspace_body["links"]["research_view"] == (
        f"/api/v1/collections/{collection_id}/research-view"
    )
    assert workspace_body["links"]["research_materials"] == (
        f"/api/v1/collections/{collection_id}/materials"
    )
    assert workspace_body["capabilities"]["can_view_research_view"] is False


@pytest.fixture()
def app_client(monkeypatch, tmp_path, auth_session_service, collection_service):
    import application.pipeline.collection_build.service as task_runner_module
    from application.source.task_service import TaskService

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin-password")
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("infra.persistence.factory.DATA_DIR", tmp_path)

    from main import create_app

    monkeypatch.setattr("main.DATA_DIR", tmp_path)

    build_repository = MemoryBuildRepository()
    task_service = TaskService(build_repository)
    source_artifact_repository = MemorySourceArtifactRepository()
    paper_fact_repository = MemoryPaperFactRepository()
    objective_repository = MemoryObjectiveRepository()
    comparison_repository = MemoryComparisonRepository()
    core_fact_repository = SqliteCoreFactRepository(tmp_path / "lens.sqlite")

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
            comparison_repository=comparison_repository,
            core_fact_repository=core_fact_repository,
        )
    ) as client:
        login_response = client.post(
            f"{API_V1_PREFIX}/auth/login",
            json={"email": "admin@example.com", "password": "admin-password"},
        )
        assert login_response.status_code == 200
        yield client


def test_goal_experiment_plan_routes_are_registered(app_client):
    openapi = app_client.get("/api/openapi.json")
    assert openapi.status_code == 200
    paths = openapi.json()["paths"]
    plan_list_path = (
        f"{API_V1_PREFIX}/collections/{{collection_id}}/goals/{{goal_id}}/"
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
    assert body["document_profiles_generated"] is True
    assert body["document_profiles_ready"] is True
    assert body["evidence_cards_generated"] is False
    assert body["evidence_cards_ready"] is False
    assert body["characterization_observations_generated"] is False
    assert body["characterization_observations_ready"] is False
    assert body["structure_features_generated"] is False
    assert body["structure_features_ready"] is False
    assert body["test_conditions_generated"] is False
    assert body["test_conditions_ready"] is False
    assert body["baseline_references_generated"] is False
    assert body["baseline_references_ready"] is False
    assert body["sample_variants_generated"] is False
    assert body["sample_variants_ready"] is False
    assert body["measurement_results_generated"] is False
    assert body["measurement_results_ready"] is False
    assert body["comparable_results_generated"] is False
    assert body["comparable_results_ready"] is False
    assert body["collection_comparable_results_generated"] is False
    assert body["collection_comparable_results_ready"] is False
    assert body["collection_comparable_results_stale"] is False
    assert body["comparison_rows_generated"] is False
    assert body["comparison_rows_ready"] is False
    assert body["comparison_rows_stale"] is False
    assert body["graph_generated"] is False
    assert body["graph_ready"] is False
    assert body["graph_stale"] is False
    assert body["blocks_generated"] is True
    assert body["blocks_ready"] is True
    assert body["figures_generated"] is True
    assert body["figures_ready"] is False
    assert body["table_rows_generated"] is True
    assert body["table_rows_ready"] is False
    assert body["table_cells_generated"] is True
    assert body["table_cells_ready"] is False

    graph = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/graph")
    assert graph.status_code == 409

    graphml = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/graphml")
    assert graphml.status_code == 409

    profiles = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/documents/profiles"
    )
    assert profiles.status_code == 200
    profiles_body = profiles.json()
    assert profiles_body["count"] == 1
    assert profiles_body["items"][0]["title"] == "Composite Paper"
    assert profiles_body["items"][0]["source_filename"] == "paper.txt"
    assert profiles_body["items"][0]["doc_type"] == "experimental"

    evidence = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/evidence/cards"
    )
    assert evidence.status_code == 409

    comparisons = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/comparisons"
    )
    assert comparisons.status_code == 409

    document_id = profiles_body["items"][0]["document_id"]
    profile = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/documents/{document_id}/profile"
    )
    assert profile.status_code == 200
    assert profile.json()["document_id"] == document_id

    document_comparison_semantics = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/documents/{document_id}/comparison-semantics"
    )
    assert document_comparison_semantics.status_code == 409


def test_comparisons_endpoint_supports_graph_drilldown_filters(app_client):
    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections",
        json={"name": "Filtered Comparisons"},
    )
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    comparable_result_1, scoped_result_1, row_id_1 = _build_semantic_comparison_record(
        collection_id=collection_id,
        comparable_result_id="cres-1",
        source_document_id="paper-1",
        variant_id="var-1",
        variant_label="A1",
        variable_axis="anneal_temp",
        variable_value=700,
        baseline_reference="as-prepared",
        result_source_type="table",
        result_type="scalar",
        result_summary="12 mS/cm",
        supporting_evidence_ids=["ev-1"],
        supporting_anchor_ids=["anchor-1"],
        characterization_observation_ids=[],
        structure_feature_ids=[],
        material_system_normalized="oxide cathode",
        process_normalized="700 C",
        property_normalized="conductivity",
        baseline_normalized="as-prepared",
        test_condition_normalized="EIS",
        comparability_status="comparable",
        comparability_warnings=[],
        comparability_basis=["baseline_resolved"],
        requires_expert_review=False,
        assessment_epistemic_status="normalized_from_evidence",
        missing_critical_context=[],
        value=12.0,
        unit="mS/cm",
        sort_order=0,
    )
    comparable_result_2, scoped_result_2, _row_id_2 = _build_semantic_comparison_record(
        collection_id=collection_id,
        comparable_result_id="cres-2",
        source_document_id="paper-2",
        variant_id="var-2",
        variant_label="B1",
        variable_axis="atmosphere",
        variable_value="air",
        baseline_reference="air annealed",
        result_source_type="text",
        result_type="trend",
        result_summary="Trend reported",
        supporting_evidence_ids=["ev-2"],
        supporting_anchor_ids=["anchor-2"],
        characterization_observation_ids=[],
        structure_feature_ids=[],
        material_system_normalized="layered oxide",
        process_normalized="air anneal",
        property_normalized="cycle retention",
        baseline_normalized="air annealed",
        test_condition_normalized="cycling",
        comparability_status="limited",
        comparability_warnings=[],
        comparability_basis=["baseline_partial"],
        requires_expert_review=True,
        assessment_epistemic_status="provisional",
        missing_critical_context=[],
        value=None,
        unit=None,
        sort_order=1,
    )
    _store_core_comparison_facts(
        app_client.app.state.comparison_service,
        collection_id,
        comparable_results=[comparable_result_1, comparable_result_2],
        scoped_results=[scoped_result_1, scoped_result_2],
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
    assert payload["items"][0]["row_id"] == row_id_1


def test_comparable_results_endpoint_deduplicates_across_collections_without_row_cache(
    app_client,
):
    first_create = app_client.post(
        f"{API_V1_PREFIX}/collections",
        json={"name": "Corpus Route A"},
    )
    assert first_create.status_code == 200
    first_collection_id = first_create.json()["collection_id"]

    second_create = app_client.post(
        f"{API_V1_PREFIX}/collections",
        json={"name": "Corpus Route B"},
    )
    assert second_create.status_code == 200
    second_collection_id = second_create.json()["collection_id"]

    shared_result, first_shared_overlay, _shared_row_id = (
        _build_semantic_comparison_record(
            collection_id=first_collection_id,
            comparable_result_id="cres-corpus-shared-1",
            source_document_id="paper-shared",
            variant_id="var-1",
            variant_label="A1",
            variable_axis=None,
            variable_value=None,
            baseline_reference="as-prepared",
            result_source_type="text",
            result_type="scalar",
            result_summary="12 mS/cm",
            supporting_evidence_ids=["ev-shared-1"],
            supporting_anchor_ids=["anchor-shared-1"],
            characterization_observation_ids=[],
            structure_feature_ids=[],
            material_system_normalized="oxide cathode",
            process_normalized="700 C",
            property_normalized="conductivity",
            baseline_normalized="as-prepared",
            test_condition_normalized="EIS",
            comparability_status="comparable",
            comparability_warnings=[],
            comparability_basis=["baseline_resolved"],
            requires_expert_review=False,
            assessment_epistemic_status="normalized_from_evidence",
            missing_critical_context=[],
            value=12.0,
            unit="mS/cm",
            sort_order=0,
        )
    )
    unique_result, unique_overlay, _unique_row_id = _build_semantic_comparison_record(
        collection_id=first_collection_id,
        comparable_result_id="cres-corpus-unique-1",
        source_document_id="paper-unique",
        variant_id="var-2",
        variant_label="B1",
        variable_axis=None,
        variable_value=None,
        baseline_reference="as-prepared",
        result_source_type="text",
        result_type="scalar",
        result_summary="15 mS/cm",
        supporting_evidence_ids=["ev-unique-1"],
        supporting_anchor_ids=["anchor-unique-1"],
        characterization_observation_ids=[],
        structure_feature_ids=[],
        material_system_normalized="oxide cathode",
        process_normalized="750 C",
        property_normalized="conductivity",
        baseline_normalized="as-prepared",
        test_condition_normalized="EIS",
        comparability_status="comparable",
        comparability_warnings=[],
        comparability_basis=["baseline_resolved"],
        requires_expert_review=False,
        assessment_epistemic_status="normalized_from_evidence",
        missing_critical_context=[],
        value=15.0,
        unit="mS/cm",
        sort_order=1,
    )
    _store_core_comparison_facts(
        app_client.app.state.comparison_service,
        first_collection_id,
        comparable_results=[shared_result, unique_result],
        scoped_results=[first_shared_overlay, unique_overlay],
    )
    second_shared_overlay = dict(first_shared_overlay)
    second_shared_overlay["collection_id"] = second_collection_id
    second_shared_overlay["sort_order"] = 4
    _store_core_comparison_facts(
        app_client.app.state.comparison_service,
        second_collection_id,
        comparable_results=[shared_result],
        scoped_results=[second_shared_overlay],
    )

    response = app_client.get(
        f"{API_V1_PREFIX}/comparable-results",
        params={"property_normalized": "conductivity"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["count"] == 2
    items_by_id = {item["comparable_result_id"]: item for item in payload["items"]}
    assert items_by_id["cres-corpus-shared-1"]["observed_collection_ids"] == sorted(
        [first_collection_id, second_collection_id]
    )
    assert len(items_by_id["cres-corpus-shared-1"]["collection_overlays"]) == 2
    assert items_by_id["cres-corpus-unique-1"]["observed_collection_ids"] == [
        first_collection_id
    ]
    detail = app_client.get(
        f"{API_V1_PREFIX}/comparable-results/cres-corpus-shared-1",
        params={"collection_id": second_collection_id},
    )
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["comparable_result_id"] == "cres-corpus-shared-1"
    assert detail_payload["observed_collection_ids"] == [second_collection_id]
    assert len(detail_payload["collection_overlays"]) == 1
    assert (
        detail_payload["collection_overlays"][0]["collection_id"]
        == second_collection_id
    )


def test_collection_results_endpoints_project_product_results_and_workspace_exposes_results(
    app_client,
):
    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections",
        json={"name": "Result Projection Collection"},
    )
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    document_profile = {
        "document_id": "paper-1",
        "collection_id": collection_id,
        "title": "Result Projection Paper",
        "source_filename": "paper-1.pdf",
        "doc_type": "experimental",
        "parsing_warnings": [],
        "confidence": 0.91,
    }
    first_result, first_scoped_result, _ = _build_semantic_comparison_record(
        collection_id=collection_id,
        comparable_result_id="cres-result-1",
        source_document_id="paper-1",
        variant_id="var-1",
        variant_label="Sample A",
        variable_axis=None,
        variable_value=None,
        baseline_reference="as-prepared",
        result_source_type="text",
        result_type="scalar",
        result_summary="12 mS/cm",
        supporting_evidence_ids=["ev-1"],
        supporting_anchor_ids=["anchor-1"],
        characterization_observation_ids=[],
        structure_feature_ids=[],
        material_system_normalized="oxide cathode",
        process_normalized="700 C",
        property_normalized="conductivity",
        baseline_normalized="as-prepared",
        test_condition_normalized="EIS",
        comparability_status="comparable",
        comparability_warnings=[],
        comparability_basis=["baseline_resolved"],
        requires_expert_review=False,
        assessment_epistemic_status="normalized_from_evidence",
        missing_critical_context=[],
        value=12.0,
        unit="mS/cm",
        sort_order=0,
    )
    second_result, second_scoped_result, _ = _build_semantic_comparison_record(
        collection_id=collection_id,
        comparable_result_id="cres-result-2",
        source_document_id="paper-1",
        variant_id="var-2",
        variant_label="Sample B",
        variable_axis="temperature",
        variable_value="750 C",
        baseline_reference="air-annealed",
        result_source_type="table",
        result_type="scalar",
        result_summary="15 mS/cm",
        supporting_evidence_ids=["ev-2"],
        supporting_anchor_ids=["anchor-2"],
        characterization_observation_ids=[],
        structure_feature_ids=[],
        material_system_normalized="oxide cathode",
        process_normalized="750 C",
        property_normalized="conductivity",
        baseline_normalized="air-annealed",
        test_condition_normalized="EIS",
        comparability_status="limited",
        comparability_warnings=["baseline drift"],
        comparability_basis=["test_condition_resolved"],
        requires_expert_review=True,
        assessment_epistemic_status="normalized_from_evidence",
        missing_critical_context=["baseline_reference"],
        value=15.0,
        unit="mS/cm",
        sort_order=1,
    )
    _store_core_comparison_facts(
        app_client.app.state.comparison_service,
        collection_id,
        comparable_results=[first_result, second_result],
        scoped_results=[first_scoped_result, second_scoped_result],
        document_profiles=[document_profile],
    )

    workspace = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/workspace")
    assert workspace.status_code == 200
    workspace_body = workspace.json()
    assert workspace_body["workflow"]["results"]["status"] == "ready"
    assert workspace_body["workflow"]["comparisons"]["status"] == "ready"
    assert workspace_body["capabilities"]["can_view_results"] is True
    assert workspace_body["links"]["results"] == (
        f"/api/v1/collections/{collection_id}/results"
    )

    results = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/results",
        params={"property_normalized": "conductivity"},
    )
    assert results.status_code == 200
    results_payload = results.json()
    assert results_payload["collection_id"] == collection_id
    assert results_payload["total"] == 2
    assert results_payload["count"] == 2
    assert results_payload["items"][0] == {
        "result_id": "cres-result-1",
        "document_id": "paper-1",
        "document_title": "Result Projection Paper",
        "material_label": "oxide cathode",
        "variant_label": "Sample A",
        "property": "conductivity",
        "value": 12.0,
        "unit": "mS/cm",
        "summary": "12 mS/cm",
        "baseline": "as-prepared",
        "test_condition": "EIS",
        "process": "700 C",
        "traceability_status": "direct",
        "comparability_status": "comparable",
        "requires_expert_review": False,
    }

    detail = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/results/cres-result-2"
    )
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["result_id"] == "cres-result-2"
    assert detail_payload["document"]["title"] == "Result Projection Paper"
    assert detail_payload["material"]["variant_label"] == "Sample B"
    assert detail_payload["measurement"]["property"] == "conductivity"
    assert detail_payload["context"]["baseline"] == "air-annealed"
    assert detail_payload["assessment"]["comparability_status"] == "limited"
    assert detail_payload["assessment"]["missing_context"] == ["baseline_reference"]
    assert detail_payload["evidence"][0]["evidence_id"] == "ev-2"
    assert detail_payload["actions"]["open_document"] == (
        f"/collections/{collection_id}/documents/paper-1"
    )
    assert detail_payload["actions"]["open_comparisons"].startswith(
        f"/collections/{collection_id}/comparisons?"
    )

    comparisons = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/comparisons"
    )
    assert comparisons.status_code == 200
    comparison_payload = comparisons.json()
    assert comparison_payload["items"][0]["result_id"] == "cres-result-1"


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
    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections", json={"name": "Pending Graph"}
    )
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    graph = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/graph")
    assert graph.status_code == 409
    graph_detail = graph.json()["detail"]
    assert graph_detail["code"] == "graph_not_ready"
    assert graph_detail["collection_id"] == collection_id
    assert (
        "core_fact_repository.comparison_artifacts" in graph_detail["missing_artifacts"]
    )

    graphml = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/graphml")
    assert graphml.status_code == 409
    graphml_detail = graphml.json()["detail"]
    assert graphml_detail["code"] == "graph_not_ready"
    assert graphml_detail["collection_id"] == collection_id


def test_graph_endpoints_serve_core_projection_without_legacy_graph_outputs(
    app_client,
):
    create_resp = app_client.post(
        f"{API_V1_PREFIX}/collections",
        json={"name": "Core Graph Only"},
    )
    assert create_resp.status_code == 200
    collection_id = create_resp.json()["collection_id"]

    _write_core_graph_outputs(app_client.app.state.comparison_service, collection_id)
    workspace = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/workspace")
    assert workspace.status_code == 200
    workspace_body = workspace.json()
    assert workspace_body["status_summary"] == "ready"
    assert workspace_body["workflow"]["comparisons"]["status"] == "ready"
    assert workspace_body["artifacts"]["comparison_rows_generated"] is True
    assert workspace_body["artifacts"]["comparison_rows_ready"] is True
    assert workspace_body["artifacts"]["collection_comparable_results_stale"] is False
    assert workspace_body["artifacts"]["comparison_rows_stale"] is False
    assert workspace_body["artifacts"]["graph_generated"] is True
    assert workspace_body["artifacts"]["graph_ready"] is True
    assert workspace_body["artifacts"]["graph_stale"] is False
    assert workspace_body["capabilities"]["can_view_graph"] is True
    assert workspace_body["capabilities"]["can_view_comparable_results"] is True
    assert workspace_body["capabilities"]["can_download_graphml"] is True
    assert workspace_body["links"]["comparable_results"] == (
        f"/api/v1/comparable-results?collection_id={collection_id}"
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
        f"{API_V1_PREFIX}/collections/{collection_id}/graph/nodes/evi:ev_result_res-graph-1/neighbors"
    )
    assert neighbors.status_code == 200
    neighbors_body = neighbors.json()
    assert neighbors_body["center_node_id"] == "evi:ev_result_res-graph-1"
    assert len(neighbors_body["nodes"]) == 3
    assert len(neighbors_body["edges"]) == 2

    graphml = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}/graphml")
    assert graphml.status_code == 200
    assert graphml.headers["content-type"].startswith("application/graphml+xml")
    assert b"<graphml" in graphml.content


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

    assert captured["method"] == task_runner_module.IndexingMethod.Standard
    assert "is_update_run" not in captured
    assert captured["verbose"] is True
    assert captured["additional_context"] == {"caller": "legacy-frontend"}
