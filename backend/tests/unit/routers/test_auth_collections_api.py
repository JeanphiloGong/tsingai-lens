from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import AsyncMock, Mock
from zipfile import ZipFile

from fastapi.testclient import TestClient
from pypdf import PdfWriter
import pytest

import application.source.collection_service as collection_service_module

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _valid_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    payload = BytesIO()
    writer.write(payload)
    return payload.getvalue()


def _app_repository_dependencies(auth_session_service) -> dict[str, object]:
    from tests.support.experiment_plan_repository import (
        InMemoryExperimentPlanRepository,
    )
    from infra.persistence.memory.objective_repository import MemoryObjectiveRepository
    from tests.support.objective_review_repository import (
        InMemoryObjectiveReviewRepository,
    )
    from infra.persistence.memory import (
        MemoryDocumentProfileRepository,
        MemoryPaperMapRepository,
        MemorySourceArtifactRepository,
    )

    return {
        "source_artifact_repository": MemorySourceArtifactRepository(),
        "document_profile_repository": MemoryDocumentProfileRepository(),
        "paper_map_repository": MemoryPaperMapRepository(),
        "objective_repository": MemoryObjectiveRepository(),
        "finding_review_repository": InMemoryObjectiveReviewRepository(),
        "experiment_plan_repository": InMemoryExperimentPlanRepository(),
        "chat_repository": object(),
    }


@contextmanager
def _build_client(
    monkeypatch,
    tmp_path,
    auth_session_service,
    collection_service,
) -> Iterator[TestClient]:
    from application.source.task_service import TaskService
    from infra.persistence.memory import MemoryTaskRepository

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin-password")
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("main.DATA_DIR", tmp_path)
    from main import create_app

    with TestClient(
        create_app(
            auth_session_service=auth_session_service,
            collection_service=collection_service,
            task_service=TaskService(MemoryTaskRepository()),
            **_app_repository_dependencies(auth_session_service),
        )
    ) as client:
        yield client


def _login(
    client: TestClient,
    email: str = "admin@example.com",
    password: str = "admin-password",
):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def test_main_app_import_defers_collection_and_database_initialization() -> None:
    env = os.environ.copy()
    env.pop("LENS_DATABASE_URL", None)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import infra.persistence.database as database\n"
                "def fail_if_called(*args, **kwargs):\n"
                "    raise RuntimeError('database initialized during import')\n"
                "database.build_database_engine = fail_if_called\n"
                "import main\n"
            ),
        ],
        cwd=BACKEND_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_app_disposes_owned_database_engine_when_bootstrap_fails(monkeypatch) -> None:
    from main import create_app

    engine = Mock()
    engine.dispose = AsyncMock()
    service = Mock()
    service.ensure_bootstrap_user = AsyncMock(
        side_effect=RuntimeError("bootstrap failed")
    )
    monkeypatch.setattr("main.DatabaseSettings", lambda: object())
    monkeypatch.setattr("main.build_database_engine", lambda _settings: engine)
    monkeypatch.setattr("main.build_session_factory", lambda _engine: object())
    monkeypatch.setattr("main.PostgresAuthRepository", lambda _factory: object())
    monkeypatch.setattr("main.AuthSessionService", lambda _repository: service)

    with pytest.raises(RuntimeError, match="bootstrap failed"):
        with TestClient(create_app()):
            pass

    engine.dispose.assert_called_once_with()


def test_app_lifespan_composes_one_shared_collection_service(
    monkeypatch,
    tmp_path,
    auth_session_service,
    collection_service,
) -> None:
    from application.source.task_service import TaskService
    from infra.persistence.memory import MemoryTaskRepository

    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("main.DATA_DIR", tmp_path)
    from main import create_app

    with TestClient(
        create_app(
            auth_session_service=auth_session_service,
            collection_service=collection_service,
            task_service=TaskService(MemoryTaskRepository()),
            **_app_repository_dependencies(auth_session_service),
        )
    ) as client:
        state = client.app.state
        collection_service = state.collection_service
        collection_consumers = (
            state.document_preparation_service,
            state.document_markdown_service,
            state.document_profile_service,
            state.goal_service,
            state.chat_session_service,
            state.research_objective_service,
            state.objective_analysis_service.research_objective_service,
        )

        assert all(
            service.collection_service is collection_service
            for service in collection_consumers
        )
        assert "start_research_process" in {
            spec.name
            for spec in state.chat_session_service.runner.capabilities.specs
        }


def test_collections_api_requires_login(
    monkeypatch,
    tmp_path,
    auth_session_service,
    collection_service,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        auth_session_service,
        collection_service,
    ) as client:
        response = client.get("/api/v1/collections")

        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "authentication_required"


def test_login_me_and_logout_flow(
    monkeypatch,
    tmp_path,
    auth_session_service,
    collection_service,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        auth_session_service,
        collection_service,
    ) as client:
        login = _login(client)
        assert login.status_code == 200
        assert login.json()["user"]["email"] == "admin@example.com"

        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["user"]["email"] == "admin@example.com"

        logout = client.post("/api/v1/auth/logout")
        assert logout.status_code == 200

        after_logout = client.get("/api/v1/auth/me")
        assert after_logout.status_code == 401


def test_collection_list_is_scoped_to_authenticated_owner(
    monkeypatch,
    tmp_path,
    auth_session_service,
    collection_service,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        auth_session_service,
        collection_service,
    ) as client:
        assert _login(client).status_code == 200

        created = client.post("/api/v1/collections", json={"name": "Admin papers"})
        assert created.status_code == 200
        collection_id = created.json()["collection_id"]

        owner_list = client.get("/api/v1/collections")
        assert owner_list.status_code == 200
        assert [item["collection_id"] for item in owner_list.json()["items"]] == [
            collection_id
        ]

        auth_service = client.app.state.auth_session_service
        asyncio.run(
            auth_service.create_user(
            email="other@example.com",
            password="other-password",
            )
        )
        client.cookies.clear()
        assert _login(client, "other@example.com", "other-password").status_code == 200

        other_list = client.get("/api/v1/collections")
        assert other_list.status_code == 200
        assert other_list.json()["items"] == []

        other_get = client.get(f"/api/v1/collections/{collection_id}")
        assert other_get.status_code == 404
        assert other_get.json()["detail"]["code"] == "collection_not_found"


def test_public_static_data_mount_is_removed(
    monkeypatch,
    tmp_path,
    auth_session_service,
    collection_service,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        auth_session_service,
        collection_service,
    ) as client:
        leaked_path = tmp_path / "leak.txt"
        leaked_path.write_text("secret", encoding="utf-8")

        response = client.get("/api/static/leak.txt")

        assert response.status_code == 404


def test_collection_source_archive_downloads_selected_original_files(
    monkeypatch,
    tmp_path,
    auth_session_service,
    collection_service,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        auth_session_service,
        collection_service,
    ) as client:
        assert _login(client).status_code == 200
        created = client.post(
            "/api/v1/collections",
            json={"name": "Failed paper reproduction"},
        )
        collection_id = created.json()["collection_id"]
        source_pdf = _valid_pdf_bytes()
        upload = client.post(
            f"/api/v1/collections/{collection_id}/documents",
            files={
                "file": (
                    "failed.pdf",
                    source_pdf,
                    "application/pdf",
                )
            },
        )
        document_id = upload.json()["document_id"]

        response = client.post(
            f"/api/v1/collections/{collection_id}/source-archives",
            json={"document_ids": [document_id]},
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert response.headers["content-disposition"].startswith("attachment;")
        with ZipFile(BytesIO(response.content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["documents"][0]["document_id"] == document_id
            assert archive.read(manifest["documents"][0]["archive_path"]) == source_pdf


def test_collection_upload_rejects_unreadable_pdf_without_persisting_it(
    monkeypatch,
    tmp_path,
    auth_session_service,
    collection_service,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        auth_session_service,
        collection_service,
    ) as client:
        assert _login(client).status_code == 200
        created = client.post(
            "/api/v1/collections",
            json={"name": "Upload validation"},
        )
        collection_id = created.json()["collection_id"]

        response = client.post(
            f"/api/v1/collections/{collection_id}/documents",
            files={
                "file": (
                    "truncated.pdf",
                    _valid_pdf_bytes()[:100],
                    "application/pdf",
                )
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == (
            "PDF is damaged, incomplete, password-protected, or otherwise unreadable."
        )
        documents = client.get(f"/api/v1/collections/{collection_id}/documents")
        assert documents.status_code == 200
        assert documents.json()["items"] == []


def test_collection_source_archive_is_scoped_to_authenticated_owner(
    monkeypatch,
    tmp_path,
    auth_session_service,
    collection_service,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        auth_session_service,
        collection_service,
    ) as client:
        assert _login(client).status_code == 200
        created = client.post(
            "/api/v1/collections",
            json={"name": "Private failures"},
        )
        collection_id = created.json()["collection_id"]
        auth_service = client.app.state.auth_session_service
        asyncio.run(
            auth_service.create_user(
                email="other@example.com",
                password="other-password",
            )
        )
        client.cookies.clear()
        assert _login(client, "other@example.com", "other-password").status_code == 200

        response = client.post(
            f"/api/v1/collections/{collection_id}/source-archives",
            json={"document_ids": ["doc_private"]},
        )

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "collection_not_found"


@pytest.mark.parametrize(
    "document_ids",
    [
        [],
        ["doc_same", "doc_same"],
        [f"doc_{index}" for index in range(101)],
    ],
)
def test_collection_source_archive_rejects_invalid_file_selection(
    monkeypatch,
    tmp_path,
    auth_session_service,
    collection_service,
    document_ids,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        auth_session_service,
        collection_service,
    ) as client:
        assert _login(client).status_code == 200
        created = client.post(
            "/api/v1/collections",
            json={"name": "Invalid selection"},
        )

        response = client.post(
            f"/api/v1/collections/{created.json()['collection_id']}/source-archives",
            json={"document_ids": document_ids},
        )

        assert response.status_code == 422


def test_collection_source_archive_returns_bounded_missing_file_error(
    monkeypatch,
    tmp_path,
    auth_session_service,
    collection_service,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        auth_session_service,
        collection_service,
    ) as client:
        assert _login(client).status_code == 200
        created = client.post(
            "/api/v1/collections",
            json={"name": "Missing file"},
        )
        collection_id = created.json()["collection_id"]

        response = client.post(
            f"/api/v1/collections/{collection_id}/source-archives",
            json={"document_ids": ["doc_missing"]},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == {
            "code": "collection_source_document_not_found",
            "message": "A requested source document does not exist in this collection.",
            "collection_id": collection_id,
            "document_id": "doc_missing",
        }


def test_collection_source_archive_returns_413_for_oversized_selection(
    monkeypatch,
    tmp_path,
    auth_session_service,
    collection_service,
):
    monkeypatch.setattr(collection_service_module, "_SOURCE_ARCHIVE_MAX_BYTES", 3)
    with _build_client(
        monkeypatch,
        tmp_path,
        auth_session_service,
        collection_service,
    ) as client:
        assert _login(client).status_code == 200
        created = client.post(
            "/api/v1/collections",
            json={"name": "Oversized archive"},
        )
        collection_id = created.json()["collection_id"]
        upload = client.post(
            f"/api/v1/collections/{collection_id}/documents",
            files={"file": ("paper.pdf", _valid_pdf_bytes(), "application/pdf")},
        )

        response = client.post(
            f"/api/v1/collections/{collection_id}/source-archives",
            json={"document_ids": [upload.json()["document_id"]]},
        )

        assert response.status_code == 413
        assert response.json()["detail"] == {
            "code": "collection_source_archive_too_large",
            "message": "Selected source files exceed the 256 MiB archive limit.",
            "collection_id": collection_id,
        }
