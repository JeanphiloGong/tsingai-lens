"""Cancellation and lease loss stop the concrete entry point's owned operation."""

import asyncio
from types import SimpleNamespace
from datetime import timedelta
from unittest.mock import AsyncMock
import importlib
import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize(
    "kind", ["document_preparation", "objective_discovery", "objective_analysis"]
)
@pytest.mark.parametrize("termination", ["cancel", "lost_lease"])
async def test_worker_reclaims_its_operation_and_heartbeat(
    monkeypatch, kind, termination
):
    module = importlib.import_module("scripts.run_" + kind)
    analysis = kind == "objective_analysis"
    job = SimpleNamespace(
        run=SimpleNamespace(run_id="run"),
        analysis=SimpleNamespace(key=("collection", "objective", 1)),
    )
    repository = SimpleNamespace()
    setattr(repository, "claim_next_" + kind + "_job", AsyncMock(return_value=job))
    error = module.AnalysisLeaseLostError if analysis else module.PipelineLeaseLostError
    setattr(
        repository,
        "renew_analysis_lease" if analysis else "renew_lease",
        AsyncMock(
            side_effect=error("expired") if termination == "lost_lease" else None
        ),
    )
    monkeypatch.setattr(
        module, "ObjectiveRepo" if analysis else "PipelineRunRepo", repository
    )
    started, stopped = asyncio.Event(), asyncio.Event()

    async def execute(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            stopped.set()

    monkeypatch.setattr(module, "execute_" + kind + "_job", execute)
    kwargs = dict(
        worker_id="worker",
        lease_duration=timedelta(seconds=60),
        heartbeat_interval=0.005,
        once=True,
    )
    if kind == "document_preparation":
        kwargs.update(
            workspace=object(), object_store=object(), profile_extractor=object()
        )
    else:
        kwargs["client"] = object()
    task = asyncio.create_task(module.run_forever(**kwargs))
    await asyncio.wait_for(started.wait(), timeout=1)
    if termination == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await asyncio.wait_for(task, timeout=1)
    assert stopped.is_set()


async def test_profile_cancellation_drains_the_actual_sync_call(monkeypatch):
    """Client shutdown must wait until a running model thread returns."""
    import threading
    from application.core.document_profiles import service
    from domain.core.document_profile import DocumentProfile
    from domain.source import SourceDocument

    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def classify(**kwargs):
        started.set()
        try:
            assert release.wait(timeout=2)
            return DocumentProfile("paper", "LPBF", "experimental", (), 0.9)
        finally:
            finished.set()

    monkeypatch.setattr(
        service.collection_service, "get_collection", AsyncMock(return_value=object())
    )
    monkeypatch.setattr(
        service.SourceArtifactRepo,
        "read_document",
        AsyncMock(
            return_value=SourceDocument(
                document_id="paper", document_order=0, title="Paper", text="Source"
            )
        ),
    )
    monkeypatch.setattr(service, "_build_collection_file_lookup", lambda _: {})
    monkeypatch.setattr(service, "_profile_document", classify)
    operation = asyncio.create_task(
        service.build_document_profile(
            "collection",
            "paper",
            source_fingerprint="source",
            profile_fingerprint="profile",
            extractor=object(),
        )
    )
    assert await asyncio.to_thread(started.wait, 1)
    operation.cancel()
    await asyncio.sleep(0)
    assert not operation.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert finished.is_set()
