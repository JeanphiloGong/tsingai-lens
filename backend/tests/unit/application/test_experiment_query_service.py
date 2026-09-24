from __future__ import annotations

from datetime import datetime, timezone

import pytest

from application.core.objectives.analysis.experiment_query_service import (
    ExperimentQueryService,
)
from application.repositories.paper_experiment_repository import (
    StoredPaperExperimentRevision,
)
from domain.core.finding import Finding
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.paper_experiment import PaperExperimentRevision


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _revision() -> PaperExperimentRevision:
    return PaperExperimentRevision.from_mapping(
        {
            "experiment_id": "exp-1",
            "document_id": "doc-1",
            "experiment_version": 1,
            "source_fingerprint": "prep-1",
            "label": "Preheat series",
            "scope_description": "A and B",
            "design_type": "parallel",
            "identity_status": "identified",
            "binding_status": "bound",
            "variants": [
                {"variant_key": "A", "variant_label": "NP"},
                {"variant_key": "B", "variant_label": "P150"},
            ],
            "test_conditions": [{"test_key": "t1", "test_type": "tensile"}],
            "measurements": [
                {
                    "measurement_key": "a-elongation",
                    "outcome": "elongation",
                    "variant_key": "A",
                    "test_key": "t1",
                    "value": 72,
                    "unit": "%",
                },
                {
                    "measurement_key": "b-elongation",
                    "outcome": "elongation",
                    "variant_key": "B",
                    "test_key": "t1",
                    "value": 82,
                    "unit": "%",
                },
            ],
        }
    )


class _Selections:
    async def list_selections(self, collection_id, objective_id, analysis_version):
        return (
            ObjectiveExperimentSelection.from_mapping(
                {
                    "selection_id": "selection-1",
                    "objective_id": objective_id,
                    "analysis_version": analysis_version,
                    "experiment_id": "exp-1",
                    "experiment_version": 1,
                    "outcome": "elongation",
                    "measurement_keys": ["a-elongation", "b-elongation"],
                }
            ),
        )


class _Groups:
    async def list_groups(self, collection_id, objective_id, analysis_version):
        return ()


class _Findings:
    async def list_findings(self, collection_id, objective_id, analysis_version):
        return ()


class _Experiments:
    async def read_revision(self, experiment_id, experiment_version):
        revision = _revision()
        return StoredPaperExperimentRevision(
            revision_id=10,
            revision=revision,
            created_at=datetime.now(timezone.utc),
        )


@pytest.mark.parametrize("export_kind", ["json", "csv"])
async def test_query_service_exports_fixed_revision_data(export_kind: str) -> None:
    service = ExperimentQueryService(_Experiments(), _Selections(), _Groups(), _Findings())

    if export_kind == "json":
        payload = await service.export_json("collection-1", "objective-1", 1)
        assert payload["experiments"][0]["experiment_version"] == 1
        assert payload["selections"][0]["measurement_keys"] == [
            "a-elongation",
            "b-elongation",
        ]
    else:
        payload = await service.export_csv("collection-1", "objective-1", 1)
        assert "measurement_key" in payload.splitlines()[0]
        assert "a-elongation" in payload
        assert "P150" in payload
