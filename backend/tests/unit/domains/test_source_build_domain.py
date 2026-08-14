from __future__ import annotations

from domain.pipeline import ExecutionTimestamps, PipelineNodeRun
from domain.source.build import (
    ArtifactVersionRecord,
    BuildStageRecord,
    CollectionBuildRecord,
    TaskRecord,
)


def test_task_record_preserves_public_fields_and_optional_diagnostics() -> None:
    payload = {
        "task_id": "task_demo",
        "collection_id": "col_demo",
        "task_type": "build",
        "status": "running",
        "current_stage": "source_artifacts_started",
        "progress_percent": 25,
        "progress_detail": {"phase": "source_artifacts_started"},
        "output_path": None,
        "errors": ["first"],
        "warnings": ["warning"],
        "created_at": "2026-07-19T10:00:00+00:00",
        "updated_at": "2026-07-19T10:01:00+00:00",
        "started_at": "2026-07-19T10:00:30+00:00",
        "finished_at": None,
        "progress": 0.25,
    }

    record = TaskRecord.from_mapping(payload)

    assert record.errors == ("first",)
    assert record.warnings == ("warning",)
    assert record.details == {"progress": 0.25}
    assert record.to_record() == payload


def test_build_stage_record_projects_pipeline_node_state() -> None:
    record = BuildStageRecord(
        stage_id="stage_demo",
        build_id="build_demo",
        stage_order=2,
        node=PipelineNodeRun(
            name="source_artifacts",
            status="failed",
            timestamps=ExecutionTimestamps(
                started_at="2026-07-19T10:01:00+00:00",
                finished_at="2026-07-19T10:02:00+00:00",
            ),
            errors=("parser failed",),
            warnings=("partial output",),
        ),
    )

    assert record.to_pipeline_state() == {
        "name": "source_artifacts",
        "dependencies": [],
        "status": "failed",
        "errors": ["parser failed"],
        "warnings": ["partial output"],
        "stats": {
            "duration_ms": None,
            "token_usage": None,
            "model_usage": [],
            "unreported_request_count": 0,
            "prompt_versions": {},
        },
        "timestamps": {
            "started_at": "2026-07-19T10:01:00+00:00",
            "finished_at": "2026-07-19T10:02:00+00:00",
        },
        "output_summary": {},
    }


def test_build_and_artifact_records_keep_lineage_fields_typed() -> None:
    build = CollectionBuildRecord(
        build_id="build_demo",
        task_id="task_demo",
        collection_id="col_demo",
        mode="standard",
        build_number=3,
        status="building",
        created_at="2026-07-19T10:00:00+00:00",
        started_at="2026-07-19T10:00:30+00:00",
        finished_at=None,
    )
    artifact = ArtifactVersionRecord(
        artifact_version_id="artifact_demo",
        build_stage_id="stage_demo",
        artifact_kind="documents",
        schema_version=1,
        content_version=1,
        status="ready",
        object_id=None,
        details={"document_count": 2},
        created_at="2026-07-19T10:02:00+00:00",
    )

    assert build.build_number == 3
    assert artifact.details == {"document_count": 2}
