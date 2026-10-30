from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from scripts import feedback_analysis_worker as worker_script


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_requeue_failed_job_uses_repository_and_closes_runtime(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str]] = []

    class Repository:
        async def requeue_failed_feedback_analysis_job(self, *, job_id: str, now: str):
            calls.append((job_id, now))
            return SimpleNamespace(status="pending")

    class Runtime:
        analysis_job_repository = Repository()

        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    runtime = Runtime()
    monkeypatch.setattr(
        "repositories.analysis_job_repository.AnalysisJobRepo",
        runtime.analysis_job_repository,
    )
    monkeypatch.setattr(
        "main.build_application_runtime",
        lambda: _runtime(runtime),
    )

    assert await worker_script.requeue_failed_job("job-123") == "pending"
    assert calls and calls[0][0] == "job-123"
    assert calls[0][1]
    assert runtime.closed is True


async def _runtime(runtime):
    return runtime


def test_cli_rejects_worker_and_requeue_actions_together(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["feedback_analysis_worker.py", "--once", "--requeue-job", "job-123"],
    )

    with pytest.raises(SystemExit) as error:
        worker_script.main()

    assert error.value.code == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    "module_name,worker_name",
    [
        ("feedback_analysis_worker", "feedback_analysis_worker"),
        ("correction_signal_analysis_worker", "correction_signal_analysis_worker"),
        ("tool_failure_analysis_worker", "tool_failure_analysis_worker"),
    ],
)
@pytest.mark.parametrize("termination", [KeyboardInterrupt, RuntimeError])
async def test_loop_reuses_one_runtime_and_closes_on_exit(
    monkeypatch, module_name, worker_name, termination
):
    import importlib
    from unittest.mock import AsyncMock

    module = importlib.import_module(f"scripts.{module_name}")
    worker = SimpleNamespace(
        run_once=AsyncMock(
            side_effect=[None, SimpleNamespace(status="succeeded"), None, termination()]
        )
    )
    runtime = SimpleNamespace(**{worker_name: worker}, close=AsyncMock())
    build = AsyncMock(return_value=runtime)
    monkeypatch.setattr("main.build_application_runtime", build)
    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())
    with pytest.raises(termination):
        await module.run_loop(2)
    assert build.await_count == 1
    assert worker.run_once.await_count == 4
    assert runtime.close.await_count == 1
