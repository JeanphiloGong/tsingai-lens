from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

if "devtools" not in sys.modules:
    sys.modules["devtools"] = SimpleNamespace(pformat=lambda value: str(value))

from application.source.artifact_registry_service import ArtifactRegistryService
from application.core.semantic_build.document_profile_service import (
    DocumentProfileService,
)
from application.core.semantic_build.research_objective_service import (
    ResearchObjectiveService,
)
from application.core.finding_synthesis_service import FindingSynthesisService
from tests.support.collection_service import build_test_collection_service
from application.pipeline.collection_build.service import CollectionBuildPipelineService
from application.source.task_service import TaskService
from domain.source import (
    SourceArtifactSet,
    SourceReferenceSet,
    build_source_document_tree,
)
from infra.persistence.memory import MemoryBuildRepository
from infra.source.runtime.artifact_bundle import SourceArtifactBundle
from infra.source.runtime.source_evidence import (
    build_blocks,
    build_table_cells,
    build_table_rows,
)
from tests.support.paper_fact_repository import MemoryPaperFactRepository
from tests.support.objective_repository import MemoryObjectiveRepository
from tests.support.comparison_repository import MemoryComparisonRepository


class DummyWorkflowOutput:
    def __init__(
        self,
        workflow: str = "build",
        errors: list[str] | None = None,
        result=None,  # noqa: ANN001
    ):
        self.workflow = workflow
        self.errors = errors
        self.result = result


class MemorySourceArtifactRepository:
    def __init__(self) -> None:
        self._artifacts: dict[tuple[str, str], SourceArtifactSet] = {}
        self._references: dict[tuple[str, str], SourceReferenceSet] = {}

    def replace_collection_artifacts(
        self,
        collection_id: str,
        build_id: str,
        artifacts: SourceArtifactSet,
    ) -> None:
        self._artifacts[(collection_id, build_id)] = artifacts

    def read_collection_artifacts(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> SourceArtifactSet:
        if build_id is None:
            return SourceArtifactSet()
        return self._artifacts.get((collection_id, build_id), SourceArtifactSet())

    def replace_collection_references(
        self,
        collection_id: str,
        build_id: str,
        references: SourceReferenceSet,
    ) -> None:
        self._references[(collection_id, build_id)] = references

    def read_collection_references(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> SourceReferenceSet:
        if build_id is None:
            return SourceReferenceSet()
        return self._references.get((collection_id, build_id), SourceReferenceSet())

    def read_document_tree(
        self,
        collection_id: str,
        document_id: str,
        build_id: str | None = None,
    ):
        artifacts = self.read_collection_artifacts(
            collection_id,
            build_id=build_id,
        )
        document = next(
            item for item in artifacts.documents if item.document_id == document_id
        )
        return build_source_document_tree(
            collection_id=collection_id,
            document=document,
            blocks=tuple(
                item for item in artifacts.blocks if item.document_id == document_id
            ),
            tables=tuple(
                item for item in artifacts.tables if item.document_id == document_id
            ),
            figures=tuple(
                item for item in artifacts.figures if item.document_id == document_id
            ),
            references=self.read_collection_references(
                collection_id,
                build_id=build_id,
            ),
        )


def _write_source_artifact_outputs(
    output_dir: Path,
) -> SourceArtifactBundle:
    output_dir.mkdir(parents=True, exist_ok=True)
    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "Composite Paper",
                "text": "\n".join(
                    [
                        "Experimental Section",
                        "The precursor powders were mixed in ethanol and stirred for 2 h.",
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
                "caption_text": "Processing summary",
                "caption_block_id": None,
                "page": None,
                "bbox": None,
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


def _build_runner(tmp_path, collection_service, build_repository):  # noqa: ANN001
    source_repository = MemorySourceArtifactRepository()
    paper_fact_repository = MemoryPaperFactRepository()
    objective_repository = MemoryObjectiveRepository()
    comparison_repository = MemoryComparisonRepository()
    document_profile_service = DocumentProfileService(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_fact_repository,
    )
    research_objective_service = ResearchObjectiveService(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_fact_repository,
        objective_repository=objective_repository,
        document_profile_service=document_profile_service,
        finding_synthesis_service=FindingSynthesisService(),
    )
    artifact_registry = ArtifactRegistryService(
        build_repository,
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_fact_repository,
        comparison_repository=comparison_repository,
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


def test_build_pipeline_service_builds_runtime_config_without_config_file(
    tmp_path,
):
    collection_service = build_test_collection_service(tmp_path / "collections")
    build_repository = MemoryBuildRepository()
    runner, _artifact_registry = _build_runner(
        tmp_path,
        collection_service,
        build_repository,
    )

    collection = collection_service.create_collection("Direct Config Collection")
    paths = collection_service.get_paths(collection["collection_id"])
    config, output_dir = runner._build_collection_config(collection["collection_id"])

    assert not (tmp_path / "configs" / "default.yaml").exists()
    assert config.root_dir == str(paths.collection_dir.resolve())
    assert config.input.storage.base_dir == str(paths.input_dir.resolve())
    assert config.output.base_dir == str(paths.output_dir.resolve())
    assert config.input.encoding == "utf-8"
    assert config.input.file_pattern == r".*\.(txt|pdf)$"
    assert config.cache.base_dir == "../cache"
    assert output_dir == paths.output_dir


def test_build_pipeline_service_builds_collection_artifacts(monkeypatch, tmp_path):
    import application.pipeline.collection_build.service as task_runner_module

    collection_service = build_test_collection_service(tmp_path / "collections")
    build_repository = MemoryBuildRepository()
    task_service = TaskService(build_repository)
    runner, artifact_registry = _build_runner(
        tmp_path,
        collection_service,
        build_repository,
    )

    collection = collection_service.create_collection("Composite Papers")
    paths = collection_service.get_paths(collection["collection_id"])
    collection_service.add_file(
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

    task = task_service.create_task(collection["collection_id"], "build")
    result = asyncio.run(runner.run_task(task["task_id"], collection["collection_id"]))

    assert result["status"] == "completed"
    assert result["current_stage"] == "artifacts_ready"
    assert result["progress_detail"]["phase"] == "artifacts_ready"
    assert captured["method"] == task_runner_module.IndexingMethod.Standard
    assert "is_update_run" not in captured
    artifacts = artifact_registry.get_for_task(task["task_id"])
    assert artifacts["documents_generated"] is True
    assert artifacts["documents_ready"] is True
    assert artifacts["document_profiles_generated"] is True
    assert artifacts["document_profiles_ready"] is True
    assert artifacts["evidence_cards_generated"] is False
    assert artifacts["evidence_cards_ready"] is False
    assert artifacts["characterization_observations_generated"] is False
    assert artifacts["characterization_observations_ready"] is False
    assert artifacts["structure_features_generated"] is False
    assert artifacts["structure_features_ready"] is False
    assert artifacts["test_conditions_generated"] is False
    assert artifacts["test_conditions_ready"] is False
    assert artifacts["baseline_references_generated"] is False
    assert artifacts["baseline_references_ready"] is False
    assert artifacts["sample_variants_generated"] is False
    assert artifacts["sample_variants_ready"] is False
    assert artifacts["measurement_results_generated"] is False
    assert artifacts["measurement_results_ready"] is False
    assert artifacts["comparable_results_generated"] is False
    assert artifacts["comparable_results_ready"] is False
    assert artifacts["collection_comparable_results_generated"] is False
    assert artifacts["collection_comparable_results_ready"] is False
    assert artifacts["comparison_rows_generated"] is False
    assert artifacts["comparison_rows_ready"] is False
    assert artifacts["graph_generated"] is False
    assert artifacts["graph_ready"] is False
    assert artifacts["blocks_generated"] is True
    assert artifacts["blocks_ready"] is True
    assert artifacts["figures_generated"] is True
    assert artifacts["figures_ready"] is False
    assert artifacts["table_rows_generated"] is True
    assert artifacts["table_rows_ready"] is False
    assert artifacts["table_cells_generated"] is True
    assert artifacts["table_cells_ready"] is False
    objective_facts = runner.research_objective_service.objective_repository.read(
        collection["collection_id"],
        build_id=artifact_registry.repository.read_build(task["task_id"]).build_id,
    )
    assert objective_facts.research_objectives_ready is True
    assert objective_facts.paper_skims


def test_build_pipeline_service_marks_empty_collection_failed(monkeypatch, tmp_path):
    import application.pipeline.collection_build.service as task_runner_module

    collection_service = build_test_collection_service(tmp_path / "collections")
    build_repository = MemoryBuildRepository()
    task_service = TaskService(build_repository)
    runner, _artifact_registry = _build_runner(
        tmp_path,
        collection_service,
        build_repository,
    )

    collection = collection_service.create_collection("Empty Collection")

    async def fail_build_source_artifacts(**kwargs):  # noqa: ANN003, ARG001
        raise AssertionError("source artifacts should not run for an empty collection")

    monkeypatch.setattr(
        task_runner_module, "build_source_artifacts", fail_build_source_artifacts
    )

    task = task_service.create_task(collection["collection_id"], "build")
    result = asyncio.run(runner.run_task(task["task_id"], collection["collection_id"]))

    assert result["status"] == "failed"
    assert result["current_stage"] == "failed"
    assert result["pipeline_nodes"]["files_registered"]["status"] == "failed"
    assert result["pipeline_nodes"]["source_artifacts"]["status"] == "skipped"
    assert "files_registered: 集合内没有可构建文件" in result["errors"]


def test_build_pipeline_service_marks_source_artifact_errors_failed(
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

    collection = collection_service.create_collection("Source Error Collection")
    collection_service.add_file(collection["collection_id"], "paper.txt", b"bad pdf")

    async def fake_build_source_artifacts(**kwargs):  # noqa: ANN003, ARG001
        return [DummyWorkflowOutput(errors=["docling import failed"])]

    monkeypatch.setattr(
        task_runner_module, "build_source_artifacts", fake_build_source_artifacts
    )

    task = task_service.create_task(collection["collection_id"], "build")
    result = asyncio.run(runner.run_task(task["task_id"], collection["collection_id"]))

    assert result["status"] == "failed"
    assert result["current_stage"] == "failed"
    assert result["pipeline_nodes"]["source_artifacts"]["status"] == "failed"
    assert result["pipeline_nodes"]["artifact_registry"]["status"] == "skipped"
    assert result["errors"] == ["source_artifacts: docling import failed"]


def test_build_pipeline_service_logs_stage_progress(monkeypatch, tmp_path, caplog):
    import application.pipeline.collection_build.service as task_runner_module

    collection_service = build_test_collection_service(tmp_path / "collections")
    build_repository = MemoryBuildRepository()
    task_service = TaskService(build_repository)
    runner, _artifact_registry = _build_runner(
        tmp_path,
        collection_service,
        build_repository,
    )

    collection = collection_service.create_collection("Logging Progress Collection")
    paths = collection_service.get_paths(collection["collection_id"])
    collection_service.add_file(
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

    task = task_service.create_task(collection["collection_id"], "build")
    with caplog.at_level("INFO"):
        asyncio.run(runner.run_task(task["task_id"], collection["collection_id"]))

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
    final_task = task_service.get_task(task["task_id"])
    assert final_task["progress_detail"]["phase"] == "artifacts_ready"
