#!/usr/bin/env python3
"""Run failed Chat tool analysis jobs explicitly."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


async def run_once() -> str:
    from main import ApplicationOverrides, build_application_runtime

    runtime = await build_application_runtime(ApplicationOverrides())
    try:
        worker = runtime.tool_failure_analysis_worker
        if worker is None:
            raise RuntimeError("tool failure analysis worker is not configured")
        job = await worker.run_once()
        return "idle" if job is None else job.status
    finally:
        await runtime.close()


async def run_loop(interval_seconds: float) -> None:
    while True:
        status = await run_once()
        print(status, flush=True)
        await asyncio.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run failed Chat tool analysis jobs explicitly"
    )
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
