#!/usr/bin/env python3
"""Claim and execute objective_analysis jobs in an independent process."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import os
import socket
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from infra.persistence.database import (
    AsyncSessionLocal,
    DatabaseSettings,
    build_database_engine,
)
from repositories.objective_repository import (
    ObjectiveRepo,
    ObjectiveAnalysisJobSnapshot,
    AnalysisLeaseLostError,
)
from application.core.objectives.analysis_service import execute_objective_analysis_job

from application.core.objectives.llm.structured_response import (
    build_default_structured_response_client,
    StructuredResponseClient,
)
from application.core.objectives.analysis.source_screening import (
    ObjectiveSourceScreener,
)
from application.core.objectives.analysis.paper_experiment_extraction import (
    PaperExperimentExtractor,
)
from application.core.objectives.discovery.paper_understanding.workflow import (
    PaperResearchMapExtractor,
)


logger = logging.getLogger(__name__)


async def run_forever(
    *,
    worker_id: str,
    client: StructuredResponseClient,
    lease_duration: timedelta,
    heartbeat_interval: float,
    interval_seconds: float = 2,
    once: bool = False,
) -> None:
    async def heartbeat(job: ObjectiveAnalysisJobSnapshot) -> None:
        while True:
            await asyncio.sleep(heartbeat_interval)
            await ObjectiveRepo.renew_analysis_lease(job, lease_duration=lease_duration)

    while True:
        job = await ObjectiveRepo.claim_next_objective_analysis_job(
            worker_id=worker_id, lease_duration=lease_duration
        )
        if job is None:
            if once:
                return
            await asyncio.sleep(interval_seconds)
            continue
        operation_task = asyncio.create_task(
            execute_objective_analysis_job(
                job,
                response_client=client,
                source_screener=ObjectiveSourceScreener(client),
                paper_map_extractor=PaperResearchMapExtractor(client),
                paper_experiment_extractor=PaperExperimentExtractor(client),
            )
        )
        heartbeat_task = asyncio.create_task(heartbeat(job))
        try:
            done, _ = await asyncio.wait(
                {operation_task, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if operation_task in done:
                operation_task.result()
            else:
                heartbeat_task.result()
                raise RuntimeError("Worker heartbeat unexpectedly stopped")
        except AnalysisLeaseLostError:
            logger.warning("Worker lease lost job=%s", job.analysis.key)
        finally:
            for task in (operation_task, heartbeat_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(operation_task, heartbeat_task, return_exceptions=True)
        if once:
            return


async def run(
    *,
    once: bool,
    interval_seconds: float,
    lease_seconds: float,
    heartbeat_interval: float,
) -> None:
    database_engine = build_database_engine(DatabaseSettings())
    AsyncSessionLocal.configure(bind=database_engine)
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
    try:
        client = build_default_structured_response_client()
        try:
            await run_forever(
                worker_id=f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex}",
                client=client,
                lease_duration=timedelta(seconds=lease_seconds),
                heartbeat_interval=heartbeat_interval,
                interval_seconds=interval_seconds,
                once=once,
            )
        finally:
            client.client.close()
    finally:
        try:
            await database_engine.dispose()
        finally:
            loop.remove_signal_handler(signal.SIGTERM)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the objective_analysis worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=2)
    parser.add_argument("--lease-seconds", type=float, default=300)
    parser.add_argument("--heartbeat-seconds", type=float, default=30)
    args = parser.parse_args()
    if not 0 < args.heartbeat_seconds < args.lease_seconds or args.interval <= 0:
        parser.error(
            "heartbeat must be positive and shorter than the lease; interval must be positive"
        )
    try:
        asyncio.run(
            run(
                once=args.once,
                interval_seconds=args.interval,
                lease_seconds=args.lease_seconds,
                heartbeat_interval=args.heartbeat_seconds,
            )
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        return


if __name__ == "__main__":
    main()
