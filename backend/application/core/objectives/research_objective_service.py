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
from application.core.objectives.analysis.evidence_routing import route_sources
from application.core.objectives.analysis.paper_experiment import (
    reconstruct_paper_experiments,
)
from application.core.objectives.analysis.source_extraction import extract_source_facts
from application.core.objectives.analysis.source_screening import screen_sources
from application.core.objectives.discovery.signal_reconciliation import (
    PaperSignalReconciler,
)
from application.core.objectives.discovery.study_window import (
    PaperStudyWindowExtractor,
)
from application.core.objectives.extraction import (
    ObjectiveExtractor,
    build_default_objective_extractor,
)
from application.core.objectives.finding_synthesis_service import (
    FindingSynthesisService,
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
        objective_extractor: ObjectiveExtractor | None = None,
        paper_study_window_extractor: PaperStudyWindowExtractor | None = None,
        paper_signal_reconciler: PaperSignalReconciler | None = None,
        paper_facts_extractor: PaperFactsExtractor | None = None,
    ) -> None:
        self.collection_service = collection_service
        self._objective_extractor = objective_extractor
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
        extractor = source_inputs["extractor"]
        if self._paper_study_window_extractor is None:
            self._paper_study_window_extractor = PaperStudyWindowExtractor(extractor)
        if self._paper_signal_reconciler is None:
            self._paper_signal_reconciler = PaperSignalReconciler(extractor)
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
            extractor=extractor,
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
        source_objective = next(
            (
                item
                for item in objective_inputs["research_objectives"]
                if item.objective_id == analysis.objective_id
            ),
            None,
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
        paper_frames = screen_sources(
            collection_id=collection_id,
            extractor=objective_inputs["extractor"],
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
        evidence_candidates = route_sources(
            collection_id=collection_id,
            extractor=objective_inputs["extractor"],
            objectives=(objective,),
            objective_paper_frames=paper_frames,
            blocks_by_document_id=objective_inputs["blocks_by_document_id"],
            tables_by_document_id=objective_inputs["tables_by_document_id"],
            document_trees_by_document_id=objective_inputs[
                "document_trees_by_document_id"
            ],
            progress_callback=progress_callback,
        )
        source_drafts = extract_source_facts(
            collection_id=collection_id,
            extractor=objective_inputs["extractor"],
            paper_facts_extractor=self._paper_facts_extractor,
            objectives=(objective,),
            objective_paper_frames=paper_frames,
            objective_evidence_routes=evidence_candidates,
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
        evidence_drafts = reconstruct_paper_experiments(
            collection_id=collection_id,
            source_facts=source_drafts,
            paper_skims=objective_inputs["paper_skims"],
            objectives=(objective,),
        )
        evidence_records, contributions = materialize_evidence(
            collection_id=collection_id,
            analysis=analysis,
            objective=objective,
            drafts=evidence_drafts,
            frames=paper_frames,
            routes=evidence_candidates,
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
            "extractor": self._get_objective_extractor(),
        }


    def _get_objective_extractor(self) -> ObjectiveExtractor:
        if self._objective_extractor is None:
            self._objective_extractor = build_default_objective_extractor()
        return self._objective_extractor


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
