from __future__ import annotations

from dataclasses import dataclass

from application.source import workspace_service
from document.domain.source import SourceReferenceSet
from exceptions import ResourceConflictException
from repositories.source_artifact_repository import SourceArtifactRepo


@dataclass(frozen=True)
class SourceReferenceWorkflowResult:
    workspace_id: str
    references: SourceReferenceSet

    def to_summary(self) -> dict[str, int | str]:
        return {
            "workspace_id": self.workspace_id,
            "entry_count": len(self.references.entries),
            "mention_count": len(self.references.mentions),
            "resolution_count": len(self.references.resolutions),
            "candidate_count": len(self.references.candidates),
        }


async def get_workspace_references(
    workspace_id: str,
    *,
    user_id: str,
) -> SourceReferenceWorkflowResult:
    await workspace_service.get_workspace_for_user(workspace_id, user_id)
    documents = await SourceArtifactRepo.read_workspace_documents(workspace_id)
    if not documents:
        raise ResourceConflictException(
            f"source artifacts not ready: {workspace_id}",
            data={"code": "source_artifacts_not_ready", "workspace_id": workspace_id},
        )
    references = await SourceArtifactRepo.read_workspace_references(workspace_id)
    return SourceReferenceWorkflowResult(
        workspace_id=workspace_id,
        references=references,
    )


async def read_workspace_references(
    workspace_id: str,
    *,
    user_id: str,
) -> SourceReferenceWorkflowResult:
    await workspace_service.get_workspace_for_user(workspace_id, user_id)
    references = await SourceArtifactRepo.read_workspace_references(workspace_id)
    return SourceReferenceWorkflowResult(
        workspace_id=workspace_id,
        references=references,
    )
