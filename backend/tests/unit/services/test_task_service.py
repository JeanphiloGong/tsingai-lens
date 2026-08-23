from __future__ import annotations

from dataclasses import replace

import pytest

from application.source.task_service import TaskService
from domain.pipeline import PipelineRun
from infra.persistence.memory import MemoryBuildRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_task_service_lists_collection_tasks_with_status_and_offset() -> None:
    task_service = TaskService(MemoryBuildRepository())

    task_a = await task_service.create_task("col_a", "build")
    task_b = await task_service.create_task("col_a", "build")
    task_c = await task_service.create_task("col_b", "build")

    await task_service.finish_task(task_a["task_id"], status="completed")
    await task_service.finish_task(
        task_b["task_id"],
        status="failed",
        progress_percent=35,
    )
    await task_service.finish_task(task_c["task_id"], status="completed")

    col_a_tasks = await task_service.list_tasks(collection_id="col_a")
    assert [item["task_id"] for item in col_a_tasks] == [
        task_b["task_id"],
        task_a["task_id"],
    ]

    completed = await task_service.list_tasks(
        collection_id="col_a", status="completed"
    )
    assert [item["task_id"] for item in completed] == [task_a["task_id"]]

    paged = await task_service.list_tasks(
        collection_id="col_a", limit=1, offset=1
    )
    assert [item["task_id"] for item in paged] == [task_a["task_id"]]


async def test_task_service_persists_pipeline_nodes_as_ordered_stages() -> None:
    repository = MemoryBuildRepository()
    task_service = TaskService(repository)
    task = await task_service.create_task("col_a", "build")
    build = await repository.read_build(task["task_id"])
    assert build is not None
    pipeline_run = PipelineRun.create(
        pipeline_name="collection_build",
        mode="standard",
        run_id=task["task_id"],
        scope_type="collection",
        scope_id="col_a",
        node_dependencies={
            "source_artifacts": (),
            "document_profiles": ("source_artifacts",),
        },
        created_at=task["created_at"],
        output_build_id=build.build_id,
    ).start(task["created_at"])
    pipeline_run = pipeline_run.with_node(
        pipeline_run.node("source_artifacts").start(task["created_at"]).succeed(
            task["created_at"],
            output_summary={"document_count": 2},
        )
    )
    pipeline_run = pipeline_run.with_node(
        pipeline_run.node("document_profiles").start(task["created_at"])
    )

    updated = await task_service.update_task(
        task["task_id"],
        status="running",
        current_stage="document_profiles_started",
        progress_percent=70,
        pipeline_run=pipeline_run,
    )

    stages = await repository.list_stages(task["task_id"])
    build = await repository.read_build(task["task_id"])
    assert build is not None
    assert build.status == "building"
    assert [stage.node.name for stage in stages] == [
        "source_artifacts",
        "document_profiles",
    ]
    assert stages[0].node.output_summary == {"document_count": 2}
    assert updated["pipeline_nodes"]["document_profiles"]["status"] == "running"
    assert (
        (await task_service.get_task(task["task_id"]))["pipeline_nodes"]
        == updated["pipeline_nodes"]
    )
    assert (
        (await task_service.list_tasks(collection_id="col_a"))[0]["pipeline_nodes"]
        == (updated["pipeline_nodes"])
    )
    restored = await task_service.read_pipeline_run(task["task_id"])
    assert restored.run_id == task["task_id"]
    assert restored.mode == "standard"
    assert restored.output_build_id == build.build_id
    assert restored.node("document_profiles").dependencies == ("source_artifacts",)
    assert restored.node("source_artifacts").output_summary == {"document_count": 2}

    with pytest.raises(ValueError, match="another build"):
        await task_service.update_task(
            task["task_id"],
            pipeline_run=replace(pipeline_run, output_build_id="build_other"),
        )
    with pytest.raises(ValueError, match="another build mode"):
        await task_service.update_task(
            task["task_id"],
            pipeline_run=replace(pipeline_run, mode="fast"),
        )


async def test_task_service_only_activates_newer_successful_builds() -> None:
    repository = MemoryBuildRepository()
    task_service = TaskService(repository)
    first = await task_service.create_task("col_a", "build")
    second = await task_service.create_task("col_a", "build")

    await task_service.finish_task(second["task_id"], status="partial_success")
    active = await repository.read_active_build("col_a")
    assert active is not None
    assert active.task_id == second["task_id"]

    await task_service.finish_task(first["task_id"], status="completed")
    assert (await repository.read_active_build("col_a")).task_id == second["task_id"]

    failed = await task_service.create_task("col_a", "build")
    await task_service.finish_task(failed["task_id"], status="failed")
    assert (await repository.read_active_build("col_a")).task_id == second["task_id"]
