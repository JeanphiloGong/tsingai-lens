from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from domain.pipeline import (
    ExecutionStats,
    ExecutionTimestamps,
    ModelUsage,
    PipelineNodeRun,
    TokenUsage,
)
from domain.source import (
    ArtifactVersionRecord,
    BuildStageRecord,
    CollectionRecord,
    TaskRecord,
)
from infra.persistence.postgres.auth_repository import PostgresAuthRepository
from infra.persistence.postgres.build_repository import PostgresBuildRepository
from infra.persistence.postgres.collection_repository import (
    PostgresCollectionRepository,
)
pytestmark = pytest.mark.anyio


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
        stage_order=stage_order,
        node=PipelineNodeRun(
            name=stage_kind,
            dependencies=("source_artifacts",)
            if stage_kind == "artifact_registry"
            else (),
            status="succeeded",
            timestamps=ExecutionTimestamps(
                started_at="2026-07-19T10:01:00+00:00",
                finished_at="2026-07-19T10:02:00+00:00",
            ),
        ),
    )


async def _prepare_database(
    sessions,
) -> tuple[PostgresBuildRepository, PostgresCollectionRepository]:
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    await PostgresAuthRepository(sessions).add_user(
        {
            "user_id": "user_builds",
            "email": "builds@example.com",
            "display_name": None,
            "password_hash": "synthetic-password-hash",
            "created_at": now.isoformat(),
        }
    )
    collections = PostgresCollectionRepository(sessions)
    await collections.add_collection(
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
async def build_repository(postgres_session_factory):
    repository, _collections = await _prepare_database(postgres_session_factory)
    return repository


async def test_build_repository_round_trips_ordered_task_stage_and_artifact_lineage(
    build_repository,
) -> None:
    first = _task("task_first", created_at="2026-07-19T10:00:00+00:00")
    second = _task("task_second", created_at="2026-07-19T10:01:00+00:00")

    first_build = await build_repository.add_task(first, build_id="build_first")
    second_build = await build_repository.add_task(second, build_id="build_second")

    assert first_build.build_number == 1
    assert second_build.build_number == 2
    assert await build_repository.read_task(first.task_id) == first
    assert await build_repository.read_build(first.task_id) == first_build
    assert await build_repository.list_tasks(
        collection_id="col_builds", limit=1
    ) == (second,)

    source_stage = _stage(first_build.build_id, "source_artifacts", 0)
    stages = (
        replace(
            source_stage,
            node=replace(
                source_stage.node,
                stats=ExecutionStats(
                    duration_ms=60000,
                    model_usage=(
                        ModelUsage(
                            "merged-qwen",
                            2,
                            TokenUsage(1800, 240, 2040),
                        ),
                    ),
                    prompt_versions={
                        "document_profile": "document_profile.v1"
                    },
                ),
            ),
        ),
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
    assert await build_repository.update_task(running, stages=stages) is True
    assert await build_repository.list_stages(first.task_id) == stages

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
    await build_repository.add_artifact_versions(first.task_id, (artifact,))
    assert await build_repository.list_artifact_versions(first.task_id) == (
        artifact,
    )

    with pytest.raises(IntegrityError):
        await build_repository.add_artifact_versions(first.task_id, (artifact,))


async def test_failed_and_older_builds_cannot_replace_active_success(
    build_repository,
) -> None:
    first = _task("task_first", created_at="2026-07-19T10:00:00+00:00")
    second = _task("task_second", created_at="2026-07-19T10:01:00+00:00")
    third = _task("task_third", created_at="2026-07-19T10:02:00+00:00")
    first_build = await build_repository.add_task(first, build_id="build_first")
    second_build = await build_repository.add_task(second, build_id="build_second")
    third_build = await build_repository.add_task(third, build_id="build_third")

    completed_second = replace(
        second,
        status="completed",
        current_stage="artifacts_ready",
        progress_percent=100,
        updated_at="2026-07-19T10:03:00+00:00",
        finished_at="2026-07-19T10:03:00+00:00",
    )
    await build_repository.finish_build(
        completed_second,
        build_status="succeeded",
        activate=True,
    )
    assert await build_repository.read_active_build("col_builds") == replace(
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
    await build_repository.finish_build(
        failed_third,
        build_status="failed",
        activate=False,
    )
    assert (
        (await build_repository.read_active_build("col_builds")).build_id
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
    await build_repository.finish_build(
        completed_first,
        build_status="succeeded",
        activate=True,
    )
    assert (
        (await build_repository.read_active_build("col_builds")).build_id
        == second_build.build_id
    )
    assert (
        first_build.build_number < second_build.build_number < third_build.build_number
    )


async def test_collection_delete_cascades_complete_build_lineage(
    build_repository,
) -> None:
    task = _task("task_delete", created_at="2026-07-19T10:00:00+00:00")
    build = await build_repository.add_task(task, build_id="build_delete")
    stage = _stage(build.build_id, "artifact_registry", 0)
    await build_repository.update_task(task, stages=(stage,))
    await build_repository.add_artifact_versions(
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
    await build_repository.finish_build(
        completed,
        build_status="succeeded",
        activate=True,
    )

    collections = PostgresCollectionRepository(build_repository.session_factory)
    assert await collections.delete_collection("col_builds") is True
    assert await build_repository.read_task(task.task_id) is None
    assert await build_repository.read_build(task.task_id) is None
    assert await build_repository.list_stages(task.task_id) == ()
    assert await build_repository.list_artifact_versions(task.task_id) == ()
    assert await build_repository.read_active_build("col_builds") is None


async def test_postgresql_serializes_concurrent_successful_activation(
    build_repository,
) -> None:
    first = _task("task_first", created_at="2026-07-19T10:00:00+00:00")
    second = _task("task_second", created_at="2026-07-19T10:01:00+00:00")
    await build_repository.add_task(first, build_id="build_first")
    second_build = await build_repository.add_task(second, build_id="build_second")

    async def finish(record: TaskRecord) -> None:
        await build_repository.finish_build(
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

    await asyncio.gather(finish(first), finish(second))

    assert (
        await build_repository.read_active_build("col_builds")
    ).build_id == second_build.build_id
