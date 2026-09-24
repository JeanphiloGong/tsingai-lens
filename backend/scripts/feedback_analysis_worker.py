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
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from main import build_application_runtime, ApplicationOverrides  # noqa: E402


async def run_once() -> str:
    runtime = await build_application_runtime(ApplicationOverrides())
    try:
        if runtime.feedback_analysis_worker is None:
            raise RuntimeError("feedback analysis worker is not configured")
        job = await runtime.feedback_analysis_worker.run_once()
        return "idle" if job is None else job.status
    finally:
        await runtime.close()


async def run_loop(interval_seconds: float) -> None:
    while True:
        status = await run_once()
        print(status, flush=True)
        await asyncio.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run feedback analysis jobs explicitly")
    parser.add_argument("--once", action="store_true", help="process at most one job")
    parser.add_argument("--interval", type=float, default=2.0, help="loop delay in seconds")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    if args.once:
        print(asyncio.run(run_once()))
    else:
        try:
            asyncio.run(run_loop(args.interval))
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
