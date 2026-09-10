from __future__ import annotations

import pytest

from application.pipeline import PipelineRunService
from application.pipeline.pipeline_run_service import document_preparation_error_message
from infra.persistence.memory import MemoryPipelineRunRepository


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_pipeline_run_service_lists_scope_status_and_progress() -> None:
    service = PipelineRunService(MemoryPipelineRunRepository())
    run_a = await service.create_run(
        "col_a",
        "document_preparation",
        scope_type="document",
        scope_id="doc_a",
        input_fingerprint="fingerprint-a",
    )
    run_b = await service.create_run(
        "col_a",
        "document_preparation",
        scope_type="document",
        scope_id="doc_b",
        input_fingerprint="fingerprint-b",
    )
    await service.finish_run(run_a["run_id"], status="completed")
    await service.finish_run(
        run_b["run_id"],
        status="failed",
        current_node="source_parsing",
        progress_percent=35,
        errors=["invalid PDF"],
    )

    runs = await service.list_runs(collection_id="col_a")
    assert [item["run_id"] for item in runs] == [
        run_b["run_id"],
        run_a["run_id"],
    ]
    assert [item["scope_id"] for item in runs] == ["doc_b", "doc_a"]
    completed = await service.list_runs(
        collection_id="col_a", status="completed"
    )
    assert [item["run_id"] for item in completed] == [run_a["run_id"]]


async def test_pipeline_run_service_persists_node_and_terminal_failure() -> None:
    service = PipelineRunService(MemoryPipelineRunRepository())
    run, _created = await service.get_or_create_document_run(
        collection_id="col_a",
        document_id="doc_a",
        pipeline_name="document_preparation",
        input_fingerprint="fingerprint-a",
    )

    running = await service.update_run(
        run["run_id"],
        status="running",
        current_node="source_parsing",
        progress_percent=25,
        progress_detail={"phase": "source_parsing", "unit": "document"},
    )
    assert running["nodes"]["source_parsing"]["status"] == "running"

    failed = await service.finish_run(
        run["run_id"],
        status="failed",
        current_node="source_parsing",
        errors=["invalid PDF"],
    )
    assert failed["status"] == "failed"
    assert failed["errors"] == [document_preparation_error_message("source_parsing")]
    assert failed["nodes"]["source_parsing"]["status"] == "failed"
    assert failed["finished_at"] is not None
    assert failed["updated_at"] == failed["finished_at"]


async def test_document_run_reuses_active_and_matching_completed_work() -> None:
    service = PipelineRunService(MemoryPipelineRunRepository())
    first, created = await service.get_or_create_document_run(
        collection_id="col_a",
        document_id="doc_a",
        pipeline_name="document_preparation",
        input_fingerprint="fingerprint-a",
    )
    active, active_created = await service.get_or_create_document_run(
        collection_id="col_a",
        document_id="doc_a",
        pipeline_name="document_preparation",
        input_fingerprint="fingerprint-b",
    )
    assert created is True
    assert active_created is False
    assert active["run_id"] == first["run_id"]

    await service.finish_run(first["run_id"], status="completed")
    completed, completed_created = await service.get_or_create_document_run(
        collection_id="col_a",
        document_id="doc_a",
        pipeline_name="document_preparation",
        input_fingerprint="fingerprint-a",
    )
    changed, changed_created = await service.get_or_create_document_run(
        collection_id="col_a",
        document_id="doc_a",
        pipeline_name="document_preparation",
        input_fingerprint="fingerprint-b",
    )
    assert completed_created is False
    assert completed["run_id"] == first["run_id"]
    assert changed_created is True
    assert changed["run_id"] != first["run_id"]


async def test_collection_run_reuses_only_active_work_and_preserves_context() -> None:
    service = PipelineRunService(MemoryPipelineRunRepository())
    first, created = await service.get_or_create_collection_run(
        collection_id="col_a",
        pipeline_name="objective_discovery",
        input_fingerprint="scope-a",
        context={"document_ids": ["doc_a"]},
    )
    active, active_created = await service.get_or_create_collection_run(
        collection_id="col_a",
        pipeline_name="objective_discovery",
        input_fingerprint="scope-b",
        context={"document_ids": ["doc_b"]},
    )
    assert created is True
    assert active_created is False
    assert active["run_id"] == first["run_id"]
    assert active["context"] == {"document_ids": ["doc_a"]}

    await service.finish_run(first["run_id"], status="failed")
    retry, retry_created = await service.get_or_create_collection_run(
        collection_id="col_a",
        pipeline_name="objective_discovery",
        input_fingerprint="scope-b",
        context={"document_ids": ["doc_b"]},
    )
    assert retry_created is True
    assert retry["run_id"] != first["run_id"]


async def test_historical_preparation_errors_are_safe_without_rewriting_storage():
    repository = MemoryPipelineRunRepository()
    service = PipelineRunService(repository)
    run = await service.create_run(
        "col_a",
        "document_preparation",
        scope_type="document",
        scope_id="doc_a",
    )
    raw_error = "provider failed at /private/provider/config"
    await service.finish_run(
        run["run_id"],
        status="failed",
        current_node="document_profile",
        errors=[raw_error],
    )
    detail = await service.get_run(run["run_id"])
    listing = await service.list_runs(collection_id="col_a")
    assert raw_error not in str(detail)
    assert raw_error not in str(listing)
    assert "classification" in detail["errors"][0].lower()
    assert detail["nodes"]["document_profile"]["errors"] == detail["errors"]
    stored = await repository.read_run(run["run_id"])
    assert raw_error in stored.errors
