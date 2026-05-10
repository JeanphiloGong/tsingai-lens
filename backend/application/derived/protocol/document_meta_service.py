from __future__ import annotations

from domain.ports import SourceArtifactRepository
from infra.persistence.factory import build_source_artifact_repository


source_artifact_repository = build_source_artifact_repository()


def load_document_title_map(
    collection_id: str,
    repository: SourceArtifactRepository | None = None,
) -> dict[str, str]:
    documents = (repository or source_artifact_repository).list_documents(collection_id)

    title_map: dict[str, str] = {}
    for document in documents:
        if document.document_id and document.title:
            title_map[document.document_id] = document.title

    return title_map
