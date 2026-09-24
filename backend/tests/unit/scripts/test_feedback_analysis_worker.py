from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from scripts import feedback_analysis_worker as worker_script


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_requeue_failed_job_uses_repository_and_closes_runtime(monkeypatch) -> None:
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
        worker_script,
        "_build_runtime",
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
