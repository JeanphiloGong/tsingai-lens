from __future__ import annotations

from application.source.task_service import TaskService


def test_task_service_lists_collection_tasks_with_status_and_offset(tmp_path):
    task_service = TaskService(tmp_path / "tasks")

    task_a = task_service.create_task("col_a", "index")
    task_b = task_service.create_task("col_a", "index")
    task_c = task_service.create_task("col_b", "index")

    task_service.update_task(task_a["task_id"], status="completed", progress_percent=100)
    task_service.update_task(task_b["task_id"], status="failed", progress_percent=35)
    task_service.update_task(task_c["task_id"], status="completed", progress_percent=100)

    col_a_tasks = task_service.list_tasks(collection_id="col_a")
    assert [item["task_id"] for item in col_a_tasks] == [task_b["task_id"], task_a["task_id"]]

    completed = task_service.list_tasks(collection_id="col_a", status="completed")
    assert [item["task_id"] for item in completed] == [task_a["task_id"]]

    paged = task_service.list_tasks(collection_id="col_a", limit=1, offset=1)
    assert [item["task_id"] for item in paged] == [task_a["task_id"]]


def test_task_service_preserves_source_stage_values_without_legacy_aliases(tmp_path):
    task_service = TaskService(tmp_path / "tasks")

    task = task_service.create_task("col_a", "index")
    stored = task_service.repository.read_task(task["task_id"])
    assert stored is not None

    task_service.repository.write_task(
        task["task_id"],
        {
            **stored,
            "current_stage": "source_index_started",
        },
    )

    fetched = task_service.get_task(task["task_id"])
    assert fetched["current_stage"] == "source_index_started"

    listed = task_service.list_tasks(collection_id="col_a")
    assert listed[0]["current_stage"] == "source_index_started"

    updated = task_service.update_task(
        task["task_id"],
        current_stage="source_index_completed",
    )
    assert updated["current_stage"] == "source_index_completed"

    persisted = task_service.repository.read_task(task["task_id"])
    assert persisted is not None
    assert persisted["current_stage"] == "source_index_completed"
