from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.core.objectives.analysis import analysis_record_source
from domain.core import PreparedDocumentInput
from exceptions import ResourceConflictException, ResourceNotFoundException
from repositories.objective_repository import ObjectiveAnalysis

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def analysis():
    return ObjectiveAnalysis(
        collection_id="col-1",
        objective_id="obj-1",
        analysis_version=2,
        document_inputs=(PreparedDocumentInput("doc-1", "source-1"),),
        pipeline_version="test.v1",
        model_name=None,
        prompt_versions={},
        total_document_count=1,
    ).start().succeed()


@pytest.mark.parametrize(
    ("origin", "source", "expected"),
    [
        ("system_generated", "experiment_graph", True),
        ("system_generated", "legacy_snapshot", False),
        ("human_authored", "authored_snapshot", False),
        ("agent_authored", "experiment_graph", False),
    ],
)
async def test_completed_analysis_selects_its_saved_scientific_record_source(
    monkeypatch, analysis, origin, source, expected,
):
    stored = replace(
        analysis,
        origin=origin,
        scientific_record_source=source,
        source_analysis_version=1 if origin != "system_generated" else None,
        created_by_user_id="researcher" if origin != "system_generated" else None,
        created_by_tool_call_id="call-1" if origin == "agent_authored" else None,
    )
    repository = SimpleNamespace(read_analysis=AsyncMock(return_value=stored))
    monkeypatch.setattr(analysis_record_source, "ObjectiveRepo", repository)

    assert await analysis_record_source.should_read_experiment_projection(
        collection_id="col-1", objective_id="obj-1", analysis_version=2,
    ) is expected
    repository.read_analysis.assert_awaited_once_with("col-1", "obj-1", 2)


@pytest.mark.parametrize("status", [None, "queued", "running", "failed"])
async def test_missing_or_unfinished_analysis_cannot_select_any_scientific_records(
    monkeypatch, analysis, status,
):
    stored = (
        replace(
            analysis, status=status,
            error_message="technical failure" if status == "failed" else None,
        )
        if status else None
    )
    repository = SimpleNamespace(read_analysis=AsyncMock(return_value=stored))
    monkeypatch.setattr(analysis_record_source, "ObjectiveRepo", repository)
    exception = ResourceConflictException if status else ResourceNotFoundException
    with pytest.raises(exception) as caught:
        await analysis_record_source.should_read_experiment_projection(
            collection_id="col-1", objective_id="obj-1", analysis_version=2,
        )
    assert caught.value.data["code"] == (
        "analysis_snapshot_not_completed" if status else "analysis_snapshot_not_found"
    )
