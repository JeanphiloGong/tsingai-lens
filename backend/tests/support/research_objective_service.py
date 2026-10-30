from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from types import ModuleType
from typing import Any

from application.core.document_profiles import service as document_profile_module
from application.core.objectives import (
    objective_analysis_service as experiment_analysis_service,
)
from application.core.objectives import (
    objective_input_service as objective_input_module,
)
from application.core.objectives import paper_research_map_service
from domain.core import DocumentProfile, PreparedDocumentInput, ResearchObjective
from domain.core.research_objective import (
    OBJECTIVE_CONFIRMATION_STATUSES,
    OBJECTIVE_ORIGINS,
    ResearchObjective,
    build_research_objective_id,
    normalize_objective_terms,
)
from domain.source import Document
from repositories.collection_repository import StoredDocument
from repositories.document_profile_repository import DocumentProfileRepository
from repositories.objective_repository import ObjectiveAnalysis, ObjectiveRepository
from repositories.paper_map_repository import PaperMapRepository
from repositories.source_artifact_repository import SourceArtifactRepository


def research_objective(payload: dict[str, Any]) -> ResearchObjective:
    return ResearchObjective(
        collection_id=payload.get("collection_id", "collection-test") or "",
        objective_id=payload.get("objective_id", None)
        or build_research_objective_id(
            question=payload.get(
                "question", "How does process condition affect the target outcome?"
            )
            or "",
            material_scope=normalize_objective_terms(payload.get("material_scope", ())),
            variables=normalize_objective_terms(
                payload.get("variables", ["process condition"])
            ),
            outcomes=normalize_objective_terms(
                payload.get("outcomes", ["target outcome"])
            ),
            mechanisms=normalize_objective_terms(payload.get("mechanisms", ())),
            constraints=normalize_objective_terms(payload.get("constraints", ())),
            requested_comparator=payload.get("requested_comparator", None),
            parent_objective_id=payload.get("parent_objective_id", None),
            parent_analysis_version=payload.get("parent_analysis_version", None),
        ),
        question=payload.get(
            "question", "How does process condition affect the target outcome?"
        )
        or "",
        material_scope=normalize_objective_terms(payload.get("material_scope", ())),
        variables=normalize_objective_terms(
            payload.get("variables", ["process condition"])
        ),
        outcomes=normalize_objective_terms(payload.get("outcomes", ["target outcome"])),
        mechanisms=normalize_objective_terms(payload.get("mechanisms", ())),
        constraints=normalize_objective_terms(payload.get("constraints", ())),
        requested_comparator=payload.get("requested_comparator", None),
        seed_document_ids=normalize_objective_terms(
            payload.get("seed_document_ids", ())
        ),
        excluded_document_ids=normalize_objective_terms(
            payload.get("excluded_document_ids", ())
        ),
        confidence=payload.get("confidence", 0.0),
        reason=payload.get("reason", None),
        source_relationship_ids=normalize_objective_terms(
            payload.get("source_relationship_ids", ())
        ),
        parent_objective_id=payload.get("parent_objective_id", None),
        parent_analysis_version=payload.get("parent_analysis_version", None),
        derivation_basis=tuple(payload.get("derivation_basis", None) or ()),
        rank=payload.get("rank", None),
        confirmation_status=payload.get("confirmation_status", None),
        active_analysis_version=payload.get("active_analysis_version", None),
        published_analysis_version=payload.get("published_analysis_version", None),
        origin=payload.get("origin", None),
        created_by_user_id=payload.get("created_by_user_id", None),
        created_by_tool_call_id=payload.get("created_by_tool_call_id", None),
    )


def build_research_objective_service(
    *,
    collection_service,
    **kwargs,
) -> ModuleType:
    objective_judgments = kwargs.pop("response_client", None)
    source_repository = kwargs.pop("source_artifact_repository", None)
    if source_repository is None:
        source_repository = (
            getattr(
                kwargs.get("document_profile_service"),
                "source_artifact_repository",
                None,
            )
            or SourceArtifactRepository()
        )
    document_profile_repository = kwargs.pop(
        "document_profile_repository",
        DocumentProfileRepository(),
    )
    paper_map_repository = kwargs.pop(
        "paper_map_repository",
        PaperMapRepository(),
    )
    objective_repository = kwargs.pop(
        "objective_repository",
        ObjectiveRepository(),
    )
    document_profile_service = kwargs.pop(
        "document_profile_service", document_profile_module
    )
    document_profile_service.collection_service = collection_service
    document_profile_service.SourceArtifactRepo = source_repository
    document_profile_service.DocumentProfileRepo = document_profile_repository
    objective_input_service = kwargs.pop(
        "objective_input_service",
        objective_input_module,
    )
    objective_input_service.collection_service = collection_service
    objective_input_service.SourceArtifactRepo = source_repository
    objective_input_service.PaperMapRepo = paper_map_repository
    objective_input_service.document_profile_service = document_profile_service
    objective_input_service.paper_research_map_service = kwargs.pop(
        "paper_map_service", paper_research_map_service
    )
    objective_input_service.build_default_structured_response_client = (
        lambda: objective_judgments
    )
    experiment_analysis_service.collection_service = collection_service
    experiment_analysis_service.PaperMapRepo = paper_map_repository
    experiment_analysis_service.ObjectiveRepo = objective_repository
    experiment_analysis_service.objective_input_service = objective_input_service
    if kwargs:
        raise TypeError(f"Unexpected test service options: {', '.join(kwargs)}")
    return experiment_analysis_service


async def seed_document_profiles(
    service: ModuleType,
    collection_id: str,
) -> None:
    documents = await service.objective_input_service.SourceArtifactRepo.read_collection_documents(
        collection_id
    )
    current_collection = (
        await service.collection_service.CollectionRepo.read_collection(collection_id)
    )
    assert current_collection is not None
    existing_document_ids = {
        document.document.document_id for document in current_collection.documents
    }
    now = datetime.now(timezone.utc).isoformat()
    new_documents = tuple(
        StoredDocument(
            document=Document(
                document_id=document.document_id,
                original_filename=str(
                    document.metadata.get("source_filename")
                    or f"{document.document_id}.pdf"
                ),
                sha256=sha256(document.document_id.encode("utf-8")).hexdigest(),
                media_type="application/pdf",
                status="ready",
                size_bytes=max(len(document.text.encode("utf-8")), 1),
                parser_version="test-parser.v1",
                document_analysis_version="test-analysis.v1",
                preparation_fingerprint=f"fingerprint-{document.document_id}",
            ),
            stored_filename=str(
                document.metadata.get("source_filename")
                or f"{document.document_id}.pdf"
            ),
            storage_key=f"{collection_id}/input/{document.document_id}.pdf",
            created_at=now,
            updated_at=now,
        )
        for document in documents
        if document.document_id not in existing_document_ids
    )
    if new_documents:
        await service.collection_service.CollectionRepo.add_documents(
            collection_id,
            new_documents,
            updated_at=now,
        )
    profiles: list[DocumentProfile] = []
    for document in documents:
        title = document.title
        profiles.append(
            DocumentProfile(
                document_id=document.document_id,
                title=title,
                doc_type="review" if "Review" in title else "experimental",
                profile_warnings=(),
                confidence=0.9,
            )
        )
    for profile in profiles:
        await service.objective_input_service.document_profile_service.DocumentProfileRepo.replace(
            collection_id, profile
        )


async def queue_running_analysis(
    service: ModuleType,
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
        document_inputs = (
            await service.objective_input_service.resolve_prepared_document_inputs(
                collection_id,
                tuple(objective.seed_document_ids),
            )
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
