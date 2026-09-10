from __future__ import annotations

from asyncio import (
    CancelledError,
    Task as AsyncTask,
    create_task,
    gather,
    get_running_loop,
    run_coroutine_threadsafe,
    to_thread,
    wrap_future,
)
from collections.abc import Coroutine
from hashlib import sha256
import json
import logging
from threading import Lock
from typing import Any, Callable

from application.core.objectives.discovery.axis_equivalence import (
    ResearchAxisEquivalenceClassifier,
)
from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from application.core.objectives.objective_input_service import (
    ObjectiveInputService,
    PAPER_RESEARCH_MAP_POLICY_VERSION,
)
from application.core.objectives.llm.structured_response import (
    StructuredResponseClient,
)
from application.pipeline import PipelineRunService
from domain.core import ObjectiveFactSet, PreparedDocumentInput
from application.repositories.objective_repository import ObjectiveRepository

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]


class ObjectiveDiscoveryService:
    """Form reviewable research-question candidates from selected paper maps."""

    def __init__(
        self,
        *,
        objective_input_service: ObjectiveInputService,
        objective_candidate_service: ObjectiveCandidateService,
        objective_repository: ObjectiveRepository,
        pipeline_run_service: PipelineRunService | None = None,
        response_client: StructuredResponseClient | None = None,
        axis_equivalence_classifier: ResearchAxisEquivalenceClassifier | None = None,
        worker_factory: Callable[[Coroutine[Any, Any, dict[str, Any]]], Any] = create_task,
    ) -> None:
        self.objective_input_service = objective_input_service
        self.objective_candidate_service = objective_candidate_service
        self.objective_repository = objective_repository
        self.pipeline_run_service = pipeline_run_service
        self._response_client = response_client
        self._axis_equivalence_classifier = axis_equivalence_classifier
        self._worker_factory = worker_factory
        self._workers: set[Any] = set()

    async def recover_interrupted_discoveries(self) -> int:
        """Make persisted discovery runs retryable after a backend restart."""

        run_service = self._require_pipeline_run_service()
        active_runs = [
            *await run_service.list_runs(status="queued"),
            *await run_service.list_runs(status="running"),
        ]
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
        self,
        collection_id: str,
        document_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        """Queue or reuse one collection-level Objective Discovery run."""

        document_inputs = await self.objective_input_service.resolve_prepared_document_inputs(
            collection_id,
            document_ids,
        )
        run_service = self._require_pipeline_run_service()
        run, created = await run_service.get_or_create_collection_run(
            collection_id=collection_id,
            pipeline_name="objective_discovery",
            input_fingerprint=self._objective_discovery_fingerprint(document_inputs),
            context={"document_ids": [item.document_id for item in document_inputs]},
        )
        if not created:
            return run

        coroutine = self.run_objective_discovery(
            run["run_id"],
            collection_id,
            tuple(item.document_id for item in document_inputs),
        )
        try:
            background = self._worker_factory(coroutine)
        except Exception as exc:  # noqa: BLE001
            coroutine.close()
            await run_service.finish_run(
                run["run_id"],
                status="failed",
                current_node="dispatch_failed",
                progress_percent=0,
                errors=["Research question formation could not be scheduled."],
            )
            raise RuntimeError(
                "Research question formation could not be scheduled. Retry it."
            ) from exc
        self._workers.add(background)
        background.add_done_callback(self._workers.discard)
        background.add_done_callback(self._log_unexpected_failure)
        return run

    async def run_objective_discovery(
        self,
        run_id: str,
        collection_id: str,
        document_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        """Execute one admitted discovery run and persist its state."""

        run_service = self._require_pipeline_run_service()
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
        progress_callback = self._build_discovery_progress_callback(
            run_id,
            pending_progress_updates,
        )
        try:
            facts = await self.discover_and_replace_objective_candidates(
                collection_id,
                document_ids,
                progress_callback=progress_callback,
            )
            await self._flush_progress_updates(pending_progress_updates)
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
            await self._flush_progress_updates(pending_progress_updates)
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
        self,
        collection_id: str,
        document_ids: tuple[str, ...],
        progress_callback: ProgressCallback | None = None,
    ) -> ObjectiveFactSet:
        """Build maps for the selected papers, form candidates, and persist them."""

        document_inputs = await self.objective_input_service.resolve_prepared_document_inputs(
            collection_id,
            document_ids,
        )
        source_inputs = await self.objective_input_service.load_source_inputs(
            collection_id,
            document_inputs=document_inputs,
        )
        paper_maps = await self.objective_input_service.load_or_build_paper_maps(
            collection_id,
            document_inputs=document_inputs,
            source_inputs=source_inputs,
            progress_callback=progress_callback,
        )
        if self._axis_equivalence_classifier is None:
            self._axis_equivalence_classifier = ResearchAxisEquivalenceClassifier(
                self._get_response_client()
            )
        candidate_facts = await to_thread(
            self.objective_candidate_service.discover_candidate_facts,
            collection_id,
            paper_maps=paper_maps,
            document_inputs=document_inputs,
            axis_equivalence_classifier=self._axis_equivalence_classifier,
            progress_callback=progress_callback,
        )
        await self.objective_repository.replace(collection_id, candidate_facts)
        logger.info(
            "Research objective candidates finished collection_id=%s paper_map_count=%s objective_count=%s",
            collection_id,
            len(paper_maps),
            len(candidate_facts.research_objectives),
        )
        return candidate_facts

    def _build_discovery_progress_callback(
        self,
        run_id: str,
        pending_updates: list[Any],
    ) -> ProgressCallback:
        loop = get_running_loop()
        progress_lock = Lock()
        last_percent = 5

        def update(progress: dict[str, Any]) -> None:
            nonlocal last_percent
            current = self._safe_progress_int(progress.get("current"))
            total = self._safe_progress_int(progress.get("total"))
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
                        self._require_pipeline_run_service().update_run(
                            run_id,
                            current_node=phase,
                            progress_percent=last_percent,
                            progress_detail=dict(progress),
                        ),
                        loop,
                    )
                )

        return update

    async def _flush_progress_updates(self, pending_updates: list[Any]) -> None:
        if pending_updates:
            await gather(
                *(wrap_future(item) for item in pending_updates),
                return_exceptions=True,
            )

    def _require_pipeline_run_service(self) -> PipelineRunService:
        if self.pipeline_run_service is None:
            raise RuntimeError("Objective Discovery run service is not configured")
        return self.pipeline_run_service

    @staticmethod
    def _objective_discovery_fingerprint(
        document_inputs: tuple[PreparedDocumentInput, ...],
    ) -> str:
        return sha256(
            json.dumps(
                {
                    "document_inputs": [item.to_record() for item in document_inputs],
                    "paper_map_policy_version": PAPER_RESEARCH_MAP_POLICY_VERSION,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _safe_progress_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _log_unexpected_failure(worker: AsyncTask[dict[str, Any]]) -> None:
        try:
            worker.result()
        except CancelledError:
            logger.info("Objective Discovery run cancelled during backend shutdown")
        except Exception:  # noqa: BLE001
            logger.exception("Objective Discovery run crashed after scheduling")

    def _get_response_client(self) -> StructuredResponseClient:
        if self._response_client is None:
            self._response_client = self.objective_input_service.response_client
        return self._response_client
