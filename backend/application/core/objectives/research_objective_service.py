from __future__ import annotations

from asyncio import Semaphore, gather, to_thread
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from typing import Any, Callable

from application.core.document_profiles.service import (
    DocumentProfileService,
    DocumentProfilesNotReadyError,
)
from application.core.objectives import property_matching
from application.core.objectives.analysis.evidence_materialization import (
    materialize_evidence,
)
from application.core.objectives.analysis.evidence_routing import (
    ObjectiveEvidenceRouter,
    route_sources,
)
from application.core.objectives.analysis.finding_synthesis import (
    FindingSynthesisService,
)
from application.core.objectives.analysis.paper_experiment import (
    reconstruct_paper_experiments,
)
from application.core.objectives.analysis.source_extraction import (
    ObjectiveSourceExtractor,
    extract_and_validate_source_facts,
)
from application.core.objectives.analysis.source_screening import (
    ObjectiveSourceScreener,
    screen_sources,
)
from application.core.objectives.discovery.axis_equivalence import (
    ResearchAxisEquivalenceClassifier,
)
from application.core.objectives.llm.structured_response import (
    StructuredResponseClient,
    build_default_structured_response_client,
)
from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from application.core.paper_facts.extraction import PaperFactsExtractor
from application.source.artifact_input_service import load_document_tree
from application.source.collection_service import CollectionService
from domain.core import (
    Finding,
    ObjectiveAnalysis,
    ObjectiveDocumentEvidence,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
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
from domain.source import SourceDocument

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]

_OBJECTIVE_DOCUMENT_EVIDENCE_VERSION = "objective-document-evidence.v1"
_OBJECTIVE_DOCUMENT_MAX_CONCURRENCY = 4


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
        response_client: StructuredResponseClient | None = None,
        axis_equivalence_classifier: ResearchAxisEquivalenceClassifier | None = None,
        objective_source_screener: ObjectiveSourceScreener | None = None,
        objective_evidence_router: ObjectiveEvidenceRouter | None = None,
        objective_source_extractor: ObjectiveSourceExtractor | None = None,
        paper_facts_extractor: PaperFactsExtractor | None = None,
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
        paper_maps = await self.paper_map_repository.list_collection(
            collection_id,
            document_ids,
        )
        maps_by_document_id = {item.document_id: item for item in paper_maps}
        missing_maps = [
            document_id
            for document_id in document_ids
            if document_id not in maps_by_document_id
        ]
        if missing_maps:
            raise ResearchObjectivesNotReadyError(collection_id)
        paper_maps = tuple(
            maps_by_document_id[document_id] for document_id in document_ids
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

        await self.collection_service.get_collection_for_user(
            collection_id, user_id
        )
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

        facts = await self.objective_repository.read(collection_id)
        if not facts.research_objectives_ready:
            raise ResearchObjectivesNotReadyError(collection_id)
        objective = replace(
            objective,
            confidence=0,
            reason=(
                "User-approved untested research question with "
                f"{len(objective.seed_document_ids)} paper scope hypothesis(es); "
                "Paper Map scope is not Evidence and analysis has not tested support."
                if objective.seed_document_ids
                else "User-approved untested research question; paper scope and "
                "Evidence support have not been established."
            ),
        )
        return await self.objective_repository.create_authored_candidate(
            objective,
            created_by_user_id=user_id,
            created_by_tool_call_id=tool_call_id,
        )

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
    def _document_evidence_input_fingerprint(
        *,
        objective: ResearchObjective,
        document_input: PreparedDocumentInput,
        model_name: str,
        extraction_version: str,
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
        document_ids = tuple(item.document_id for item in document_inputs)
        paper_maps = await self.paper_map_repository.list_collection(
            collection_id,
            document_ids,
        )
        maps_by_document_id = {item.document_id: item for item in paper_maps}
        if any(document_id not in maps_by_document_id for document_id in document_ids):
            raise ResearchObjectivesNotReadyError(collection_id)
        return {
            **source_inputs,
            "paper_maps": tuple(
                maps_by_document_id[document_id] for document_id in document_ids
            ),
        }

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

        # Load structural trees
        # For every document, it loads a SourceDocumentTree
        document_trees_by_document_id = {
            document.document_id: await load_document_tree(
                collection_id,
                document.document_id,
                self.source_artifact_repository,
            )
            for document in documents
        }
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
        documents: list[SourceDocument] = []
        for item in document_inputs:
            document = await self.source_artifact_repository.read_document(
                collection_id,
                item.document_id,
            )
            if document is not None:
                documents.append(document)
        if len(documents) != len(document_inputs):
            raise FileNotFoundError(f"source artifacts not ready: {collection_id}")
        return tuple(documents)

    async def resolve_prepared_document_inputs(
        self,
        collection_id: str,
        document_ids: tuple[str, ...],
    ) -> tuple[PreparedDocumentInput, ...]:
        if not document_ids:
            raise ValueError("Objective discovery requires at least one document")
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("Objective discovery document IDs must be unique")
        inputs: list[PreparedDocumentInput] = []
        for document_id in document_ids:
            document = await self.collection_service.get_document(
                collection_id,
                document_id,
            )
            if document.status != "ready" or not document.preparation_fingerprint:
                raise ResearchObjectivesNotReadyError(collection_id)
            inputs.append(
                PreparedDocumentInput(
                    document_id=document_id,
                    preparation_fingerprint=document.preparation_fingerprint,
                )
            )
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
    "ResearchObjectiveService",
    "ResearchObjectivesNotReadyError",
]
