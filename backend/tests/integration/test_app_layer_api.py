from __future__ import annotations

from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from application.source.task_service import TaskService
from infra.persistence.memory import (
    MemoryDocumentProfileRepository,
    MemoryObjectiveRepository,
    MemoryPaperMapRepository,
    MemorySourceArtifactRepository,
    MemoryTaskRepository,
)
from tests.support.chat_repository import MemoryChatRepository
from tests.support.experiment_plan_repository import (
    InMemoryExperimentPlanRepository,
)
from tests.support.objective_review_repository import (
    InMemoryObjectiveReviewRepository,
)


API_V1_PREFIX = "/api/v1"


class _ImmediateDocumentPreparationService:
    """Complete the HTTP boundary test without invoking parser or LLM providers."""

    def __init__(self, collection_service, task_service) -> None:  # noqa: ANN001
        self.collection_service = collection_service
        self.task_service = task_service

    async def queue_document(
        self,
        collection_id: str,
        document_id: str,
        *,
        mode: str,
        request_id: str | None,
    ) -> dict:
        del request_id
        document = await self.collection_service.get_document(
            collection_id,
            document_id,
        )
        fingerprint = sha256(
            f"{document.sha256}:test-parser:test-analysis".encode("utf-8")
        ).hexdigest()
        task, created = await self.task_service.get_or_create_document_task(
            collection_id=collection_id,
            document_id=document_id,
            task_type="document_preparation",
            input_fingerprint=fingerprint,
            mode=mode,
        )
        if not created:
            return task
        await self.collection_service.update_document_preparation(
            collection_id,
            document_id,
            status="ready",
            preparation_fingerprint=fingerprint,
            parser_version="test-parser",
            document_analysis_version="test-analysis",
        )
        return await self.task_service.finish_task(
            task["task_id"],
            status="completed",
            current_stage="ready",
            progress_percent=100,
            progress_detail={
                "phase": "ready",
                "unit": "document",
                "message": "The document is ready.",
            },
        )


@pytest.fixture()
def app_client(monkeypatch, tmp_path, auth_session_service, collection_service):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin-password")
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("main.DATA_DIR", tmp_path)

    from main import create_app

    task_service = TaskService(MemoryTaskRepository())
    with TestClient(
        create_app(
            auth_session_service=auth_session_service,
            collection_service=collection_service,
            task_service=task_service,
            source_artifact_repository=MemorySourceArtifactRepository(),
            document_profile_repository=MemoryDocumentProfileRepository(),
            paper_map_repository=MemoryPaperMapRepository(),
            objective_repository=MemoryObjectiveRepository(),
            finding_review_repository=InMemoryObjectiveReviewRepository(),
            experiment_plan_repository=InMemoryExperimentPlanRepository(),
            chat_repository=MemoryChatRepository(),
        )
    ) as client:
        client.app.state.document_preparation_service = (
            _ImmediateDocumentPreparationService(collection_service, task_service)
        )
        login = client.post(
            f"{API_V1_PREFIX}/auth/login",
            json={"email": "admin@example.com", "password": "admin-password"},
        )
        assert login.status_code == 200
        yield client


def _create_collection(app_client, name: str = "Ti-6Al-4V papers") -> str:  # noqa: ANN001
    response = app_client.post(
        f"{API_V1_PREFIX}/collections",
        json={"name": name},
    )
    assert response.status_code == 200
    return response.json()["collection_id"]


def _upload(app_client, collection_id: str, filename: str, content: bytes) -> dict:  # noqa: ANN001
    response = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/documents",
        files={"file": (filename, content, "text/plain")},
    )
    assert response.status_code == 200
    return response.json()


def test_request_id_is_generated_and_echoed(app_client) -> None:
    response = app_client.get(f"{API_V1_PREFIX}/collections")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"].startswith("req_")


def test_documents_prepare_independently_and_new_uploads_do_not_rebuild_ready_work(
    app_client,
) -> None:
    collection_id = _create_collection(app_client)
    first = _upload(app_client, collection_id, "paper-a.txt", b"Methods\nPaper A")
    second = _upload(app_client, collection_id, "paper-b.txt", b"Results\nPaper B")

    prepared = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/documents/"
        f"{first['document_id']}/preparation",
        json={"mode": "standard"},
    )
    assert prepared.status_code == 200
    assert prepared.json()["status"] == "completed"
    assert prepared.json()["document_id"] == first["document_id"]

    after_first_preparation = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}"
    ).json()
    by_id = {
        item["document_id"]: item
        for item in after_first_preparation["documents"]
    }
    assert by_id[first["document_id"]]["status"] == "ready"
    assert by_id[first["document_id"]]["preparation_fingerprint"]
    assert by_id[second["document_id"]]["status"] == "stored"

    third = _upload(app_client, collection_id, "paper-c.txt", b"Discussion\nPaper C")
    after_addition = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}"
    ).json()
    by_id = {item["document_id"]: item for item in after_addition["documents"]}
    assert after_addition["paper_count"] == 3
    assert by_id[first["document_id"]]["status"] == "ready"
    assert by_id[second["document_id"]]["status"] == "stored"
    assert by_id[third["document_id"]]["status"] == "stored"

    repeated = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/documents/"
        f"{first['document_id']}/preparation",
        json={"mode": "standard"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["task_id"] == prepared.json()["task_id"]

    task_list = app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}/tasks"
    )
    assert task_list.status_code == 200
    assert task_list.json()["count"] == 1
    assert task_list.json()["items"][0]["task_type"] == "document_preparation"


def test_document_preparation_rejects_unknown_mode(app_client) -> None:
    collection_id = _create_collection(app_client, "Invalid preparation mode")
    document = _upload(app_client, collection_id, "paper.txt", b"Paper")

    response = app_client.post(
        f"{API_V1_PREFIX}/collections/{collection_id}/documents/"
        f"{document['document_id']}/preparation",
        json={"mode": "unknown"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "retired_path",
    (
        "/collections/{collection_id}/tasks/build",
        "/collections/{collection_id}/tasks/index",
        "/comparable-results",
        "/collections/{collection_id}/research-view",
        "/collections/{collection_id}/materials",
        "/collections/{collection_id}/results",
        "/collections/{collection_id}/evidence/cards",
        "/collections/{collection_id}/graph",
        "/collections/{collection_id}/graphml",
    ),
)
def test_retired_build_and_projection_routes_are_not_registered(
    app_client,
    retired_path,
) -> None:
    collection_id = _create_collection(app_client, "Current routes only")
    path = retired_path.format(collection_id=collection_id)
    response = (
        app_client.post(f"{API_V1_PREFIX}{path}", json={})
        if "/tasks/" in path
        else app_client.get(f"{API_V1_PREFIX}{path}")
    )

    assert response.status_code == 404


def test_objective_experiment_plan_routes_are_registered(app_client) -> None:
    openapi = app_client.get("/api/openapi.json")
    assert openapi.status_code == 200
    paths = openapi.json()["paths"]
    plan_list_path = (
        f"{API_V1_PREFIX}/collections/{{collection_id}}/objectives/"
        "{objective_id}/experiment-plans"
    )
    plan_detail_path = f"{plan_list_path}/{{plan_id}}"

    assert "get" in paths[plan_list_path]
    assert "post" in paths[plan_list_path]
    assert "patch" in paths[plan_detail_path]


def test_goal_intake_creates_a_collection_with_no_documents(app_client) -> None:
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
    collection_id = response.json()["seed_collection"]["collection_id"]
    collection = app_client.get(f"{API_V1_PREFIX}/collections/{collection_id}")
    assert collection.status_code == 200
    assert collection.json()["collection_id"] == collection_id
    assert collection.json()["documents"] == []
    assert collection.json()["paper_count"] == 0


def test_delete_collection_removes_current_documents(app_client) -> None:
    collection_id = _create_collection(app_client, "Delete current documents")
    _upload(app_client, collection_id, "paper.txt", b"Paper")

    deleted = app_client.delete(f"{API_V1_PREFIX}/collections/{collection_id}")

    assert deleted.status_code == 200
    assert deleted.json()["collection_id"] == collection_id
    assert app_client.get(
        f"{API_V1_PREFIX}/collections/{collection_id}"
    ).status_code == 404
