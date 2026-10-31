#!/usr/bin/env python3
"""Claim and execute document_preparation jobs in an independent process."""

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
from repositories.pipeline_run_repository import (
    PipelineRunRepo,
    PipelineRunJobSnapshot,
    PipelineLeaseLostError,
 )
from application.source.document_preparation_service import (
    execute_document_preparation_job,
)

from config import DATA_DIR
from infra.persistence.file import FileCollectionWorkspace
from infra.persistence.file.object_store import FileObjectStore
from infra.source.build_source_artifacts import build_source_artifacts
from application.core.document_profiles.extraction import (
    build_default_document_profile_extractor,
    DocumentProfileExtractor,
)


logger = logging.getLogger(__name__)


async def run_forever(
    *,
    worker_id: str,
    workspace: FileCollectionWorkspace,
    object_store: FileObjectStore,
    profile_extractor: DocumentProfileExtractor,
    lease_duration: timedelta,
    heartbeat_interval: float,
    interval_seconds: float = 2,
    once: bool = False,
) -> None:
    async def heartbeat(job: PipelineRunJobSnapshot) -> None:
        while True:
            await asyncio.sleep(heartbeat_interval)
            await PipelineRunRepo.renew_lease(job, lease_duration=lease_duration)

    while True:
        job = await PipelineRunRepo.claim_next_document_preparation_job(
            worker_id=worker_id, lease_duration=lease_duration
        )
        if job is None:
            if once:
                return
            await asyncio.sleep(interval_seconds)
            continue
        operation_task = asyncio.create_task(
            execute_document_preparation_job(
                job,
                workspace=workspace,
                object_store=object_store,
                source_artifact_builder=build_source_artifacts,
                profile_extractor=profile_extractor,
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
        except PipelineLeaseLostError:
            logger.warning("Worker lease lost job=%s", job.run.run_id)
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
        workspace = FileCollectionWorkspace(DATA_DIR / "collections")
        object_store = FileObjectStore(workspace.root_dir)
        profile_extractor = build_default_document_profile_extractor()
        try:
            await run_forever(
                worker_id=f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex}",
                workspace=workspace,
                object_store=object_store,
                profile_extractor=profile_extractor,
                lease_duration=timedelta(seconds=lease_seconds),
                heartbeat_interval=heartbeat_interval,
                interval_seconds=interval_seconds,
                once=once,
            )
        finally:
            profile_extractor.client.close()
    finally:
        try:
            await database_engine.dispose()
        finally:
            loop.remove_signal_handler(signal.SIGTERM)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the document_preparation worker")
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
