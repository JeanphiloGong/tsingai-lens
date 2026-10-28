from __future__ import annotations

from infra.persistence import database
from tests.support.postgres import seed_collection

from infra.source.artifact_bundle import source_documents_from_records

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from domain.core import DocumentProfile
from domain.core.finding import Finding, FindingPaperContribution
from domain.core.research_objective import ObjectiveEvidence
from domain.core.scientific_fact import ScientificContext
from repositories.document_profile_repository import DocumentProfileRepository
from repositories.source_artifact_repository import SourceArtifactRepository


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
            ObjectiveEvidence(
                collection_id="col-test",
                objective_id="obj-1",
                analysis_version=2,
                evidence_id="ev-1",
                document_id="paper-1",
                source_kind="text_window",
                source_ref="block-1",
                source_excerpt="Preheating increased ductility by 14%.",
                page_numbers=(),
                related_source_refs=(),
                evidence_role="direct_result",
                selection_status="candidate",
                selection_reason=None,
                changed_variables=(),
                comparison=None,
                reported_result=None,
                attribution_scope="descriptive_only",
                scientific_context=ScientificContext(),
                resolution_status="unknown",
                failure_reason=None,
                confidence=0.0,
            ),
        )
        return records, len(records)

    async def list_findings(self, *args, **kwargs):
        if not self.published:
            return (), 0
        records = (
            Finding(
                collection_id="col-test",
                objective_id="obj-1",
                analysis_version=2,
                finding_id="finding-1",
                statement="Preheating was associated with higher ductility.",
                factors=("preheating",),
                outcome="ductility",
                direction="unknown",
                assertion_strength="descriptive",
                attribution_scope="isolated_effect",
                synthesis_status="insufficient_confirmation",
                certainty=0.8,
                display_rank=0,
                mechanisms=(),
                scientific_context=ScientificContext(),
                limitations=("single paper",),
                paper_contributions=(
                    FindingPaperContribution(
                        document_id="paper-1",
                        analysis_status="analyzed",
                        supporting_evidence_ids=("ev-1",),
                    ),
                ),
            ),
        )
        return records, len(records)


@pytest.mark.anyio
async def test_export_prediction_bundle_uses_current_published_results(tmp_path, monkeypatch, *, postgres_session_factory):
    exporter = _load_exporter_module()
    source_repository = SourceArtifactRepository()
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
    await seed_collection(database.AsyncSessionLocal, 'col-test', document_ids=(source_document.document_id,))
    await source_repository.replace_document("col-test", source_document)
    profile_repository = DocumentProfileRepository()
    await profile_repository.replace(
        "col-test",
        DocumentProfile(
            document_id="paper-1",
            title="Prediction Paper",
            doc_type="experimental",
            profile_warnings=(),
            confidence=0.9,
        )
    )
    monkeypatch.setattr(
        exporter,
        "build_database_engine",
        lambda _settings: SimpleNamespace(dispose=AsyncMock()),
    )
    monkeypatch.setattr(exporter.AsyncSessionLocal, "configure", lambda **_kwargs: None)
    monkeypatch.setattr(
        exporter,
        "SourceArtifactRepository",
        lambda: source_repository,
    )
    monkeypatch.setattr(
        exporter,
        "DocumentProfileRepository",
        lambda: profile_repository,
    )
    monkeypatch.setattr(
        exporter,
        "ObjectiveRepository",
        lambda: _PublishedObjectiveRepository(),
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
async def test_export_prediction_bundle_allows_missing_current_artifacts(tmp_path, monkeypatch, *, postgres_session_factory):
    exporter = _load_exporter_module()
    monkeypatch.setattr(
        exporter,
        "build_database_engine",
        lambda _settings: SimpleNamespace(dispose=AsyncMock()),
    )
    monkeypatch.setattr(exporter.AsyncSessionLocal, "configure", lambda **_kwargs: None)
    monkeypatch.setattr(
        exporter,
        "SourceArtifactRepository",
        lambda: SourceArtifactRepository(),
    )
    monkeypatch.setattr(
        exporter,
        "DocumentProfileRepository",
        lambda: DocumentProfileRepository(),
    )
    monkeypatch.setattr(
        exporter,
        "ObjectiveRepository",
        lambda: _PublishedObjectiveRepository(published=False),
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
