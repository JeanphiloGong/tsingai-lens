#!/usr/bin/env python3
"""Run task-specific dataset sample build jobs explicitly."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


async def _build_runtime():
    from main import ApplicationOverrides, build_application_runtime

    return await build_application_runtime(ApplicationOverrides())


async def run_once() -> str:
    runtime = await _build_runtime()
    try:
        worker = runtime.dataset_sample_build_worker
        if worker is None:
            raise RuntimeError("dataset sample build worker is not configured")
        result = await worker.run_once()
        return "idle" if result is None else str(result.status)
    finally:
        await runtime.close()


async def run_loop(interval_seconds: float) -> None:
    while True:
        print(await run_once(), flush=True)
        await asyncio.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run dataset sample build jobs explicitly")
    parser.add_argument("--once", action="store_true", help="process at most one job")
    parser.add_argument("--interval", type=float, default=2.0, help="loop delay in seconds")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    if args.once:
        print(asyncio.run(run_once()))
        return
    try:
        asyncio.run(run_loop(args.interval))
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
