"""Discovery queue is durable and progress updates carry their claimed lease."""
from datetime import timedelta
from unittest.mock import AsyncMock
import pytest
from research.discovery.application import discovery_service as discovery
from domain.core import PreparedDocumentInput
from repositories.pipeline_run_repository import PipelineRunRepo
from tests.support.postgres import seed_workspace

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return "asyncio"

async def test_discovery_queue_reuses_active_work_without_executing(
    monkeypatch, postgres_session_factory
):
    await seed_workspace(
        postgres_session_factory, "discovery-papers", document_ids=("a", "b")
    )
    inputs = (
        PreparedDocumentInput("a", "prepared-a"),
        PreparedDocumentInput("b", "prepared-b"),
    )
    monkeypatch.setattr(
        discovery.objective_input_service,
        "resolve_prepared_document_inputs",
        AsyncMock(return_value=inputs),
    )
    execute = AsyncMock()
    monkeypatch.setattr(discovery, "execute_objective_discovery_job", execute)
    first = await discovery.start_objective_discovery(
        "discovery-papers", ("a", "b"), user_id="user-1"
    )
    repeated = await discovery.start_objective_discovery(
        "discovery-papers", ("a", "b"), user_id="user-1"
    )
    assert first.run_id == repeated.run_id
    assert first.status == "queued"
    assert first.context["document_inputs"] == [
        {"document_id": "a", "preparation_fingerprint": "prepared-a"},
        {"document_id": "b", "preparation_fingerprint": "prepared-b"},
    ]
    execute.assert_not_awaited()
    job = await PipelineRunRepo.claim_next_objective_discovery_job(
        worker_id="worker", lease_duration=timedelta(seconds=60)
    )
    assert job.run.run_id == first.run_id


@pytest.mark.parametrize("outcome", ["partial_coverage", "candidate_failure", "stale_input"])
async def test_discovery_job_publishes_only_current_results(
    monkeypatch, postgres_session_factory, outcome
):
    from dataclasses import replace
    from unittest.mock import Mock

    from document.domain.profile import DocumentProfile
    from document.repositories.profile_repository import ProfileRepo
    from research.discovery.domain.paper_map import (
        PaperResearchMap,
        PaperSourceUnitCoverage,
        PaperSourceUnitCoverageStatus,
    )

    workspace_id = "alloy-papers"
    await seed_workspace(postgres_session_factory, workspace_id, document_ids=("paper",))
    profile = DocumentProfile(
        document_id="paper", description="Alloy porosity", doc_type="experimental",
        source_fingerprint="source-a", profile_fingerprint="prepared-a",
        profile_version="document_profile.v2", generated_at="2026-01-01T00:00:00Z",
    )
    await ProfileRepo.replace(workspace_id, profile)
    await discovery.workspace_service.update_document_preparation(
        workspace_id, "paper", status="ready"
    )
    run = await discovery.start_objective_discovery(workspace_id, ("paper",), user_id="user-1")
    job = await PipelineRunRepo.claim_next_objective_discovery_job(
        worker_id="worker", lease_duration=timedelta(seconds=60)
    )
    assert job.run.run_id == run.run_id
    paper_map = PaperResearchMap(
        document_id="paper", doc_role="experimental", studies=(), evidence_density="low",
        confidence=0.0, warnings=(), source_unit_coverage=(
            PaperSourceUnitCoverage("unit", "window", "table", "t1",
                                    PaperSourceUnitCoverageStatus.EXTRACTION_FAILED, "table unreadable"),
        ),
    )
    load_sources = AsyncMock(return_value={})
    monkeypatch.setattr(discovery.objective_input_service, "load_source_inputs", load_sources)
    monkeypatch.setattr(discovery.objective_input_service, "load_or_build_paper_maps",
                        AsyncMock(return_value=(paper_map,)))
    if outcome == "stale_input":
        await ProfileRepo.replace(workspace_id, replace(profile, profile_fingerprint="prepared-b"))
    if outcome == "candidate_failure":
        monkeypatch.setattr(discovery.candidate_formation, "discover_candidate_facts",
                            Mock(side_effect=ValueError("candidate formation failed")))
    result = await discovery.execute_objective_discovery_job(job, client=Mock())
    if outcome == "partial_coverage":
        assert result.status == "completed"
        assert result.progress_detail["incomplete_coverage_document_ids"] == ["paper"]
    else:
        assert result.status == "failed"
        if outcome == "stale_input":
            load_sources.assert_not_awaited()
            assert "discovery document input changed" in result.errors
        else:
            assert "candidate formation failed" in result.errors
