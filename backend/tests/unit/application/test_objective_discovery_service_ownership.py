import asyncio
from types import ModuleType

import pytest
from application.core.objectives import (
    objective_candidate_service,
    objective_discovery_service,
    objective_input_service,
    paper_research_map_service,
)
from application.pipeline import pipeline_run_service
from domain.core import ObjectiveFactSet, PreparedDocumentInput
from repositories.pipeline_run_repository import PipelineRunRepository

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
async def research_collection(postgres_session_factory, anyio_backend):
    from tests.support.postgres import seed_collection

    await seed_collection(
        postgres_session_factory, "col_a", document_ids=("doc_a", "doc_b")
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_objective_discovery_stages_have_direct_owners() -> None:
    assert "build_collection_paper_maps" in paper_research_map_service.__dict__
    assert "discover_candidate_facts" in objective_candidate_service.__dict__

    assert "start_objective_discovery" in objective_discovery_service.ObjectiveDiscoveryService.__dict__
    assert (
        "discover_and_replace_objective_candidates"
        in objective_discovery_service.ObjectiveDiscoveryService.__dict__
    )


def _service(pipeline_run_service: ModuleType) -> objective_discovery_service.ObjectiveDiscoveryService:
    objective_input_service.collection_service = object()
    objective_input_service.SourceArtifactRepo = object()
    objective_input_service.PaperMapRepo = object()
    objective_input_service.document_profile_service = object()
    objective_input_service.paper_research_map_service = object()
    input_service = objective_input_service
    objective_discovery_service.objective_input_service = input_service
    objective_discovery_service.objective_candidate_service = (
        objective_candidate_service
    )
    objective_discovery_service.ObjectiveRepo = object()
    objective_discovery_service.pipeline_run_service = pipeline_run_service
    return objective_discovery_service.ObjectiveDiscoveryService()


async def _wait_for_run(pipeline_run_service: ModuleType, run_id: str) -> None:
    for _ in range(100):
        run = await pipeline_run_service.get_run(run_id, user_id="user-1")
        if run["status"] in {"completed", "failed", "partial_success"}:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"run did not finish: {run_id}")


async def test_discovery_shutdown_only_cancels_its_own_tasks(
    monkeypatch, *, postgres_session_factory
) -> None:
    from tests.support.postgres import seed_collection

    await seed_collection(postgres_session_factory, "col_b", document_ids=("doc_c",))
    first = objective_discovery_service.ObjectiveDiscoveryService()
    second = objective_discovery_service.ObjectiveDiscoveryService()
    first_started, second_started = asyncio.Event(), asyncio.Event()
    release = asyncio.Event()

    async def resolve_inputs(collection_id, document_ids):
        return tuple(PreparedDocumentInput(value, value) for value in document_ids)

    async def first_run(*args):
        first_started.set()
        await release.wait()
        return {}

    async def second_run(*args):
        second_started.set()
        await release.wait()
        return {}

    monkeypatch.setattr(objective_input_service, "resolve_prepared_document_inputs", resolve_inputs)
    monkeypatch.setattr(first, "run_objective_discovery", first_run)
    monkeypatch.setattr(second, "run_objective_discovery", second_run)
    try:
        await first.start_objective_discovery("col_a", ("doc_a",), user_id="user-1")
        await second.start_objective_discovery("col_b", ("doc_c",), user_id="user-1")
        await asyncio.wait_for(first_started.wait(), timeout=1)
        await asyncio.wait_for(second_started.wait(), timeout=1)
        second_tasks = tuple(second._workers)
        await first.close()
        assert not first._workers
        assert second_tasks and all(not task.done() for task in second_tasks)
    finally:
        release.set()
        await first.close()
        await second.close()


async def test_objective_discovery_reuses_one_active_run_and_executes_once(
    monkeypatch: pytest.MonkeyPatch, *, postgres_session_factory
) -> None:
    pipeline_run_service.PipelineRunRepo = PipelineRunRepository()
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
        objective_input_service,
        "resolve_prepared_document_inputs",
        resolve_inputs,
    )
    monkeypatch.setattr(service, "discover_and_replace_objective_candidates", discover)

    first = await service.start_objective_discovery(
        "col_a", ("doc_a", "doc_b"), user_id="user-1"
    )
    duplicate = await service.start_objective_discovery(
        "col_a", ("doc_a", "doc_b"), user_id="user-1"
    )

    assert first["run_id"] == duplicate["run_id"]
    assert first["status"] == "queued"
    await _wait_for_run(pipeline_run_service, first["run_id"])

    completed = await pipeline_run_service.get_run(first["run_id"], user_id="user-1")
    assert calls == 1
    assert completed["status"] == "completed"
    assert completed["current_node"] == "objectives_ready"


async def test_objective_discovery_records_failure_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch, *, postgres_session_factory
) -> None:
    pipeline_run_service.PipelineRunRepo = PipelineRunRepository()
    service = _service(pipeline_run_service)

    async def resolve_inputs(_collection_id, document_ids):
        return tuple(
            PreparedDocumentInput(document_id, f"fingerprint-{document_id}")
            for document_id in document_ids
        )

    async def fail_discovery(*_args, **_kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(
        objective_input_service,
        "resolve_prepared_document_inputs",
        resolve_inputs,
    )
    monkeypatch.setattr(
        service, "discover_and_replace_objective_candidates", fail_discovery
    )

    first = await service.start_objective_discovery(
        "col_a", ("doc_a",), user_id="user-1"
    )
    await _wait_for_run(pipeline_run_service, first["run_id"])
    failed = await pipeline_run_service.get_run(first["run_id"], user_id="user-1")

    assert failed["status"] == "failed"
    assert failed["errors"] == ["model unavailable"]

    retry = await service.start_objective_discovery(
        "col_a", ("doc_a",), user_id="user-1"
    )
    assert retry["run_id"] != first["run_id"]
    await _wait_for_run(pipeline_run_service, retry["run_id"])


async def test_objective_discovery_progress_does_not_move_backwards(
    *, postgres_session_factory
) -> None:
    pipeline_run_service.PipelineRunRepo = PipelineRunRepository()
    service = _service(pipeline_run_service)
    run = await pipeline_run_service.create_run(
        "col_a",
        "objective_discovery",
        scope_type="collection",
        scope_id="col_a",
        input_fingerprint="scope-a",
    )
    pending_updates = []
    report = objective_discovery_service._build_discovery_progress_callback(
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
    mapped = await pipeline_run_service.get_run(run["run_id"], user_id="user-1")

    report(
        {
            "phase": "objective_discovery_started",
            "current": 0,
            "total": 4,
            "unit": "relationship_groups",
        }
    )
    await asyncio.wrap_future(pending_updates[-1])
    aggregating = await pipeline_run_service.get_run(run["run_id"], user_id="user-1")

    assert aggregating["progress_percent"] >= mapped["progress_percent"]


async def test_objective_discovery_restart_recovery_allows_retry(
    *, postgres_session_factory
) -> None:
    pipeline_run_service.PipelineRunRepo = PipelineRunRepository()
    service = _service(pipeline_run_service)
    active, _created = await pipeline_run_service.get_or_create_collection_run(
        collection_id="col_a",
        pipeline_name="objective_discovery",
        input_fingerprint="scope-a",
        context={"document_ids": ["doc_a"]},
    )
    await pipeline_run_service.update_run(active["run_id"], status="running")

    recovered = await service.recover_interrupted_discoveries()
    interrupted = await pipeline_run_service.get_run(active["run_id"], user_id="user-1")
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
