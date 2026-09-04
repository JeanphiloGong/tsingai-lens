from __future__ import annotations

from asyncio import (
    CancelledError,
    Semaphore,
    Task,
    create_task,
    gather,
    get_running_loop,
    run_coroutine_threadsafe,
    to_thread,
    wrap_future,
)
from collections.abc import Coroutine
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from threading import Lock
from typing import Any, Callable

from application.core.document_profiles.service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.core.objectives import property_matching
from application.core.objectives.analysis.evidence_materialization import (
    OBJECTIVE_EVIDENCE_MATERIALIZATION_VERSION,
    materialize_evidence,
)
from application.core.objectives.analysis.evidence_routing import (
    OBJECTIVE_EVIDENCE_ROUTE_PROMPT_VERSION,
    ObjectiveEvidenceRouter,
    route_sources,
)
from application.core.objectives.analysis.finding_synthesis import (
    FindingSynthesisService,
)
from application.core.objectives.analysis.paper_experiment import (
    PAPER_EXPERIMENT_RECONSTRUCTION_VERSION,
    reconstruct_paper_experiments,
)
from application.core.objectives.analysis.source_extraction import (
    OBJECTIVE_SOURCE_EXTRACTION_PROMPT_VERSION,
    ObjectiveSourceExtractor,
    extract_and_validate_source_facts,
)
from application.core.objectives.analysis.source_screening import (
    OBJECTIVE_PAPER_FRAME_PROMPT_VERSION,
    ObjectiveSourceScreener,
    screen_sources,
)
from application.core.objectives.analysis.source_validation import (
    OBJECTIVE_SOURCE_GROUNDING_VERSION,
)
from application.core.objectives.discovery.axis_equivalence import (
    ResearchAxisEquivalenceClassifier,
)
from application.core.objectives.discovery.signal_reconciliation import (
    PAPER_SIGNAL_RECONCILIATION_PROMPT_VERSION,
    PaperSignalReconciler,
)
from application.core.objectives.discovery.study_window import (
    PAPER_RESEARCH_MAP_PROMPT_VERSION,
    PAPER_SOURCE_SIGNAL_PROMPT_VERSION,
    PaperResearchMapExtractor,
)
from application.core.objectives.llm.structured_response import (
    StructuredResponseClient,
    build_default_structured_response_client,
)
from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from application.core.objectives.paper_research_map_service import (
    PaperResearchMapService,
)
from application.core.objectives.scope_screening import (
    ObjectiveScopePreview,
    screen_objective_scope,
)
from application.core.paper_facts.extraction import PaperFactsExtractor
from application.source.collection_service import CollectionService
from application.source.task_service import TaskService
from domain.core import (
    Finding,
    ObjectiveAnalysis,
    ObjectiveDocumentEvidence,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PaperResearchMap,
    PreparedDocumentInput,
    ResearchObjective,
    is_question_shaped_objective,
)
from domain.core.document_profile import DocumentProfile
from domain.ports import (
    ObjectiveRepository,
    PaperMapRepository,
    SourceArtifactRepository,
)
from domain.source import (
    SourceDocument,
    SourceReferenceSet,
    build_source_document_tree,
    render_markdown_table,
    render_plain_table_text,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]

_OBJECTIVE_DOCUMENT_EVIDENCE_VERSION = "objective-document-evidence.v1"
OBJECTIVE_DOCUMENT_EVIDENCE_SCIENTIFIC_VERSIONS = (
    ("paper_framing", OBJECTIVE_PAPER_FRAME_PROMPT_VERSION),
    ("evidence_routing", OBJECTIVE_EVIDENCE_ROUTE_PROMPT_VERSION),
    ("source_extraction", OBJECTIVE_SOURCE_EXTRACTION_PROMPT_VERSION),
    ("source_grounding", OBJECTIVE_SOURCE_GROUNDING_VERSION),
    ("paper_experiment", PAPER_EXPERIMENT_RECONSTRUCTION_VERSION),
    ("evidence_materialization", OBJECTIVE_EVIDENCE_MATERIALIZATION_VERSION),
)
_OBJECTIVE_DOCUMENT_MAX_CONCURRENCY = 4
_PAPER_MAP_DOCUMENT_MAX_CONCURRENCY = 10
# Paper reconstruction needs title/abstract/materials context, not a second
# copy of the entire document.  Keep this bounded so context recovery cannot
# inflate every result's lineage or analysis prompt.
_OBJECTIVE_DOCUMENT_CONTEXT_LIMIT = 96
PAPER_RESEARCH_MAP_POLICY_VERSION = "+".join(
    (
        "paper_research_map_selection.v2",
        PAPER_RESEARCH_MAP_PROMPT_VERSION,
        PAPER_SOURCE_SIGNAL_PROMPT_VERSION,
        PAPER_SIGNAL_RECONCILIATION_PROMPT_VERSION,
    )
)


def _paper_map_input_fingerprint(preparation_fingerprint: str) -> str:
    return sha256(
        json.dumps(
            {
                "preparation_fingerprint": preparation_fingerprint,
                "paper_map_policy_version": PAPER_RESEARCH_MAP_POLICY_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ObjectiveAnalysisArtifacts:
    """Canonical values produced by one versioned Objective analysis run."""

    contributions: tuple[PaperContribution, ...]
    evidence_records: tuple[ObjectiveEvidence, ...]
    findings: tuple[Finding, ...]
    model_name: str | None = None


@dataclass(frozen=True)
class ObjectiveDocumentEvidenceArtifacts:
    """Scientific inspection result for one Objective and one document."""

    contribution: PaperContribution
    evidence_records: tuple[ObjectiveEvidence, ...]


class ResearchObjectivesNotReadyError(RuntimeError):
    """Raised when a collection cannot yet serve research objectives."""

    def __init__(self, collection_id: str) -> None:
        self.collection_id = collection_id
        super().__init__(f"research objectives not ready: {collection_id}")


class ResearchObjectiveNotFoundError(FileNotFoundError):
    """Raised when one persisted research objective cannot be found."""

    def __init__(self, collection_id: str, objective_id: str) -> None:
        self.collection_id = collection_id
        self.objective_id = objective_id
        super().__init__(f"research objective not found: {collection_id}/{objective_id}")


class ObjectiveScopeNotReadyError(RuntimeError):
    """Raised when no collection Paper Maps are available for scope screening."""

    def __init__(self, collection_id: str) -> None:
        self.collection_id = collection_id
        super().__init__(f"objective paper scope not ready: {collection_id}")


class ResearchObjectiveService:
    """Discover objective candidates and generate analysis artifacts."""

    def __init__(
        self,
        collection_service: CollectionService,
        source_artifact_repository: SourceArtifactRepository,
        paper_map_repository: PaperMapRepository,
        objective_repository: ObjectiveRepository,
        document_profile_service: DocumentProfileService,
        finding_synthesis_service: FindingSynthesisService,
        objective_candidate_service: ObjectiveCandidateService,
        paper_map_service: PaperResearchMapService,
        response_client: StructuredResponseClient | None = None,
        axis_equivalence_classifier: ResearchAxisEquivalenceClassifier | None = None,
        objective_source_screener: ObjectiveSourceScreener | None = None,
        objective_evidence_router: ObjectiveEvidenceRouter | None = None,
        objective_source_extractor: ObjectiveSourceExtractor | None = None,
        paper_facts_extractor: PaperFactsExtractor | None = None,
        task_service: TaskService | None = None,
        task_factory: Callable[[Coroutine[Any, Any, dict[str, Any]]], Any] = create_task,
    ) -> None:
        self.collection_service = collection_service
        self._response_client = response_client
        self._axis_equivalence_classifier = axis_equivalence_classifier
        self._objective_source_screener = objective_source_screener
        self._objective_evidence_router = objective_evidence_router
        self._objective_source_extractor = objective_source_extractor
        self._paper_facts_extractor = paper_facts_extractor
        self.paper_map_repository = paper_map_repository
        self.objective_repository = objective_repository
        self.source_artifact_repository = source_artifact_repository
        self.document_profile_service = document_profile_service
        self.finding_synthesis_service = finding_synthesis_service
        self.objective_candidate_service = objective_candidate_service
        self.paper_map_service = paper_map_service
        self.task_service = task_service
        self._task_factory = task_factory
        self._discovery_tasks: set[Any] = set()

    async def recover_interrupted_discoveries(self) -> int:
        """Make persisted discovery tasks retryable after a backend restart."""

        task_service = self._require_task_service()
        active_tasks = [
            *await task_service.list_tasks(status="queued"),
            *await task_service.list_tasks(status="running"),
        ]
        interrupted_count = 0
        for task in active_tasks:
            if task.get("task_type") != "objective_discovery":
                continue
            await task_service.finish_task(
                task["task_id"],
                status="failed",
                current_stage="interrupted",
                progress_percent=task.get("progress_percent", 0),
                errors=[
                    *task.get("errors", ()),
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
                "Recovered interrupted Objective Discovery tasks count=%s",
                interrupted_count,
            )
        return interrupted_count

    # define a method that admits and schedules automatic objective discovery
    async def start_objective_discovery(
        self,
        collection_id: str,
        document_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        """
        Queue or reuse one collection-level Objective Discovery task.
        Args:
            collection_id: collection in which objectives will be discovered
            document_ids: exact papers selected for discovery
        Returns:
            dict[str, Any]: return the processing status
        """
        # validate and freeze the selected inputs
        document_inputs = await self.resolve_prepared_document_inputs(
            collection_id,
            document_ids,
        )

        # obtain the task service
        task_service = self._require_task_service()

        # create or reuse a task
        task, created = await task_service.get_or_create_collection_task(
            collection_id=collection_id,
            task_type="objective_discovery",
            input_fingerprint=self._objective_discovery_fingerprint(document_inputs),
            details={
                "document_ids": [item.document_id for item in document_inputs],
            },
        )
        if not created:
            return task

        coroutine = self.run_objective_discovery_task(
            task["task_id"],
            collection_id,
            tuple(item.document_id for item in document_inputs),
        )
        try:
            background = self._task_factory(coroutine)
        except Exception as exc:  # noqa: BLE001
            coroutine.close()
            await task_service.finish_task(
                task["task_id"],
                status="failed",
                current_stage="dispatch_failed",
                progress_percent=0,
                errors=["Research question formation could not be scheduled."],
            )
            raise RuntimeError(
                "Research question formation could not be scheduled. Retry it."
            ) from exc
        self._discovery_tasks.add(background)
        background.add_done_callback(self._discovery_tasks.discard)
        background.add_done_callback(self._log_unexpected_discovery_failure)
        return task

    async def run_objective_discovery_task(
        self,
        task_id: str,
        collection_id: str,
        document_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        """Execute one admitted Objective Discovery task and persist its state."""

        task_service = self._require_task_service()
        await task_service.update_task(
            task_id,
            status="running",
            current_stage="paper_map",
            progress_percent=5,
            progress_detail={
                "phase": "paper_map",
                "current": 0,
                "total": len(document_ids),
                "unit": "documents",
                "message": "Mapping the selected papers before forming research questions.",
            },
        )
        pending_progress_updates = []
        progress_callback = self._build_discovery_progress_callback(
            task_id,
            pending_progress_updates,
        )
        try:
            facts = await self.discover_and_replace_objective_candidates(
                collection_id,
                document_ids,
                progress_callback=progress_callback,
            )
            if pending_progress_updates:
                await gather(
                    *(wrap_future(item) for item in pending_progress_updates),
                    return_exceptions=True,
                )
            return await task_service.finish_task(
                task_id,
                status="completed",
                current_stage="objectives_ready",
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
                "Objective Discovery failed collection_id=%s task_id=%s",
                collection_id,
                task_id,
            )
            if pending_progress_updates:
                await gather(
                    *(wrap_future(item) for item in pending_progress_updates),
                    return_exceptions=True,
                )
            await task_service.finish_task(
                task_id,
                status="failed",
                current_stage="failed",
                progress_percent=100,
                errors=[str(exc)],
                progress_detail={
                    "phase": "failed",
                    "unit": "documents",
                    "message": "Research question formation failed. Retry it.",
                },
            )
            raise

    def _build_discovery_progress_callback(
        self,
        task_id: str,
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
                        self._require_task_service().update_task(
                            task_id,
                            current_stage=phase,
                            progress_percent=last_percent,
                            progress_detail=dict(progress),
                        ),
                        loop,
                    )
                )

        return update

    # define a helper to obtain the task service
    def _require_task_service(self) -> TaskService:
        if self.task_service is None:
            raise RuntimeError("Objective Discovery task service is not configured")
        return self.task_service

    # define a helper that calculate the fingerprint of the objective discovery
    @staticmethod
    def _objective_discovery_fingerprint(
        document_inputs: tuple[PreparedDocumentInput, ...],
    ) -> str:
        return sha256(
            json.dumps(
                {
                    "document_inputs": [
                        item.to_record() for item in document_inputs
                    ],
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
    def _log_unexpected_discovery_failure(task: Task[dict[str, Any]]) -> None:
        try:
            task.result()
        except CancelledError:
            logger.info("Objective Discovery task cancelled during backend shutdown")
        except Exception:  # noqa: BLE001
            logger.exception("Objective Discovery task crashed after scheduling")

    # define a main method for turning a completed collection build into candidate research objectives
    async def discover_and_replace_objective_candidates(
        self,
        collection_id: str,
        document_ids: tuple[str, ...],
        progress_callback: ProgressCallback | None = None,
    ) -> ObjectiveFactSet:
        """
        Load selected prepared papers
         -> read each current Paper Map
         -> aggregate relationships across papers
         -> persist completed Objective candidates
        Args:
            collection_id: the collection being studied
            document_ids: exact ready document scope to inspect
            progress_callback: reports progress to the collection task
        Returns:
            ObjectiveFactSet: selected inputs, candidate Objectives, and relationship dispositions.
        """
        document_inputs = await self.resolve_prepared_document_inputs(
            collection_id,
            document_ids,
        )
        source_inputs = await self._load_objective_source_inputs(
            collection_id,
            document_inputs=document_inputs,
        )
        paper_maps = await self._load_or_build_paper_maps(
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
        await self.objective_repository.replace(
            collection_id,
            candidate_facts,
        )
        research_objectives = candidate_facts.research_objectives
        logger.info(
            "Research objective candidates finished collection_id=%s paper_map_count=%s objective_count=%s",
            collection_id,
            len(paper_maps),
            len(research_objectives),
        )
        return candidate_facts

    async def create_chat_assisted_candidate(
        self,
        *,
        collection_id: str,
        user_id: str,
        tool_call_id: str,
        question: str,
        material_scope: list[str],
        variables: list[str],
        outcomes: list[str],
        mechanisms: list[str],
        constraints: list[str],
        requested_comparator: str | None,
        seed_document_ids: list[str],
        excluded_document_ids: list[str],
    ) -> ResearchObjective:
        """Persist one user-approved, explicitly untested research question."""

        await self.collection_service.get_collection_for_user(collection_id, user_id)
        if len(outcomes) != 1:
            raise ValueError("chat-assisted objective requires exactly one outcome")
        objective = ResearchObjective.from_mapping(
            {
                "collection_id": collection_id,
                "question": question,
                "material_scope": material_scope,
                "variables": variables,
                "outcomes": outcomes,
                "mechanisms": mechanisms,
                "constraints": constraints,
                "requested_comparator": requested_comparator,
                "seed_document_ids": seed_document_ids,
                "excluded_document_ids": excluded_document_ids,
                "confidence": 0,
                "origin": "chat_assisted",
                "created_by_user_id": user_id,
                "created_by_tool_call_id": tool_call_id,
            }
        )
        if not is_question_shaped_objective(objective):
            raise ValueError("chat-assisted objective question is not question-shaped")

        for document_id in dict.fromkeys(
            (*objective.seed_document_ids, *objective.excluded_document_ids)
        ):
            await self.collection_service.get_document(collection_id, document_id)
        objective = replace(
            objective,
            confidence=0,
            reason=(
                "User-approved untested research question with "
                f"{len(objective.seed_document_ids)} question-source paper(s); "
                "question provenance is not Evidence and analysis has not tested support."
                if objective.seed_document_ids
                else "User-approved untested research question; no question-source "
                "paper was recorded and analysis has not tested Evidence support."
            ),
        )
        return await self.objective_repository.create_authored_candidate(
            objective,
            created_by_user_id=user_id,
            created_by_tool_call_id=tool_call_id,
        )

    async def preview_objective_scope(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveScopePreview:
        """Screen every current collection Paper Map for one persisted Objective."""

        await self.collection_service.get_collection(collection_id)
        objective = await self.objective_repository.read_objective(
            collection_id,
            objective_id,
        )
        if objective is None:
            raise ResearchObjectiveNotFoundError(collection_id, objective_id)
        paper_maps = await self.paper_map_repository.list_collection(collection_id)
        if not paper_maps:
            raise ObjectiveScopeNotReadyError(collection_id)
        return screen_objective_scope(paper_maps, objective=objective)

    async def generate_objective_analysis_artifacts(
        self,
        collection_id: str,
        analysis: ObjectiveAnalysis,
        progress_callback: ProgressCallback | None = None,
    ) -> ObjectiveAnalysisArtifacts:
        if analysis.collection_id != collection_id:
            raise ValueError("analysis belongs to another collection")
        active_objective = await self.objective_repository.read_objective(
            collection_id, analysis.objective_id
        )
        if active_objective is None:
            raise ResearchObjectiveNotFoundError(collection_id, analysis.objective_id)
        if active_objective.active_analysis_version != analysis.analysis_version:
            raise ValueError("analysis is not the active objective version")
        objective_inputs = await self._build_objective_analysis_inputs(
            collection_id,
            document_inputs=analysis.document_inputs,
        )
        response_client = objective_inputs["response_client"]
        if self._objective_source_screener is None:
            self._objective_source_screener = ObjectiveSourceScreener(response_client)
        if self._objective_evidence_router is None:
            self._objective_evidence_router = ObjectiveEvidenceRouter(response_client)
        if self._objective_source_extractor is None:
            self._objective_source_extractor = ObjectiveSourceExtractor(response_client)
        model_name = str(
            getattr(response_client, "model", None) or analysis.model_name or ""
        ).strip()
        if not model_name:
            raise ValueError("Objective document Evidence requires model identity")

        extraction_limit = Semaphore(_OBJECTIVE_DOCUMENT_MAX_CONCURRENCY)
        document_count = len(analysis.document_inputs)

        async def inspect_document(
            position: int,
            document_input: PreparedDocumentInput,
        ) -> ObjectiveDocumentEvidenceArtifacts:
            input_fingerprint = self._document_evidence_input_fingerprint(
                objective=active_objective,
                document_input=document_input,
                model_name=model_name,
                extraction_version=_OBJECTIVE_DOCUMENT_EVIDENCE_VERSION,
            )
            checkpoint = await self.objective_repository.read_document_evidence(
                collection_id,
                active_objective.objective_id,
                document_input.document_id,
                input_fingerprint,
            )
            if checkpoint is not None and checkpoint.status == "succeeded":
                return self._rebind_document_evidence(checkpoint, analysis)

            running = ObjectiveDocumentEvidence.start(
                collection_id=collection_id,
                objective_id=active_objective.objective_id,
                document_id=document_input.document_id,
                input_fingerprint=input_fingerprint,
                analysis_version=analysis.analysis_version,
                extraction_version=_OBJECTIVE_DOCUMENT_EVIDENCE_VERSION,
                model_name=model_name,
                started_at=datetime.now(timezone.utc),
            )
            await self.objective_repository.write_document_evidence(running)
            document_objective_inputs = self._objective_inputs_for_document(
                collection_id,
                objective_inputs,
                document_input.document_id,
            )

            document_progress_callback: ProgressCallback | None = None
            if progress_callback is not None:

                def document_progress_callback(detail: dict[str, Any]) -> None:
                    progress_callback(
                        {
                            **detail,
                            "current": position,
                            "total": document_count,
                            "active_document_id": document_input.document_id,
                        }
                    )

            try:
                async with extraction_limit:
                    artifacts = await to_thread(
                        self._generate_document_evidence,
                        collection_id=collection_id,
                        analysis=analysis,
                        objective=active_objective,
                        objective_inputs=document_objective_inputs,
                        progress_callback=document_progress_callback,
                    )
                checkpoint = running.succeed(
                    contribution=artifacts.contribution,
                    evidence_records=artifacts.evidence_records,
                    completed_at=datetime.now(timezone.utc),
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Objective document Evidence extraction failed "
                    "collection_id=%s objective_id=%s document_id=%s",
                    collection_id,
                    active_objective.objective_id,
                    document_input.document_id,
                )
                checkpoint = running.fail(
                    contribution=self._failed_document_contribution(
                        collection_id=collection_id,
                        objective_id=active_objective.objective_id,
                        analysis_version=analysis.analysis_version,
                        document_id=document_input.document_id,
                    ),
                    error_code="document_evidence_extraction_failed",
                    error_message=str(exc) or exc.__class__.__name__,
                    completed_at=datetime.now(timezone.utc),
                )
            await self.objective_repository.write_document_evidence(checkpoint)
            return self._rebind_document_evidence(checkpoint, analysis)

        document_artifacts = await gather(
            *(
                inspect_document(position, document_input)
                for position, document_input in enumerate(
                    analysis.document_inputs,
                    start=1,
                )
            )
        )
        contributions = tuple(item.contribution for item in document_artifacts)
        evidence_records = tuple(
            evidence
            for item in document_artifacts
            for evidence in item.evidence_records
        )
        findings = await to_thread(
            self.finding_synthesis_service.synthesize,
            collection_id=collection_id,
            objective=active_objective,
            analysis=analysis,
            contributions=contributions,
            evidence_records=evidence_records,
        )
        return ObjectiveAnalysisArtifacts(
            contributions=contributions,
            evidence_records=evidence_records,
            findings=findings,
            model_name=model_name,
        )

    def _generate_document_evidence(
        self,
        *,
        collection_id: str,
        analysis: ObjectiveAnalysis,
        objective: ResearchObjective,
        objective_inputs: dict[str, Any],
        progress_callback: ProgressCallback | None,
    ) -> ObjectiveDocumentEvidenceArtifacts:
        screened_sources = screen_sources(
            collection_id=collection_id,
            source_screener=self._objective_source_screener,
            objectives=(objective,),
            paper_maps=objective_inputs["paper_maps"],
            documents=objective_inputs["documents"],
            profiles_by_document_id=objective_inputs["profiles_by_document_id"],
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            document_trees_by_document_id=objective_inputs[
                "document_trees_by_document_id"
            ],
            progress_callback=progress_callback,
        )
        source_inspection_routes = route_sources(
            collection_id=collection_id,
            evidence_router=self._objective_evidence_router,
            objectives=(objective,),
            objective_paper_frames=screened_sources,
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            document_trees_by_document_id=objective_inputs[
                "document_trees_by_document_id"
            ],
            progress_callback=progress_callback,
        )
        validated_source_facts = extract_and_validate_source_facts(
            collection_id=collection_id,
            source_extractor=self._objective_source_extractor,
            paper_facts_extractor=self._paper_facts_extractor,
            objectives=(objective,),
            objective_paper_frames=screened_sources,
            objective_evidence_routes=source_inspection_routes,
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            document_trees_by_document_id=objective_inputs[
                "document_trees_by_document_id"
            ],
            table_cells_by_document_id=objective_inputs[
                "table_cells_by_document_id"
            ],
            progress_callback=progress_callback,
        )
        paper_evidence_drafts = reconstruct_paper_experiments(
            collection_id=collection_id,
            source_facts=validated_source_facts,
            objectives=(objective,),
            document_contexts=self._document_contexts_for_evidence(objective_inputs),
        )
        evidence_records, contributions = materialize_evidence(
            collection_id=collection_id,
            analysis=analysis,
            objective=objective,
            drafts=paper_evidence_drafts,
            paper_maps=objective_inputs["paper_maps"],
            frames=screened_sources,
            routes=source_inspection_routes,
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            figures_by_document_id=objective_inputs["figures_by_document_id"],
            document_trees_by_document_id=objective_inputs[
                "document_trees_by_document_id"
            ],
        )
        if len(contributions) != 1:
            raise RuntimeError(
                "document Evidence extraction requires one paper contribution"
            )
        return ObjectiveDocumentEvidenceArtifacts(
            contribution=contributions[0],
            evidence_records=evidence_records,
        )

    @staticmethod
    def _document_contexts_for_evidence(
        objective_inputs: dict[str, Any],
    ) -> dict[str, tuple[dict[str, Any], ...]]:
        """Expose bounded, resolvable same-paper context to reconstruction.

        A result is often separated from its material or condition by a table
        or figure caption.  Keep those artifacts in the same context stream as
        text blocks so reconstruction has the information a researcher would
        have while reading the paper.  Source identity remains explicit and
        no context is imported from another document.
        """

        contexts: dict[str, tuple[dict[str, Any], ...]] = {}
        blocks_by_document_id = objective_inputs.get("blocks_by_document_id", {})
        tables_by_document_id = objective_inputs.get("tables_by_document_id", {})
        figures_by_document_id = objective_inputs.get("figures_by_document_id", {})
        document_ids = tuple(
            dict.fromkeys(
                (
                    *blocks_by_document_id.keys(),
                    *tables_by_document_id.keys(),
                    *figures_by_document_id.keys(),
                )
            )
        )
        for document_id in document_ids:
            ranked: list[tuple[int, int, dict[str, Any]]] = []
            blocks = blocks_by_document_id.get(document_id, ())
            for position, block in enumerate(blocks):
                text = str(getattr(block, "text", "") or "").strip()
                source_ref = str(getattr(block, "block_id", "") or "").strip()
                if not text or not source_ref:
                    continue
                block_type = str(getattr(block, "block_type", "") or "").casefold()
                heading = str(getattr(block, "heading_path", "") or "").casefold()
                priority = (
                    0
                    if block_type == "title"
                    else 1
                    if "abstract" in heading
                    else 2
                    if any(
                        marker in heading
                        for marker in ("method", "material", "experimental")
                    )
                    else 3
                )
                ranked.append(
                    (
                        priority,
                        position,
                        {
                            "source_kind": "text_window",
                            "source_ref": source_ref,
                            "page": getattr(block, "page", None),
                            "heading_path": getattr(block, "heading_path", None),
                            "text": text,
                        },
                    )
                )
            for position, table in enumerate(
                tables_by_document_id.get(document_id, ())
            ):
                table_id = str(getattr(table, "table_id", "") or "").strip()
                if not table_id:
                    continue
                caption_text = str(getattr(table, "caption_text", "") or "").strip()
                heading_path = getattr(table, "heading_path", None)
                column_headers = tuple(
                    str(value).strip()
                    for value in (getattr(table, "column_headers", ()) or ())
                    if str(value).strip()
                )
                matrix = tuple(
                    tuple(str(cell).strip() for cell in row)
                    for row in (getattr(table, "table_matrix", ()) or ())
                    if isinstance(row, (list, tuple))
                )
                table_markdown = ""
                table_text = ""
                table_visual_text = ""
                to_record = getattr(table, "to_record", None)
                if callable(to_record):
                    record = to_record()
                    table_markdown = str(record.get("table_markdown") or "").strip()
                    table_text = str(record.get("table_text") or "").strip()
                    metadata = record.get("metadata")
                    if isinstance(metadata, dict):
                        table_visual_text = str(
                            metadata.get("visual_text") or ""
                        ).strip()
                if not table_markdown:
                    table_markdown = str(
                        render_markdown_table(
                            [list(row) for row in matrix],
                            list(column_headers),
                            header_row_count=int(
                                getattr(table, "header_row_count", 1) or 0
                            ),
                        )
                        or ""
                    ).strip()
                if not table_text:
                    table_text = str(
                        render_plain_table_text([list(row) for row in matrix]) or ""
                    ).strip()
                text = "\n".join(
                    part
                    for part in (
                        caption_text,
                        table_markdown or table_text,
                        table_visual_text,
                    )
                    if part
                ).strip()
                if not text:
                    continue
                heading = str(heading_path or "").casefold()
                caption = caption_text.casefold()
                priority = (
                    2
                    if any(
                        marker in heading or marker in caption
                        for marker in (
                            "result",
                            "mechanical",
                            "microstructure",
                            "material",
                            "method",
                            "experimental",
                        )
                    )
                    else 3
                )
                ranked.append(
                    (
                        priority,
                        len(blocks) + position,
                        {
                            "source_kind": "table",
                            "source_ref": table_id,
                            "page": getattr(table, "page", None),
                            "heading_path": heading_path,
                            "caption_text": caption_text or None,
                            "column_headers": list(column_headers),
                            "table_matrix": [list(row) for row in matrix],
                            "table_markdown": table_markdown or None,
                            "table_visual_text": table_visual_text or None,
                            "table_text": table_text or None,
                            "text": text,
                        },
                    )
                )
            for position, figure in enumerate(
                figures_by_document_id.get(document_id, ())
            ):
                figure_id = str(getattr(figure, "figure_id", "") or "").strip()
                caption_text = str(getattr(figure, "caption_text", "") or "").strip()
                if not figure_id or not caption_text:
                    continue
                heading_path = getattr(figure, "heading_path", None)
                heading = str(heading_path or "").casefold()
                caption = caption_text.casefold()
                priority = (
                    2
                    if any(
                        marker in heading or marker in caption
                        for marker in (
                            "result",
                            "mechanical",
                            "microstructure",
                            "material",
                            "method",
                            "experimental",
                        )
                    )
                    else 3
                )
                ranked.append(
                    (
                        priority,
                        len(blocks) + len(tables_by_document_id.get(document_id, ())) + position,
                        {
                            "source_kind": "figure",
                            "source_ref": figure_id,
                            "page": getattr(figure, "page", None),
                            "heading_path": heading_path,
                            "figure_label": getattr(figure, "figure_label", None),
                            "caption_text": caption_text,
                            "text": caption_text,
                        },
                    )
                )
            ranked.sort(key=lambda item: (item[0], item[1]))
            contexts[document_id] = tuple(
                item[2] for item in ranked[:_OBJECTIVE_DOCUMENT_CONTEXT_LIMIT]
            )
        return contexts

    @staticmethod
    def _document_evidence_input_fingerprint(
        *,
        objective: ResearchObjective,
        document_input: PreparedDocumentInput,
        model_name: str,
        extraction_version: str,
        scientific_versions: tuple[tuple[str, str], ...] = (
            OBJECTIVE_DOCUMENT_EVIDENCE_SCIENTIFIC_VERSIONS
        ),
    ) -> str:
        payload = {
            "objective": {
                "question": objective.question,
                "material_scope": list(objective.material_scope),
                "variables": list(objective.variables),
                "outcomes": list(objective.outcomes),
                "mechanisms": list(objective.mechanisms),
                "constraints": list(objective.constraints),
                "requested_comparator": objective.requested_comparator,
                "source_relationship_ids": list(objective.source_relationship_ids),
                "excluded_document_ids": list(objective.excluded_document_ids),
            },
            "document": document_input.to_record(),
            "extraction_version": extraction_version,
            "scientific_versions": dict(scientific_versions),
            "model_name": model_name,
        }
        return sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _objective_inputs_for_document(
        collection_id: str,
        objective_inputs: dict[str, Any],
        document_id: str,
    ) -> dict[str, Any]:
        documents = tuple(
            item
            for item in objective_inputs["documents"]
            if item.document_id == document_id
        )
        paper_maps = tuple(
            item
            for item in objective_inputs["paper_maps"]
            if item.document_id == document_id
        )
        if len(documents) != 1 or len(paper_maps) != 1:
            raise ResearchObjectivesNotReadyError(collection_id)
        return {
            "documents": documents,
            "paper_maps": paper_maps,
            "profiles_by_document_id": {
                document_id: objective_inputs["profiles_by_document_id"][document_id]
            },
            "blocks_by_document_id": {
                document_id: objective_inputs["blocks_by_document_id"][document_id]
            },
            "tables_by_document_id": {
                document_id: objective_inputs["tables_by_document_id"][document_id]
            },
            "table_cells_by_document_id": {
                document_id: objective_inputs["table_cells_by_document_id"][document_id]
            },
            "figures_by_document_id": {
                document_id: objective_inputs["figures_by_document_id"][document_id]
            },
            "document_trees_by_document_id": {
                document_id: objective_inputs["document_trees_by_document_id"][
                    document_id
                ]
            },
            "response_client": objective_inputs["response_client"],
        }

    @staticmethod
    def _rebind_document_evidence(
        checkpoint: ObjectiveDocumentEvidence,
        analysis: ObjectiveAnalysis,
    ) -> ObjectiveDocumentEvidenceArtifacts:
        if checkpoint.contribution is None:
            raise ValueError("terminal document Evidence lacks a contribution")
        return ObjectiveDocumentEvidenceArtifacts(
            contribution=replace(
                checkpoint.contribution,
                analysis_version=analysis.analysis_version,
            ),
            evidence_records=tuple(
                replace(record, analysis_version=analysis.analysis_version)
                for record in checkpoint.evidence_records
            ),
        )

    @staticmethod
    def _failed_document_contribution(
        *,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        document_id: str,
    ) -> PaperContribution:
        return PaperContribution(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=analysis_version,
            document_id=document_id,
            analysis_status="failed",
            relevance="uncertain",
            paper_role="uncertain",
            contribution_summary=None,
            material_match=(),
            changed_variables=(),
            measured_property_scope=(),
            test_environment_scope=(),
            exclusion_reason=None,
            warnings=(
                "Evidence extraction failed for this paper; retry the analysis.",
            ),
            confidence=0,
        )

    async def _build_objective_analysis_inputs(
        self,
        collection_id: str,
        *,
        document_inputs: tuple[PreparedDocumentInput, ...],
    ) -> dict[str, Any]:
        source_inputs = await self._load_objective_source_inputs(
            collection_id,
            document_inputs=document_inputs,
        )
        paper_maps = await self._load_or_build_paper_maps(
            collection_id,
            document_inputs=document_inputs,
            source_inputs=source_inputs,
        )
        return {
            **source_inputs,
            "paper_maps": paper_maps,
        }

    async def _load_or_build_paper_maps(
        self,
        collection_id: str,
        *,
        document_inputs: tuple[PreparedDocumentInput, ...],
        source_inputs: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[PaperResearchMap, ...]:
        document_ids = tuple(item.document_id for item in document_inputs)
        existing_maps = await self.paper_map_repository.list_collection(
            collection_id,
            document_ids,
        )
        maps_by_document_id = {item.document_id: item for item in existing_maps}
        inputs_by_document_id = {
            item.document_id: item for item in document_inputs
        }
        map_input_fingerprints = {
            document_id: _paper_map_input_fingerprint(item.preparation_fingerprint)
            for document_id, item in inputs_by_document_id.items()
        }
        documents_by_id = {
            document.document_id: document
            for document in source_inputs["documents"]
        }
        response_client = source_inputs["response_client"]
        build_limit = Semaphore(_PAPER_MAP_DOCUMENT_MAX_CONCURRENCY)
        completed_map_count = 0

        async def build_map(document_id: str) -> None:
            nonlocal completed_map_count

            def report_document_progress(detail: dict[str, Any]) -> None:
                if progress_callback is None:
                    return
                progress_callback(
                    {
                        **detail,
                        "current": completed_map_count,
                        "total": len(stale_document_ids),
                        "unit": "documents",
                        "active_document_id": document_id,
                    }
                )

            async with build_limit:
                paper_map = await to_thread(
                    self.paper_map_service.build_document_paper_map,
                    collection_id,
                    document=documents_by_id[document_id],
                    profile=source_inputs["profiles_by_document_id"][document_id],
                    document_tree=source_inputs["document_trees_by_document_id"][
                        document_id
                    ],
                    paper_map_extractor=PaperResearchMapExtractor(response_client),
                    signal_reconciler=PaperSignalReconciler(response_client),
                    progress_callback=report_document_progress,
                )
            paper_map = replace(
                paper_map,
                input_fingerprint=map_input_fingerprints[document_id],
            )
            await self.paper_map_repository.replace(collection_id, paper_map)
            maps_by_document_id[document_id] = paper_map
            completed_map_count += 1
            if progress_callback is not None:
                progress_callback(
                    {
                        "phase": "paper_research_map_completed",
                        "current": completed_map_count,
                        "total": len(stale_document_ids),
                        "unit": "documents",
                        "message": "Mapped one selected paper for research question formation.",
                        "active_document_id": document_id,
                    }
                )

        stale_document_ids = tuple(
            document_id
            for document_id in document_ids
            if maps_by_document_id.get(document_id) is None
            or maps_by_document_id[document_id].input_fingerprint
            != map_input_fingerprints[document_id]
        )
        await gather(*(build_map(document_id) for document_id in stale_document_ids))
        return tuple(maps_by_document_id[document_id] for document_id in document_ids)

    # Define a helper that loads one exact prepared-document selection and
    # prepares the data structures shared by Objective discovery and analysis.
    async def _load_objective_source_inputs(
        self,
        collection_id: str,
        *,
        document_inputs: tuple[PreparedDocumentInput, ...],
    ) -> dict[str, Any]:
        """
        Args:
            collection_id: identifies the literature collection
            document_inputs: exact prepared document states selected for this work
        Returns:
            returns a heterogeneous dictionary containing several data types
        """
        current_inputs = await self.resolve_prepared_document_inputs(
            collection_id,
            tuple(item.document_id for item in document_inputs),
        )
        if current_inputs != document_inputs:
            raise ValueError(
                "prepared document input is stale; select the current document state"
            )
        # load document profile
        try:
            # Profiles answer paper-level class ification questions
            # 1. Is this an experimental paper?
            # 2. Is it a review?
            # 3. Was parsing uncertain?
            # 4. What is the profile confidence
            profiles: tuple[DocumentProfile, ...] = await self.document_profile_service.read_document_profiles(
                collection_id,
                tuple(item.document_id for item in document_inputs),
            )
        except DocumentProfilesNotReadyError as exc:
            raise ResearchObjectivesNotReadyError(collection_id) from exc
        if {profile.document_id for profile in profiles} != {
            item.document_id for item in document_inputs
        }:
            raise ResearchObjectivesNotReadyError(collection_id)

        # Load parsed documents
        try:
            # Each SourceDocument contains the parsed paper and its Source objects:
            # 1.blocks
            # 2.tables
            # 3.table rows
            # 4.table cells
            # 5.figures
            documents = await self._load_source_documents(
                collection_id,
                document_inputs=document_inputs,
            )
        except FileNotFoundError as exc:
            raise ResearchObjectivesNotReadyError(collection_id) from exc

        document_ids = tuple(document.document_id for document in documents)
        references = await self.source_artifact_repository.read_collection_references(
            collection_id,
            document_ids,
        )
        document_trees_by_document_id = {}
        for document in documents:
            document_references = self._references_for_document(
                references,
                document.document_id,
            )
            document_trees_by_document_id[document.document_id] = (
                build_source_document_tree(
                    collection_id=collection_id,
                    document=document,
                    blocks=document.blocks,
                    tables=document.tables,
                    figures=document.figures,
                    references=document_references,
                )
            )
        return {
            "documents": documents,
            "profiles_by_document_id": {
                profile.document_id: profile
                for profile in profiles
            },
            "blocks_by_document_id": {
                document.document_id: list(document.blocks)
                for document in documents
            },
            "tables_by_document_id": {
                document.document_id: list(document.tables)
                for document in documents
            },
            "table_cells_by_document_id": {
                document.document_id: list(document.table_cells)
                for document in documents
            },
            "figures_by_document_id": {
                document.document_id: list(document.figures)
                for document in documents
            },
            "document_trees_by_document_id": document_trees_by_document_id,
            "response_client": self._get_response_client(),
        }

    def _get_response_client(self) -> StructuredResponseClient:
        if self._response_client is None:
            self._response_client = build_default_structured_response_client()
        return self._response_client

    async def _load_source_documents(
        self,
        collection_id: str,
        *,
        document_inputs: tuple[PreparedDocumentInput, ...],
    ) -> tuple[SourceDocument, ...]:
        document_ids = tuple(item.document_id for item in document_inputs)
        documents = await self.source_artifact_repository.read_documents(
            collection_id,
            document_ids,
        )
        if tuple(document.document_id for document in documents) != document_ids:
            raise FileNotFoundError(f"source artifacts not ready: {collection_id}")
        return documents

    @staticmethod
    def _references_for_document(
        references: SourceReferenceSet,
        document_id: str,
    ) -> SourceReferenceSet:
        entries = tuple(
            item for item in references.entries if item.document_id == document_id
        )
        reference_ids = {item.reference_id for item in entries}
        return SourceReferenceSet(
            entries=entries,
            mentions=tuple(
                item for item in references.mentions if item.document_id == document_id
            ),
            resolutions=tuple(
                item
                for item in references.resolutions
                if item.reference_id in reference_ids
            ),
            candidates=tuple(
                item
                for item in references.candidates
                if item.reference_id in reference_ids
            ),
        )

    # define a method that converts a user-provided list of documents IDs into the exact prepared-document records that a research operation is allowed to consume
    async def resolve_prepared_document_inputs(
        self,
        collection_id: str,
        document_ids: tuple[str, ...],
    ) -> tuple[PreparedDocumentInput, ...]:
        """
        Args:
            collection_id: the identifies the literature collection
            document_ids: the explicit scope selected for the operation
        """
        # reject an empty selection
        if not document_ids:
            raise ValueError("Objective discovery requires at least one document")

        # reject duplicate IDs
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("Objective discovery document IDs must be unique")

        # create a mutable local result list
        inputs: list[PreparedDocumentInput] = []

        # process every selected document
        for document_id in document_ids:
            # load the current document record
            document = await self.collection_service.get_document(
                collection_id,
                document_id,
            )

            # require preparation completion
            if document.status != "ready" or not document.preparation_fingerprint:
                raise ResearchObjectivesNotReadyError(collection_id)

            # capture a prepared input snapshot
            inputs.append(
                PreparedDocumentInput(
                    document_id=document_id,
                    preparation_fingerprint=document.preparation_fingerprint,
                )
            )

        # return an immutable ordered tuple
        return tuple(inputs)


    def _append_unique_axis(
        self,
        target: list[str],
        seen: set[str],
        value: Any,
    ) -> None:
        text = str(value or "").strip()
        if not text:
            return
        key = property_matching.axis_key(text)
        if key in seen:
            return
        seen.add(key)
        target.append(text)

    def _group_by_document_id(self, values: tuple[Any, ...]) -> dict[str, list[Any]]:
        grouped: dict[str, list[Any]] = {}
        for value in values:
            document_id = str(getattr(value, "document_id", "") or "")
            if not document_id:
                continue
            grouped.setdefault(document_id, []).append(value)
        return grouped


__all__ = [
    "OBJECTIVE_DOCUMENT_EVIDENCE_SCIENTIFIC_VERSIONS",
    "ResearchObjectiveService",
    "ResearchObjectivesNotReadyError",
]
