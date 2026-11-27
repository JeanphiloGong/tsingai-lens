from __future__ import annotations

from infra.persistence.file import object_store as store_module

from infra.persistence import database

import asyncio
from hashlib import sha256

import pytest
from tests.support.identity import subjects as auth_service
from application.pipeline import pipeline_run_service
from domain.core import DocumentProfile
from document.domain.source import SourceDocument
from fastapi.testclient import TestClient
from repositories.document_profile_repository import DocumentProfileRepository
from repositories.pipeline_run_repository import PipelineRun, PipelineRunRepository
from document.repositories.source_repository import SourceRepository

API_V1_PREFIX = "/api/v1"


class _ImmediateDocumentPreparationService:
    """Complete the HTTP boundary test without invoking parser or LLM providers."""

    def __init__(
        self, workspace_service, pipeline_run_service, object_store
    ) -> None:  # noqa: ANN001
        self.workspace_service = workspace_service
        self.pipeline_run_service = pipeline_run_service
        self.object_store = object_store

    async def queue_document_preparation(
        self,
        workspace_id: str,
        document_id: str,
        *,
        user_id: str,
    ) -> PipelineRun:
        await self.workspace_service.get_workspace_for_user(workspace_id, user_id)
        document = await self.workspace_service.get_document(
            workspace_id,
            document_id,
        )
        fingerprint = sha256(
            f"{document.document.sha256}:test-parser:test-analysis".encode("utf-8")
        ).hexdigest()
        run, created = await self.pipeline_run_service.get_or_create_document_run(
            workspace_id=workspace_id,
            document_id=document_id,
            pipeline_name="document_preparation",
            input_fingerprint=fingerprint,
        )
        if not created:
            return run
        from datetime import timedelta
        from repositories.pipeline_run_repository import PipelineRunRepo

        job = await PipelineRunRepo.claim_next_document_preparation_job(
            worker_id="test-worker", lease_duration=timedelta(seconds=300)
        )
        await SourceRepository().replace_document(
            workspace_id,
            SourceDocument(
                document_id=document_id,
                document_order=0,
                title=document.document.filename,
                text=self.object_store.read(
                    document.storage_key,
                    document.document.sha256,
                ).decode("utf-8"),
                metadata={"source_fingerprint": fingerprint},
            ),
        )
        await DocumentProfileRepository().replace(
            workspace_id,
            DocumentProfile(
                document_id=document_id,
                title=document.document.filename,
                doc_type="experimental",
                profile_warnings=(),
                confidence=1.0,
                source_fingerprint=fingerprint,
                profile_version="test-analysis",
                profile_fingerprint=fingerprint,
            ),
        )
        await self.workspace_service.update_document_preparation(
            workspace_id,
            document_id,
            status="ready",
            preparation_fingerprint=fingerprint,
            parser_version="test-parser",
            document_analysis_version="test-analysis",
        )
        async with database.AsyncSessionLocal() as db, db.begin():
            return await self.pipeline_run_service.finish_run(
                run.run_id,
                job=job,
                status="completed",
                current_node="ready",
                progress_percent=100,
                progress_detail={
                    "phase": "ready",
                    "unit": "document",
                    "message": "The document is ready.",
                },
                db=db,
            )
@pytest.fixture()
def app_client(
    monkeypatch,
    tmp_path,
    identity_subjects,
    workspace_service,
    *,
    postgres_session_factory,
):
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("main.DATA_DIR", tmp_path)

    from main import create_app

    monkeypatch.setattr(
        "infra.persistence.database.AsyncSessionLocal", postgres_session_factory
    )
    monkeypatch.setattr(
        "main.build_database_engine",
        lambda _settings: postgres_session_factory.kw["bind"],
    )
    pipeline_run_service.PipelineRunRepo = PipelineRunRepository()
    with TestClient(create_app()) as client:
        monkeypatch.setattr(
            "controllers.source.pipeline_run_routes.queue_document_preparation",
            _ImmediateDocumentPreparationService(
                workspace_service,
                pipeline_run_service,
                store_module.Store,
            ).queue_document_preparation,
        )
        client.cookies.set("lens_session", "fixture:" + "admin@example.com")

        yield client


def _create_workspace(
    app_client, name: str = "Ti-6Al-4V papers"
) -> str:  # noqa: ANN001
    response = app_client.post(
        f"{API_V1_PREFIX}/workspaces",
        json={"name": name},
    )
    assert response.status_code == 200
    return response.json()["data"]["workspace_id"]


def _upload(
    app_client, workspace_id: str, filename: str, content: bytes
) -> dict:  # noqa: ANN001
    response = app_client.post(
        f"{API_V1_PREFIX}/workspaces/{workspace_id}/documents",
        files={"file": (filename, content, "text/plain")},
    )
    assert response.status_code == 200
    return response.json()["data"]


def test_request_id_is_generated_and_echoed(app_client) -> None:
    response = app_client.get(f"{API_V1_PREFIX}/workspaces")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"].startswith("req_")


def test_lost_upload_response_can_be_retried_then_prepared_once(app_client) -> None:
    workspace_id = _create_workspace(app_client)
    original = _upload(
        app_client, workspace_id, "paper.txt", b"Methods\nLPBF treatment"
    )
    path = f"{API_V1_PREFIX}/workspaces/{workspace_id}/documents"
    recovered = app_client.post(
        path,
        params={"reuse_existing": "true"},
        files={"file": ("renamed.txt", b"Methods\nLPBF treatment", "text/plain")},
    )
    assert recovered.status_code == 200
    assert recovered.json()["data"]["document_id"] == original["document_id"]
    preparation_path = f"{path}/{original['document_id']}/preparation"
    prepared = app_client.post(preparation_path)
    assert prepared.status_code == 200
    repeated = app_client.post(preparation_path)
    assert repeated.status_code == 200
    assert repeated.json()["data"]["run_id"] == prepared.json()["data"]["run_id"]
    documents = app_client.get(path).json()["data"]["items"]
    assert len(documents) == 1
    assert documents[0]["status"] == "ready"


def test_upload_recovery_is_restricted_to_the_workspace_owner(app_client) -> None:
    workspace_id = _create_workspace(app_client)
    _upload(app_client, workspace_id, "private.txt", b"Private LPBF treatment")
    asyncio.run(
        auth_service.create_subject(
            email="other@example.test",
        )
    )
    app_client.cookies.clear()
    app_client.cookies.set("lens_session", "fixture:" + "other@example.test")
    response = app_client.post(
        f"{API_V1_PREFIX}/workspaces/{workspace_id}/documents",
        params={"reuse_existing": "true"},
        files={"file": ("private.txt", b"Private LPBF treatment", "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["code"] == 200201


def test_workspace_list_returns_compact_document_rows(app_client) -> None:
    workspace_id = _create_workspace(app_client)
    uploaded = _upload(app_client, workspace_id, "paper-a.txt", b"Methods\nPaper A")

    response = app_client.get(f"{API_V1_PREFIX}/workspaces")

    assert response.status_code == 200
    document = response.json()["data"]["items"][0]["documents"][0]
    assert document["document_id"] == uploaded["document_id"]
    assert document["filename"] == "paper-a.txt"
    assert document["status"] == "stored"
    assert "storage_key" not in document
    assert "sha256" not in document
    assert "parser_version" not in document
    assert "preparation_fingerprint" not in document


def test_documents_prepare_independently_and_new_uploads_do_not_rebuild_ready_work(
    app_client,
) -> None:
    workspace_id = _create_workspace(app_client)
    first = _upload(app_client, workspace_id, "paper-a.txt", b"Methods\nPaper A")
    second = _upload(app_client, workspace_id, "paper-b.txt", b"Results\nPaper B")

    prepared = app_client.post(
        f"{API_V1_PREFIX}/workspaces/{workspace_id}/documents/"
        f"{first['document_id']}/preparation",
    )
    assert prepared.status_code == 200
    assert prepared.json()["data"]["status"] == "completed"
    assert prepared.json()["data"]["scope_type"] == "document"
    assert prepared.json()["data"]["scope_id"] == first["document_id"]

    after_first_preparation = app_client.get(
        f"{API_V1_PREFIX}/workspaces/{workspace_id}"
    ).json()["data"]
    by_id = {item["document_id"]: item for item in after_first_preparation["documents"]}
    assert by_id[first["document_id"]]["status"] == "ready"
    assert by_id[first["document_id"]]["preparation_fingerprint"]
    assert by_id[second["document_id"]]["status"] == "stored"

    third = _upload(app_client, workspace_id, "paper-c.txt", b"Discussion\nPaper C")
    after_addition = app_client.get(
        f"{API_V1_PREFIX}/workspaces/{workspace_id}"
    ).json()["data"]
    by_id = {item["document_id"]: item for item in after_addition["documents"]}
    assert after_addition["paper_count"] == 3
    assert by_id[first["document_id"]]["status"] == "ready"
    assert by_id[second["document_id"]]["status"] == "stored"
    assert by_id[third["document_id"]]["status"] == "stored"

    repeated = app_client.post(
        f"{API_V1_PREFIX}/workspaces/{workspace_id}/documents/"
        f"{first['document_id']}/preparation",
    )
    assert repeated.status_code == 200
    assert repeated.json()["data"]["run_id"] == prepared.json()["data"]["run_id"]

    run_list = app_client.get(
        f"{API_V1_PREFIX}/workspaces/{workspace_id}/pipeline-runs"
    )
    assert run_list.status_code == 200
    assert run_list.json()["data"]["count"] == 1
    run_summary = run_list.json()["data"]["items"][0]
    assert set(run_summary) == {
        "run_id",
        "pipeline_name",
        "scope_type",
        "scope_id",
        "status",
        "current_node",
        "progress_percent",
        "progress_detail",
        "errors",
        "warnings",
        "updated_at",
    }
    assert run_summary["pipeline_name"] == "document_preparation"

    run_detail = app_client.get(
        f"{API_V1_PREFIX}/pipeline-runs/{prepared.json()['data']['run_id']}"
    )
    assert run_detail.status_code == 200
    assert {
        "workspace_id",
        "mode",
        "input_fingerprint",
        "nodes",
        "stats",
        "context",
        "resumed_from_run_id",
        "created_at",
        "started_at",
        "finished_at",
    } <= set(run_detail.json()["data"])


def test_pipeline_run_detail_is_hidden_from_non_owner(app_client) -> None:
    workspace_id = _create_workspace(app_client, "Private pipeline run")
    document = _upload(app_client, workspace_id, "paper.txt", b"Methods")
    prepared = app_client.post(
        f"{API_V1_PREFIX}/workspaces/{workspace_id}/documents/"
        f"{document['document_id']}/preparation",
    )
    assert prepared.status_code == 200

    auth = auth_service
    asyncio.run(
        auth.create_subject(
            email="other@example.com",
        )
    )
    app_client.cookies.set("lens_session", "fixture:" + "other@example.com")

    response = app_client.get(
        f"{API_V1_PREFIX}/pipeline-runs/{prepared.json()['data']['run_id']}"
    )
    assert response.status_code == 200
    assert response.json()["code"] == 200201


def test_pipeline_run_workspace_endpoints_are_hidden_from_non_owner(
    app_client,
) -> None:
    workspace_id = _create_workspace(app_client, "Private pipeline history")
    document = _upload(app_client, workspace_id, "paper.txt", b"Methods")
    prepared = app_client.post(
        f"{API_V1_PREFIX}/workspaces/{workspace_id}/documents/"
        f"{document['document_id']}/preparation",
    )
    assert prepared.status_code == 200

    auth = auth_service
    asyncio.run(
        auth.create_subject(
            email="other@example.com",
        )
    )
    app_client.cookies.set("lens_session", "fixture:" + "other@example.com")

    listed = app_client.get(
        f"{API_V1_PREFIX}/workspaces/{workspace_id}/pipeline-runs"
    )
    assert listed.status_code == 200
    assert listed.json()["code"] == 200201
    queued = app_client.post(
        f"{API_V1_PREFIX}/workspaces/{workspace_id}/documents/"
        f"{document['document_id']}/preparation",
    )
    assert queued.status_code == 200
    assert queued.json()["code"] == 200201


def test_document_preparation_contract_has_no_request_body(app_client) -> None:
    operation = app_client.get("/api/openapi.json").json()["paths"][
        "/api/v1/workspaces/{workspace_id}/documents/{document_id}/preparation"
    ]["post"]

    assert "requestBody" not in operation


@pytest.mark.parametrize(
    "retired_path",
    (
        "/comparable-results",
        "/workspaces/{workspace_id}/research-view",
        "/workspaces/{workspace_id}/materials",
        "/workspaces/{workspace_id}/results",
        "/workspaces/{workspace_id}/evidence/cards",
        "/workspaces/{workspace_id}/graph",
        "/workspaces/{workspace_id}/graphml",
    ),
)
def test_retired_build_and_projection_routes_are_not_registered(
    app_client,
    retired_path,
) -> None:
    workspace_id = _create_workspace(app_client, "Current routes only")
    path = retired_path.format(workspace_id=workspace_id)
    response = (
        app_client.post(f"{API_V1_PREFIX}{path}", json={})
        if "/pipeline-runs/" in path
        else app_client.get(f"{API_V1_PREFIX}{path}")
    )

    assert response.status_code == 200
    assert response.json()["code"] == 200201


def test_objective_experiment_plan_routes_are_registered(app_client) -> None:
    openapi = app_client.get("/api/openapi.json")
    assert openapi.status_code == 200
    paths = openapi.json()["paths"]
    plan_list_path = (
        f"{API_V1_PREFIX}/workspaces/{{workspace_id}}/objectives/"
        "{objective_id}/experiment-plans"
    )
    plan_detail_path = f"{plan_list_path}/{{plan_id}}"

    assert "get" in paths[plan_list_path]
    assert "post" in paths[plan_list_path]
    assert "patch" in paths[plan_detail_path]


def test_goal_intake_creates_a_workspace_with_no_documents(app_client) -> None:
    response = app_client.post(
        f"{API_V1_PREFIX}/goals/intake",
        json={
            "material_system": "Ti-6Al-4V",
            "target_property": "tensile strength",
            "intent": "compare",
            "constraints": {"process": "LPBF"},
        },
    )

    assert response.status_code == 200
    workspace_id = response.json()["data"]["seed_workspace"]["workspace_id"]
    workspace = app_client.get(f"{API_V1_PREFIX}/workspaces/{workspace_id}")
    assert workspace.status_code == 200
    assert workspace.json()["data"]["workspace_id"] == workspace_id
    assert workspace.json()["data"]["documents"] == []
    assert workspace.json()["data"]["paper_count"] == 0


def test_delete_workspace_removes_current_documents(app_client) -> None:
    workspace_id = _create_workspace(app_client, "Delete current documents")
    _upload(app_client, workspace_id, "paper.txt", b"Paper")

    deleted = app_client.delete(f"{API_V1_PREFIX}/workspaces/{workspace_id}")

    assert deleted.status_code == 200
    assert deleted.json()["data"]["workspace_id"] == workspace_id
    assert app_client.get(f'{API_V1_PREFIX}/workspaces/{workspace_id}').status_code == 200
    assert app_client.get(f'{API_V1_PREFIX}/workspaces/{workspace_id}').json()["code"] == 200201
