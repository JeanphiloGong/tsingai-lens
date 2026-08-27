from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

if "devtools" not in sys.modules:
    sys.modules["devtools"] = SimpleNamespace(pformat=lambda value: str(value))

from application.core.document_profiles.service import (
    DocumentProfileService,
)
from application.core.objectives.analysis.finding_synthesis import (
    FindingSynthesisService,
)
from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from application.core.objectives.paper_skim_service import PaperSkimService
from application.core.objectives.research_objective_service import (
    ResearchObjectiveService,
)
from application.pipeline.collection_build.service import CollectionBuildPipelineService
from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.task_service import TaskService
from infra.persistence.memory import MemoryBuildRepository
from infra.source.config.pipeline_mode import IndexingMethod
from infra.source.runtime.artifact_bundle import SourceArtifactBundle
from infra.source.runtime.source_evidence import (
    build_blocks,
    build_table_cells,
    build_table_rows,
)
from tests.support.collection_service import build_test_collection_service
from tests.support.objective_extractor import FakeObjectiveExtractor
from tests.support.objective_repository import MemoryObjectiveRepository
from tests.support.paper_fact_repository import MemoryPaperFactRepository
from tests.support.source_artifact_repository import MemorySourceArtifactRepository


pytestmark = pytest.mark.anyio


class DummyWorkflowOutput:
    def __init__(
        self,
        workflow: str = "build",
        errors: list[str] | None = None,
        result=None,  # noqa: ANN001
        state: dict | None = None,
    ):
        self.workflow = workflow
        self.errors = errors
        self.result = result
        self.state = state or {}


def _write_source_artifact_outputs(
    output_dir: Path,
    *,
    include_nul: bool = False,
) -> SourceArtifactBundle:
    output_dir.mkdir(parents=True, exist_ok=True)
    nul = "\x00" if include_nul else ""
    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": f"Composite{nul} Paper",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        f"The precursor powders were mixed{nul} in ethanol and stirred for 2 h.",
                        "The slurry was dried at 80 C and annealed at 600 C for 2 h under Ar.",
                        "Characterization",
                        "XRD and SEM were used to characterize the powders.",
                        "Flexural strength at 25 C increased to 97 MPa relative to the untreated baseline.",
                    ]
                ),
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "The precursor powders were mixed in ethanol and stirred for 2 h.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-2",
                "text": "The slurry was dried at 80 C and annealed at 600 C for 2 h under Ar.",
                "document_ids": ["paper-1"],
            },
            {
                "id": "tu-3",
                "text": "Flexural strength at 25 C increased to 97 MPa relative to the untreated baseline.",
                "document_ids": ["paper-1"],
            },
        ]
    )
    blocks = build_blocks(documents, text_units)
    tables = pd.DataFrame(
        [
            {
                "table_id": "tbl-1",
                "document_id": "paper-1",
                "table_order": 0,
                "caption_text": f"Processing{nul} summary",
                "caption_block_id": None,
                "page": None,
                "heading_path": ["Experimental Section"],
                "row_count": 1,
                "col_count": 2,
                "column_headers": ["condition", "result"],
                "table_markdown": "| condition | result |\n| --- | --- |\n| annealed | 97 MPa |",
                "table_text": "condition: annealed; result: 97 MPa",
                "metadata": {},
            }
        ]
    )
    table_rows = build_table_rows(documents, text_units)
    table_cells = build_table_cells(documents, text_units)
    return SourceArtifactBundle(
        documents=documents,
        text_units=text_units,
        blocks=blocks,
        figures=pd.DataFrame(),
        tables=tables,
        table_rows=table_rows,
        table_cells=table_cells,
        figure_assets={},
    )


def _build_runner(
    tmp_path,  # noqa: ARG001
    collection_service,
    build_repository,
):  # noqa: ANN001
    source_repository = MemorySourceArtifactRepository()
    paper_fact_repository = MemoryPaperFactRepository()
    objective_repository = MemoryObjectiveRepository()
    document_profile_service = DocumentProfileService(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_fact_repository,
    )
    objective_extractor = FakeObjectiveExtractor()
    research_objective_service = ResearchObjectiveService(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_fact_repository,
        objective_repository=objective_repository,
        document_profile_service=document_profile_service,
        finding_synthesis_service=FindingSynthesisService(),
        paper_skim_service=PaperSkimService(),
        objective_candidate_service=ObjectiveCandidateService(),
        response_client=objective_extractor,
        axis_equivalence_classifier=objective_extractor,
        objective_evidence_router=objective_extractor,
        objective_source_extractor=objective_extractor,
        objective_source_screener=objective_extractor,
        paper_study_window_extractor=objective_extractor,
        paper_signal_reconciler=objective_extractor,
    )
    artifact_registry = ArtifactRegistryService(
        build_repository,
        source_artifact_repository=source_repository,
    )
    runner = CollectionBuildPipelineService(
        collection_service,
        TaskService(build_repository),
        artifact_registry,
        source_artifact_repository=source_repository,
        document_profile_service=document_profile_service,
        research_objective_service=research_objective_service,
    )
    return runner, artifact_registry


async def test_build_pipeline_service_builds_runtime_config_without_config_file(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    build_repository = MemoryBuildRepository()
    runner, _artifact_registry = _build_runner(
        tmp_path,
        collection_service,
        build_repository,
    )

    collection = await collection_service.create_collection("Direct Config Collection")
    paths = collection_service.get_paths(collection["collection_id"])
    config = runner._build_pipeline_config(collection["collection_id"])

    assert not (tmp_path / "configs" / "default.yaml").exists()
    assert config.source.root_dir == str(paths.collection_dir.resolve())
    assert config.source.input.storage.base_dir == str(paths.input_dir.resolve())
    assert config.source.output.base_dir == str(paths.output_dir.resolve())
    assert config.source.input.encoding == "utf-8"
    assert config.source.input.file_pattern == r".*\.(txt|pdf)$"
    assert config.source.cache.base_dir == "../cache"
    assert config.mode == IndexingMethod.Standard


async def test_build_pipeline_service_queues_one_background_collection_process(
    monkeypatch,
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    build_repository = MemoryBuildRepository()
    runner, _artifact_registry = _build_runner(
        tmp_path,
        collection_service,
        build_repository,
    )
    collection = await collection_service.create_collection("Agent Paper Map")
    await collection_service.add_document(
        collection["collection_id"],
        "paper.txt",
        b"Abstract\nLaser exposure affected porosity.",
    )
    started = asyncio.Event()
    captured: dict[str, object] = {}

    async def fake_run_task(*args, **kwargs):  # noqa: ANN002, ANN003
        captured["args"] = args
        captured["kwargs"] = kwargs
        started.set()
        return {
            "task_id": args[0],
            "collection_id": args[1],
            "status": "completed",
        }

    monkeypatch.setattr(runner, "run_task", fake_run_task)

    queued = await runner.queue_build(
        collection["collection_id"],
        mode="standard",
        request_id="req-agent-1",
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    assert queued["status"] == "queued"
    assert queued["mode"] == "standard"
    assert captured == {
        "args": (queued["task_id"], collection["collection_id"]),
        "kwargs": {
            "verbose": False,
            "additional_context": None,
            "request_id": "req-agent-1",
        },
    }
    assert await build_repository.read_build(queued["task_id"]) is not None


async def test_build_pipeline_service_rejects_empty_collection_before_task_creation(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    build_repository = MemoryBuildRepository()
    runner, _artifact_registry = _build_runner(
        tmp_path,
        collection_service,
        build_repository,
    )
    collection = await collection_service.create_collection("Empty Paper Map")

    with pytest.raises(
        ValueError,
        match="collection contains no documents available for building",
    ):
        await runner.queue_build(collection["collection_id"])

    assert await build_repository.list_tasks(
        collection_id=collection["collection_id"]
    ) == ()


async def test_build_pipeline_service_builds_collection_artifacts(monkeypatch, tmp_path):
    import application.pipeline.collection_build.service as task_runner_module

    collection_service = build_test_collection_service(tmp_path / "collections")
    build_repository = MemoryBuildRepository()
    task_service = TaskService(build_repository)
    runner, artifact_registry = _build_runner(
        tmp_path,
        collection_service,
        build_repository,
    )

    collection = await collection_service.create_collection("Composite Papers")
    paths = collection_service.get_paths(collection["collection_id"])
    await collection_service.add_document(
        collection["collection_id"],
        "paper.txt",
        b"Experimental Section\nMix and anneal.",
    )

    captured: dict[str, object] = {}

    async def fake_build_source_artifacts(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return [
            DummyWorkflowOutput(result=_write_source_artifact_outputs(paths.output_dir))
        ]

    monkeypatch.setattr(
        task_runner_module, "build_source_artifacts", fake_build_source_artifacts
    )

    task = await task_service.create_task(collection["collection_id"], "build")
    result = await runner.run_task(task["task_id"], collection["collection_id"])

    assert result["status"] == "completed"
    assert result["current_stage"] == "artifacts_ready"
    assert result["progress_detail"]["phase"] == "artifacts_ready"
    assert captured["method"] == task_runner_module.IndexingMethod.Standard
    assert "is_update_run" not in captured
    pipeline_run = await task_service.read_pipeline_run(task["task_id"])
    assert pipeline_run.status == "completed"
    assert pipeline_run.run_id == task["task_id"]
    stored_build = await build_repository.read_build(task["task_id"])
    assert stored_build is not None
    assert pipeline_run.output_build_id == stored_build.build_id
    assert pipeline_run.node("source_artifacts").output_summary["document_count"] == 1
    assert pipeline_run.stats.duration_ms is not None
    artifacts = await artifact_registry.get_for_task(task["task_id"])
    assert artifacts["documents_generated"] is True
    assert artifacts["documents_ready"] is True
    assert artifacts["blocks_generated"] is True
    assert artifacts["blocks_ready"] is True
    assert artifacts["figures_generated"] is True
    assert artifacts["figures_ready"] is False
    assert artifacts["table_rows_generated"] is True
    assert artifacts["table_rows_ready"] is False
    assert artifacts["table_cells_generated"] is True
    assert artifacts["table_cells_ready"] is False
    objective_facts = await runner.research_objective_service.objective_repository.read(
        collection["collection_id"],
        build_id=stored_build.build_id,
    )
    assert objective_facts.research_objectives_ready is True
    assert objective_facts.paper_skims


async def test_build_pipeline_removes_parser_nul_before_source_persistence(
    monkeypatch,
    tmp_path,
):
    import application.pipeline.collection_build.service as task_runner_module

    collection_service = build_test_collection_service(tmp_path / "collections")
    build_repository = MemoryBuildRepository()
    task_service = TaskService(build_repository)
    runner, _artifact_registry = _build_runner(
        tmp_path,
        collection_service,
        build_repository,
    )
    collection = await collection_service.create_collection("NUL Source Collection")
    paths = collection_service.get_paths(collection["collection_id"])
    await collection_service.add_document(
        collection["collection_id"],
        "paper.txt",
        b"Experimental Section\nMix and anneal.",
    )

    async def fake_build_source_artifacts(**kwargs):  # noqa: ANN003, ARG001
        return [
            DummyWorkflowOutput(
                result=_write_source_artifact_outputs(
                    paths.output_dir,
                    include_nul=True,
                )
            )
        ]

    monkeypatch.setattr(
        task_runner_module,
        "build_source_artifacts",
        fake_build_source_artifacts,
    )

    task = await task_service.create_task(collection["collection_id"], "build")
    result = await runner.run_task(task["task_id"], collection["collection_id"])

    assert result["status"] == "completed"
    build = await build_repository.read_build(task["task_id"])
    assert build is not None
    source_document = (await runner.source_artifact_repository.read_collection_documents(
        collection["collection_id"],
        build_id=build.build_id,
    ))[0]
    assert "\x00" not in source_document.title
    assert "\x00" not in source_document.text
    assert "\x00" not in source_document.tables[0].caption_text


async def test_build_pipeline_service_keeps_objectives_and_reports_partial_skim_coverage(
    monkeypatch,
    tmp_path,
):
    import application.pipeline.collection_build.service as task_runner_module

    class PartiallyFailingObjectiveExtractor(FakeObjectiveExtractor):
        def extract(self, payload):  # noqa: ANN001
            if any(
                unit.get("source_unit_id") == "source-unit-000002"
                for unit in payload.get("source_units") or ()
            ):
                raise RuntimeError("invalid relationship in Source unit")
            return super().extract(payload)

    collection_service = build_test_collection_service(tmp_path / "collections")
    build_repository = MemoryBuildRepository()
    task_service = TaskService(build_repository)
    runner, artifact_registry = _build_runner(
        tmp_path,
        collection_service,
        build_repository,
    )
    failing_extractor = PartiallyFailingObjectiveExtractor()
    runner.research_objective_service._response_client = failing_extractor
    runner.research_objective_service._axis_equivalence_classifier = (
        failing_extractor
    )
    runner.research_objective_service._objective_source_screener = failing_extractor
    runner.research_objective_service._objective_evidence_router = failing_extractor
    runner.research_objective_service._objective_source_extractor = failing_extractor
    runner.research_objective_service._paper_study_window_extractor = failing_extractor
    runner.research_objective_service._paper_signal_reconciler = failing_extractor

    collection = await collection_service.create_collection("Partial PaperSkim Collection")
    paths = collection_service.get_paths(collection["collection_id"])
    await collection_service.add_document(
        collection["collection_id"],
        "paper.txt",
        b"Experimental Section\nMix and anneal.",
    )

    async def fake_build_source_artifacts(**kwargs):  # noqa: ANN003, ARG001
        return [
            DummyWorkflowOutput(result=_write_source_artifact_outputs(paths.output_dir))
        ]

    monkeypatch.setattr(
        task_runner_module, "build_source_artifacts", fake_build_source_artifacts
    )

    task = await task_service.create_task(collection["collection_id"], "build")
    result = await runner.run_task(task["task_id"], collection["collection_id"])

    assert result["status"] == "partial_success"
    assert result["errors"] == []
    assert result["warnings"] == [
        "objective_candidates: 1 PaperSkim Source unit failed extraction "
        "permanently; candidate objectives were built from the remaining coverage."
    ]
    pipeline_run = await task_service.read_pipeline_run(task["task_id"])
    objective_node = pipeline_run.node("objective_candidates")
    assert objective_node.status == "succeeded"
    assert objective_node.output_summary["extraction_failed_source_unit_count"] == 1

    build = await artifact_registry.repository.read_build(task["task_id"])
    assert build is not None
    objective_facts = await runner.research_objective_service.objective_repository.read(
        collection["collection_id"],
        build_id=build.build_id,
    )
    assert objective_facts.research_objectives_ready is True
    assert objective_facts.research_objectives
    assert any(not skim.coverage_complete for skim in objective_facts.paper_skims)


async def test_build_pipeline_service_reports_partial_source_coverage(
    monkeypatch,
    tmp_path,
):
    import application.pipeline.collection_build.service as task_runner_module

    collection_service = build_test_collection_service(tmp_path / "collections")
    build_repository = MemoryBuildRepository()
    task_service = TaskService(build_repository)
    runner, _artifact_registry = _build_runner(
        tmp_path,
        collection_service,
        build_repository,
    )
    collection = await collection_service.create_collection("Partial Source Collection")
    paths = collection_service.get_paths(collection["collection_id"])
    await collection_service.add_document(
        collection["collection_id"],
        "valid.txt",
        b"Experimental Section\nMix and anneal.",
    )
    await collection_service.add_document(
        collection["collection_id"],
        "damaged.txt",
        b"unreadable source placeholder",
    )
    files = (await collection_service.get_collection(collection["collection_id"]))[
        "documents"
    ]
    damaged = next(
        item for item in files if item["original_filename"] == "damaged.txt"
    )

    async def fake_build_source_artifacts(**_kwargs):
        return [
            DummyWorkflowOutput(
                result=_write_source_artifact_outputs(paths.output_dir),
                state={
                    "source_document_failures": [
                        {
                            "source_path": damaged["stored_filename"],
                            "error_code": "source_text_parse_failed",
                            "error_type": "UnicodeDecodeError",
                        }
                    ]
                },
            )
        ]

    monkeypatch.setattr(
        task_runner_module,
        "build_source_artifacts",
        fake_build_source_artifacts,
    )

    task = await task_service.create_task(collection["collection_id"], "build")
    result = await runner.run_task(task["task_id"], collection["collection_id"])

    assert result["status"] == "partial_success"
    assert result["errors"] == []
    assert result["warnings"] == [
        "source_artifacts: 1 Source document could not be parsed and was excluded; "
        "the build continued with 1 parsed document."
    ]
    pipeline_run = await task_service.read_pipeline_run(task["task_id"])
    source_node = pipeline_run.node("source_artifacts")
    assert source_node.status == "succeeded"
    assert source_node.output_summary["source_failed_document_count"] == 1
    assert source_node.output_summary["source_failed_documents"][0]["document_id"] == (
        damaged["document_id"]
    )


async def test_build_pipeline_service_marks_empty_collection_failed(monkeypatch, tmp_path):
    import application.pipeline.collection_build.service as task_runner_module

    collection_service = build_test_collection_service(tmp_path / "collections")
    build_repository = MemoryBuildRepository()
    task_service = TaskService(build_repository)
    runner, _artifact_registry = _build_runner(
        tmp_path,
        collection_service,
        build_repository,
    )

    collection = await collection_service.create_collection("Empty Collection")

    async def fail_build_source_artifacts(**kwargs):  # noqa: ANN003, ARG001
        raise AssertionError("source artifacts should not run for an empty collection")

    monkeypatch.setattr(
        task_runner_module, "build_source_artifacts", fail_build_source_artifacts
    )

    task = await task_service.create_task(collection["collection_id"], "build")
    result = await runner.run_task(task["task_id"], collection["collection_id"])

    assert result["status"] == "failed"
    assert result["current_stage"] == "failed"
    assert "files_registered" not in result["pipeline_nodes"]
    assert result["pipeline_nodes"]["source_artifacts"]["status"] == "failed"
    assert (
        "source_artifacts: The collection contains no documents available for building"
        in result["errors"]
    )


async def test_build_pipeline_service_marks_source_artifact_errors_failed(
    monkeypatch, tmp_path
):
    import application.pipeline.collection_build.service as task_runner_module

    collection_service = build_test_collection_service(tmp_path / "collections")
    build_repository = MemoryBuildRepository()
    task_service = TaskService(build_repository)
    runner, _artifact_registry = _build_runner(
        tmp_path,
        collection_service,
        build_repository,
    )

    collection = await collection_service.create_collection("Source Error Collection")
    await collection_service.add_document(
        collection["collection_id"], "paper.txt", b"bad pdf"
    )

    async def fake_build_source_artifacts(**kwargs):  # noqa: ANN003, ARG001
        return [DummyWorkflowOutput(errors=["docling import failed"])]

    monkeypatch.setattr(
        task_runner_module, "build_source_artifacts", fake_build_source_artifacts
    )

    task = await task_service.create_task(collection["collection_id"], "build")
    result = await runner.run_task(task["task_id"], collection["collection_id"])

    assert result["status"] == "failed"
    assert result["current_stage"] == "failed"
    assert result["pipeline_nodes"]["source_artifacts"]["status"] == "failed"
    assert result["pipeline_nodes"]["artifact_registry"]["status"] == "skipped"
    assert result["errors"] == ["source_artifacts: docling import failed"]
    pipeline_run = await task_service.read_pipeline_run(task["task_id"])
    assert pipeline_run.status == "failed"
    assert pipeline_run.node("artifact_registry").dependencies == (
        "source_artifacts",
    )


async def test_build_pipeline_service_logs_stage_progress(monkeypatch, tmp_path, caplog):
    import application.pipeline.collection_build.service as task_runner_module

    collection_service = build_test_collection_service(tmp_path / "collections")
    build_repository = MemoryBuildRepository()
    task_service = TaskService(build_repository)
    runner, _artifact_registry = _build_runner(
        tmp_path,
        collection_service,
        build_repository,
    )

    collection = await collection_service.create_collection("Logging Progress Collection")
    paths = collection_service.get_paths(collection["collection_id"])
    await collection_service.add_document(
        collection["collection_id"],
        "paper.txt",
        b"Experimental Section\nMix and anneal.",
    )

    async def fake_build_source_artifacts(**kwargs):  # noqa: ANN003, ARG001
        return [
            DummyWorkflowOutput(result=_write_source_artifact_outputs(paths.output_dir))
        ]

    monkeypatch.setattr(
        task_runner_module, "build_source_artifacts", fake_build_source_artifacts
    )

    task = await task_service.create_task(collection["collection_id"], "build")
    with caplog.at_level("INFO"):
        await runner.run_task(task["task_id"], collection["collection_id"])

    assert any(
        "Build task progress" in record.message
        and "stage=source_artifacts_started" in record.message
        and "progress_percent=25" in record.message
        for record in caplog.records
    )
    assert any(
        "Build task progress" in record.message
        and "stage=document_profiles_completed" in record.message
        and "progress_percent=70" in record.message
        for record in caplog.records
    )
    assert any(
        "Build task progress" in record.message
        and "stage=objective_candidates_started" in record.message
        and "progress_percent=71" in record.message
        for record in caplog.records
    )
    assert any(
        "Build task progress" in record.message
        and "stage=objective_candidates_completed" in record.message
        and "progress_percent=71" in record.message
        for record in caplog.records
    )
    assert any(
        "Build task progress" in record.message
        and "stage=artifacts_ready" in record.message
        and "progress_percent=100" in record.message
        for record in caplog.records
    )
    final_task = await task_service.get_task(task["task_id"])
    assert final_task["progress_detail"]["phase"] == "artifacts_ready"
