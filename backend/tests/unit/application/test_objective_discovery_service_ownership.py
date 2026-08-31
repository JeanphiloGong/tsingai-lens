import asyncio

import pytest

from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from application.core.objectives.paper_research_map_service import PaperResearchMapService
from application.core.objectives.research_objective_service import (
    ResearchObjectiveService,
)
from application.source.task_service import TaskService
from domain.core import ObjectiveFactSet, PreparedDocumentInput
from infra.persistence.memory import MemoryTaskRepository


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_objective_discovery_stages_have_direct_owners() -> None:
    assert "build_collection_paper_maps" in PaperResearchMapService.__dict__
    assert "discover_candidate_facts" in ObjectiveCandidateService.__dict__

    assert "_build_objective_candidate_inputs" not in ResearchObjectiveService.__dict__
    assert "_build_paper_research_map_payload" not in ResearchObjectiveService.__dict__
    assert "_build_objective_discovery_skim" not in ResearchObjectiveService.__dict__


def _service(task_service: TaskService) -> ResearchObjectiveService:
    return ResearchObjectiveService(
        collection_service=object(),
        source_artifact_repository=object(),
        paper_map_repository=object(),
        objective_repository=object(),
        document_profile_service=object(),
        finding_synthesis_service=object(),
        objective_candidate_service=object(),
        paper_map_service=object(),
        task_service=task_service,
    )


async def test_objective_discovery_reuses_one_active_task_and_runs_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_service = TaskService(MemoryTaskRepository())
    service = _service(task_service)
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

    monkeypatch.setattr(service, "resolve_prepared_document_inputs", resolve_inputs)
    monkeypatch.setattr(
        service,
        "discover_and_replace_objective_candidates",
        discover,
    )

    first = await service.start_objective_discovery("col_a", ("doc_a", "doc_b"))
    duplicate = await service.start_objective_discovery(
        "col_a", ("doc_a", "doc_b")
    )

    assert first["task_id"] == duplicate["task_id"]
    assert first["status"] == "queued"
    await asyncio.gather(*tuple(service._discovery_tasks))

    completed = await task_service.get_task(first["task_id"])
    assert calls == 1
    assert completed["status"] == "completed"
    assert completed["current_stage"] == "objectives_ready"


async def test_objective_discovery_records_failure_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_service = TaskService(MemoryTaskRepository())
    service = _service(task_service)

    async def resolve_inputs(_collection_id, document_ids):
        return tuple(
            PreparedDocumentInput(document_id, f"fingerprint-{document_id}")
            for document_id in document_ids
        )

    async def fail_discovery(*_args, **_kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(service, "resolve_prepared_document_inputs", resolve_inputs)
    monkeypatch.setattr(
        service,
        "discover_and_replace_objective_candidates",
        fail_discovery,
    )

    first = await service.start_objective_discovery("col_a", ("doc_a",))
    await asyncio.gather(*tuple(service._discovery_tasks), return_exceptions=True)
    failed = await task_service.get_task(first["task_id"])

    assert failed["status"] == "failed"
    assert failed["errors"] == ["model unavailable"]

    retry = await service.start_objective_discovery("col_a", ("doc_a",))
    assert retry["task_id"] != first["task_id"]
    await asyncio.gather(*tuple(service._discovery_tasks), return_exceptions=True)


async def test_objective_discovery_progress_does_not_move_backwards() -> None:
    task_service = TaskService(MemoryTaskRepository())
    service = _service(task_service)
    task = await task_service.create_task(
        "col_a",
        task_type="objective_discovery",
        input_fingerprint="scope-a",
    )
    pending_updates = []
    report = service._build_discovery_progress_callback(
        task["task_id"],
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
    mapped = await task_service.get_task(task["task_id"])

    report(
        {
            "phase": "objective_discovery_started",
            "current": 0,
            "total": 4,
            "unit": "relationship_groups",
        }
    )
    await asyncio.wrap_future(pending_updates[-1])
    aggregating = await task_service.get_task(task["task_id"])

    assert aggregating["progress_percent"] >= mapped["progress_percent"]


async def test_objective_discovery_restart_recovery_allows_retry() -> None:
    task_service = TaskService(MemoryTaskRepository())
    service = _service(task_service)
    active, _created = await task_service.get_or_create_collection_task(
        collection_id="col_a",
        task_type="objective_discovery",
        input_fingerprint="scope-a",
        details={"document_ids": ["doc_a"]},
    )
    await task_service.update_task(active["task_id"], status="running")

    recovered = await service.recover_interrupted_discoveries()
    interrupted = await task_service.get_task(active["task_id"])
    retry, retry_created = await task_service.get_or_create_collection_task(
        collection_id="col_a",
        task_type="objective_discovery",
        input_fingerprint="scope-a",
        details={"document_ids": ["doc_a"]},
    )

    assert recovered == 1
    assert interrupted["status"] == "failed"
    assert interrupted["current_stage"] == "interrupted"
    assert retry_created is True
    assert retry["task_id"] != active["task_id"]
