from __future__ import annotations

from dataclasses import replace

import pytest

from domain.pipeline import PipelineRun, PipelineRunStatus
from infra.persistence.postgres.pipeline_run_repository import (
    PostgresPipelineRunRepository,
)
from tests.integration.persistence.test_postgres_source_artifacts import COLLECTION_ID


pytest_plugins = ("tests.integration.persistence.test_postgres_source_artifacts",)
pytestmark = pytest.mark.anyio

NOW = "2026-08-27T10:00:00+00:00"


def _run(
    run_id: str,
    fingerprint: str,
    *,
    scope_type: str = "document",
    scope_id: str = "doc_a",
) -> PipelineRun:
    return PipelineRun.create(
        pipeline_name=(
            "document_preparation"
            if scope_type == "document"
            else "objective_discovery"
        ),
        mode="standard",
        run_id=run_id,
        collection_id=COLLECTION_ID,
        scope_type=scope_type,
        scope_id=scope_id,
        input_fingerprint=fingerprint,
        context={"document_ids": ["doc_a", "doc_b"]},
        node_dependencies={
            "source_parsing": (),
            "document_profile": ("source_parsing",),
        },
        created_at=NOW,
    )


async def test_document_run_reuses_active_and_matching_completed_work(
    source_repository,
) -> None:
    runs = PostgresPipelineRunRepository(source_repository.session_factory)
    first = _run("run-first", "fingerprint-a")
    assert await runs.get_or_create_document_run(first) == (first, True)

    reused_active, created = await runs.get_or_create_document_run(
        _run("run-active-request", "fingerprint-b")
    )
    assert (reused_active, created) == (first, False)

    completed = first.start(NOW).finish(
        PipelineRunStatus.COMPLETED,
        "2026-08-27T10:01:00+00:00",
    )
    assert await runs.update_run(completed) is True

    reused_completed, created = await runs.get_or_create_document_run(
        _run("run-matching-request", "fingerprint-a")
    )
    assert (reused_completed, created) == (completed, False)

    changed, created = await runs.get_or_create_document_run(
        _run("run-changed-request", "fingerprint-b")
    )
    assert (changed.run_id, created) == ("run-changed-request", True)


async def test_collection_run_reuses_only_active_work(source_repository) -> None:
    runs = PostgresPipelineRunRepository(source_repository.session_factory)
    first = _run(
        "run-discovery-first",
        "scope-a",
        scope_type="collection",
        scope_id=COLLECTION_ID,
    )
    assert await runs.get_or_create_collection_run(first) == (first, True)

    reused_active, created = await runs.get_or_create_collection_run(
        _run(
            "run-discovery-duplicate",
            "scope-b",
            scope_type="collection",
            scope_id=COLLECTION_ID,
        )
    )
    assert (reused_active, created) == (first, False)

    assert await runs.update_run(
        first.start(NOW).finish(
            PipelineRunStatus.COMPLETED,
            "2026-08-27T10:01:00+00:00",
        )
    )
    retry = _run(
        "run-discovery-retry",
        "scope-b",
        scope_type="collection",
        scope_id=COLLECTION_ID,
    )
    assert await runs.get_or_create_collection_run(retry) == (retry, True)


async def test_pipeline_run_round_trips_progress_nodes_and_context(
    source_repository,
) -> None:
    runs = PostgresPipelineRunRepository(source_repository.session_factory)
    queued = _run("run-round-trip", "fingerprint-a")
    await runs.add_run(queued)
    source_node = queued.node("source_parsing").start(NOW).succeed(
        "2026-08-27T10:00:10+00:00",
        output_summary={"block_count": 12},
    )
    running = replace(
        queued.start(NOW).with_node(source_node).with_progress(
            current_node="document_profile",
            progress_percent=45,
            progress_detail={"unit": "document", "message": "Profiling."},
        ),
        warnings=("low confidence title",),
    )

    assert await runs.update_run(running) is True
    assert await runs.read_run(running.run_id) == running
    summary, = await runs.list_runs(collection_id=COLLECTION_ID)
    assert summary.run_id == running.run_id
    assert summary.progress_percent == 45
    assert summary.warnings == ["low confidence title"]
    assert not hasattr(summary, "nodes")


async def test_pipeline_history_does_not_reconstruct_full_diagnostics(
    source_repository, monkeypatch
) -> None:
    from infra.persistence.postgres import pipeline_run_repository as module

    runs = PostgresPipelineRunRepository(source_repository.session_factory)
    await runs.add_run(_run("history-only", "fingerprint-history"))

    def reject_full_hydration(_row):
        pytest.fail("history must not reconstruct full pipeline diagnostics")

    monkeypatch.setattr(module, "_to_run", reject_full_hydration)
    summary, = await runs.list_runs(collection_id=COLLECTION_ID)

    assert summary.run_id == "history-only"
    assert summary.collection_id == COLLECTION_ID
    assert summary.status == "queued"
