"""Exports preserve fixed sources and records beyond repository page caps."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.unit.scripts.test_export_prediction_bundle import (
    _PublishedObjectiveRepository, _load_exporter_module,
)
from tests.unit.scripts.test_export_extraction_trace import _load_trace_module


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("load", [_load_exporter_module, _load_trace_module])
@pytest.mark.parametrize("experiment_backed", [False, True])
async def test_exports_include_complete_fixed_results(load, experiment_backed, monkeypatch):
    monkeypatch.setenv("LENS_DATABASE_URL", "postgresql+psycopg://fixture@localhost/lens_test")
    module = load()
    seed = _PublishedObjectiveRepository()
    (evidence,), _ = await seed.list_evidence()
    (finding,), _ = await seed.list_findings()
    evidence = tuple(replace(evidence, evidence_id=f"ev-{i}") for i in range(501))
    findings = tuple(replace(finding, finding_id=f"finding-{i}") for i in range(201))
    calls = []

    class Repository:
        list_objectives = seed.list_objectives

        async def read_analysis(self, *args):
            return SimpleNamespace(
                origin="system_generated" if experiment_backed else "human_authored",
                scientific_record_source="experiment_graph" if experiment_backed else "authored_snapshot",
            )

        async def list_evidence(self, *args, offset, limit):
            assert not experiment_backed
            calls.append(("evidence", offset))
            return evidence[offset:offset + min(limit, 500)], len(evidence)

        async def list_findings(self, *args, offset, limit):
            assert not experiment_backed
            calls.append(("findings", offset))
            return findings[offset:offset + min(limit, 200)], len(findings)

    monkeypatch.setattr(module, "ObjectiveRepository", Repository)
    monkeypatch.setattr(module, "build_database_engine", lambda _: SimpleNamespace(dispose=AsyncMock()))
    monkeypatch.setattr(module.AsyncSessionLocal, "configure", lambda **_: None)
    monkeypatch.setattr(module, "SourceArtifactRepository", lambda: SimpleNamespace(read_collection_documents=AsyncMock(return_value=())))
    monkeypatch.setattr(module, "DocumentProfileRepository", lambda: SimpleNamespace(list_collection=AsyncMock(return_value=())))
    if hasattr(module, "PaperMapRepository"):
        monkeypatch.setattr(module, "PaperMapRepository", lambda: SimpleNamespace(list_collection=AsyncMock(return_value=())))
    projection = AsyncMock(return_value=(findings, evidence, ()))
    monkeypatch.setattr(module.experiment_projection, "read_analysis_records", projection)

    loaded = await module._load_artifacts("col-test")
    records = loaded[0] if isinstance(loaded, tuple) else {name: frame.to_dict("records") for name, frame in loaded.items()}
    assert len(records["objective_evidence"]) == 501
    assert records["objective_evidence"][-1]["evidence_id"] == "ev-500"
    assert len(records["objective_findings"]) == 201
    assert records["objective_findings"][-1]["finding_id"] == "finding-200"
    if experiment_backed:
        projection.assert_awaited_once_with("col-test", "obj-1", 2)
        assert calls == []
    else:
        assert ("evidence", 500) in calls
        assert ("findings", 200) in calls
        projection.assert_not_awaited()
