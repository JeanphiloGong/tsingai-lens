#!/usr/bin/env python3
"""Run the concrete feedback_analysis worker without constructing the web application."""
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
from application.feedback.analysis_worker import execute_feedback_analysis_job
from application.feedback.worker_lease import run_with_lease_heartbeat

from application.feedback.analysis_handler import RuleBasedFeedbackAnalysisEngine


logger = logging.getLogger(__name__)

async def run_loop(interval_seconds: float, *, once: bool = False) -> None:
    database_engine = build_database_engine(DatabaseSettings())
    AsyncSessionLocal.configure(bind=database_engine)
    try:
        engine = RuleBasedFeedbackAnalysisEngine()
        while True:
            now = datetime.now(timezone.utc).isoformat()
            await AnalysisJobRepo.recover_expired_jobs(now=now)
            job = await AnalysisJobRepo.claim_next_feedback_analysis_job(now=now)
            if job is not None:
                try:
                    result = await run_with_lease_heartbeat(
                        job, lambda: execute_feedback_analysis_job(job, engine=engine, model_name='rule-based-v1'),
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


async def requeue_failed_job(job_id: str) -> str:
    database_engine = build_database_engine(DatabaseSettings())
    AsyncSessionLocal.configure(bind=database_engine)
    try:
        job = await AnalysisJobRepo.requeue_failed_feedback_analysis_job(
            job_id=job_id, now=datetime.now(timezone.utc).isoformat(),
        )
        return job.status
    finally:
        await database_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run feedback analysis jobs explicitly"
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--once", action="store_true", help="process at most one job")
    actions.add_argument(
        "--requeue-job",
        metavar="JOB_ID",
        help="manually return one failed feedback-analysis job to pending",
    )
    parser.add_argument(
        "--interval", type=float, default=2.0, help="loop delay in seconds"
    )
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    if args.requeue_job is not None:
        print(asyncio.run(requeue_failed_job(args.requeue_job)))
    elif args.once:
        asyncio.run(run_loop(args.interval, once=True))
    else:
        try:
            asyncio.run(run_loop(args.interval))
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
