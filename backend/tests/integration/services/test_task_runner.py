from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

if "devtools" not in sys.modules:
    sys.modules["devtools"] = SimpleNamespace(pformat=lambda value: str(value))

from application.source.artifact_registry_service import ArtifactRegistryService
from application.source.collection_service import CollectionService
from application.source.collection_build_task_runner import CollectionBuildTaskRunner
from application.source.task_service import TaskService
from domain.source import SourceArtifactSet
from infra.persistence.sqlite import (
    SqliteCoreFactRepository,
    SqliteSourceArtifactRepository,
)
from infra.source.runtime.source_evidence import build_blocks, build_table_cells, build_table_rows


class DummyWorkflowOutput:
    def __init__(self, workflow: str = "build", errors: list[str] | None = None):
        self.workflow = workflow
        self.errors = errors


def _build_config(output_dir: Path, input_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        output=SimpleNamespace(base_dir=str(output_dir)),
        input=SimpleNamespace(storage=SimpleNamespace(base_dir=str(input_dir))),
        root_dir=str(output_dir.parent),
    )


def _write_source_artifact_outputs(
    output_dir: Path,
    *,
    collection_id: str | None = None,
    source_repository=None,  # noqa: ANN001
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    collection_id = collection_id or output_dir.parent.name
    if source_repository is None:
        source_repository = SqliteSourceArtifactRepository(output_dir.parents[2] / "lens.sqlite")
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
    source_repository.replace_collection_artifacts(
        collection_id,
        SourceArtifactSet.from_records(
            documents=documents.to_dict(orient="records"),
            text_units=text_units.to_dict(orient="records"),
            blocks=blocks.to_dict(orient="records"),
            tables=tables.to_dict(orient="records"),
            table_rows=table_rows.to_dict(orient="records"),
            table_cells=table_cells.to_dict(orient="records"),
        ),
    )


def test_build_task_runner_builds_collection_artifacts(monkeypatch, tmp_path):
    import application.source.collection_build_task_runner as task_runner_module

    collection_service = CollectionService(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    source_artifact_repository = SqliteSourceArtifactRepository(tmp_path / "lens.sqlite")
    artifact_registry = ArtifactRegistryService(
        tmp_path / "collections",
    )
    runner = CollectionBuildTaskRunner(collection_service, task_service, artifact_registry)

    collection = collection_service.create_collection("Composite Papers")
    paths = collection_service.get_paths(collection["collection_id"])
    collection_service.add_file(collection["collection_id"], "paper.txt", b"Experimental Section\nMix and anneal.")

    default_config = tmp_path / "configs" / "default.yaml"
    default_config.parent.mkdir(parents=True, exist_ok=True)
    default_config.write_text("dummy: true\n", encoding="utf-8")

    captured: dict[str, object] = {}

    async def fake_build_source_artifacts(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        _write_source_artifact_outputs(
            paths.output_dir,
            source_repository=source_artifact_repository,
        )
        return [DummyWorkflowOutput()]

    monkeypatch.setattr(task_runner_module, "CONFIG_DIR", default_config.parent)
    monkeypatch.setattr(task_runner_module, "load_config", lambda *args, **kwargs: _build_config(paths.output_dir, paths.input_dir))
    monkeypatch.setattr(task_runner_module, "build_source_artifacts", fake_build_source_artifacts)

    task = task_service.create_task(collection["collection_id"], "build")
    result = asyncio.run(runner.run_build_task(task["task_id"], collection["collection_id"]))

    assert result["status"] == "completed"
    assert result["current_stage"] == "artifacts_ready"
    assert captured["method"] == task_runner_module.IndexingMethod.Standard
    assert "is_update_run" not in captured
    artifacts = artifact_registry.get(collection["collection_id"])
    assert artifacts["documents_generated"] is True
    assert artifacts["documents_ready"] is True
    assert artifacts["document_profiles_generated"] is True
    assert artifacts["document_profiles_ready"] is True
    assert artifacts["evidence_cards_generated"] is True
    assert artifacts["evidence_cards_ready"] is True
    assert artifacts["characterization_observations_generated"] is True
    assert artifacts["characterization_observations_ready"] is False
    assert artifacts["structure_features_generated"] is True
    assert artifacts["structure_features_ready"] is False
    assert artifacts["test_conditions_generated"] is True
    assert artifacts["test_conditions_ready"] is True
    assert artifacts["baseline_references_generated"] is True
    assert artifacts["baseline_references_ready"] is False
    assert artifacts["sample_variants_generated"] is True
    assert artifacts["sample_variants_ready"] is False
    assert artifacts["measurement_results_generated"] is True
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
    core_facts = SqliteCoreFactRepository(tmp_path / "lens.sqlite").read_collection_facts(
        collection["collection_id"]
    )
    assert core_facts.research_objectives_ready is True
    assert core_facts.paper_skims

def test_build_task_runner_logs_stage_progress(monkeypatch, tmp_path, caplog):
    import application.source.collection_build_task_runner as task_runner_module

    collection_service = CollectionService(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    runner = CollectionBuildTaskRunner(collection_service, task_service, artifact_registry)

    collection = collection_service.create_collection("Logging Progress Collection")
    paths = collection_service.get_paths(collection["collection_id"])
    collection_service.add_file(collection["collection_id"], "paper.txt", b"Experimental Section\nMix and anneal.")

    default_config = tmp_path / "configs" / "default.yaml"
    default_config.parent.mkdir(parents=True, exist_ok=True)
    default_config.write_text("dummy: true\n", encoding="utf-8")

    async def fake_build_source_artifacts(**kwargs):  # noqa: ANN003, ARG001
        _write_source_artifact_outputs(paths.output_dir)
        return [DummyWorkflowOutput()]

    monkeypatch.setattr(task_runner_module, "CONFIG_DIR", default_config.parent)
    monkeypatch.setattr(
        task_runner_module,
        "load_config",
        lambda *args, **kwargs: _build_config(paths.output_dir, paths.input_dir),
    )
    monkeypatch.setattr(task_runner_module, "build_source_artifacts", fake_build_source_artifacts)

    task = task_service.create_task(collection["collection_id"], "build")
    with caplog.at_level("INFO"):
        asyncio.run(runner.run_build_task(task["task_id"], collection["collection_id"]))

    assert any(
        "Build task progress" in record.message
        and "stage=source_artifacts_started" in record.message
        and "progress_percent=25" in record.message
        for record in caplog.records
    )
    assert any(
        "Build task progress" in record.message
        and "stage=paper_facts_started" in record.message
        and "progress_percent=76" in record.message
        for record in caplog.records
    )
    assert any(
        "Build task progress" in record.message
        and "stage=artifacts_ready" in record.message
        and "progress_percent=100" in record.message
        for record in caplog.records
    )
