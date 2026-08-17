from __future__ import annotations

from typing import Any

from application.core.document_profiles.service import DocumentProfileService
from application.core.objectives.finding_synthesis_service import (
    FindingSynthesisService,
)
from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from application.core.objectives.paper_skim_service import PaperSkimService
from application.core.objectives.research_objective_service import (
    ResearchObjectiveService,
)
from domain.core import DocumentProfile, ObjectiveAnalysis, ResearchObjective
from tests.support.objective_repository import MemoryObjectiveRepository
from tests.support.paper_fact_repository import MemoryPaperFactRepository
from tests.support.source_artifact_repository import MemorySourceArtifactRepository


def research_objective(payload: dict[str, Any]) -> ResearchObjective:
    return ResearchObjective.from_mapping(
        {
            "collection_id": "collection-test",
            "question": "How does process condition affect the target outcome?",
            "variables": ["process condition"],
            "outcomes": ["target outcome"],
            **payload,
        }
    )


def build_research_objective_service(
    *,
    collection_service,
    **kwargs,
) -> ResearchObjectiveService:
    objective_extractor = kwargs.get("objective_extractor")
    if objective_extractor is not None:
        kwargs.setdefault("axis_equivalence_classifier", objective_extractor)
        kwargs.setdefault("objective_evidence_router", objective_extractor)
        kwargs.setdefault("objective_source_extractor", objective_extractor)
        kwargs.setdefault("objective_source_screener", objective_extractor)
        kwargs.setdefault("paper_study_window_extractor", objective_extractor)
        kwargs.setdefault("paper_signal_reconciler", objective_extractor)
    source_repository = kwargs.pop("source_artifact_repository", None)
    if source_repository is None:
        source_repository = getattr(
            kwargs.get("document_profile_service"),
            "source_artifact_repository",
            None,
        ) or MemorySourceArtifactRepository()
    paper_fact_repository = kwargs.pop(
        "paper_fact_repository",
        MemoryPaperFactRepository(),
    )
    objective_repository = kwargs.pop(
        "objective_repository",
        MemoryObjectiveRepository(),
    )
    document_profile_service = kwargs.pop("document_profile_service", None)
    if document_profile_service is None:
        document_profile_service = DocumentProfileService(
            collection_service=collection_service,
            source_artifact_repository=source_repository,
            paper_fact_repository=paper_fact_repository,
        )
    finding_synthesis_service = kwargs.pop(
        "finding_synthesis_service",
        FindingSynthesisService(
            finding_extractor=kwargs.get("objective_extractor"),
        ),
    )
    return ResearchObjectiveService(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
        paper_fact_repository=paper_fact_repository,
        objective_repository=objective_repository,
        document_profile_service=document_profile_service,
        finding_synthesis_service=finding_synthesis_service,
        paper_skim_service=PaperSkimService(),
        objective_candidate_service=ObjectiveCandidateService(),
        **kwargs,
    )


def seed_document_profiles(
    service: ResearchObjectiveService,
    collection_id: str,
) -> None:
    documents = service.source_artifact_repository.read_collection_documents(collection_id)
    profiles: list[DocumentProfile] = []
    for document in documents:
        metadata = dict(document.metadata)
        title = document.title
        profiles.append(
            DocumentProfile.from_mapping(
                {
                    "document_id": document.document_id,
                    "collection_id": collection_id,
                    "title": title,
                    "source_filename": metadata.get("source_filename"),
                    "doc_type": "review" if "Review" in title else "experimental",
                    "parsing_warnings": [],
                    "confidence": 0.9,
                }
            )
        )
    service.paper_fact_repository.replace_document_profiles(
        collection_id,
        "build_test",
        tuple(profiles),
    )


def queue_running_analysis(
    service: ResearchObjectiveService,
    collection_id: str,
    objective_id: str,
) -> ObjectiveAnalysis:
    service.objective_repository.confirm_objective(collection_id, objective_id)
    _, queued = service.objective_repository.queue_analysis(
        collection_id,
        objective_id,
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    claimed = service.objective_repository.claim_analysis(
        collection_id,
        objective_id,
        queued.analysis_version,
    )
    assert claimed is not None
    return claimed


__all__ = [
    "build_research_objective_service",
    "queue_running_analysis",
    "research_objective",
    "seed_document_profiles",
]
