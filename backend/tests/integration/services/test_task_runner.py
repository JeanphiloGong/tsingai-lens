from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

if "devtools" not in sys.modules:
    sys.modules["devtools"] = SimpleNamespace(pformat=lambda value: str(value))

from application.workspace.artifact_registry_service import ArtifactRegistryService
from application.collections.service import CollectionService
from application.indexing.index_task_runner import IndexTaskRunner
from application.indexing.task_service import TaskService
from retrieval.index.operations.source_evidence import build_sections, build_table_cells


class DummyWorkflowOutput:
    def __init__(self, workflow: str = "index", errors: list[str] | None = None):
        self.workflow = workflow
        self.errors = errors


def _patch_parquet(monkeypatch) -> None:  # noqa: ANN001
    def fake_to_parquet(self, path, index=False):  # noqa: ANN001
        frame = self.reset_index(drop=True) if index else self
        Path(path).write_text(frame.to_json(orient="records"), encoding="utf-8")

    def fake_read_parquet(path, *args, **kwargs):  # noqa: ANN001, ARG001
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return pd.DataFrame(payload)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet, raising=False)
    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)


def _build_config(output_dir: Path, input_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        output=SimpleNamespace(base_dir=str(output_dir)),
        input=SimpleNamespace(storage=SimpleNamespace(base_dir=str(input_dir))),
        root_dir=str(output_dir.parent),
    )


def _write_index_outputs(output_dir: Path) -> None:
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
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    build_sections(documents, text_units).to_parquet(output_dir / "sections.parquet", index=False)
    build_table_cells(documents, text_units).to_parquet(output_dir / "table_cells.parquet", index=False)


def _write_review_only_outputs(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    documents = pd.DataFrame(
        [
            {
                "id": "paper-1",
                "title": "A Review of Composite Fillers",
                "text": "This review summarizes recent advances in composite fillers and processing routes.",
            }
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "tu-1",
                "text": "This review summarizes recent advances in composite fillers.",
                "document_ids": ["paper-1"],
            }
        ]
    )
    documents.to_parquet(output_dir / "documents.parquet", index=False)
    text_units.to_parquet(output_dir / "text_units.parquet", index=False)
    build_sections(documents, text_units).to_parquet(output_dir / "sections.parquet", index=False)
    build_table_cells(documents, text_units).to_parquet(output_dir / "table_cells.parquet", index=False)


def test_index_task_runner_builds_collection_artifacts(monkeypatch, tmp_path):
    _patch_parquet(monkeypatch)

    import application.indexing.index_task_runner as task_runner_module

    collection_service = CollectionService(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    runner = IndexTaskRunner(collection_service, task_service, artifact_registry)

    collection = collection_service.create_collection("Composite Papers")
    paths = collection_service.get_paths(collection["collection_id"])
    collection_service.add_file(collection["collection_id"], "paper.txt", b"Experimental Section\nMix and anneal.")

    default_config = tmp_path / "configs" / "default.yaml"
    default_config.parent.mkdir(parents=True, exist_ok=True)
    default_config.write_text("dummy: true\n", encoding="utf-8")

    captured: dict[str, object] = {}

    async def fake_build_index(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        _write_index_outputs(paths.output_dir)
        return [DummyWorkflowOutput()]

    monkeypatch.setattr(task_runner_module, "CONFIG_DIR", default_config.parent)
    monkeypatch.setattr(task_runner_module, "load_config", lambda *args, **kwargs: _build_config(paths.output_dir, paths.input_dir))
    monkeypatch.setattr(task_runner_module, "build_index", fake_build_index)

    task = task_service.create_task(collection["collection_id"], "index")
    result = asyncio.run(runner.run_index_task(task["task_id"], collection["collection_id"]))

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
    assert artifacts["comparison_rows_generated"] is True
    assert artifacts["comparison_rows_ready"] is True
    assert artifacts["graph_generated"] is True
    assert artifacts["graph_ready"] is True
    assert artifacts["sections_generated"] is True
    assert artifacts["sections_ready"] is True
    assert artifacts["table_cells_generated"] is True
    assert artifacts["table_cells_ready"] is False
    assert artifacts["procedure_blocks_generated"] is True
    assert artifacts["procedure_blocks_ready"] is True
    assert artifacts["protocol_steps_generated"] is True
    assert artifacts["protocol_steps_ready"] is True
    assert paths.output_dir.joinpath("document_profiles.parquet").exists()
    assert paths.output_dir.joinpath("evidence_cards.parquet").exists()
    assert paths.output_dir.joinpath("comparison_rows.parquet").exists()
    assert paths.output_dir.joinpath("entities.parquet").exists() is False
    assert paths.output_dir.joinpath("relationships.parquet").exists() is False


def test_index_task_runner_skips_protocol_when_profiles_are_not_extractable(
    monkeypatch, tmp_path
):
    _patch_parquet(monkeypatch)

    import application.indexing.index_task_runner as task_runner_module

    collection_service = CollectionService(tmp_path / "collections")
    task_service = TaskService(tmp_path / "tasks")
    artifact_registry = ArtifactRegistryService(tmp_path / "collections")
    runner = IndexTaskRunner(collection_service, task_service, artifact_registry)

    collection = collection_service.create_collection("Review Papers")
    paths = collection_service.get_paths(collection["collection_id"])
    collection_service.add_file(
        collection["collection_id"],
        "paper.txt",
        b"This review summarizes recent advances in composite fillers.",
    )

    default_config = tmp_path / "configs" / "default.yaml"
    default_config.parent.mkdir(parents=True, exist_ok=True)
    default_config.write_text("dummy: true\n", encoding="utf-8")

    async def fake_build_index(**kwargs):  # noqa: ANN003
        _write_review_only_outputs(paths.output_dir)
        return [DummyWorkflowOutput()]

    monkeypatch.setattr(task_runner_module, "CONFIG_DIR", default_config.parent)
    monkeypatch.setattr(
        task_runner_module,
        "load_config",
        lambda *args, **kwargs: _build_config(paths.output_dir, paths.input_dir),
    )
    monkeypatch.setattr(task_runner_module, "build_index", fake_build_index)

    task = task_service.create_task(collection["collection_id"], "index")
    result = asyncio.run(runner.run_index_task(task["task_id"], collection["collection_id"]))

    assert result["status"] == "completed"
    assert "未检测到适合 protocol 提取的文档，已跳过 protocol artifacts。" in result["warnings"]
    artifacts = artifact_registry.get(collection["collection_id"])
    assert artifacts["documents_generated"] is True
    assert artifacts["documents_ready"] is True
    assert artifacts["document_profiles_generated"] is True
    assert artifacts["document_profiles_ready"] is True
    assert artifacts["graph_generated"] is True
    assert artifacts["graph_ready"] is True
    assert artifacts["table_cells_generated"] is True
    assert artifacts["table_cells_ready"] is False
    assert artifacts["evidence_cards_generated"] is True
    assert artifacts["evidence_cards_ready"] is False
    assert artifacts["comparison_rows_generated"] is True
    assert artifacts["comparison_rows_ready"] is False
    assert artifacts["protocol_steps_generated"] is False
    assert artifacts["protocol_steps_ready"] is False
    assert paths.output_dir.joinpath("document_profiles.parquet").exists()
