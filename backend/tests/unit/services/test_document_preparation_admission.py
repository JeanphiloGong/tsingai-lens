from __future__ import annotations

import pytest

from application.source.task_service import TaskService
from infra.persistence.memory import MemoryTaskRepository


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_same_document_reuses_its_active_preparation_task() -> None:
    service = TaskService(MemoryTaskRepository())

    first, first_created = await service.get_or_create_document_task(
        collection_id="col_a",
        document_id="doc_a",
        task_type="document_preparation",
        input_fingerprint="fp_a",
    )
    second, second_created = await service.get_or_create_document_task(
        collection_id="col_a",
        document_id="doc_a",
        task_type="document_preparation",
        input_fingerprint="fp_a",
    )

    assert first_created is True
    assert second_created is False
    assert second["task_id"] == first["task_id"]


async def test_different_documents_receive_independent_preparation_tasks() -> None:
    service = TaskService(MemoryTaskRepository())

    first, _ = await service.get_or_create_document_task(
        collection_id="col_a",
        document_id="doc_a",
        task_type="document_preparation",
        input_fingerprint="fp_a",
    )
    second, second_created = await service.get_or_create_document_task(
        collection_id="col_a",
        document_id="doc_b",
        task_type="document_preparation",
        input_fingerprint="fp_b",
    )

    assert second_created is True
    assert second["task_id"] != first["task_id"]


async def test_completed_matching_preparation_is_reused() -> None:
    service = TaskService(MemoryTaskRepository())
    first, _ = await service.get_or_create_document_task(
        collection_id="col_a",
        document_id="doc_a",
        task_type="document_preparation",
        input_fingerprint="fp_a",
    )
    await service.finish_task(first["task_id"], status="completed")

    second, second_created = await service.get_or_create_document_task(
        collection_id="col_a",
        document_id="doc_a",
        task_type="document_preparation",
        input_fingerprint="fp_a",
    )

    assert second_created is False
    assert second["task_id"] == first["task_id"]


async def test_changed_input_creates_a_new_preparation_task() -> None:
    service = TaskService(MemoryTaskRepository())
    first, _ = await service.get_or_create_document_task(
        collection_id="col_a",
        document_id="doc_a",
        task_type="document_preparation",
        input_fingerprint="fp_a",
    )
    await service.finish_task(first["task_id"], status="completed")

    second, second_created = await service.get_or_create_document_task(
        collection_id="col_a",
        document_id="doc_a",
        task_type="document_preparation",
        input_fingerprint="fp_b",
    )

    assert second_created is True
    assert second["task_id"] != first["task_id"]


async def test_running_document_is_reused_even_when_requested_version_changes() -> None:
    service = TaskService(MemoryTaskRepository())
    first, _ = await service.get_or_create_document_task(
        collection_id="col_a",
        document_id="doc_a",
        task_type="document_preparation",
        input_fingerprint="fp_a",
    )

    second, second_created = await service.get_or_create_document_task(
        collection_id="col_a",
        document_id="doc_a",
        task_type="document_preparation",
        input_fingerprint="fp_b",
    )

    assert second_created is False
    assert second["task_id"] == first["task_id"]
