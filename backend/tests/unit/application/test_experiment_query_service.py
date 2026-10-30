from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.core.objectives.analysis import experiment_query_service
from domain.core.finding import Finding
from domain.core.objective_experiment_selection import ObjectiveExperimentSelection
from domain.core.paper_experiment import (
    ExperimentalVariant,
    ExperimentMeasurementResult,
    ExperimentTestCondition,
    PaperExperimentRevision,
)
from domain.core.scientific_fact import (
    ScientificAttribute,
)
from exceptions import ResourceConflictException, ResourceNotFoundException
from repositories.paper_experiment_repository import (
    StoredPaperExperimentRevision,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _revision() -> PaperExperimentRevision:
    return PaperExperimentRevision(
        experiment_id="exp-1",
        document_id="doc-1",
        experiment_version=int(1),
        source_fingerprint="prep-1",
        label="Preheat series",
        scope_description="A and B",
        design_type="parallel",
        identity_status="identified",
        binding_status="bound",
        variants=(
            ExperimentalVariant(
                variant_key="A",
                variant_label="NP",
                subject_attributes=(
                    ScientificAttribute(name="material", value="316L"),
                ),
                intervention_attributes=(
                    ScientificAttribute(name="preheat", value="0 C"),
                ),
                state=(ScientificAttribute(name="orientation", value="vertical"),),
                population_scope=dict({"kind": "group", "n": 5}),
            ),
            ExperimentalVariant(
                variant_key="B",
                variant_label="P150",
                subject_attributes=(
                    ScientificAttribute(name="material", value="316L"),
                ),
                intervention_attributes=(
                    ScientificAttribute(name="preheat", value="150 C"),
                ),
                state=(ScientificAttribute(name="orientation", value="vertical"),),
                population_scope=dict({"kind": "group", "n": 5}),
            ),
        ),
        test_conditions=(
            ExperimentTestCondition(
                test_key="t1",
                test_type="tensile",
                parameters=(ScientificAttribute(name="strain_rate", value="0.001 /s"),),
                population_scope=dict({"kind": "group", "n": 5}),
                method="uniaxial tensile",
                standard="ASTM E8",
                outcome_scope=("elongation",),
            ),
        ),
        measurements=(
            ExperimentMeasurementResult(
                measurement_key="a-elongation",
                outcome="elongation",
                variant_key="A",
                test_key="t1",
                value=72,
                unit="%",
            ),
            ExperimentMeasurementResult(
                measurement_key="b-elongation",
                outcome="elongation",
                variant_key="B",
                test_key="t1",
                value=82,
                unit="%",
            ),
        ),
    )


class _Selections:
    async def list_selections(self, db, collection_id, objective_id, analysis_version):
        return (
            ObjectiveExperimentSelection(
                selection_id="selection-1",
                objective_id=objective_id,
                analysis_version=analysis_version,
                experiment_id="exp-1",
                experiment_version=1,
                outcome="elongation",
                measurement_keys=("a-elongation", "b-elongation"),
            ),
        )


class _Groups:
    async def list_groups(self, db, collection_id, objective_id, analysis_version):
        return ()


class _Findings:
    async def list_findings(self, db, collection_id, objective_id, analysis_version):
        return ()


class _Experiments:
    async def read_revision(self, db, experiment_id, experiment_version):
        revision = _revision()
        return StoredPaperExperimentRevision(
            revision_id=10,
            revision=revision,
            created_at=datetime.now(timezone.utc),
        )


class _ObjectiveAnalyses:
    def __init__(self, analysis=None):
        self.analysis = analysis

    async def read_analysis(self, collection_id, objective_id, analysis_version):
        return self.analysis


@pytest.mark.parametrize("export_kind", ["json", "csv"])
async def test_query_service_exports_fixed_revision_data(export_kind: str) -> None:
    experiment_query_service.PaperExperimentRepo = _Experiments()
    experiment_query_service.ObjectiveExperimentSelectionRepo = _Selections()
    experiment_query_service.ComparisonGroupRepo = _Groups()
    experiment_query_service.ExperimentFindingRepo = _Findings()
    experiment_query_service.ObjectiveRepo = _ObjectiveAnalyses(
        SimpleNamespace(status="succeeded")
    )
    service = experiment_query_service

    if export_kind == "json":
        payload = await service.export_json(
            "collection-1", "objective-1", 1, user_id="user-1"
        )
        assert payload["experiments"][0]["experiment_version"] == 1
        assert payload["selections"][0]["measurement_keys"] == [
            "a-elongation",
            "b-elongation",
        ]
    else:
        payload = await service.export_csv(
            "collection-1", "objective-1", 1, user_id="user-1"
        )
        header = payload.splitlines()[0]
        assert "measurement_key" in header
        assert "variant_intervention_attributes" in header
        assert "test_parameters" in header
        assert "a-elongation" in payload
        assert "P150" in payload
        assert "preheat" in payload
        assert "strain_rate" in payload
        assert "ASTM E8" in payload


async def test_query_service_rejects_unknown_analysis_snapshot() -> None:
    experiment_query_service.PaperExperimentRepo = _Experiments()
    experiment_query_service.ObjectiveExperimentSelectionRepo = _Selections()
    experiment_query_service.ComparisonGroupRepo = _Groups()
    experiment_query_service.ExperimentFindingRepo = _Findings()
    experiment_query_service.ObjectiveRepo = _ObjectiveAnalyses()
    service = experiment_query_service

    with pytest.raises(ResourceNotFoundException, match="Analysis snapshot not found"):
        await service.export_json("collection-1", "objective-1", 99, user_id="user-1")


async def test_query_service_rejects_incomplete_analysis_snapshot() -> None:
    experiment_query_service.PaperExperimentRepo = _Experiments()
    experiment_query_service.ObjectiveExperimentSelectionRepo = _Selections()
    experiment_query_service.ComparisonGroupRepo = _Groups()
    experiment_query_service.ExperimentFindingRepo = _Findings()
    experiment_query_service.ObjectiveRepo = _ObjectiveAnalyses(
        type("Analysis", (), {"status": "running"})()
    )
    service = experiment_query_service

    with pytest.raises(
        ResourceConflictException, match="Analysis snapshot is not completed"
    ):
        await service.export_json("collection-1", "objective-1", 1, user_id="user-1")


@pytest.fixture(autouse=True)
def export_owner(monkeypatch):
    monkeypatch.setattr(
        experiment_query_service,
        "collection_service",
        SimpleNamespace(
            get_collection_for_user=AsyncMock(return_value={"owner_user_id": "user-1"})
        ),
    )
