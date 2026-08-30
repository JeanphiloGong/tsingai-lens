from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from application.core.document_profiles.service import DocumentProfileService
from application.core.objectives.analysis.finding_synthesis import (
    FindingSynthesisService,
)
from application.core.objectives.objective_candidate_service import (
    ObjectiveCandidateService,
)
from application.core.objectives.paper_research_map_service import (
    PaperResearchMapService,
)
from application.core.objectives.research_objective_service import (
    ResearchObjectiveService,
)
from domain.core import (
    DocumentProfile,
    ObjectiveAnalysis,
    PreparedDocumentInput,
    ResearchObjective,
)
from domain.source import Document
from infra.persistence.memory import (
    MemoryDocumentProfileRepository,
    MemoryPaperMapRepository,
    MemorySourceArtifactRepository,
)
from infra.persistence.memory.objective_repository import MemoryObjectiveRepository


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
    objective_judgments = kwargs.get("response_client")
    if objective_judgments is not None:
        kwargs.setdefault("axis_equivalence_classifier", objective_judgments)
        kwargs.setdefault("objective_evidence_router", objective_judgments)
        kwargs.setdefault("objective_source_extractor", objective_judgments)
        kwargs.setdefault("objective_source_screener", objective_judgments)
    source_repository = kwargs.pop("source_artifact_repository", None)
    if source_repository is None:
        source_repository = getattr(
            kwargs.get("document_profile_service"),
            "source_artifact_repository",
            None,
        ) or MemorySourceArtifactRepository()
    document_profile_repository = kwargs.pop(
        "document_profile_repository",
        MemoryDocumentProfileRepository(),
    )
    paper_map_repository = kwargs.pop(
        "paper_map_repository",
        MemoryPaperMapRepository(),
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
            document_profile_repository=document_profile_repository,
        )
    finding_synthesis_service = kwargs.pop(
        "finding_synthesis_service",
        FindingSynthesisService(
            assertion_judge=objective_judgments,
        ),
    )
    return ResearchObjectiveService(
        collection_service=collection_service,
        source_artifact_repository=source_repository,
        paper_map_repository=paper_map_repository,
        objective_repository=objective_repository,
        document_profile_service=document_profile_service,
        finding_synthesis_service=finding_synthesis_service,
        objective_candidate_service=ObjectiveCandidateService(),
        paper_map_service=kwargs.pop("paper_map_service", PaperResearchMapService()),
        **kwargs,
    )


async def seed_document_profiles(
    service: ResearchObjectiveService,
    collection_id: str,
) -> None:
    documents = await service.source_artifact_repository.read_collection_documents(
        collection_id
    )
    current_collection = await service.collection_service.repository.read_collection(
        collection_id
    )
    assert current_collection is not None
    existing_document_ids = {
        document.document_id for document in current_collection.documents
    }
    now = datetime.now(timezone.utc).isoformat()
    new_documents = tuple(
        Document(
            document_id=document.document_id,
            original_filename=str(
                document.metadata.get("source_filename") or f"{document.document_id}.pdf"
            ),
            stored_filename=str(
                document.metadata.get("source_filename") or f"{document.document_id}.pdf"
            ),
            storage_key=f"{collection_id}/input/{document.document_id}.pdf",
            sha256=sha256(document.document_id.encode("utf-8")).hexdigest(),
            media_type="application/pdf",
            status="ready",
            size_bytes=max(len(document.text.encode("utf-8")), 1),
            created_at=now,
            updated_at=now,
            parser_version="test-parser.v1",
            document_analysis_version="test-analysis.v1",
            preparation_fingerprint=f"fingerprint-{document.document_id}",
        )
        for document in documents
        if document.document_id not in existing_document_ids
    )
    if new_documents:
        await service.collection_service.repository.add_documents(
            collection_id,
            new_documents,
            updated_at=now,
        )
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
    for profile in profiles:
        await service.document_profile_service.document_profile_repository.replace(
            profile
        )


async def queue_running_analysis(
    service: ResearchObjectiveService,
    collection_id: str,
    objective_id: str,
) -> ObjectiveAnalysis:
    facts = await service.objective_repository.read(collection_id)
    document_inputs = facts.document_inputs
    if not document_inputs:
        objective = await service.objective_repository.read_objective(
            collection_id,
            objective_id,
        )
        assert objective is not None
        document_inputs = await service.resolve_prepared_document_inputs(
            collection_id,
            tuple(objective.seed_document_ids),
        )
    _, queued = await service.objective_repository.queue_analysis(
        collection_id,
        objective_id,
        document_inputs=tuple(
            PreparedDocumentInput(
                document_id=item.document_id,
                preparation_fingerprint=item.preparation_fingerprint,
            )
            for item in document_inputs
        ),
        pipeline_version="test.v1",
        model_name="test-model",
        prompt_versions={},
    )
    claimed = await service.objective_repository.claim_analysis(
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
