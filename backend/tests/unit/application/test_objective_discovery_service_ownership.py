import asyncio

import pytest

from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from application.core.objectives.objective_discovery_service import (
    ObjectiveDiscoveryService,
)
from application.core.objectives.objective_input_service import (
    ObjectiveInputService,
)
from application.core.objectives.paper_research_map_service import PaperResearchMapService
from application.pipeline import PipelineRunService
from domain.core import ObjectiveFactSet, PreparedDocumentInput
from infra.persistence.memory import MemoryPipelineRunRepository


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_objective_discovery_stages_have_direct_owners() -> None:
    assert "build_collection_paper_maps" in PaperResearchMapService.__dict__
    assert "discover_candidate_facts" in ObjectiveCandidateService.__dict__

    assert "start_objective_discovery" in ObjectiveDiscoveryService.__dict__
    assert "discover_and_replace_objective_candidates" in ObjectiveDiscoveryService.__dict__


def _service(pipeline_run_service: PipelineRunService) -> ObjectiveDiscoveryService:
    input_service = ObjectiveInputService(
        collection_service=object(),
        source_artifact_repository=object(),
        paper_map_repository=object(),
        document_profile_service=object(),
        paper_map_service=object(),
    )
    return ObjectiveDiscoveryService(
        objective_input_service=input_service,
        objective_candidate_service=ObjectiveCandidateService(),
        objective_repository=object(),
        pipeline_run_service=pipeline_run_service,
    )


async def test_objective_discovery_reuses_one_active_run_and_executes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline_run_service = PipelineRunService(MemoryPipelineRunRepository())
    service = _service(pipeline_run_service)
    calls = 0

    async def resolve_inputs(collection_id, document_ids):
        assert collection_id == "col_a"
        return tuple(
            PreparedDocumentInput(document_id, f"fingerprint-{document_id}")
            for document_id in document_ids
        )

    async def discover(collection_id, document_ids, progress_callback=None):
        nonlocal calls
        calls += 1
        assert collection_id == "col_a"
        progress_callback(
            {
                "phase": "objective_candidates",
                "current": 2,
                "total": 2,
                "unit": "documents",
                "message": "Forming candidate research questions.",
            }
        )
        return ObjectiveFactSet(research_objectives_ready=True)

    monkeypatch.setattr(
        service.objective_input_service,
        "resolve_prepared_document_inputs",
        resolve_inputs,
    )
    monkeypatch.setattr(service, "discover_and_replace_objective_candidates", discover)

    first = await service.start_objective_discovery("col_a", ("doc_a", "doc_b"))
    duplicate = await service.start_objective_discovery(
        "col_a", ("doc_a", "doc_b")
    )

    assert first["run_id"] == duplicate["run_id"]
    assert first["status"] == "queued"
    await asyncio.gather(*tuple(service._workers))

    completed = await pipeline_run_service.get_run(first["run_id"])
    assert calls == 1
    assert completed["status"] == "completed"
    assert completed["current_node"] == "objectives_ready"


async def test_objective_discovery_records_failure_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline_run_service = PipelineRunService(MemoryPipelineRunRepository())
    service = _service(pipeline_run_service)

    async def resolve_inputs(_collection_id, document_ids):
        return tuple(
            PreparedDocumentInput(document_id, f"fingerprint-{document_id}")
            for document_id in document_ids
        )

    async def fail_discovery(*_args, **_kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(
        service.objective_input_service,
        "resolve_prepared_document_inputs",
        resolve_inputs,
    )
    monkeypatch.setattr(service, "discover_and_replace_objective_candidates", fail_discovery)

    first = await service.start_objective_discovery("col_a", ("doc_a",))
    await asyncio.gather(*tuple(service._workers), return_exceptions=True)
    failed = await pipeline_run_service.get_run(first["run_id"])

    assert failed["status"] == "failed"
    assert failed["errors"] == ["model unavailable"]

    retry = await service.start_objective_discovery("col_a", ("doc_a",))
    assert retry["run_id"] != first["run_id"]
    await asyncio.gather(*tuple(service._workers), return_exceptions=True)


async def test_objective_discovery_progress_does_not_move_backwards() -> None:
    pipeline_run_service = PipelineRunService(MemoryPipelineRunRepository())
    service = _service(pipeline_run_service)
    run = await pipeline_run_service.create_run(
        "col_a",
        "objective_discovery",
        scope_type="collection",
        scope_id="col_a",
        input_fingerprint="scope-a",
    )
    pending_updates = []
    report = service._build_discovery_progress_callback(
        run["run_id"],
        pending_updates,
    )

    report(
        {
            "phase": "paper_research_map_started",
            "current": 1,
            "total": 1,
            "unit": "documents",
        }
    )
    await asyncio.wrap_future(pending_updates[-1])
    mapped = await pipeline_run_service.get_run(run["run_id"])

    report(
        {
            "phase": "objective_discovery_started",
            "current": 0,
            "total": 4,
            "unit": "relationship_groups",
        }
    )
    await asyncio.wrap_future(pending_updates[-1])
    aggregating = await pipeline_run_service.get_run(run["run_id"])

    assert aggregating["progress_percent"] >= mapped["progress_percent"]


async def test_objective_discovery_restart_recovery_allows_retry() -> None:
    pipeline_run_service = PipelineRunService(MemoryPipelineRunRepository())
    service = _service(pipeline_run_service)
    active, _created = await pipeline_run_service.get_or_create_collection_run(
        collection_id="col_a",
        pipeline_name="objective_discovery",
        input_fingerprint="scope-a",
        context={"document_ids": ["doc_a"]},
    )
    await pipeline_run_service.update_run(active["run_id"], status="running")

    recovered = await service.recover_interrupted_discoveries()
    interrupted = await pipeline_run_service.get_run(active["run_id"])
    retry, retry_created = await pipeline_run_service.get_or_create_collection_run(
        collection_id="col_a",
        pipeline_name="objective_discovery",
        input_fingerprint="scope-a",
        context={"document_ids": ["doc_a"]},
    )

    assert recovered == 1
    assert interrupted["status"] == "failed"
    assert interrupted["current_node"] == "interrupted"
    assert retry_created is True
    assert retry["run_id"] != active["run_id"]
