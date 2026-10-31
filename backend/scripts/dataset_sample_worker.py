#!/usr/bin/env python3
"""Run the concrete dataset_sample_build worker without constructing the web application."""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from infra.persistence.database import AsyncSessionLocal, DatabaseSettings, build_database_engine
from repositories.analysis_job_repository import AnalysisJobRepo, LeaseLostError
from application.feedback.sample_build_worker import execute_dataset_sample_build_job

from openai import AsyncOpenAI
from infra.llm.feedback_sample_generator import OpenAIFeedbackSampleGenerator
from application.feedback.sft_sample_builder import SftSampleBuilder
from application.feedback.preference_sample_builder import PreferenceSampleBuilder
from application.feedback.evaluation_sample_builder import EvaluationSampleBuilder
from repositories.feedback_dataset_sample_repository import FeedbackDatasetSampleRepo


logger = logging.getLogger(__name__)

async def run_loop(interval_seconds: float, *, once: bool = False) -> None:
    database_engine = build_database_engine(DatabaseSettings())
    AsyncSessionLocal.configure(bind=database_engine)
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
    try:
        async with AsyncOpenAI(
            api_key=os.getenv("LLM_API_KEY", "").strip() or "not-needed",
            base_url=os.getenv("LLM_BASE_URL", "").strip() or None,
            timeout=float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "180")),
            max_retries=0,
        ) as client:
            generator = OpenAIFeedbackSampleGenerator(client=client)
            builders = {
                "sft": SftSampleBuilder(generator=generator),
                "preference": PreferenceSampleBuilder(generator=generator),
                "evaluation": EvaluationSampleBuilder(generator=generator),
            }
            await FeedbackDatasetSampleRepo.backfill_existing_cases()
            while True:
                now = datetime.now(timezone.utc).isoformat()
                await AnalysisJobRepo.recover_expired_jobs(now=now)
                job = await AnalysisJobRepo.claim_next_dataset_sample_build_job(now=now)
                if job is not None:
                    try:
                        result = await execute_dataset_sample_build_job(
                            job, builders=builders
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
        try:
            await database_engine.dispose()
        finally:
            loop.remove_signal_handler(signal.SIGTERM)


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
    try:
        asyncio.run(run_loop(args.interval, once=args.once))
    except (KeyboardInterrupt, asyncio.CancelledError):
        return


if __name__ == "__main__":
    main()
