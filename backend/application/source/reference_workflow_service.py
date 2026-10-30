from __future__ import annotations

from dataclasses import dataclass

from application.source import collection_service
from domain.source import SourceReferenceSet
from exceptions import ResourceConflictException
from repositories.source_artifact_repository import SourceArtifactRepo


@dataclass(frozen=True)
class SourceReferenceWorkflowResult:
    collection_id: str
    references: SourceReferenceSet

    def to_summary(self) -> dict[str, int | str]:
        return {
            "collection_id": self.collection_id,
            "entry_count": len(self.references.entries),
            "mention_count": len(self.references.mentions),
            "resolution_count": len(self.references.resolutions),
            "candidate_count": len(self.references.candidates),
        }


async def build_collection_references(
    collection_id: str,
    *,
    user_id: str,
) -> SourceReferenceWorkflowResult:
    await collection_service.get_collection_for_user(collection_id, user_id)
    documents = await SourceArtifactRepo.read_collection_documents(collection_id)
    if not documents:
        raise ResourceConflictException(
            f"source artifacts not ready: {collection_id}",
            data={"code": "source_artifacts_not_ready", "collection_id": collection_id},
        )
    references = await SourceArtifactRepo.read_collection_references(collection_id)
    return SourceReferenceWorkflowResult(
        collection_id=collection_id,
        references=references,
    )


async def read_collection_references(
    collection_id: str,
    *,
    user_id: str,
) -> SourceReferenceWorkflowResult:
    await collection_service.get_collection_for_user(collection_id, user_id)
    references = await SourceArtifactRepo.read_collection_references(collection_id)
    return SourceReferenceWorkflowResult(
        collection_id=collection_id,
        references=references,
    )
