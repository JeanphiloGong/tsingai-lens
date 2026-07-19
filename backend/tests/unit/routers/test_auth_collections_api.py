from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[3]


@contextmanager
def _build_client(
    monkeypatch,
    tmp_path,
    auth_session_service,
    collection_service,
) -> Iterator[TestClient]:
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin-password")
    monkeypatch.setenv("LENS_PERSISTENCE_BACKEND", "file")
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("main.DATA_DIR", tmp_path)
    monkeypatch.setattr("infra.persistence.factory.DATA_DIR", tmp_path)
    monkeypatch.setattr("infra.persistence.file.artifact_repository.DATA_DIR", tmp_path)
    monkeypatch.setattr("infra.persistence.file.task_repository.DATA_DIR", tmp_path)

    from main import create_app

    with TestClient(
        create_app(
            auth_session_service=auth_session_service,
            collection_service=collection_service,
        )
    ) as client:
        yield client


def _login(client: TestClient, email: str = "admin@example.com", password: str = "admin-password"):
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
    service = Mock()
    service.ensure_bootstrap_user.side_effect = RuntimeError("bootstrap failed")
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
    monkeypatch.setenv("LENS_PERSISTENCE_BACKEND", "file")
    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("main.DATA_DIR", tmp_path)
    monkeypatch.setattr("infra.persistence.factory.DATA_DIR", tmp_path)
    monkeypatch.setattr("infra.persistence.file.artifact_repository.DATA_DIR", tmp_path)
    monkeypatch.setattr("infra.persistence.file.task_repository.DATA_DIR", tmp_path)

    from main import create_app

    with TestClient(
        create_app(
            auth_session_service=auth_session_service,
            collection_service=collection_service,
        )
    ) as client:
        state = client.app.state
        collection_service = state.collection_service
        collection_consumers = (
            state.build_pipeline_service,
            state.comparison_service,
            state.document_markdown_service,
            state.document_profile_service,
            state.goal_service,
            state.goal_session_service,
            state.paper_facts_service,
            state.research_objective_service,
            state.research_view_service,
            state.workspace_service,
            state.goal_analysis_service.research_objective_service,
        )

        assert all(
            service.collection_service is collection_service
            for service in collection_consumers
        )


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
        auth_service.create_user(email="other@example.com", password="other-password")
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
