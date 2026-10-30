from __future__ import annotations

from dataclasses import replace

import pytest
from application.pipeline import pipeline_run_service
from application.pipeline import pipeline_run_service as module
from controllers.schemas.source.pipeline_run import pipeline_run_response
from repositories.pipeline_run_repository import (
    ExecutionStats,
    ExecutionTimestamps,
    ModelUsage,
    PipelineNodeStatus,
    PipelineRunStatus,
    TokenUsage,
)


class _Runs:
    async def read_run(self, run_id):
        return self.run

    async def update_run(self, run):
        self.run = run
        return True


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_preparation_keeps_sources_when_classification_fails(monkeypatch):
    times = iter(f"2026-08-11T01:00:0{n}+00:00" for n in range(6))
    monkeypatch.setattr(module, "_now_iso", lambda: next(times))
    runs = _Runs()
    pipeline_run_service.PipelineRunRepo = runs
    service = pipeline_run_service
    runs.run = service._new_run(
        collection_id="col_1",
        pipeline_name="document_preparation",
        scope_type="document",
        scope_id="doc_1",
        mode="standard",
        input_fingerprint="fingerprint",
        context={"requested_by": "upload"},
    )
    assert [(node.name, node.dependencies) for node in runs.run.nodes] == [
        ("source_parsing", ()),
        ("document_profile", ("source_parsing",)),
    ]
    run_id = runs.run.run_id
    await service.update_run(run_id, status="running", current_node="source_parsing")
    running = await service.update_run(run_id, current_node="source_parsing")
    assert running.nodes[0].status == "running"
    profiling = await service.update_run(
        run_id,
        current_node="document_profile",
        progress_percent=50,
        progress_detail={"unit": "document", "message": "Profiling."},
    )
    assert profiling.nodes[0].status == "succeeded"
    assert profiling.nodes[1].status == "running"
    assert profiling.progress_percent == 50
    result = await service.finish_run(
        run_id,
        status="failed",
        current_node="document_profile",
        errors=["private provider text"],
    )
    assert result.nodes[0].status == "succeeded"
    assert result.nodes[1].status == "failed"
    assert result.errors == ("private provider text",)
    assert "private provider text" not in str(pipeline_run_response(result))
    assert runs.run.nodes[0].stats.duration_ms == 2000
    assert runs.run.nodes[1].stats.duration_ms == 1000
    assert runs.run.stats.duration_ms == 3000
    assert runs.run.input_fingerprint == "fingerprint"
    assert runs.run.context == {"requested_by": "upload"}
    assert await runs.read_run(run_id) == runs.run


@pytest.mark.anyio
async def test_progress_without_a_node_keeps_reported_errors():
    runs = _Runs()
    pipeline_run_service.PipelineRunRepo = runs
    service = pipeline_run_service
    runs.run = service._new_run(
        collection_id="col_1",
        pipeline_name="document_preparation",
        scope_type="document",
        scope_id="doc_1",
        mode="standard",
        input_fingerprint=None,
        context=None,
    )
    runs.run = replace(runs.run, errors=("dispatch failure",))
    result = await service.update_run(runs.run.run_id, progress_percent=10)
    assert runs.run.errors == ("dispatch failure",)
    assert result.progress_percent == 10


@pytest.mark.anyio
async def test_partial_success_skips_unstarted_nodes():
    runs = _Runs()
    pipeline_run_service.PipelineRunRepo = runs
    service = pipeline_run_service
    runs.run = service._new_run(
        collection_id="col_1",
        pipeline_name="objective_discovery",
        scope_type="collection",
        scope_id="col_1",
        mode="standard",
        input_fingerprint=None,
        context=None,
    )
    assert [(node.name, node.dependencies) for node in runs.run.nodes] == [
        ("paper_map", ()),
        ("objective_candidates", ("paper_map",)),
    ]
    await service.update_run(
        runs.run.run_id, status="running", current_node="paper_map"
    )
    result = await service.finish_run(runs.run.run_id, status="partial_success")
    assert result.nodes[0].status == "succeeded"
    assert result.nodes[1].status == "skipped"
    assert result.nodes[1].timestamps.started_at is None


@pytest.mark.anyio
async def test_invalid_progress_is_rejected_before_loading():
    pipeline_run_service.PipelineRunRepo = _Runs()
    service = pipeline_run_service
    with pytest.raises(ValueError, match="progress_percent"):
        await service.update_run("run-1", progress_percent=101)


def test_execution_stats_aggregate_usage_by_model() -> None:
    stats = ExecutionStats.aggregate(
        (
            ExecutionStats(
                prompt_versions={"document_profile": "document_profile.v1"},
                model_usage=(ModelUsage("model-a", 1, TokenUsage(100, 20, 120)),),
            ),
            ExecutionStats(
                prompt_versions={"paper_facts": "paper_facts.v1"},
                model_usage=(
                    ModelUsage("model-a", 2, TokenUsage(200, 40, 240)),
                    ModelUsage("model-b", 1, TokenUsage(50, 10, 60)),
                ),
            ),
        )
    )

    assert stats.model_usage == (
        ModelUsage("model-a", 3, TokenUsage(300, 60, 360)),
        ModelUsage("model-b", 1, TokenUsage(50, 10, 60)),
    )
    assert stats.token_usage == TokenUsage(350, 70, 420)
    assert stats.prompt_versions == {
        "document_profile": "document_profile.v1",
        "paper_facts": "paper_facts.v1",
    }


def test_pipeline_statuses_reject_unknown_values() -> None:
    with pytest.raises(ValueError, match="PipelineRunStatus"):
        PipelineRunStatus("done")
    with pytest.raises(ValueError, match="PipelineNodeStatus"):
        PipelineNodeStatus("done")


def test_execution_timestamps_reject_finish_before_start() -> None:
    with pytest.raises(ValueError, match="finished_at"):
        ExecutionTimestamps(
            started_at="2026-08-11T01:00:02+00:00",
            finished_at="2026-08-11T01:00:01+00:00",
        )
