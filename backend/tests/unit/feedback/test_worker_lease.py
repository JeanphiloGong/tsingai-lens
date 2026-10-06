from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from application.feedback.worker_lease import LeaseLostError, run_with_lease_heartbeat
from application.repositories.analysis_job_repository import AnalysisJob


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _job() -> AnalysisJob:
    return AnalysisJob(
        job_id="job-1",
        job_type="feedback_analysis",
        payload_version=1,
        payload={"feedback_id": "feedback-1"},
        status="running",
        idempotency_key="feedback-1",
        available_at="2026-10-01T00:00:00+00:00",
        created_at="2026-10-01T00:00:00+00:00",
        updated_at="2026-10-01T00:00:00+00:00",
        worker_id="worker-1",
        lease_expires_at="2026-10-01T00:15:00+00:00",
        heartbeat_at="2026-10-01T00:00:00+00:00",
        lease_version=4,
    )


async def test_long_operation_renews_its_lease() -> None:
    calls: list[tuple[str, str, int]] = []

    class Jobs:
        async def renew_lease(self, *, job_id, worker_id, lease_version, now):
            calls.append((job_id, worker_id, lease_version))
            return replace(_job(), heartbeat_at=now)

    result = await run_with_lease_heartbeat(
        Jobs(),
        _job(),
        lambda: asyncio.sleep(0.035, result="done"),
        interval_seconds=0.005,
    )

    assert result == "done"
    assert calls
    assert calls[0] == ("job-1", "worker-1", 4)


async def test_operation_cannot_publish_after_lease_is_lost() -> None:
    class Jobs:
        async def renew_lease(self, **_kwargs):
            return None

    with pytest.raises(LeaseLostError):
        await run_with_lease_heartbeat(
            Jobs(),
            _job(),
            lambda: asyncio.sleep(0.03, result="must-not-publish"),
            interval_seconds=0.005,
        )
