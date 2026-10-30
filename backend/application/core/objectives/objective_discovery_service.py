from __future__ import annotations

import json
import logging
from asyncio import (
    CancelledError,
)
from asyncio import Task as AsyncTask
from asyncio import (
    create_task,
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
from application.core.objectives.objective_input_service import (
    PAPER_RESEARCH_MAP_POLICY_VERSION,
)
from application.pipeline import pipeline_run_service
from application.source import collection_service
from domain.core import ObjectiveFactSet, PreparedDocumentInput
from exceptions import ServiceUnavailableException

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]


from repositories.objective_repository import ObjectiveRepo

_worker_factory = create_task
_workers: set[Any] = set()


async def recover_interrupted_discoveries() -> int:
    """Make persisted discovery runs retryable after a backend restart."""

    run_service = pipeline_run_service
    active_runs = await run_service.list_interrupted_runs()
    interrupted_count = 0
    for run in active_runs:
        if run.get("pipeline_name") != "objective_discovery":
            continue
        await run_service.finish_run(
            run["run_id"],
            status="failed",
            current_node="interrupted",
            progress_percent=run.get("progress_percent", 0),
            errors=[
                *run.get("errors", ()),
                "Research question formation was interrupted by a backend restart.",
            ],
            progress_detail={
                "phase": "interrupted",
                "unit": "documents",
                "message": "Research question formation was interrupted. Retry it.",
            },
        )
        interrupted_count += 1
    if interrupted_count:
        logger.warning(
            "Recovered interrupted Objective Discovery runs count=%s",
            interrupted_count,
        )
    return interrupted_count


async def start_objective_discovery(
    collection_id: str,
    document_ids: tuple[str, ...],
    *,
    user_id: str,
) -> dict[str, Any]:
    """Queue or reuse one collection-level Objective Discovery run."""
    await collection_service.get_collection_for_user(collection_id, user_id)

    document_inputs = await objective_input_service.resolve_prepared_document_inputs(
        collection_id,
        document_ids,
    )
    run_service = pipeline_run_service
    run, created = await run_service.get_or_create_collection_run(
        collection_id=collection_id,
        pipeline_name="objective_discovery",
        input_fingerprint=_objective_discovery_fingerprint(document_inputs),
        context={"document_ids": [item.document_id for item in document_inputs]},
    )
    if not created:
        return run

    coroutine = run_objective_discovery(
        run["run_id"],
        collection_id,
        tuple(item.document_id for item in document_inputs),
    )
    try:
        background = _worker_factory(coroutine)
    except Exception as exc:  # noqa: BLE001
        coroutine.close()
        await run_service.finish_run(
            run["run_id"],
            status="failed",
            current_node="dispatch_failed",
            progress_percent=0,
            errors=["Research question formation could not be scheduled."],
        )
        raise ServiceUnavailableException(
            "Research question formation could not be scheduled. Retry it.",
            data={
                "code": "objective_discovery_dispatch_failed",
                "run_id": run["run_id"],
                "collection_id": collection_id,
            },
        ) from exc
    _workers.add(background)
    background.add_done_callback(_workers.discard)
    background.add_done_callback(_log_unexpected_failure)
    return run


async def run_objective_discovery(
    run_id: str,
    collection_id: str,
    document_ids: tuple[str, ...],
) -> dict[str, Any]:
    """Execute one admitted discovery run and persist its state."""

    run_service = pipeline_run_service
    await run_service.update_run(
        run_id,
        status="running",
        current_node="paper_map",
        progress_percent=5,
        progress_detail={
            "phase": "paper_map",
            "current": 0,
            "total": len(document_ids),
            "unit": "documents",
            "message": "Mapping the selected papers before forming research questions.",
        },
    )
    pending_progress_updates: list[Any] = []
    progress_callback = _build_discovery_progress_callback(
        run_id,
        pending_progress_updates,
    )
    try:
        facts = await discover_and_replace_objective_candidates(
            collection_id,
            document_ids,
            progress_callback=progress_callback,
        )
        await _flush_progress_updates(pending_progress_updates)
        return await run_service.finish_run(
            run_id,
            status="completed",
            current_node="objectives_ready",
            progress_percent=100,
            progress_detail={
                "phase": "objectives_ready",
                "current": len(document_ids),
                "total": len(document_ids),
                "unit": "documents",
                "message": "Candidate research questions are ready for review.",
                "objective_count": len(facts.research_objectives),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Objective Discovery failed collection_id=%s run_id=%s",
            collection_id,
            run_id,
        )
        await _flush_progress_updates(pending_progress_updates)
        await run_service.finish_run(
            run_id,
            status="failed",
            current_node="failed",
            progress_percent=100,
            errors=[str(exc)],
            progress_detail={
                "phase": "failed",
                "unit": "documents",
                "message": "Research question formation failed. Retry it.",
            },
        )
        raise


async def discover_and_replace_objective_candidates(
    collection_id: str,
    document_ids: tuple[str, ...],
    progress_callback: ProgressCallback | None = None,
) -> ObjectiveFactSet:
    """Build maps for the selected papers, form candidates, and persist them."""

    document_inputs = await objective_input_service.resolve_prepared_document_inputs(
        collection_id,
        document_ids,
    )
    source_inputs = await objective_input_service.load_source_inputs(
        collection_id,
        document_inputs=document_inputs,
    )
    paper_maps = await objective_input_service.load_or_build_paper_maps(
        collection_id,
        document_inputs=document_inputs,
        source_inputs=source_inputs,
        progress_callback=progress_callback,
    )
    axis_equivalence_classifier = ResearchAxisEquivalenceClassifier(
        objective_input_service.get_response_client()
    )
    candidate_facts = await to_thread(
        objective_candidate_service.discover_candidate_facts,
        collection_id,
        paper_maps=paper_maps,
        document_inputs=document_inputs,
        axis_equivalence_classifier=axis_equivalence_classifier,
        progress_callback=progress_callback,
    )
    await ObjectiveRepo.replace(collection_id, candidate_facts)
    logger.info(
        "Research objective candidates finished collection_id=%s paper_map_count=%s objective_count=%s",
        collection_id,
        len(paper_maps),
        len(candidate_facts.research_objectives),
    )
    return candidate_facts


def _build_discovery_progress_callback(
    run_id: str,
    pending_updates: list[Any],
) -> ProgressCallback:
    loop = get_running_loop()
    progress_lock = Lock()
    last_percent = 5

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
                    pipeline_run_service.update_run(
                        run_id,
                        current_node=phase,
                        progress_percent=last_percent,
                        progress_detail=dict(progress),
                    ),
                    loop,
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


def _log_unexpected_failure(worker: AsyncTask[dict[str, Any]]) -> None:
    try:
        worker.result()
    except CancelledError:
        logger.info("Objective Discovery run cancelled during backend shutdown")
    except Exception:  # noqa: BLE001
        logger.exception("Objective Discovery run crashed after scheduling")
