"""Lease heartbeats for long-running feedback workers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class LeaseLostError(RuntimeError):
    """The worker no longer owns the job lease and must not publish a result."""


async def run_with_lease_heartbeat(
    job_repository: Any,
    job: Any,
    operation: Callable[[], Awaitable[T]],
    *,
    interval_seconds: float = 60.0,
) -> T:
    """Run an operation while extending its active job lease.

    Repositories that predate the lease contract are allowed to omit the
    method in unit-test doubles; production repositories must implement it.
    A failed renewal is treated as lease loss, so callers cannot announce a
    successful result after ownership has become uncertain.
    """

    renew = getattr(job_repository, "renew_lease", None)
    if not callable(renew) or not getattr(job, "worker_id", None):
        return await operation()
    if interval_seconds <= 0:
        raise ValueError("lease heartbeat interval must be positive")

    stop = asyncio.Event()

    async def heartbeat() -> None:
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
                return
            except asyncio.TimeoutError:
                pass
            try:
                renewed = await renew(
                    job_id=job.job_id,
                    worker_id=job.worker_id,
                    lease_version=job.lease_version,
                    now=datetime.now(timezone.utc).isoformat(),
                )
            except Exception:  # noqa: BLE001
                logger.exception("job lease heartbeat failed job_id=%s", job.job_id)
                return
            if renewed is None:
                return

    operation_task = asyncio.create_task(operation())
    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        done, _pending = await asyncio.wait(
            {operation_task, heartbeat_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if heartbeat_task in done:
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)
            raise LeaseLostError(f"job lease lost: {job.job_id}")
        return operation_task.result()
    finally:
        stop.set()
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


__all__ = ["LeaseLostError", "run_with_lease_heartbeat"]
