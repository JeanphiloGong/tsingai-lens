from __future__ import annotations

from dataclasses import replace

import pytest

from domain.pipeline import (
    ExecutionStats,
    ExecutionTimestamps,
    ModelUsage,
    PipelineNodeRun,
    PipelineNodeStatus,
    PipelineRun,
    PipelineRunStatus,
    TokenUsage,
)


def test_pipeline_run_tracks_execution_separately_from_output_build() -> None:
    run = PipelineRun.create(
        pipeline_name="collection_build",
        mode="standard",
        run_id="task_1",
        scope_type="collection",
        scope_id="col_1",
        node_dependencies={
            "source_artifacts": (),
            "document_profiles": ("source_artifacts",),
        },
        created_at="2026-08-11T01:00:00+00:00",
        output_build_id="build_1",
    ).start("2026-08-11T01:00:01+00:00")

    source = run.node("source_artifacts").start(
        "2026-08-11T01:00:02+00:00"
    ).succeed(
        "2026-08-11T01:00:04+00:00",
        output_summary={"document_count": 3},
        stats=ExecutionStats(
            duration_ms=2000,
            model_usage=(
                ModelUsage(
                    model_name="model-a",
                    request_count=2,
                    token_usage=TokenUsage(
                        input_tokens=100,
                        output_tokens=20,
                        total_tokens=120,
                    ),
                ),
            ),
        ),
    )
    run = run.with_node(source)
    profiles = run.node("document_profiles").start(
        "2026-08-11T01:00:05+00:00"
    ).fail("profile extraction failed", "2026-08-11T01:00:06+00:00")
    run = run.with_node(profiles).finish(
        PipelineRunStatus.PARTIAL_SUCCESS,
        "2026-08-11T01:00:07+00:00",
    )

    assert run.run_id == "task_1"
    assert run.output_build_id == "build_1"
    assert run.errors == (
        "document_profiles: profile extraction failed",
    )
    assert run.stats.duration_ms == 6000
    assert run.stats.token_usage == TokenUsage(100, 20, 120)
    assert run.stats.model_usage[0].model_name == "model-a"


def test_pipeline_node_records_the_runtime_dependency_graph() -> None:
    node = PipelineNodeRun(name="objective_candidates").skip(
        finished_at="2026-08-11T01:00:07+00:00",
    )

    assert node.status is PipelineNodeStatus.SKIPPED
    assert node.dependencies == ()
    assert node.to_record()["dependencies"] == []
    assert node.to_record()["output_summary"] == {}


def test_execution_stats_aggregate_usage_by_model() -> None:
    stats = ExecutionStats.aggregate(
        (
            ExecutionStats(
                model_usage=(
                    ModelUsage("model-a", 1, TokenUsage(100, 20, 120)),
                )
            ),
            ExecutionStats(
                model_usage=(
                    ModelUsage("model-a", 2, TokenUsage(200, 40, 240)),
                    ModelUsage("model-b", 1, TokenUsage(50, 10, 60)),
                )
            ),
        )
    )

    assert stats.model_usage == (
        ModelUsage("model-a", 3, TokenUsage(300, 60, 360)),
        ModelUsage("model-b", 1, TokenUsage(50, 10, 60)),
    )
    assert stats.token_usage == TokenUsage(350, 70, 420)


def test_pipeline_run_round_trips_as_one_typed_aggregate() -> None:
    payload = {
        "pipeline_name": "collection_build",
        "mode": "standard",
        "run_id": "task_1",
        "scope_type": "collection",
        "scope_id": "col_1",
        "status": "running",
        "nodes": {
            "source_artifacts": {
                "name": "source_artifacts",
                "dependencies": [],
                "status": "succeeded",
                "errors": [],
                "warnings": ["one warning"],
                "stats": {
                    "duration_ms": 1000,
                    "token_usage": None,
                    "model_usage": [],
                },
                "timestamps": {
                    "started_at": "2026-08-11T01:00:01+00:00",
                    "finished_at": "2026-08-11T01:00:02+00:00",
                },
                "output_summary": {"document_count": 2},
            }
        },
        "errors": [],
        "warnings": ["source_artifacts: one warning"],
        "stats": {
            "duration_ms": 1000,
            "token_usage": None,
            "model_usage": [],
        },
        "timestamps": {
            "created_at": "2026-08-11T01:00:00+00:00",
            "started_at": "2026-08-11T01:00:01+00:00",
            "finished_at": None,
        },
        "output_build_id": "build_1",
    }

    assert PipelineRun.from_mapping(payload).to_record() == payload


def test_pipeline_statuses_reject_unknown_values() -> None:
    with pytest.raises(ValueError, match="pipeline run status"):
        PipelineRun.from_mapping(
            {
                "pipeline_name": "collection_build",
                "mode": "standard",
                "run_id": "task_1",
                "scope_type": "collection",
                "scope_id": "col_1",
                "status": "done",
                "nodes": {},
                "timestamps": {},
            }
        )

    with pytest.raises(ValueError, match="pipeline node status"):
        replace(PipelineNodeRun(name="source_artifacts"), status="done").to_record()


def test_execution_timestamps_reject_finish_before_start() -> None:
    with pytest.raises(ValueError, match="finished_at"):
        ExecutionTimestamps(
            started_at="2026-08-11T01:00:02+00:00",
            finished_at="2026-08-11T01:00:01+00:00",
        )


def test_pipeline_run_rejects_invalid_dependency_graphs() -> None:
    run = PipelineRun.create(
        pipeline_name="collection_build",
        mode="standard",
        run_id="task_1",
        scope_type="collection",
        scope_id="col_1",
        node_dependencies={"source_artifacts": ()},
        created_at="2026-08-11T01:00:00+00:00",
        output_build_id="build_1",
    )

    with pytest.raises(ValueError, match="dependencies are not part"):
        run.with_node(
            PipelineNodeRun(
                name="source_artifacts",
                status="skipped",
                dependencies=("missing_node",),
            )
        )

    with pytest.raises(ValueError, match="contain a cycle"):
        PipelineRun.create(
            pipeline_name="collection_build",
            mode="standard",
            run_id="task_2",
            scope_type="collection",
            scope_id="col_1",
            node_dependencies={"first": ("second",), "second": ("first",)},
            created_at="2026-08-11T01:00:00+00:00",
        )
