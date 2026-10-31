"""Discovery queue is durable and progress updates carry their claimed lease."""
from datetime import timedelta
from unittest.mock import AsyncMock
import pytest
from application.core.objectives import objective_discovery_service as discovery
from domain.core import PreparedDocumentInput
from repositories.pipeline_run_repository import PipelineRunRepo
from tests.support.postgres import seed_collection

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return "asyncio"

async def test_discovery_queue_reuses_active_work_without_executing(
    monkeypatch, postgres_session_factory
):
    await seed_collection(
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
