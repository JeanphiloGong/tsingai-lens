from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from domain.core import DocumentProfile
from domain.source import source_documents_from_records
from infra.persistence.memory import (
    MemoryDocumentProfileRepository,
    MemorySourceArtifactRepository,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _load_exporter_module():
    path = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "evaluation"
        / "expert_gold"
        / "export_prediction_bundle.py"
    )
    spec = importlib.util.spec_from_file_location("export_prediction_bundle", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Record:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def to_record(self) -> dict:
        return dict(self.payload)


class _PublishedObjectiveRepository:
    def __init__(self, *, published: bool = True) -> None:
        self.published = published

    async def list_objectives(self, collection_id: str):
        if not self.published:
            return ()
        return (
            SimpleNamespace(
                objective_id="obj-1",
                published_analysis_version=2,
            ),
        )

    async def list_evidence(self, *args, **kwargs):
        if not self.published:
            return (), 0
        records = (
            _Record(
                {
                    "collection_id": "col-test",
                    "objective_id": "obj-1",
                    "analysis_version": 2,
                    "evidence_id": "ev-1",
                    "document_id": "paper-1",
                    "source_kind": "text_window",
                    "source_ref": "block-1",
                    "source_excerpt": "Preheating increased ductility by 14%.",
                    "evidence_role": "direct_result",
                }
            ),
        )
        return records, len(records)

    async def list_findings(self, *args, **kwargs):
        if not self.published:
            return (), 0
        records = (
            _Record(
                {
                    "collection_id": "col-test",
                    "objective_id": "obj-1",
                    "analysis_version": 2,
                    "finding_id": "finding-1",
                    "statement": "Preheating was associated with higher ductility.",
                    "factors": ["preheating"],
                    "outcome": "ductility",
                    "synthesis_status": "insufficient_confirmation",
                    "attribution_scope": "isolated_effect",
                    "certainty": 0.8,
                    "limitations": ["single paper"],
                }
            ),
        )
        return records, len(records)


@pytest.mark.anyio
async def test_export_prediction_bundle_uses_current_published_results(
    tmp_path,
    monkeypatch,
):
    exporter = _load_exporter_module()
    source_repository = MemorySourceArtifactRepository()
    source_document = source_documents_from_records(
        documents=[
            {
                "id": "paper-1",
                "title": "Prediction Paper",
                "text": "Preheating increased ductility by 14%.",
                "metadata": {
                    "doi": "10.1000/test",
                    "source_filename": "paper.pdf",
                },
            }
        ]
    )[0]
    await source_repository.replace_document("col-test", source_document)
    profile_repository = MemoryDocumentProfileRepository()
    await profile_repository.replace(
        DocumentProfile.from_mapping(
            {
                "document_id": "paper-1",
                "collection_id": "col-test",
                "title": "Prediction Paper",
                "source_filename": "paper.pdf",
                "doc_type": "experimental",
                "parsing_warnings": [],
                "confidence": 0.9,
            }
        )
    )
    monkeypatch.setattr(
        exporter,
        "build_database_engine",
        lambda _settings: SimpleNamespace(dispose=AsyncMock()),
    )
    monkeypatch.setattr(exporter, "build_session_factory", lambda _engine: None)
    monkeypatch.setattr(
        exporter,
        "PostgresSourceArtifactRepository",
        lambda _sessions: source_repository,
    )
    monkeypatch.setattr(
        exporter,
        "PostgresDocumentProfileRepository",
        lambda _sessions: profile_repository,
    )
    monkeypatch.setattr(
        exporter,
        "PostgresObjectiveRepository",
        lambda _sessions: _PublishedObjectiveRepository(),
    )
    output = tmp_path / "prediction.json"

    result = await exporter.export_prediction_bundle(
        backend_root=tmp_path,
        collection_id="col-test",
        output_path=output,
    )

    bundle = json.loads(output.read_text(encoding="utf-8"))
    assert result == output
    assert bundle["metadata"]["schema_version"] == "prediction-bundle-v0.4"
    assert bundle["metadata"]["fact_source"] == "published_objectives"
    assert bundle["papers"][0]["paper_id"] == "paper-1"
    assert bundle["objective_evidence"][0]["evidence_id"] == "ev-1"
    assert bundle["objective_findings"][0]["finding_id"] == "finding-1"


def test_prediction_bundle_preserves_exact_evidence_and_uncertainty(tmp_path):
    exporter = _load_exporter_module()
    records = {name: [] for name in exporter.ARTIFACT_NAMES}
    records["objective_evidence"] = [
        {
            "evidence_id": "ev-1",
            "source_excerpt": "Preheating increased ductility by 14%.",
        }
    ]
    records["objective_findings"] = [
        {
            "finding_id": "finding-1",
            "synthesis_status": "insufficient_confirmation",
            "attribution_scope": "isolated_effect",
            "certainty": 0.8,
            "limitations": ["single paper"],
        }
    ]

    bundle = exporter.build_prediction_bundle(
        collection_id="col-test",
        source_output_dir=tmp_path,
        records_by_artifact=records,
        missing_artifacts=[],
    )

    assert bundle["evidence"][0]["source_excerpt"] == (
        "Preheating increased ductility by 14%."
    )
    assert bundle["evidence"][0]["source"] == {
        "artifact": "objective_evidence",
        "row": 1,
    }
    assert bundle["uncertainties"][0]["limitations"] == ["single paper"]


def test_prediction_bundle_projects_source_backed_samples_measurements_and_comparisons(
    tmp_path,
):
    exporter = _load_exporter_module()
    records = {name: [] for name in exporter.ARTIFACT_NAMES}
    records["objective_evidence"] = [
        {
            "evidence_id": "ev-contrast",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-2",
            "source_excerpt": "As-built 95.4% and HIP 98.2%.",
            "source_refs": [
                {"source_kind": "table", "source_ref": "table-2"},
            ],
            "evidence_role": "direct_result",
            "attribution_scope": "isolated_effect",
            "scientific_context": {
                "sample": [{"name": "sample", "value": "as-built"}],
                "material": [{"name": "material", "value": "316L stainless steel"}],
                "process": [{"name": "heat treatment", "value": "HIP"}],
                "test": [{"name": "method", "value": "density measurement"}],
            },
            "comparison": {
                "baseline_label": "as-built",
                "target_label": "HIP",
                "comparable": True,
            },
            "changed_variables": [
                {
                    "name": "heat treatment",
                    "baseline_value": "as-built",
                    "target_value": "HIP",
                    "unit": None,
                }
            ],
            "reported_result": {
                "outcome": "relative density",
                "value": 98.2,
                "baseline_value": 95.4,
                "target_value": 98.2,
                "unit": "%",
                "direction": "increase",
                "result_text": "Relative density increased.",
            },
        }
    ]

    bundle = exporter.build_prediction_bundle(
        collection_id="col-test",
        source_output_dir=tmp_path,
        records_by_artifact=records,
        missing_artifacts=[],
    )

    labels = {row["label_in_paper"] for row in bundle["samples"]}
    assert labels == {"as-built", "HIP"}
    assert {row["metric_name"] for row in bundle["measurement_results"]} == {
        "relative density"
    }
    assert {row["value_payload"] for row in bundle["measurement_results"]} == {
        95.4,
        98.2,
    }
    assert len(bundle["comparisons"]) == 1
    assert bundle["comparisons"][0]["evidence_ids"] == ["ev-contrast"]


def test_prediction_bundle_preserves_scalar_measurement_when_target_value_is_null(
    tmp_path,
):
    exporter = _load_exporter_module()
    records = {name: [] for name in exporter.ARTIFACT_NAMES}
    records["objective_evidence"] = [
        {
            "evidence_id": "ev-row-result",
            "document_id": "paper-1",
            "source_kind": "table",
            "source_ref": "table-results",
            "scientific_context": {
                "sample": [{"name": "sample_number", "value": "2"}],
            },
            "reported_result": {
                "outcome": "elongation",
                "value": 82.0,
                "baseline_value": None,
                "target_value": None,
                "unit": "%",
                "direction": "unknown",
                "result_text": "elongation = 82 %",
            },
        }
    ]

    bundle = exporter.build_prediction_bundle(
        collection_id="col-test",
        source_output_dir=tmp_path,
        records_by_artifact=records,
        missing_artifacts=[],
    )

    assert len(bundle["measurement_results"]) == 1
    assert bundle["measurement_results"][0]["value_payload"] == 82.0
    assert bundle["measurement_results"][0]["value_or_trend"] == 82.0


@pytest.mark.anyio
async def test_export_prediction_bundle_allows_missing_current_artifacts(
    tmp_path,
    monkeypatch,
):
    exporter = _load_exporter_module()
    monkeypatch.setattr(
        exporter,
        "build_database_engine",
        lambda _settings: SimpleNamespace(dispose=AsyncMock()),
    )
    monkeypatch.setattr(exporter, "build_session_factory", lambda _engine: None)
    monkeypatch.setattr(
        exporter,
        "PostgresSourceArtifactRepository",
        lambda _sessions: MemorySourceArtifactRepository(),
    )
    monkeypatch.setattr(
        exporter,
        "PostgresDocumentProfileRepository",
        lambda _sessions: MemoryDocumentProfileRepository(),
    )
    monkeypatch.setattr(
        exporter,
        "PostgresObjectiveRepository",
        lambda _sessions: _PublishedObjectiveRepository(published=False),
    )
    output = tmp_path / "empty.json"

    await exporter.export_prediction_bundle(
        backend_root=tmp_path,
        collection_id="col-empty",
        output_path=output,
    )

    bundle = json.loads(output.read_text(encoding="utf-8"))
    assert bundle["papers"] == []
    assert bundle["metadata"]["artifact_rows"]["documents"] == 0
    assert set(bundle["metadata"]["missing_artifacts"]) == set(
        exporter.ARTIFACT_NAMES
    )
