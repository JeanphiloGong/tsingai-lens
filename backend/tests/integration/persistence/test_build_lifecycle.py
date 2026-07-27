from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import Barrier
from concurrent.futures import ThreadPoolExecutor

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import URL, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from domain.source import (
    ArtifactVersionRecord,
    BuildStageRecord,
    CollectionRecord,
    TaskRecord,
)
from infra.persistence.database import build_session_factory
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.build_repository import PostgresBuildRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from tests.integration.persistence.database_cleanup import reset_postgres_schema


BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _task(task_id: str, *, created_at: str, status: str = "queued") -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        collection_id="col_builds",
        task_type="build",
        status=status,
        current_stage="queued",
        progress_percent=0,
        progress_detail=None,
        output_path=None,
        errors=(),
        warnings=(),
        created_at=created_at,
        updated_at=created_at,
        started_at=None,
        finished_at=None,
    )


def _stage(build_id: str, stage_kind: str, stage_order: int) -> BuildStageRecord:
    return BuildStageRecord(
        stage_id=f"stage_{stage_order}",
        build_id=build_id,
        stage_kind=stage_kind,
        stage_version=1,
        stage_order=stage_order,
        status="succeeded",
        started_at="2026-07-19T10:01:00+00:00",
        finished_at="2026-07-19T10:02:00+00:00",
        errors=(),
        warnings=(),
        skip_reason=None,
    )


def _prepare_database(
    engine,
) -> tuple[PostgresBuildRepository, PostgresCollectionRepository]:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    sessions = build_session_factory(engine)
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    PostgresAuthRepository(sessions).add_user(
        {
            "user_id": "user_builds",
            "email": "builds@example.com",
            "display_name": None,
            "password_hash": "synthetic-password-hash",
            "created_at": now.isoformat(),
        }
    )
    collections = PostgresCollectionRepository(sessions)
    collections.add_collection(
        CollectionRecord(
            collection_id="col_builds",
            owner_user_id="user_builds",
            name="Build collection",
            description=None,
            status="idle",
            paper_count=0,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
    )
    return PostgresBuildRepository(sessions), collections


@pytest.fixture
def build_repository(tmp_path):
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(tmp_path / "builds.sqlite"))
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    repository, _collections = _prepare_database(engine)
    try:
        yield repository
    finally:
        engine.dispose()


def test_build_repository_round_trips_ordered_task_stage_and_artifact_lineage(
    build_repository,
) -> None:
    first = _task("task_first", created_at="2026-07-19T10:00:00+00:00")
    second = _task("task_second", created_at="2026-07-19T10:01:00+00:00")

    first_build = build_repository.add_task(first, build_id="build_first")
    second_build = build_repository.add_task(second, build_id="build_second")

    assert first_build.build_number == 1
    assert second_build.build_number == 2
    assert build_repository.read_task(first.task_id) == first
    assert build_repository.read_build(first.task_id) == first_build
    assert build_repository.list_tasks(collection_id="col_builds", limit=1) == (second,)

    stages = (
        _stage(first_build.build_id, "source_artifacts", 0),
        _stage(first_build.build_id, "artifact_registry", 1),
    )
    running = replace(
        first,
        status="running",
        current_stage="source_artifacts_completed",
        progress_percent=60,
        updated_at="2026-07-19T10:02:00+00:00",
        started_at="2026-07-19T10:01:00+00:00",
    )
    assert build_repository.update_task(running, stages=stages) is True
    assert build_repository.list_stages(first.task_id) == stages

    artifact = ArtifactVersionRecord(
        artifact_version_id="artifact_documents",
        build_stage_id=stages[1].stage_id,
        artifact_kind="documents",
        schema_version=1,
        content_version=1,
        status="ready",
        object_id=None,
        details={},
        created_at="2026-07-19T10:02:30+00:00",
    )
    build_repository.add_artifact_versions(first.task_id, (artifact,))
    assert build_repository.list_artifact_versions(first.task_id) == (artifact,)

    with pytest.raises(IntegrityError):
        build_repository.add_artifact_versions(first.task_id, (artifact,))


def test_failed_and_older_builds_cannot_replace_active_success(
    build_repository,
) -> None:
    first = _task("task_first", created_at="2026-07-19T10:00:00+00:00")
    second = _task("task_second", created_at="2026-07-19T10:01:00+00:00")
    third = _task("task_third", created_at="2026-07-19T10:02:00+00:00")
    first_build = build_repository.add_task(first, build_id="build_first")
    second_build = build_repository.add_task(second, build_id="build_second")
    third_build = build_repository.add_task(third, build_id="build_third")

    completed_second = replace(
        second,
        status="completed",
        current_stage="artifacts_ready",
        progress_percent=100,
        updated_at="2026-07-19T10:03:00+00:00",
        finished_at="2026-07-19T10:03:00+00:00",
    )
    build_repository.finish_build(
        completed_second,
        build_status="succeeded",
        activate=True,
    )
    assert build_repository.read_active_build("col_builds") == replace(
        second_build,
        status="succeeded",
        finished_at=completed_second.finished_at,
    )

    failed_third = replace(
        third,
        status="failed",
        current_stage="failed",
        progress_percent=100,
        updated_at="2026-07-19T10:04:00+00:00",
        finished_at="2026-07-19T10:04:00+00:00",
    )
    build_repository.finish_build(
        failed_third,
        build_status="failed",
        activate=False,
    )
    assert (
        build_repository.read_active_build("col_builds").build_id
        == second_build.build_id
    )

    completed_first = replace(
        first,
        status="completed",
        current_stage="artifacts_ready",
        progress_percent=100,
        updated_at="2026-07-19T10:05:00+00:00",
        finished_at="2026-07-19T10:05:00+00:00",
    )
    build_repository.finish_build(
        completed_first,
        build_status="succeeded",
        activate=True,
    )
    assert (
        build_repository.read_active_build("col_builds").build_id
        == second_build.build_id
    )
    assert (
        first_build.build_number < second_build.build_number < third_build.build_number
    )


def test_collection_delete_cascades_complete_build_lineage(build_repository) -> None:
    task = _task("task_delete", created_at="2026-07-19T10:00:00+00:00")
    build = build_repository.add_task(task, build_id="build_delete")
    stage = _stage(build.build_id, "artifact_registry", 0)
    build_repository.update_task(task, stages=(stage,))
    build_repository.add_artifact_versions(
        task.task_id,
        (
            ArtifactVersionRecord(
                artifact_version_id="artifact_delete",
                build_stage_id=stage.stage_id,
                artifact_kind="documents",
                schema_version=1,
                content_version=1,
                status="ready",
                object_id=None,
                details={},
                created_at="2026-07-19T10:02:30+00:00",
            ),
        ),
    )
    completed = replace(
        task,
        status="completed",
        current_stage="artifacts_ready",
        progress_percent=100,
        updated_at="2026-07-19T10:03:00+00:00",
        finished_at="2026-07-19T10:03:00+00:00",
    )
    build_repository.finish_build(
        completed,
        build_status="succeeded",
        activate=True,
    )

    collections = PostgresCollectionRepository(build_repository.session_factory)
    assert collections.delete_collection("col_builds") is True
    assert build_repository.read_task(task.task_id) is None
    assert build_repository.read_build(task.task_id) is None
    assert build_repository.list_stages(task.task_id) == ()
    assert build_repository.list_artifact_versions(task.task_id) == ()
    assert build_repository.read_active_build("col_builds") is None


def test_postgresql_serializes_concurrent_successful_activation() -> None:
    database_url = os.getenv("LENS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("LENS_TEST_DATABASE_URL is not configured")
    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg" or not str(url.database).endswith(
        "_test"
    ):
        pytest.fail(
            "LENS_TEST_DATABASE_URL must use postgresql+psycopg and a *_test database"
        )

    engine = create_engine(url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    try:
        reset_postgres_schema(engine)
        repository, _collections = _prepare_database(engine)
        first = _task("task_first", created_at="2026-07-19T10:00:00+00:00")
        second = _task("task_second", created_at="2026-07-19T10:01:00+00:00")
        repository.add_task(first, build_id="build_first")
        second_build = repository.add_task(second, build_id="build_second")
        barrier = Barrier(2)

        def finish(record: TaskRecord) -> None:
            barrier.wait()
            repository.finish_build(
                replace(
                    record,
                    status="completed",
                    current_stage="artifacts_ready",
                    progress_percent=100,
                    updated_at="2026-07-19T10:05:00+00:00",
                    finished_at="2026-07-19T10:05:00+00:00",
                ),
                build_status="succeeded",
                activate=True,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(finish, item) for item in (first, second)]
            for future in futures:
                future.result()

        assert (
            repository.read_active_build("col_builds").build_id == second_build.build_id
        )
    finally:
        reset_postgres_schema(engine)
        engine.dispose()
