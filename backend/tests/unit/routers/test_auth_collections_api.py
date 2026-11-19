from __future__ import annotations

from application.chat import session_service as shared_chat_service

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock
from zipfile import ZipFile

import application.source.source_archive_service as source_archive_service_module
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _valid_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    payload = BytesIO()
    writer.write(payload)
    return payload.getvalue()


@contextmanager
def _build_client(
    monkeypatch,
    tmp_path,
    identity_subjects,
    collection_service,
    *,
    postgres_session_factory,
) -> Iterator[TestClient]:
    from application.pipeline import pipeline_run_service
    from repositories.pipeline_run_repository import PipelineRunRepository

    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("main.DATA_DIR", tmp_path)
    monkeypatch.setattr(
        "infra.persistence.database.AsyncSessionLocal", postgres_session_factory
    )
    monkeypatch.setattr(
        "main.build_database_engine",
        lambda _settings: postgres_session_factory.kw["bind"],
    )
    from main import create_app

    pipeline_run_service.PipelineRunRepo = PipelineRunRepository()
    with TestClient(create_app()) as client:
        yield client


def _bind_subject(client: TestClient, email="admin@example.com"):
    client.cookies.set("lens_session", "fixture:" + email)


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


def test_app_disposes_owned_database_engine_when_identity_start_fails(
    monkeypatch,
) -> None:
    from main import create_app

    engine = Mock()
    engine.dispose = AsyncMock()
    service = Mock(side_effect=RuntimeError("identity failed"))
    monkeypatch.setattr("main.DatabaseSettings", lambda: object())
    monkeypatch.setattr("main.build_database_engine", lambda _settings: engine)
    sessions = MagicMock()
    sessions.return_value.__aenter__.return_value.execute = AsyncMock(
        return_value=Mock(all=lambda: [])
    )
    monkeypatch.setattr("infra.persistence.database.AsyncSessionLocal", sessions)
    monkeypatch.setattr(
        "infra.identity.client.IdentityClient",
        service,
    )

    with pytest.raises(RuntimeError, match="identity failed"):
        with TestClient(create_app()):
            pass

    engine.dispose.assert_called_once_with()


def test_app_lifespan_uses_shared_module_dependencies(
    monkeypatch,
    tmp_path,
    identity_subjects,
    collection_service,
    *,
    postgres_session_factory,
) -> None:
    from application.chat import session_service as chat_session_service
    from application.core.document_profiles import service as document_profile_service
    from application.core.objectives import analysis_service, objective_analysis_service
    from application.goal import brief_service
    from application.pipeline import pipeline_run_service
    from application.source import (
        document_markdown_service,
        document_preparation_service,
    )
    from repositories.pipeline_run_repository import PipelineRunRepository

    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("main.DATA_DIR", tmp_path)
    monkeypatch.setattr(
        "infra.persistence.database.AsyncSessionLocal", postgres_session_factory
    )
    monkeypatch.setattr(
        "main.build_database_engine",
        lambda _settings: postgres_session_factory.kw["bind"],
    )
    from main import create_app

    pipeline_run_service.PipelineRunRepo = PipelineRunRepository()
    with TestClient(create_app()) as client:
        collection_consumers = (
            document_markdown_service,
            document_profile_service,
            brief_service,
            chat_session_service,
            objective_analysis_service,
            analysis_service.experiment_analysis_service,
        )

        assert all(
            service.collection_service is collection_service
            for service in collection_consumers
        )
        capability_names = {
            spec.name
            for spec in shared_chat_service.ChatService.capabilities.specs
        }
        assert {
            "get_collection_context",
            "inspect_document_sources",
            "search_sources",
            "read_source",
            "inspect_table",
            "inspect_research_process",
            "start_research_process",
            "query_published_findings",
            "inspect_published_finding",
            "record_finding_feedback",
            "curate_finding",
            "create_finding_draft",
            "create_finding_version",
            "propose_paper_experiment_draft",
            "create_paper_experiment_revision",
            "propose_objective_drafts",
            "preview_research_scope",
            "create_objective_candidate",
            "start_objective_analysis",
            "inspect_objective_analysis",
            "assess_objective_quality",
            "derive_objective",
            "propose_research_plan",
            "create_research_plan",
        }.issubset(capability_names)


def test_web_lifespan_does_not_claim_or_interrupt_worker_jobs(
    monkeypatch,
    tmp_path,
    identity_subjects,
    collection_service,
    *,
    postgres_session_factory,
) -> None:
    from application.core.objectives import (
        analysis_service as objective_analysis_service,
    )
    from application.pipeline import pipeline_run_service
    from application.source import document_preparation_service
    from main import create_app
    from repositories.pipeline_run_repository import PipelineRunRepository

    monkeypatch.setattr("config.DATA_DIR", tmp_path)
    monkeypatch.setattr("main.DATA_DIR", tmp_path)
    monkeypatch.setattr(
        "infra.persistence.database.AsyncSessionLocal", postgres_session_factory
    )
    monkeypatch.setattr(
        "main.build_database_engine",
        lambda _settings: postgres_session_factory.kw["bind"],
    )

    pipeline_run_service.PipelineRunRepo = PipelineRunRepository()
    with TestClient(create_app()):
        assert not hasattr(create_app, "_active_workers")


def test_collections_api_requires_authenticated_subject(
    monkeypatch,
    tmp_path,
    identity_subjects,
    collection_service,
    *,
    postgres_session_factory,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        identity_subjects,
        collection_service,
        postgres_session_factory=postgres_session_factory,
    ) as client:
        response = client.get("/api/v1/collections")

        assert response.status_code == 401
        assert response.json()["code"] == 200301
        assert response.json()["data"]["code"] == "authentication_required"




def test_collection_list_is_scoped_to_authenticated_owner(
    monkeypatch,
    tmp_path,
    identity_subjects,
    collection_service,
    *,
    postgres_session_factory,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        identity_subjects,
        collection_service,
        postgres_session_factory=postgres_session_factory,
    ) as client:
        _bind_subject(client)

        created = client.post("/api/v1/collections", json={"name": "Admin papers"})
        assert created.status_code == 200
        collection_id = created.json()["data"]["collection_id"]

        owner_list = client.get("/api/v1/collections")
        assert owner_list.status_code == 200
        assert [
            item["collection_id"] for item in owner_list.json()["data"]["items"]
        ] == [collection_id]

        auth_service = identity_subjects
        asyncio.run(
            auth_service.create_subject(
                email="other@example.com",
            )
        )
        client.cookies.clear()
        _bind_subject(client, "other@example.com")

        other_list = client.get("/api/v1/collections")
        assert other_list.status_code == 200
        assert other_list.json()["data"]["items"] == []

        other_get = client.get(f"/api/v1/collections/{collection_id}")
        assert other_get.status_code == 200
        assert other_get.json()["code"] == 200201
        assert other_get.json()["data"]["code"] == "collection_not_found"


def test_public_static_data_mount_is_removed(
    monkeypatch,
    tmp_path,
    identity_subjects,
    collection_service,
    *,
    postgres_session_factory,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        identity_subjects,
        collection_service,
        postgres_session_factory=postgres_session_factory,
    ) as client:
        leaked_path = tmp_path / "leak.txt"
        leaked_path.write_text("secret", encoding="utf-8")

        response = client.get("/api/static/leak.txt")

        assert response.status_code == 200
        assert response.json()["code"] == 200201


def test_collection_source_archive_downloads_selected_original_files(
    monkeypatch,
    tmp_path,
    identity_subjects,
    collection_service,
    *,
    postgres_session_factory,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        identity_subjects,
        collection_service,
        postgres_session_factory=postgres_session_factory,
    ) as client:
        _bind_subject(client)
        created = client.post(
            "/api/v1/collections",
            json={"name": "Failed paper reproduction"},
        )
        collection_id = created.json()["data"]["collection_id"]
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
        document_id = upload.json()["data"]["document_id"]

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
    identity_subjects,
    collection_service,
    *,
    postgres_session_factory,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        identity_subjects,
        collection_service,
        postgres_session_factory=postgres_session_factory,
    ) as client:
        _bind_subject(client)
        created = client.post(
            "/api/v1/collections",
            json={"name": "Upload validation"},
        )
        collection_id = created.json()["data"]["collection_id"]

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

        assert response.status_code == 200
        assert response.json()["code"] == 200100
        assert response.json()["message"] == (
            "PDF is damaged, incomplete, password-protected, or otherwise unreadable."
        )
        assert response.json()["data"]["code"] == "upload_invalid"
        documents = client.get(f"/api/v1/collections/{collection_id}/documents")
        assert documents.status_code == 200
        assert documents.json()["data"]["items"] == []


def test_collection_source_archive_is_scoped_to_authenticated_owner(
    monkeypatch,
    tmp_path,
    identity_subjects,
    collection_service,
    *,
    postgres_session_factory,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        identity_subjects,
        collection_service,
        postgres_session_factory=postgres_session_factory,
    ) as client:
        _bind_subject(client)
        created = client.post(
            "/api/v1/collections",
            json={"name": "Private failures"},
        )
        collection_id = created.json()["data"]["collection_id"]
        auth_service = identity_subjects
        asyncio.run(
            auth_service.create_subject(
                email="other@example.com",
            )
        )
        client.cookies.clear()
        _bind_subject(client, "other@example.com")

        response = client.post(
            f"/api/v1/collections/{collection_id}/source-archives",
            json={"document_ids": ["doc_private"]},
        )

        assert response.status_code == 200
        assert response.json()["code"] == 200201
        assert response.json()["data"]["code"] == "collection_not_found"


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
    identity_subjects,
    collection_service,
    document_ids,
    *,
    postgres_session_factory,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        identity_subjects,
        collection_service,
        postgres_session_factory=postgres_session_factory,
    ) as client:
        _bind_subject(client)
        created = client.post(
            "/api/v1/collections",
            json={"name": "Invalid selection"},
        )

        response = client.post(
            f"/api/v1/collections/{created.json()['data']['collection_id']}/source-archives",
            json={"document_ids": document_ids},
        )

        assert response.status_code == 200
        assert response.json()["code"] == 200100


def test_collection_source_archive_returns_bounded_missing_file_error(
    monkeypatch,
    tmp_path,
    identity_subjects,
    collection_service,
    *,
    postgres_session_factory,
):
    with _build_client(
        monkeypatch,
        tmp_path,
        identity_subjects,
        collection_service,
        postgres_session_factory=postgres_session_factory,
    ) as client:
        _bind_subject(client)
        created = client.post(
            "/api/v1/collections",
            json={"name": "Missing file"},
        )
        collection_id = created.json()["data"]["collection_id"]

        response = client.post(
            f"/api/v1/collections/{collection_id}/source-archives",
            json={"document_ids": ["doc_missing"]},
        )

        assert response.status_code == 200
        assert response.json()["code"] == 200201
        assert response.json()["data"] == {
            "code": "collection_source_document_not_found",
            "collection_id": collection_id,
            "document_id": "doc_missing",
        }


def test_collection_source_archive_returns_413_for_oversized_selection(
    monkeypatch,
    tmp_path,
    identity_subjects,
    collection_service,
    *,
    postgres_session_factory,
):
    monkeypatch.setattr(source_archive_service_module, "_SOURCE_ARCHIVE_MAX_BYTES", 3)
    with _build_client(
        monkeypatch,
        tmp_path,
        identity_subjects,
        collection_service,
        postgres_session_factory=postgres_session_factory,
    ) as client:
        _bind_subject(client)
        created = client.post(
            "/api/v1/collections",
            json={"name": "Oversized archive"},
        )
        collection_id = created.json()["data"]["collection_id"]
        upload = client.post(
            f"/api/v1/collections/{collection_id}/documents",
            files={"file": ("paper.pdf", _valid_pdf_bytes(), "application/pdf")},
        )

        response = client.post(
            f"/api/v1/collections/{collection_id}/source-archives",
            json={"document_ids": [upload.json()["data"]["document_id"]]},
        )

        assert response.status_code == 200
        assert response.json()["code"] == 200100
        assert response.json()["data"] == {
            "code": "collection_source_archive_too_large",
            "collection_id": collection_id,
        }
