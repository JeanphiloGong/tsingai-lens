#!/usr/bin/env python3
"""Run task-specific dataset sample build jobs explicitly."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


async def run_once() -> str:
    from main import build_application_runtime
    from repositories.feedback_dataset_sample_repository import (
        FeedbackDatasetSampleRepo,
    )

    runtime = await build_application_runtime()
    try:
        await FeedbackDatasetSampleRepo.backfill_existing_cases()
        worker = runtime.dataset_sample_build_worker
        result = await worker.run_once()
        return "idle" if result is None else str(result.status)
    finally:
        await runtime.close()


async def run_loop(interval_seconds: float) -> None:
    from main import build_application_runtime
    from repositories.feedback_dataset_sample_repository import (
        FeedbackDatasetSampleRepo,
    )

    runtime = None
    initialized = False
    try:
        while True:
            try:
                if runtime is None:
                    runtime = await build_application_runtime()
                if not initialized:
                    await FeedbackDatasetSampleRepo.backfill_existing_cases()
                    initialized = True
                result = await runtime.dataset_sample_build_worker.run_once()
                print("idle" if result is None else str(result.status), flush=True)
            except Exception:
                logger.exception("dataset sample worker iteration failed")
            await asyncio.sleep(interval_seconds)
    finally:
        if runtime is not None:
            await runtime.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run dataset sample build jobs explicitly"
    )
    parser.add_argument("--once", action="store_true", help="process at most one job")
    parser.add_argument(
        "--interval", type=float, default=2.0, help="loop delay in seconds"
    )
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
