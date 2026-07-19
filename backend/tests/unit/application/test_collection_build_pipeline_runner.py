from __future__ import annotations

import asyncio
from hashlib import sha256
from types import SimpleNamespace

import pandas as pd

from application.pipeline.collection_build.context import CollectionBuildContext
from application.pipeline.collection_build.nodes import source_artifacts
from application.pipeline.collection_build.definitions import (
    COLLECTION_BUILD_NODE_DEFINITIONS,
    CollectionBuildNodeDefinition,
    DOCUMENT_PROFILES,
    FINALIZE,
    OBJECTIVE_CANDIDATES,
)
from application.pipeline.collection_build.runner import CollectionBuildPipelineRunner
from infra.source.runtime.artifact_bundle import SourceArtifactBundle


class MemoryTaskService:
    def __init__(self) -> None:
        self.record = {
            "task_id": "task_1",
            "collection_id": "col_1",
            "status": "queued",
            "current_stage": "queued",
            "progress_percent": 0,
            "errors": [],
            "warnings": [],
        }

    def update_task(self, task_id: str, **fields):  # noqa: ANN001
        assert task_id == self.record["task_id"]
        self.record.update(fields)
        return dict(self.record)


def build_context(task_service: MemoryTaskService) -> CollectionBuildContext:
    return CollectionBuildContext(
        task_id="task_1",
        build_id="build_1",
        collection_id="col_1",
        task_service=task_service,
        collection_service=SimpleNamespace(),
        artifact_registry_service=SimpleNamespace(),
        source_artifact_repository=SimpleNamespace(),
    )


def test_collection_build_pipeline_runner_runs_ready_nodes_in_definition_order():
    task_service = MemoryTaskService()
    calls: list[str] = []
    definitions = (
        CollectionBuildNodeDefinition("first", (), 10, "First done.", "first", "first"),
        CollectionBuildNodeDefinition(
            "second",
            ("first",),
            20,
            "Second done.",
            "second",
            "second",
        ),
    )

    async def first(context):  # noqa: ANN001
        calls.append("first")
        context.state["first_seen"] = True

    def second(context):  # noqa: ANN001
        assert context.state["first_seen"] is True
        calls.append("second")

    result = asyncio.run(
        CollectionBuildPipelineRunner(
            {"first": first, "second": second},
            definitions=definitions,
        ).run(build_context(task_service))
    )

    assert calls == ["first", "second"]
    assert result["errors"] == []
    assert result["pipeline_nodes"]["first"]["status"] == "succeeded"
    assert result["pipeline_nodes"]["second"]["status"] == "succeeded"
    assert task_service.record["pipeline_nodes"]["second"]["status"] == "succeeded"


def test_source_node_persists_figure_metadata_and_references_before_activation():
    content = b"figure-bytes"
    digest = sha256(content).hexdigest()
    bundle = SourceArtifactBundle(
        documents=pd.DataFrame(
            [
                {
                    "id": "doc-1",
                    "title": "Paper",
                    "text": "Prior work [1].\nReferences\n[1] Smith A. Paper. 2024.",
                }
            ]
        ),
        text_units=pd.DataFrame(),
        blocks=pd.DataFrame(
            [
                {
                    "block_id": "body",
                    "document_id": "doc-1",
                    "block_type": "paragraph",
                    "block_order": 1,
                    "text": "Prior work [1].",
                },
                {
                    "block_id": "references-heading",
                    "document_id": "doc-1",
                    "block_type": "heading",
                    "block_order": 2,
                    "text": "References",
                },
                {
                    "block_id": "reference-1",
                    "document_id": "doc-1",
                    "block_type": "paragraph",
                    "block_order": 3,
                    "text": "[1] Smith A. Paper. 2024.",
                },
            ]
        ),
        figures=pd.DataFrame(
            [
                {
                    "figure_id": "figure-1",
                    "document_id": "doc-1",
                    "figure_order": 1,
                    "image_path": "image_assets/figure-1.png",
                    "image_mime_type": "image/png",
                    "asset_sha256": digest,
                }
            ]
        ),
        tables=pd.DataFrame(),
        table_rows=pd.DataFrame(),
        table_cells=pd.DataFrame(),
        figure_assets={"image_assets/figure-1.png": content},
    )
    calls = []

    async def build_source_artifacts(**kwargs):  # noqa: ANN003, ARG001
        return [SimpleNamespace(result=bundle, errors=[])]

    def replace_artifacts(collection_id, build_id, artifacts):  # noqa: ANN001
        calls.append(("artifacts", collection_id, build_id, artifacts))

    def replace_references(collection_id, build_id, references):  # noqa: ANN001
        calls.append(("references", collection_id, build_id, references))

    context = CollectionBuildContext(
        task_id="task-1",
        build_id="build-1",
        collection_id="col-1",
        task_service=SimpleNamespace(),
        collection_service=SimpleNamespace(
            write_figure_asset=lambda *args: (
                f"col-1/objects/source/build-1/figures/{digest}.png"
            )
        ),
        artifact_registry_service=SimpleNamespace(),
        source_artifact_repository=SimpleNamespace(
            replace_collection_artifacts=replace_artifacts,
            replace_collection_references=replace_references,
        ),
        services={"build_source_artifacts": build_source_artifacts},
    )

    result = asyncio.run(source_artifacts.run(context))

    assert [call[0] for call in calls] == ["artifacts", "references"]
    assert calls[0][3].figures[0].image_path.endswith(f"{digest}.png")
    assert calls[0][3].figures[0].image_size_bytes == len(content)
    assert len(calls[1][3].entries) == 1
    assert len(calls[1][3].mentions) == 1
    assert result["figure_count"] == 1


def test_collection_build_pipeline_runner_skips_downstream_nodes_after_failure():
    task_service = MemoryTaskService()
    definitions = (
        CollectionBuildNodeDefinition(
            "source_artifacts",
            (),
            60,
            "Source done.",
            "source_artifacts_started",
            "source_artifacts_completed",
        ),
        CollectionBuildNodeDefinition(
            "document_profiles",
            ("source_artifacts",),
            70,
            "Profiles done.",
            "document_profiles_started",
            "document_profiles_started",
        ),
        CollectionBuildNodeDefinition(
            "paper_facts",
            ("document_profiles",),
            80,
            "Facts done.",
            "paper_facts_started",
            "paper_facts_started",
        ),
    )

    def source_artifacts(context):  # noqa: ANN001
        return {"warnings": ["source warning"]}

    def document_profiles(context):  # noqa: ANN001, ARG001
        raise RuntimeError("Error code: 502")

    def paper_facts(context):  # noqa: ANN001, ARG001
        raise AssertionError("paper_facts should be skipped")

    result = asyncio.run(
        CollectionBuildPipelineRunner(
            {
                "source_artifacts": source_artifacts,
                "document_profiles": document_profiles,
                "paper_facts": paper_facts,
            },
            definitions=definitions,
        ).run(build_context(task_service))
    )

    assert result["pipeline_nodes"]["source_artifacts"]["status"] == "succeeded"
    assert result["pipeline_nodes"]["document_profiles"]["status"] == "failed"
    assert result["pipeline_nodes"]["paper_facts"]["status"] == "skipped"
    assert result["pipeline_nodes"]["paper_facts"]["skip_reason"] == (
        "dependency_failed: document_profiles"
    )
    assert result["errors"] == ["document_profiles: Error code: 502"]
    assert result["warnings"] == ["source_artifacts: source warning"]
    assert task_service.record["current_stage"] == "failed"


def test_collection_build_pipeline_runner_waits_for_terminal_nodes_without_dependency_skip():
    task_service = MemoryTaskService()
    calls: list[str] = []
    definitions = (
        CollectionBuildNodeDefinition(
            "source_artifacts",
            (),
            60,
            "Source done.",
            "source",
            "source",
        ),
        CollectionBuildNodeDefinition(
            "document_profiles",
            ("source_artifacts",),
            70,
            "Profiles done.",
            "profiles",
            "profiles",
        ),
        CollectionBuildNodeDefinition(
            "paper_facts",
            ("document_profiles",),
            80,
            "Facts done.",
            "facts",
            "facts",
        ),
        CollectionBuildNodeDefinition(
            "artifact_registry",
            ("source_artifacts",),
            98,
            "Artifacts done.",
            "artifacts",
            "artifacts",
        ),
        CollectionBuildNodeDefinition(
            "finalize",
            ("artifact_registry",),
            100,
            "Finalized.",
            "finalize",
            "finalize",
            wait_for=("document_profiles", "paper_facts"),
        ),
    )

    def source_artifacts(context):  # noqa: ANN001, ARG001
        calls.append("source_artifacts")

    def document_profiles(context):  # noqa: ANN001, ARG001
        calls.append("document_profiles")
        raise RuntimeError("profile failed")

    def paper_facts(context):  # noqa: ANN001, ARG001
        raise AssertionError("paper_facts should be skipped")

    def artifact_registry(context):  # noqa: ANN001, ARG001
        calls.append("artifact_registry")

    def finalize(context):  # noqa: ANN001, ARG001
        calls.append("finalize")

    result = asyncio.run(
        CollectionBuildPipelineRunner(
            {
                "source_artifacts": source_artifacts,
                "document_profiles": document_profiles,
                "paper_facts": paper_facts,
                "artifact_registry": artifact_registry,
                "finalize": finalize,
            },
            definitions=definitions,
        ).run(build_context(task_service))
    )

    assert calls == [
        "source_artifacts",
        "document_profiles",
        "artifact_registry",
        "finalize",
    ]
    assert result["pipeline_nodes"]["paper_facts"]["status"] == "skipped"
    assert result["pipeline_nodes"]["artifact_registry"]["status"] == "succeeded"
    assert result["pipeline_nodes"]["finalize"]["status"] == "succeeded"


def test_collection_build_pipeline_runner_rejects_wait_for_before_terminal():
    task_service = MemoryTaskService()
    definitions = (
        CollectionBuildNodeDefinition(
            "finalize",
            (),
            100,
            "Finalized.",
            "finalize",
            "finalize",
            wait_for=("document_profiles",),
        ),
        CollectionBuildNodeDefinition(
            "document_profiles",
            (),
            70,
            "Profiles done.",
            "profiles",
            "profiles",
        ),
    )

    try:
        asyncio.run(
            CollectionBuildPipelineRunner(
                {
                    "finalize": lambda context: None,  # noqa: ARG005
                    "document_profiles": lambda context: None,  # noqa: ARG005
                },
                definitions=definitions,
            ).run(build_context(task_service))
        )
    except RuntimeError as exc:
        assert str(exc) == "node finalize wait_for is not terminal: document_profiles"
    else:
        raise AssertionError("runner should reject non-terminal wait_for nodes")


def test_default_collection_build_pipeline_stops_after_objective_candidates():
    node_ids = tuple(
        definition.node_id for definition in COLLECTION_BUILD_NODE_DEFINITIONS
    )
    finalize = next(
        definition
        for definition in COLLECTION_BUILD_NODE_DEFINITIONS
        if definition.node_id == FINALIZE
    )

    assert OBJECTIVE_CANDIDATES in node_ids
    assert "research_objectives" not in node_ids
    assert "paper_facts" not in node_ids
    assert "comparison_rows" not in node_ids
    assert "research_understandings" not in node_ids
    assert finalize.wait_for == (DOCUMENT_PROFILES, OBJECTIVE_CANDIDATES)
