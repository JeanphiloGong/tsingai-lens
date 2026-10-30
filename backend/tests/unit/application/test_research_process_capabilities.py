from dataclasses import replace

import pytest

from application.chat.capabilities.contracts import CapabilityExecutionContext
from application.chat.capabilities.research_process import (
    InspectResearchProcessCapability,
    InspectResearchProcessToolRequest,
)
from application.chat.capabilities.research_process_start import (
    StartResearchProcessCapability,
    StartResearchProcessToolRequest,
)
from application.pipeline import pipeline_run_service
from controllers.schemas.source.pipeline_run import pipeline_run_response
from domain.chat import ToolResultStatus
from repositories.pipeline_run_repository import (
    ExecutionStats,
    ModelUsage,
    PipelineNodeStatus,
    PipelineRunStatus,
    TokenUsage,
)
from tests.support.postgres import seed_collection

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_start_reuses_active_preparation_with_complete_safe_run_observation(
    postgres_session_factory, document_preparation_runtime,
):
    await seed_collection(postgres_session_factory, "col_process", document_ids=("doc_a",))
    run = await pipeline_run_service.create_run(
        "col_process", "document_preparation", scope_type="document", scope_id="doc_a",
    )
    stats = ExecutionStats(
        duration_ms=1200,
        model_usage=(ModelUsage("profile-model", 2, TokenUsage(100, 20, 120), 1),),
        prompt_versions={"document_profile": "profile.v1"},
    )
    raw_error = "provider failed at /private/provider/config"
    run = replace(
        run,
        status=PipelineRunStatus.RUNNING,
        current_node="document_profile",
        progress_percent=50,
        stats=stats,
        errors=(raw_error,),
        timestamps=replace(run.timestamps, started_at=run.timestamps.created_at),
        nodes=(
            replace(run.nodes[0], status=PipelineNodeStatus.SUCCEEDED),
            replace(run.nodes[1], status=PipelineNodeStatus.RUNNING, stats=stats, errors=(raw_error,)),
        ),
    )
    await pipeline_run_service.PipelineRunRepo.update_run(run)
    result = await StartResearchProcessCapability(
        document_preparation_service=document_preparation_runtime,
    ).execute(
        CapabilityExecutionContext("session-1", "user-1", "col_process", "call-start"),
        StartResearchProcessToolRequest(document_ids=["doc_a"]),
    )

    assert result.status is ToolResultStatus.QUEUED
    assert not document_preparation_runtime._active_workers
    observation, = result.data["runs"]
    assert observation == pipeline_run_response(run)
    assert observation["stats"]["token_usage"] == {
        "input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
    }
    assert observation["stats"]["unreported_request_count"] == 1
    assert isinstance(observation["stats"]["model_usage"], list)
    assert observation["nodes"]["document_profile"]["stats"] == observation["stats"]
    assert observation["started_at"] == run.timestamps.started_at
    assert observation["finished_at"] is None
    assert result.resource_refs[0].resource_id == run.run_id
    assert raw_error not in str(result)
    assert (await pipeline_run_service.PipelineRunRepo.read_run(run.run_id)).errors == (raw_error,)


async def test_inspect_reports_historical_failure_without_exposing_provider_details(
    postgres_session_factory,
):
    await seed_collection(postgres_session_factory, "col_process", document_ids=("doc_a",))
    run = await pipeline_run_service.create_run(
        "col_process", "document_preparation", scope_type="document", scope_id="doc_a",
    )
    raw_error = "provider failed at /private/provider/config"
    await pipeline_run_service.finish_run(
        run.run_id, status="failed", current_node="document_profile", errors=[raw_error],
    )
    result = await InspectResearchProcessCapability().execute(
        CapabilityExecutionContext("session-1", "user-1", "col_process", "call-inspect"),
        InspectResearchProcessToolRequest(),
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    process = result.data["process"]
    assert process["status"] == "attention_required"
    assert process["documents"][0]["run_id"] == run.run_id
    assert process["documents"][0]["stage"] == "document_profile"
    assert process["failures"] == [pipeline_run_service.document_preparation_error_message("document_profile")]
    assert raw_error not in str(result)
    assert (await pipeline_run_service.PipelineRunRepo.read_run(run.run_id)).errors == (raw_error,)
