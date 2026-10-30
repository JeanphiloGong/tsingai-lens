from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import dataset_sample_worker

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_loop_reuses_runtime_and_backfills_once(monkeypatch):
    worker = SimpleNamespace(
        run_once=AsyncMock(side_effect=[None, KeyboardInterrupt()])
    )
    runtime = SimpleNamespace(
        dataset_sample_build_worker=worker,
        close=AsyncMock(),
    )
    build = AsyncMock(return_value=runtime)
    monkeypatch.setattr("main.build_application_runtime", build)
    backfill = AsyncMock()
    monkeypatch.setattr(
        "repositories.feedback_dataset_sample_repository.FeedbackDatasetSampleRepo.backfill_existing_cases",
        backfill,
    )
    monkeypatch.setattr(dataset_sample_worker.asyncio, "sleep", AsyncMock())
    with pytest.raises(KeyboardInterrupt):
        await dataset_sample_worker.run_loop(2)
    assert build.await_count == 1
    assert runtime.close.await_count == 1
    assert backfill.await_count == 1


async def test_loop_retries_runtime_initialization(monkeypatch):
    runtime = SimpleNamespace(
        dataset_sample_build_worker=SimpleNamespace(
            run_once=AsyncMock(side_effect=KeyboardInterrupt())
        ),
        close=AsyncMock(),
    )
    build = AsyncMock(
        side_effect=[RuntimeError("temporary initialization failure"), runtime]
    )
    monkeypatch.setattr("main.build_application_runtime", build)
    backfill = AsyncMock()
    monkeypatch.setattr(
        "repositories.feedback_dataset_sample_repository.FeedbackDatasetSampleRepo.backfill_existing_cases",
        backfill,
    )
    monkeypatch.setattr(dataset_sample_worker.asyncio, "sleep", AsyncMock())
    with pytest.raises(KeyboardInterrupt):
        await dataset_sample_worker.run_loop(2)
    assert build.await_count == 2
    assert runtime.close.await_count == 1
