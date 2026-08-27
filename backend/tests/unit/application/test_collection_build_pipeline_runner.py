from __future__ import annotations

import asyncio
from hashlib import sha256
from types import SimpleNamespace

import pandas as pd
import pytest

from application.pipeline.collection_build.config import CollectionBuildPipelineConfig
from application.pipeline.collection_build.context import CollectionBuildContext
from application.pipeline.collection_build import nodes
from application.pipeline.collection_build.definitions import (
    COLLECTION_BUILD_NODE_DEFINITIONS,
    CollectionBuildNodeDefinition,
    DOCUMENT_PROFILES,
    OBJECTIVE_CANDIDATES,
    SOURCE_ARTIFACTS,
    dependency_graph_for_mode,
)
from application.pipeline.collection_build.runner import CollectionBuildPipelineRunner
from application.pipeline.collection_build.service import CollectionBuildPipelineService
from controllers.schemas.source.task import TaskResponse
from domain.pipeline import ModelUsage, PipelineRun, TokenUsage
from infra.llm.usage import record_llm_completion, record_llm_prompt_version
from infra.source.config.source_runtime_config import SourceRuntimeConfig
from infra.source.runtime.artifact_bundle import SourceArtifactBundle

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


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
            "created_at": "2026-08-11T01:00:00+00:00",
        }
        self.pipeline_run = None

    async def get_task(self, task_id: str):
        assert task_id == self.record["task_id"]
        return dict(self.record)

    async def update_task(self, task_id: str, **fields):  # noqa: ANN001
        assert task_id == self.record["task_id"]
        pipeline_run = fields.pop("pipeline_run", None)
        if pipeline_run is not None:
            self.pipeline_run = pipeline_run
            fields["pipeline_nodes"] = pipeline_run.to_record()["nodes"]
        self.record.update(fields)
        return dict(self.record)


class RecordingTaskService(MemoryTaskService):
    def __init__(self) -> None:
        super().__init__()
        self.progress_updates = []

    async def update_task(self, task_id: str, **fields):  # noqa: ANN001
        record = await super().update_task(task_id, **fields)
        if "progress_detail" in fields:
            self.progress_updates.append(fields["progress_detail"])
        return record


def build_context(task_service: MemoryTaskService) -> CollectionBuildContext:
    async def build_source_artifacts(**kwargs):  # noqa: ANN003, ARG001
        return []

    return CollectionBuildContext(
        task_id="task_1",
        build_id="build_1",
        collection_id="col_1",
        task_service=task_service,
        collection_service=SimpleNamespace(),
        artifact_registry_service=SimpleNamespace(),
        source_artifact_repository=SimpleNamespace(),
        document_profile_service=SimpleNamespace(),
        research_objective_service=SimpleNamespace(),
        build_source_artifacts=build_source_artifacts,
    )


def build_config() -> CollectionBuildPipelineConfig:
    return CollectionBuildPipelineConfig(
        source=SourceRuntimeConfig(),
        mode="standard",
    )


def build_run(node_dependencies) -> PipelineRun:  # noqa: ANN001
    return PipelineRun.create(
        pipeline_name="collection_build",
        mode="standard",
        run_id="task_1",
        scope_type="collection",
        scope_id="col_1",
        node_dependencies=node_dependencies,
        created_at="2026-08-11T01:00:00+00:00",
        output_build_id="build_1",
    )


async def test_objective_progress_persists_each_window_for_the_active_document():
    task_service = RecordingTaskService()
    service = CollectionBuildPipelineService(
        collection_service=SimpleNamespace(),
        task_service=task_service,
        artifact_registry_service=SimpleNamespace(),
        source_artifact_repository=SimpleNamespace(),
        document_profile_service=SimpleNamespace(),
        research_objective_service=SimpleNamespace(),
    )
    callback = service._build_objective_progress_callback("task_1", "col_1")

    for window_position in (1, 2, 3):
        await asyncio.to_thread(
            callback,
            {
                "phase": "objective_paper_skim_started",
                "current": 2,
                "total": 10,
                "unit": "documents",
                "active_window_position": window_position,
                "active_window_count": 3,
            }
        )

    assert [
        detail["active_window_position"]
        for detail in task_service.progress_updates
    ] == [1, 2, 3]


async def test_objective_progress_projects_internal_phase_to_public_task_stage():
    task_service = RecordingTaskService()
    service = CollectionBuildPipelineService(
        collection_service=SimpleNamespace(),
        task_service=task_service,
        artifact_registry_service=SimpleNamespace(),
        source_artifact_repository=SimpleNamespace(),
        document_profile_service=SimpleNamespace(),
        research_objective_service=SimpleNamespace(),
    )

    await asyncio.to_thread(
        service._build_objective_progress_callback("task_1", "col_1"),
        {
            "phase": "objective_discovery_batch_finished",
            "current": 1,
            "total": 2,
            "unit": "groups",
        }
    )

    assert task_service.record["current_stage"] == "objective_discovery_started"
    assert (
        task_service.record["progress_detail"]["phase"]
        == "objective_discovery_batch_finished"
    )
    TaskResponse.model_validate(
        {
            **task_service.record,
            "task_type": "build",
            "output_path": None,
            "updated_at": "2026-08-11T01:00:01+00:00",
            "started_at": None,
            "finished_at": None,
        }
    )


async def test_collection_build_pipeline_runner_uses_run_dependencies_not_config_order():
    task_service = MemoryTaskService()
    calls: list[str] = []
    definitions = (
        CollectionBuildNodeDefinition(
            "second",
            20,
            "Second done.",
            "second",
            "second",
        ),
        CollectionBuildNodeDefinition("first", 10, "First done.", "first", "first"),
    )

    async def first(context, config):  # noqa: ANN001
        assert config.mode == "standard"
        calls.append("first")
        context.state["first_seen"] = True

    def second(context, config):  # noqa: ANN001
        assert config.mode == "standard"
        assert context.state["first_seen"] is True
        calls.append("second")

    result = await CollectionBuildPipelineRunner(
            {"first": first, "second": second},
            definitions=definitions,
        ).run(
            build_context(task_service),
            build_config(),
            build_run({"second": ("first",), "first": ()}),
        )

    assert calls == ["first", "second"]
    assert result.errors == ()
    assert result.node("first").status == "succeeded"
    assert result.node("second").status == "succeeded"
    assert task_service.record["pipeline_nodes"]["second"]["status"] == "succeeded"


async def test_collection_build_pipeline_runner_persists_provider_usage_per_node():
    task_service = MemoryTaskService()
    definitions = (
        CollectionBuildNodeDefinition(
            "model_node",
            20,
            "Model node done.",
            "model_node_started",
            "model_node_completed",
        ),
    )

    def model_node(context, config):  # noqa: ANN001, ARG001
        record_llm_prompt_version("paper_framing", "paper_framing.v1")
        record_llm_completion(
            SimpleNamespace(
                model="model-a",
                usage=SimpleNamespace(
                    prompt_tokens=120,
                    completion_tokens=30,
                    total_tokens=150,
                ),
            ),
            requested_model="configured-model",
        )

    result = await CollectionBuildPipelineRunner(
            {"model_node": model_node},
            definitions=definitions,
        ).run(
            build_context(task_service),
            build_config(),
            build_run({"model_node": ()}),
        )

    expected = (
        ModelUsage("model-a", 1, TokenUsage(120, 30, 150)),
    )
    assert result.node("model_node").stats.model_usage == expected
    assert result.stats.model_usage == expected
    assert result.node("model_node").stats.prompt_versions == {
        "paper_framing": "paper_framing.v1"
    }
    assert result.stats.prompt_versions == {"paper_framing": "paper_framing.v1"}


async def test_objective_candidate_node_reports_permanent_source_unit_failures():
    paper_skim = SimpleNamespace(
        source_unit_coverage=(
            SimpleNamespace(status="relationship_emitted"),
            SimpleNamespace(status="extraction_failed"),
        )
    )
    facts = SimpleNamespace(
        research_objectives=(object(),),
        paper_skims=(paper_skim,),
    )

    async def return_facts(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        return facts

    context = build_context(MemoryTaskService())
    context.research_objective_service = SimpleNamespace(
        discover_and_replace_objective_candidates=return_facts
    )

    result = await nodes.discover_and_replace_objective_candidates(
        context,
        build_config(),
    )

    assert result["objective_candidate_count"] == 1
    assert result["paper_skim_count"] == 1
    assert result["source_unit_count"] == 2
    assert result["extraction_failed_source_unit_count"] == 1
    assert result["warnings"] == [
        "1 PaperSkim Source unit failed extraction permanently; candidate "
        "objectives were built from the remaining coverage."
    ]


async def test_collection_build_final_status_is_partial_when_paper_skim_coverage_failed():
    pipeline_run = PipelineRun.create(
        pipeline_name="collection_build",
        mode="standard",
        run_id="task_1",
        scope_type="collection",
        scope_id="col_1",
        node_dependencies={
            SOURCE_ARTIFACTS: (),
            OBJECTIVE_CANDIDATES: (SOURCE_ARTIFACTS,),
        },
        created_at="2026-08-11T01:00:00+00:00",
        output_build_id="build_1",
    )
    pipeline_run = pipeline_run.with_node(
        pipeline_run.node(SOURCE_ARTIFACTS).succeed(
            "2026-08-11T01:00:01+00:00"
        )
    )
    pipeline_run = pipeline_run.with_node(
        pipeline_run.node(OBJECTIVE_CANDIDATES).succeed(
            "2026-08-11T01:00:02+00:00",
            output_summary={"extraction_failed_source_unit_count": 1},
        )
    )
    service = CollectionBuildPipelineService(
        collection_service=SimpleNamespace(),
        task_service=SimpleNamespace(),
        artifact_registry_service=SimpleNamespace(),
        source_artifact_repository=SimpleNamespace(),
        document_profile_service=SimpleNamespace(),
        research_objective_service=SimpleNamespace(),
    )

    assert service._resolve_final_status(SimpleNamespace(), pipeline_run) == (
        "partial_success"
    )


async def test_collection_build_final_status_is_partial_when_source_documents_failed():
    pipeline_run = PipelineRun.create(
        pipeline_name="collection_build",
        mode="standard",
        run_id="task_1",
        scope_type="collection",
        scope_id="col_1",
        node_dependencies={
            SOURCE_ARTIFACTS: (),
            OBJECTIVE_CANDIDATES: (SOURCE_ARTIFACTS,),
        },
        created_at="2026-08-11T01:00:00+00:00",
        output_build_id="build_1",
    )
    pipeline_run = pipeline_run.with_node(
        pipeline_run.node(SOURCE_ARTIFACTS).succeed(
            "2026-08-11T01:00:01+00:00",
            output_summary={"source_failed_document_count": 1},
        )
    )
    pipeline_run = pipeline_run.with_node(
        pipeline_run.node(OBJECTIVE_CANDIDATES).succeed(
            "2026-08-11T01:00:02+00:00",
        )
    )
    service = CollectionBuildPipelineService(
        collection_service=SimpleNamespace(),
        task_service=SimpleNamespace(),
        artifact_registry_service=SimpleNamespace(),
        source_artifact_repository=SimpleNamespace(),
        document_profile_service=SimpleNamespace(),
        research_objective_service=SimpleNamespace(),
    )

    assert service._resolve_final_status(SimpleNamespace(), pipeline_run) == (
        "partial_success"
    )


async def test_collection_build_pipeline_runner_keeps_usage_from_failed_node():
    task_service = MemoryTaskService()
    definitions = (
        CollectionBuildNodeDefinition(
            "model_node",
            20,
            "Model node done.",
            "model_node_started",
            "model_node_completed",
        ),
    )

    def model_node(context, config):  # noqa: ANN001, ARG001
        record_llm_completion(None, requested_model="model-a")
        raise RuntimeError("invalid model output")

    result = await CollectionBuildPipelineRunner(
            {"model_node": model_node},
            definitions=definitions,
        ).run(
            build_context(task_service),
            build_config(),
            build_run({"model_node": ()}),
        )

    assert result.node("model_node").stats.model_usage == (
        ModelUsage("model-a", 1, None, 1),
    )


async def test_source_node_persists_figure_metadata_and_references_before_activation():
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

    async def replace_artifacts(collection_id, build_id, artifacts):  # noqa: ANN001
        calls.append(("artifacts", collection_id, build_id, artifacts))

    async def replace_references(collection_id, build_id, references):  # noqa: ANN001
        calls.append(("references", collection_id, build_id, references))

    async def get_collection(_collection_id):
        return {"documents": [{"document_id": "doc-1"}]}

    context = CollectionBuildContext(
        task_id="task-1",
        build_id="build-1",
        collection_id="col-1",
        task_service=SimpleNamespace(),
        collection_service=SimpleNamespace(
            get_collection=get_collection,
            write_figure_asset=lambda *args: (
                f"col-1/objects/source/build-1/figures/{digest}.png"
            )
        ),
        artifact_registry_service=SimpleNamespace(),
        source_artifact_repository=SimpleNamespace(
            replace_collection_documents=replace_artifacts,
            replace_collection_references=replace_references,
        ),
        document_profile_service=SimpleNamespace(),
        research_objective_service=SimpleNamespace(),
        build_source_artifacts=build_source_artifacts,
    )

    result = await nodes.build_source_artifacts(context, build_config())

    assert [call[0] for call in calls] == ["artifacts", "references"]
    assert calls[0][3][0].figures[0].image_path.endswith(f"{digest}.png")
    assert calls[0][3][0].figures[0].image_size_bytes == len(content)
    assert len(calls[1][3].entries) == 1
    assert len(calls[1][3].mentions) == 1
    assert context.state["document_count"] == 1
    assert result["figure_count"] == 1


async def test_source_node_reports_failed_collection_document_lineage():
    bundle = SourceArtifactBundle(
        documents=pd.DataFrame(
            [{"id": "doc-1", "title": "Valid paper", "text": "Methods."}]
        ),
        text_units=pd.DataFrame(),
        blocks=pd.DataFrame(),
        figures=pd.DataFrame(),
        tables=pd.DataFrame(),
        table_rows=pd.DataFrame(),
        table_cells=pd.DataFrame(),
        figure_assets={},
    )

    async def build_source_artifacts(**_kwargs):
        return [
            SimpleNamespace(
                result=bundle,
                errors=[],
                state={
                    "source_document_failures": [
                        {
                            "source_path": "stored-damaged.pdf",
                            "error_code": "source_pdf_parse_failed",
                            "error_type": "RuntimeError",
                        }
                    ]
                },
            )
        ]

    async def get_collection(_collection_id):
        return {
            "documents": [
                {
                "document_id": "doc-good",
                "stored_filename": "stored-valid.pdf",
                "original_filename": "valid.pdf",
            },
            {
                "document_id": "doc-bad",
                "stored_filename": "stored-damaged.pdf",
                "original_filename": "damaged.pdf",
            },
            ]
        }

    async def replace_records(*_args):
        return None

    context = CollectionBuildContext(
        task_id="task-1",
        build_id="build-1",
        collection_id="col-1",
        task_service=SimpleNamespace(),
        collection_service=SimpleNamespace(get_collection=get_collection),
        artifact_registry_service=SimpleNamespace(),
        source_artifact_repository=SimpleNamespace(
            replace_collection_documents=replace_records,
            replace_collection_references=replace_records,
        ),
        document_profile_service=SimpleNamespace(),
        research_objective_service=SimpleNamespace(),
        build_source_artifacts=build_source_artifacts,
    )

    result = await nodes.build_source_artifacts(context, build_config())

    assert result["document_count"] == 1
    assert result["source_failed_document_count"] == 1
    assert result["source_failed_documents"] == [
        {
            "document_id": "doc-bad",
            "filename": "damaged.pdf",
            "error_code": "source_pdf_parse_failed",
            "error_type": "RuntimeError",
        }
    ]
    assert result["warnings"] == [
        "1 Source document could not be parsed and was excluded; "
        "the build continued with 1 parsed document."
    ]


async def test_collection_build_pipeline_runner_skips_downstream_nodes_after_failure():
    task_service = MemoryTaskService()
    definitions = (
        CollectionBuildNodeDefinition(
            "source_artifacts",
            60,
            "Source done.",
            "source_artifacts_started",
            "source_artifacts_completed",
        ),
        CollectionBuildNodeDefinition(
            "document_profiles",
            70,
            "Profiles done.",
            "document_profiles_started",
            "document_profiles_started",
        ),
        CollectionBuildNodeDefinition(
            "paper_facts",
            80,
            "Facts done.",
            "paper_facts_started",
            "paper_facts_started",
        ),
    )

    def source_artifacts(context, config):  # noqa: ANN001
        return {"warnings": ["source warning"]}

    def document_profiles(context, config):  # noqa: ANN001, ARG001
        raise RuntimeError("Error code: 502")

    def paper_facts(context, config):  # noqa: ANN001, ARG001
        raise AssertionError("paper_facts should be skipped")

    result = await CollectionBuildPipelineRunner(
            {
                "source_artifacts": source_artifacts,
                "document_profiles": document_profiles,
                "paper_facts": paper_facts,
            },
            definitions=definitions,
        ).run(
            build_context(task_service),
            build_config(),
            build_run(
                {
                    "source_artifacts": (),
                    "document_profiles": ("source_artifacts",),
                    "paper_facts": ("document_profiles",),
                }
            ),
        )

    assert result.node("source_artifacts").status == "succeeded"
    assert result.node("document_profiles").status == "failed"
    assert result.node("paper_facts").status == "skipped"
    assert result.node("paper_facts").dependencies == ("document_profiles",)
    assert result.errors == ("document_profiles: Error code: 502",)
    assert result.warnings == ("source_artifacts: source warning",)
    assert task_service.record["current_stage"] == "failed"


async def test_collection_build_pipeline_runner_continues_independent_branch_after_failure():
    task_service = MemoryTaskService()
    calls: list[str] = []
    definitions = (
        CollectionBuildNodeDefinition(
            "source_artifacts",
            60,
            "Source done.",
            "source",
            "source",
        ),
        CollectionBuildNodeDefinition(
            "document_profiles",
            70,
            "Profiles done.",
            "profiles",
            "profiles",
        ),
        CollectionBuildNodeDefinition(
            "paper_facts",
            80,
            "Facts done.",
            "facts",
            "facts",
        ),
        CollectionBuildNodeDefinition(
            "artifact_registry",
            98,
            "Artifacts done.",
            "artifacts",
            "artifacts",
        ),
    )

    def source_artifacts(context, config):  # noqa: ANN001, ARG001
        calls.append("source_artifacts")

    def document_profiles(context, config):  # noqa: ANN001, ARG001
        calls.append("document_profiles")
        raise RuntimeError("profile failed")

    def paper_facts(context, config):  # noqa: ANN001, ARG001
        raise AssertionError("paper_facts should be skipped")

    def artifact_registry(context, config):  # noqa: ANN001, ARG001
        calls.append("artifact_registry")

    result = await CollectionBuildPipelineRunner(
            {
                "source_artifacts": source_artifacts,
                "document_profiles": document_profiles,
                "paper_facts": paper_facts,
                "artifact_registry": artifact_registry,
            },
            definitions=definitions,
        ).run(
            build_context(task_service),
            build_config(),
            build_run(
                {
                    "source_artifacts": (),
                    "document_profiles": ("source_artifacts",),
                    "paper_facts": ("document_profiles",),
                    "artifact_registry": ("source_artifacts",),
                }
            ),
        )

    assert calls == [
        "source_artifacts",
        "document_profiles",
        "artifact_registry",
    ]
    assert result.node("paper_facts").status == "skipped"
    assert result.node("artifact_registry").status == "succeeded"


async def test_default_collection_build_pipeline_stops_after_objective_candidates():
    node_ids = tuple(
        definition.node_id for definition in COLLECTION_BUILD_NODE_DEFINITIONS
    )
    graph = dependency_graph_for_mode("standard")

    assert OBJECTIVE_CANDIDATES in node_ids
    assert "files_registered" not in node_ids
    assert "research_objectives" not in node_ids
    assert "paper_facts" not in node_ids
    assert "comparison_rows" not in node_ids
    assert "research_understandings" not in node_ids
    assert graph[DOCUMENT_PROFILES] == ("source_artifacts",)
    assert graph[OBJECTIVE_CANDIDATES] == (DOCUMENT_PROFILES,)
