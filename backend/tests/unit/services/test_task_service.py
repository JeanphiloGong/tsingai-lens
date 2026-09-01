from __future__ import annotations

import pytest

from application.source.task_service import TaskService
from infra.persistence.memory import MemoryTaskRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_task_service_lists_document_tasks_with_status_and_offset() -> None:
    task_service = TaskService(MemoryTaskRepository())
    task_a = await task_service.create_task(
        "col_a", document_id="doc_a", input_fingerprint="fingerprint-a"
    )
    task_b = await task_service.create_task(
        "col_a", document_id="doc_b", input_fingerprint="fingerprint-b"
    )
    task_c = await task_service.create_task(
        "col_b", document_id="doc_c", input_fingerprint="fingerprint-c"
    )

    await task_service.finish_task(task_a["task_id"], status="completed")
    await task_service.finish_task(
        task_b["task_id"], status="failed", progress_percent=35
    )
    await task_service.finish_task(task_c["task_id"], status="completed")

    col_a_tasks = await task_service.list_tasks(collection_id="col_a")
    assert [item["task_id"] for item in col_a_tasks] == [
        task_b["task_id"],
        task_a["task_id"],
    ]
    assert [item["document_id"] for item in col_a_tasks] == ["doc_b", "doc_a"]

    completed = await task_service.list_tasks(
        collection_id="col_a", status="completed"
    )
    assert [item["task_id"] for item in completed] == [task_a["task_id"]]

    paged = await task_service.list_tasks(
        collection_id="col_a", limit=1, offset=1
    )
    assert [item["task_id"] for item in paged] == [task_a["task_id"]]


async def test_task_service_persists_document_progress_and_terminal_failure() -> None:
    task_service = TaskService(MemoryTaskRepository())
    task = await task_service.create_task(
        "col_a", document_id="doc_a", input_fingerprint="fingerprint-a"
    )

    running = await task_service.update_task(
        task["task_id"],
        status="running",
        current_stage="paper_map",
        progress_percent=65,
        progress_detail={
            "phase": "paper_map",
            "unit": "document",
            "message": "Mapping the paper's research scope.",
        },
    )
    assert running["document_id"] == "doc_a"
    assert running["current_stage"] == "paper_map"
    assert running["progress_percent"] == 65

    failed = await task_service.finish_task(
        task["task_id"],
        status="failed",
        current_stage="failed",
        errors=["invalid PDF"],
    )
    assert failed["status"] == "failed"
    assert failed["errors"] == ["invalid PDF"]
    assert failed["finished_at"] is not None


async def test_task_service_exposes_its_document_execution_identity() -> None:
    task_service = TaskService(MemoryTaskRepository())
    task = await task_service.create_task(
        "col_a", document_id="doc_a", input_fingerprint="fingerprint-a"
    )

    stored = await task_service.get_task(task["task_id"])

    assert stored["collection_id"] == "col_a"
    assert stored["document_id"] == "doc_a"
    assert stored["input_fingerprint"] == "fingerprint-a"


async def test_task_service_reuses_only_an_active_collection_task() -> None:
    task_service = TaskService(MemoryTaskRepository())

    first, first_created = await task_service.get_or_create_collection_task(
        collection_id="col_a",
        task_type="objective_discovery",
        input_fingerprint="scope-a",
        details={"document_ids": ["doc_a"]},
    )
    duplicate, duplicate_created = await task_service.get_or_create_collection_task(
        collection_id="col_a",
        task_type="objective_discovery",
        input_fingerprint="scope-b",
        details={"document_ids": ["doc_b"]},
    )

    assert first_created is True
    assert duplicate_created is False
    assert duplicate["task_id"] == first["task_id"]
    assert duplicate["details"] == {"document_ids": ["doc_a"]}

    finished = await task_service.finish_task(first["task_id"], status="failed")
    assert finished["details"] == {"document_ids": ["doc_a"]}
    retry, retry_created = await task_service.get_or_create_collection_task(
        collection_id="col_a",
        task_type="objective_discovery",
        input_fingerprint="scope-b",
        details={"document_ids": ["doc_b"]},
    )

    assert retry_created is True
    assert retry["task_id"] != first["task_id"]
    assert retry["details"] == {"document_ids": ["doc_b"]}
