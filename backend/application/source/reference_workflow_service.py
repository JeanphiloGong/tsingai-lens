from __future__ import annotations

from dataclasses import dataclass

from domain.ports import SourceArtifactRepository
from domain.source import SourceReferenceSet


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


class SourceReferenceWorkflowService:
    """Run the independent Source refs expansion workflow."""

    def __init__(
        self,
        source_artifact_repository: SourceArtifactRepository,
    ) -> None:
        self.source_artifact_repository = source_artifact_repository

    async def build_collection_references(
        self,
        collection_id: str,
    ) -> SourceReferenceWorkflowResult:
        documents = await self.source_artifact_repository.read_collection_documents(
            collection_id
        )
        if not documents:
            raise FileNotFoundError(f"source artifacts not ready: {collection_id}")
        references = await self.source_artifact_repository.read_collection_references(
            collection_id
        )
        return SourceReferenceWorkflowResult(
            collection_id=collection_id,
            references=references,
        )

    async def read_collection_references(
        self,
        collection_id: str,
    ) -> SourceReferenceWorkflowResult:
        references = await self.source_artifact_repository.read_collection_references(
            collection_id
        )
        return SourceReferenceWorkflowResult(
            collection_id=collection_id,
            references=references,
        )
