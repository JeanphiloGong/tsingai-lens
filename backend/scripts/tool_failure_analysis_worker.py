#!/usr/bin/env python3
"""Run the concrete tool_failure_analysis worker without constructing the web application."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from infra.persistence.database import AsyncSessionLocal, DatabaseSettings, build_database_engine
from repositories.analysis_job_repository import AnalysisJobRepo, LeaseLostError
from application.feedback.tool_failure_worker import execute_tool_failure_analysis_job
from application.feedback.worker_lease import run_with_lease_heartbeat

from application.feedback.tool_failure_handler import RuleBasedToolFailureAnalysisEngine


logger = logging.getLogger(__name__)

async def run_loop(interval_seconds: float, *, once: bool = False) -> None:
    database_engine = build_database_engine(DatabaseSettings())
    AsyncSessionLocal.configure(bind=database_engine)
    try:
        engine = RuleBasedToolFailureAnalysisEngine()
        while True:
            now = datetime.now(timezone.utc).isoformat()
            await AnalysisJobRepo.recover_expired_jobs(now=now)
            job = await AnalysisJobRepo.claim_next_tool_failure_analysis_job(now=now)
            if job is not None:
                try:
                    result = await run_with_lease_heartbeat(
                        job, lambda: execute_tool_failure_analysis_job(job, engine=engine, model_name='rule-based-tool-failure-v1'),
                    )
                    print(result.status, flush=True)
                except LeaseLostError:
                    logger.warning("Worker lease lost job_id=%s", job.job_id)
            else:
                print("idle", flush=True)
            if once:
                return
            await asyncio.sleep(interval_seconds)
    finally:
        await database_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run failed Chat tool analysis jobs explicitly"
    )
    parser.add_argument("--once", action="store_true", help="process at most one job")
    parser.add_argument(
        "--interval", type=float, default=2.0, help="loop delay in seconds"
    )
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    if args.once:
        asyncio.run(run_loop(args.interval, once=True))
    else:
        try:
            asyncio.run(run_loop(args.interval))
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
