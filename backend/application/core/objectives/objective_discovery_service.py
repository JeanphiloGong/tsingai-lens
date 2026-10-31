from __future__ import annotations

import asyncio
import json
import logging
from asyncio import (
    gather,
    get_running_loop,
    run_coroutine_threadsafe,
    to_thread,
    wrap_future,
)
from hashlib import sha256
from threading import Lock
from typing import Any, Callable

from application.core.objectives import (
    objective_candidate_service,
    objective_input_service,
)
from application.core.objectives.discovery.axis_equivalence import (
    ResearchAxisEquivalenceClassifier,
)
from application.core.objectives.discovery.paper_understanding.workflow import (
    PaperResearchMapExtractor,
)
from application.core.objectives.llm.structured_response import StructuredResponseClient
from application.core.objectives.objective_input_service import (
    PAPER_RESEARCH_MAP_POLICY_VERSION,
)
from application.pipeline import pipeline_run_service
from application.source import collection_service
from domain.core import PreparedDocumentInput
from infra.persistence.database import AsyncSessionLocal
from repositories.objective_repository import ObjectiveRepo
from repositories.paper_map_repository import PaperMapRepo
from repositories.pipeline_run_repository import (
    PipelineLeaseLostError,
    PipelineRun,
    PipelineRunJobSnapshot,
    PipelineRunRepo,
)
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]


async def start_objective_discovery(
    collection_id: str,
    document_ids: tuple[str, ...],
    *,
    user_id: str,
) -> PipelineRun:
    """Queue or reuse one collection-level Objective Discovery run."""
    await collection_service.get_collection_for_user(collection_id, user_id)

    document_inputs = await objective_input_service.resolve_prepared_document_inputs(
        collection_id,
        document_ids,
    )
    run, _ = await pipeline_run_service.get_or_create_collection_run(
        collection_id=collection_id,
        pipeline_name="objective_discovery",
        input_fingerprint=_objective_discovery_fingerprint(document_inputs),
        context={
            "document_inputs": [
                {
                    "document_id": item.document_id,
                    "preparation_fingerprint": item.preparation_fingerprint,
                }
                for item in document_inputs
            ]
        },
    )
    return run


async def _check_discovery_inputs(
    db: AsyncSession, job: PipelineRunJobSnapshot
) -> tuple[PreparedDocumentInput, ...]:
    await PipelineRunRepo.lock_job(db, job)
    document_inputs = tuple(
        PreparedDocumentInput(**item) for item in job.run.context["document_inputs"]
    )
    for item in sorted(document_inputs, key=lambda item: item.document_id):
        record = await collection_service.get_document(
            job.run.collection_id, item.document_id, db=db
        )
        if (
            record.document.status != "ready"
            or record.document.preparation_fingerprint != item.preparation_fingerprint
        ):
            raise ValueError("discovery document input changed")
    if _objective_discovery_fingerprint(document_inputs) != job.run.input_fingerprint:
        raise ValueError("discovery policy or input changed")
    return document_inputs


async def execute_objective_discovery_job(
    job: PipelineRunJobSnapshot, *, client: StructuredResponseClient
) -> PipelineRun:
    run_id = job.run.run_id
    collection_id = job.run.collection_id
    pending_progress_updates: list[Any] = []
    progress_callback = _build_discovery_progress_callback(
        job, pending_progress_updates
    )
    try:
        async with AsyncSessionLocal() as db, db.begin():
            document_inputs = await _check_discovery_inputs(db, job)
            await pipeline_run_service.update_run(
                run_id, job=job, db=db, current_node="paper_map", progress_percent=5
            )
        source_inputs = await objective_input_service.load_source_inputs(
            collection_id, document_inputs=document_inputs
        )
        paper_maps = await objective_input_service.load_or_build_paper_maps(
            collection_id,
            document_inputs=document_inputs,
            source_inputs=source_inputs,
            paper_map_extractor=PaperResearchMapExtractor(client),
            progress_callback=progress_callback,
        )
        async with AsyncSessionLocal() as db, db.begin():
            await _check_discovery_inputs(db, job)
            for paper_map in paper_maps:
                await PaperMapRepo.replace(collection_id, paper_map, db=db)
        candidate_task = asyncio.create_task(
            to_thread(
                objective_candidate_service.discover_candidate_facts,
                collection_id,
                paper_maps=paper_maps,
                document_inputs=document_inputs,
                axis_equivalence_classifier=ResearchAxisEquivalenceClassifier(client),
                progress_callback=progress_callback,
            )
        )
        try:
            facts = await asyncio.shield(candidate_task)
        except asyncio.CancelledError:
            await asyncio.gather(candidate_task, return_exceptions=True)
            raise
        await _flush_progress_updates(pending_progress_updates)
        async with AsyncSessionLocal() as db, db.begin():
            await _check_discovery_inputs(db, job)
            await ObjectiveRepo.replace(collection_id, facts, db=db)
            return await pipeline_run_service.finish_run(
                run_id,
                job=job,
                db=db,
                status="completed",
                current_node="objectives_ready",
                progress_percent=100,
                progress_detail={
                    "phase": "objectives_ready",
                    "unit": "documents",
                    "current": len(document_inputs),
                    "total": len(document_inputs),
                    "message": "Candidate research questions are ready for review.",
                    "objective_count": len(facts.research_objectives),
                },
            )
    except PipelineLeaseLostError:
        raise
    except Exception as exc:
        logger.exception("Objective discovery failed run_id=%s", run_id)
        await _flush_progress_updates(pending_progress_updates)
        async with AsyncSessionLocal() as db, db.begin():
            return await pipeline_run_service.finish_run(
                run_id,
                job=job,
                db=db,
                status="failed",
                current_node="failed",
                errors=[str(exc)],
                progress_detail={
                    "phase": "failed",
                    "unit": "documents",
                    "message": "Research question formation failed. Retry it.",
                },
            )
    finally:
        await _flush_progress_updates(pending_progress_updates)


def _build_discovery_progress_callback(
    job: PipelineRunJobSnapshot,
    pending_updates: list[Any],
) -> ProgressCallback:
    loop = get_running_loop()
    progress_lock = Lock()
    last_percent = 5

    async def persist_progress(
        phase: str, percent: int, detail: dict[str, Any]
    ) -> None:
        async with AsyncSessionLocal() as db, db.begin():
            await pipeline_run_service.update_run(
                job.run.run_id,
                job=job,
                db=db,
                current_node=phase,
                progress_percent=percent,
                progress_detail=detail,
            )

    def update(progress: dict[str, Any]) -> None:
        nonlocal last_percent
        current = _safe_progress_int(progress.get("current"))
        total = _safe_progress_int(progress.get("total"))
        phase = str(progress.get("phase") or "running")
        fraction = (
            max(0.0, min(1.0, current / total))
            if current is not None and total
            else 0.0
        )
        if phase.startswith("paper_"):
            percent = 5 + round(60 * fraction)
        elif phase.startswith("objective_discovery"):
            percent = 70 + round(25 * fraction)
        else:
            percent = 10 + round(85 * fraction)
        with progress_lock:
            last_percent = max(last_percent, min(95, percent))
            pending_updates.append(
                run_coroutine_threadsafe(
                    persist_progress(phase, last_percent, dict(progress)), loop
                )
            )

    return update


async def _flush_progress_updates(pending_updates: list[Any]) -> None:
    if pending_updates:
        await gather(
            *(wrap_future(item) for item in pending_updates),
            return_exceptions=True,
        )


def _objective_discovery_fingerprint(
    document_inputs: tuple[PreparedDocumentInput, ...],
) -> str:
    return sha256(
        json.dumps(
            {
                "document_inputs": [
                    {
                        "document_id": item.document_id,
                        "preparation_fingerprint": item.preparation_fingerprint,
                    }
                    for item in document_inputs
                ],
                "paper_map_policy_version": PAPER_RESEARCH_MAP_POLICY_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _safe_progress_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
