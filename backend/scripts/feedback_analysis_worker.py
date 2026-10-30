#!/usr/bin/env python3
"""Run the feedback-analysis worker explicitly.

The production app exposes the worker as an object for tests and operators;
this script is the small operational entry point and does not start a hidden
background task inside FastAPI.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


async def run_once() -> str:
    from main import build_application_runtime

    runtime = await build_application_runtime()
    try:
        job = await runtime.feedback_analysis_worker.run_once()
        return "idle" if job is None else job.status
    finally:
        await runtime.close()


async def requeue_failed_job(job_id: str) -> str:
    """Explicitly requeue one failed feedback-analysis job for inspection."""
    from main import build_application_runtime

    runtime = await build_application_runtime()
    try:
        from repositories.analysis_job_repository import AnalysisJobRepo

        job = await AnalysisJobRepo.requeue_failed_feedback_analysis_job(
            job_id=job_id,
            now=datetime.now(timezone.utc).isoformat(),
        )
        return job.status
    finally:
        await runtime.close()


async def run_loop(interval_seconds: float) -> None:
    from main import build_application_runtime

    runtime = await build_application_runtime()
    try:
        worker = runtime.feedback_analysis_worker
        while True:
            job = await worker.run_once()
            print("idle" if job is None else job.status, flush=True)
            await asyncio.sleep(interval_seconds)
    finally:
        await runtime.close()


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
        print(asyncio.run(run_once()))
    else:
        try:
            asyncio.run(run_loop(args.interval))
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
