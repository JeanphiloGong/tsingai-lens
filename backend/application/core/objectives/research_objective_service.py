from __future__ import annotations

import logging
from dataclasses import dataclass, replace
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
from application.core.objectives.discovery.signal_reconciliation import (
    PaperSignalReconciler,
)
from application.core.objectives.discovery.study_window import (
    PaperStudyWindowExtractor,
)
from application.core.objectives.llm.structured_response import (
    StructuredResponseClient,
    build_default_structured_response_client,
)
from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from application.core.objectives.paper_skim_service import PaperSkimService
from application.core.paper_facts.extraction import PaperFactsExtractor
from application.source.artifact_input_service import load_document_tree
from application.source.collection_service import CollectionService
from domain.core import (
    Finding,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PaperStudyDisposition,
    PaperStudyDispositionStatus,
    ResearchObjective,
    is_question_shaped_objective,
)
from domain.ports import (
    ObjectiveRepository,
    PaperFactRepository,
    SourceArtifactRepository,
)
from domain.source import SourceDocument

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class ObjectiveAnalysisArtifacts:
    """Canonical values produced by one versioned Objective analysis run."""

    contributions: tuple[PaperContribution, ...]
    evidence_records: tuple[ObjectiveEvidence, ...]
    findings: tuple[Finding, ...]


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
        paper_fact_repository: PaperFactRepository,
        objective_repository: ObjectiveRepository,
        document_profile_service: DocumentProfileService,
        finding_synthesis_service: FindingSynthesisService,
        paper_skim_service: PaperSkimService,
        objective_candidate_service: ObjectiveCandidateService,
        response_client: StructuredResponseClient | None = None,
        axis_equivalence_classifier: ResearchAxisEquivalenceClassifier | None = None,
        objective_source_screener: ObjectiveSourceScreener | None = None,
        objective_evidence_router: ObjectiveEvidenceRouter | None = None,
        objective_source_extractor: ObjectiveSourceExtractor | None = None,
        paper_study_window_extractor: PaperStudyWindowExtractor | None = None,
        paper_signal_reconciler: PaperSignalReconciler | None = None,
        paper_facts_extractor: PaperFactsExtractor | None = None,
    ) -> None:
        self.collection_service = collection_service
        self._response_client = response_client
        self._axis_equivalence_classifier = axis_equivalence_classifier
        self._objective_source_screener = objective_source_screener
        self._objective_evidence_router = objective_evidence_router
        self._objective_source_extractor = objective_source_extractor
        self._paper_study_window_extractor = paper_study_window_extractor
        self._paper_signal_reconciler = paper_signal_reconciler
        self._paper_facts_extractor = paper_facts_extractor
        self.paper_fact_repository = paper_fact_repository
        self.objective_repository = objective_repository
        self.source_artifact_repository = source_artifact_repository
        self.document_profile_service = document_profile_service
        self.finding_synthesis_service = finding_synthesis_service
        self.paper_skim_service = paper_skim_service
        self.objective_candidate_service = objective_candidate_service

    def discover_and_replace_objective_candidates(
        self,
        collection_id: str,
        progress_callback: ProgressCallback | None = None,
        *,
        build_id: str,
    ) -> ObjectiveFactSet:
        source_inputs = self._load_objective_source_inputs(
            collection_id,
            build_id=build_id,
        )
        documents = source_inputs["documents"]
        response_client = source_inputs["response_client"]
        if self._paper_study_window_extractor is None:
            self._paper_study_window_extractor = PaperStudyWindowExtractor(
                response_client
            )
        if self._paper_signal_reconciler is None:
            self._paper_signal_reconciler = PaperSignalReconciler(response_client)
        if self._axis_equivalence_classifier is None:
            self._axis_equivalence_classifier = ResearchAxisEquivalenceClassifier(
                response_client
            )
        paper_skims = self.paper_skim_service.build_collection_paper_skims(
            collection_id,
            documents=documents,
            profiles_by_document_id=source_inputs["profiles_by_document_id"],
            document_trees_by_document_id=source_inputs[
                "document_trees_by_document_id"
            ],
            study_window_extractor=self._paper_study_window_extractor,
            signal_reconciler=self._paper_signal_reconciler,
            progress_callback=progress_callback,
        )
        self.objective_repository.replace(
            collection_id,
            build_id,
            ObjectiveFactSet(
                research_objectives_ready=False,
                paper_skims=paper_skims,
                study_dispositions=tuple(
                    PaperStudyDisposition(
                        document_id=skim.document_id,
                        study_id=study.study_id,
                        relationship_id=relationship.relationship_id,
                        status=PaperStudyDispositionStatus.PENDING,
                    )
                    for skim in paper_skims
                    for study in skim.studies
                    for relationship in study.relationships
                ),
            ),
        )
        candidate_facts = self.objective_candidate_service.discover_candidate_facts(
            collection_id,
            paper_skims=paper_skims,
            axis_equivalence_classifier=self._axis_equivalence_classifier,
            progress_callback=progress_callback,
        )
        self.objective_repository.replace(
            collection_id,
            build_id,
            candidate_facts,
        )
        research_objectives = candidate_facts.research_objectives
        logger.info(
            "Research objective candidates finished collection_id=%s paper_skim_count=%s objective_count=%s",
            collection_id,
            len(paper_skims),
            len(research_objectives),
        )
        return candidate_facts

    def create_chat_assisted_candidate(
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
        """Persist one user-approved candidate supported by PaperSkim context."""

        self.collection_service.get_collection_for_user(collection_id, user_id)
        if len(outcomes) != 1:
            raise ValueError("chat-assisted objective requires exactly one outcome")
        if not seed_document_ids:
            raise ValueError("chat-assisted objective requires seed documents")

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

        facts = self.objective_repository.read(collection_id)
        if not facts.research_objectives_ready:
            raise ResearchObjectivesNotReadyError(collection_id)
        skims_by_document_id = {
            skim.document_id: skim for skim in facts.paper_skims
        }
        support_confidences: list[float] = []
        for document_id in objective.seed_document_ids:
            skim = skims_by_document_id.get(document_id)
            matches = (
                [
                    relationship.confidence
                    for study in skim.studies
                    for relationship in study.relationships
                    if self._paper_relationship_supports_objective(
                        objective,
                        study.material_scope,
                        relationship.varied_factors,
                        relationship.outcome,
                    )
                ]
                if skim is not None
                else []
            )
            if not matches:
                raise ValueError(
                    "seed PaperSkim context does not support the Objective axes: "
                    f"{document_id}"
                )
            support_confidences.append(max(matches))

        objective = replace(
            objective,
            confidence=sum(support_confidences) / len(support_confidences),
            reason=(
                "User-approved candidate supported by PaperSkim relationship context "
                f"from {len(support_confidences)} seed document(s); support is not "
                "extracted Evidence."
            ),
        )
        return self.objective_repository.create_authored_candidate(
            objective,
            created_by_user_id=user_id,
            created_by_tool_call_id=tool_call_id,
        )

    @staticmethod
    def _paper_relationship_supports_objective(
        objective: ResearchObjective,
        study_materials: tuple[str, ...],
        varied_factors: tuple[str, ...],
        outcome: str,
    ) -> bool:
        material_matches = (
            not objective.material_scope
            or not study_materials
            or any(
                property_matching.axis_values_match(target, observed)
                for target in objective.material_scope
                for observed in study_materials
            )
        )
        variables_match = all(
            any(
                property_matching.axis_values_match(variable, factor)
                for factor in varied_factors
            )
            for variable in objective.variables
        )
        return (
            material_matches
            and variables_match
            and property_matching.axis_values_match(objective.outcomes[0], outcome)
        )

    def generate_objective_analysis_artifacts(
        self,
        collection_id: str,
        analysis: ObjectiveAnalysis,
        progress_callback: ProgressCallback | None = None,
    ) -> ObjectiveAnalysisArtifacts:
        if analysis.collection_id != collection_id:
            raise ValueError("analysis belongs to another collection")
        active_objective = self.objective_repository.read_objective(
            collection_id, analysis.objective_id
        )
        if active_objective is None:
            raise ResearchObjectiveNotFoundError(collection_id, analysis.objective_id)
        if active_objective.active_analysis_version != analysis.analysis_version:
            raise ValueError("analysis is not the active objective version")
        objective_inputs = self._build_objective_analysis_inputs(
            collection_id,
            build_id=analysis.source_build_id,
        )
        source_objective = (
            active_objective
            if active_objective.origin == "chat_assisted"
            and active_objective.source_build_id == analysis.source_build_id
            else next(
                (
                    item
                    for item in objective_inputs["research_objectives"]
                    if item.objective_id == analysis.objective_id
                ),
                None,
            )
        )
        if source_objective is None:
            raise ResearchObjectiveNotFoundError(collection_id, analysis.objective_id)
        objective = replace(
            source_objective,
            confirmation_status=active_objective.confirmation_status,
            active_analysis_version=active_objective.active_analysis_version,
            published_analysis_version=active_objective.published_analysis_version,
            created_at=active_objective.created_at,
            updated_at=active_objective.updated_at,
        )
        response_client = objective_inputs["response_client"]
        if self._objective_source_screener is None:
            self._objective_source_screener = ObjectiveSourceScreener(response_client)
        if self._objective_evidence_router is None:
            self._objective_evidence_router = ObjectiveEvidenceRouter(response_client)
        if self._objective_source_extractor is None:
            self._objective_source_extractor = ObjectiveSourceExtractor(response_client)

        screened_sources = screen_sources(
            collection_id=collection_id,
            source_screener=self._objective_source_screener,
            objectives=(objective,),
            paper_skims=objective_inputs["paper_skims"],
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
            paper_skims=objective_inputs["paper_skims"],
            objectives=(objective,),
        )
        evidence_records, contributions = materialize_evidence(
            collection_id=collection_id,
            analysis=analysis,
            objective=objective,
            drafts=paper_evidence_drafts,
            frames=screened_sources,
            routes=source_inspection_routes,
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            figures_by_document_id=objective_inputs["figures_by_document_id"],
        )
        findings = self.finding_synthesis_service.synthesize(
            collection_id=collection_id,
            objective=objective,
            analysis=analysis,
            contributions=contributions,
            evidence_records=evidence_records,
        )
        return ObjectiveAnalysisArtifacts(
            contributions=contributions,
            evidence_records=evidence_records,
            findings=findings,
        )

    def _build_objective_analysis_inputs(
        self,
        collection_id: str,
        *,
        build_id: str,
    ) -> dict[str, Any]:
        source_inputs = self._load_objective_source_inputs(
            collection_id,
            build_id=build_id,
        )
        facts = self.objective_repository.read(collection_id, build_id=build_id)
        if facts.research_objectives_ready and facts.paper_skims:
            return {
                **source_inputs,
                "paper_skims": facts.paper_skims,
                "research_objectives": facts.research_objectives,
            }
        raise ResearchObjectivesNotReadyError(collection_id)

    def _load_objective_source_inputs(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> dict[str, Any]:
        self.collection_service.get_collection(collection_id)
        try:
            documents = self._load_source_documents(
                collection_id, build_id=build_id
            )
            profiles = self.document_profile_service.read_document_profiles(
                collection_id,
                build_id=build_id,
            )
        except (FileNotFoundError, DocumentProfilesNotReadyError) as exc:
            raise ResearchObjectivesNotReadyError(collection_id) from exc

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
            "document_trees_by_document_id": {
                document.document_id: load_document_tree(
                    collection_id,
                    document.document_id,
                    self.source_artifact_repository,
                    build_id=build_id,
                )
                for document in documents
            },
            "response_client": self._get_response_client(),
        }

    def _get_response_client(self) -> StructuredResponseClient:
        if self._response_client is None:
            self._response_client = build_default_structured_response_client()
        return self._response_client

    def _load_source_documents(
        self,
        collection_id: str,
        *,
        build_id: str | None = None,
    ) -> tuple[SourceDocument, ...]:
        documents = (
            self.source_artifact_repository.read_collection_documents(
                collection_id,
                build_id=build_id,
            )
            if build_id is not None
            else self.source_artifact_repository.read_collection_documents(collection_id)
        )
        if not documents:
            raise FileNotFoundError(f"source artifacts not ready: {collection_id}")
        return documents


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
