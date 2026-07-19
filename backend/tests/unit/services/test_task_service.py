from __future__ import annotations

from application.source.task_service import TaskService
from infra.persistence.memory import MemoryBuildRepository


def test_task_service_lists_collection_tasks_with_status_and_offset() -> None:
    task_service = TaskService(MemoryBuildRepository())

    task_a = task_service.create_task("col_a", "build")
    task_b = task_service.create_task("col_a", "build")
    task_c = task_service.create_task("col_b", "build")

    task_service.finish_task(task_a["task_id"], status="completed")
    task_service.finish_task(
        task_b["task_id"],
        status="failed",
        progress_percent=35,
    )
    task_service.finish_task(task_c["task_id"], status="completed")

    col_a_tasks = task_service.list_tasks(collection_id="col_a")
    assert [item["task_id"] for item in col_a_tasks] == [
        task_b["task_id"],
        task_a["task_id"],
    ]

    completed = task_service.list_tasks(collection_id="col_a", status="completed")
    assert [item["task_id"] for item in completed] == [task_a["task_id"]]

    paged = task_service.list_tasks(collection_id="col_a", limit=1, offset=1)
    assert [item["task_id"] for item in paged] == [task_a["task_id"]]


def test_task_service_persists_pipeline_nodes_as_ordered_stages() -> None:
    repository = MemoryBuildRepository()
    task_service = TaskService(repository)
    task = task_service.create_task("col_a", "build")

    updated = task_service.update_task(
        task["task_id"],
        status="running",
        current_stage="source_artifacts_started",
        progress_percent=25,
        pipeline_nodes={
            "files_registered": {
                "status": "succeeded",
                "started_at": "2026-07-19T10:00:00+00:00",
                "finished_at": "2026-07-19T10:00:01+00:00",
                "errors": [],
                "warnings": [],
                "skip_reason": None,
            },
            "source_artifacts": {
                "status": "running",
                "started_at": "2026-07-19T10:00:01+00:00",
                "finished_at": None,
                "errors": [],
                "warnings": ["slow parser"],
                "skip_reason": None,
            },
        },
    )

    build = repository.read_build(task["task_id"])
    stages = repository.list_stages(task["task_id"])
    assert build is not None
    assert build.status == "building"
    assert [stage.stage_kind for stage in stages] == [
        "files_registered",
        "source_artifacts",
    ]
    assert stages[1].warnings == ("slow parser",)
    assert updated["pipeline_nodes"]["source_artifacts"]["status"] == "running"
    assert (
        task_service.get_task(task["task_id"])["pipeline_nodes"]
        == updated["pipeline_nodes"]
    )
    assert (
        task_service.list_tasks(collection_id="col_a")[0]["pipeline_nodes"]
        == (updated["pipeline_nodes"])
    )


def test_task_service_only_activates_newer_successful_builds() -> None:
    repository = MemoryBuildRepository()
    task_service = TaskService(repository)
    first = task_service.create_task("col_a", "build")
    second = task_service.create_task("col_a", "build")

    task_service.finish_task(second["task_id"], status="partial_success")
    active = repository.read_active_build("col_a")
    assert active is not None
    assert active.task_id == second["task_id"]

    task_service.finish_task(first["task_id"], status="completed")
    assert repository.read_active_build("col_a").task_id == second["task_id"]

    failed = task_service.create_task("col_a", "build")
    task_service.finish_task(failed["task_id"], status="failed")
    assert repository.read_active_build("col_a").task_id == second["task_id"]
