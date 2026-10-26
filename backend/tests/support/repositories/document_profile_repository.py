"""In-memory current document-profile persistence."""

from __future__ import annotations

from copy import deepcopy

from domain.core import DocumentProfile


class MemoryDocumentProfileRepository:
    def __init__(self) -> None:
        self._profiles: dict[tuple[str, str], DocumentProfile] = {}

    async def replace(self, collection_id: str, profile: DocumentProfile) -> None:
        self._profiles[(collection_id, profile.document_id)] = deepcopy(profile)

    async def read(
        self,
        collection_id: str,
        document_id: str,
    ) -> DocumentProfile | None:
        profile = self._profiles.get((collection_id, document_id))
        return deepcopy(profile)

    async def list_collection(
        self,
        collection_id: str,
        document_ids: tuple[str, ...] | None = None,
    ) -> tuple[DocumentProfile, ...]:
        selected = set(document_ids) if document_ids is not None else None
        return tuple(
            deepcopy(profile)
            for profile in sorted(
                (
                    profile
                    for (owner_collection_id, _), profile in self._profiles.items()
                    if owner_collection_id == collection_id
                ),
                key=lambda item: item.document_id,
            )
            if selected is None or profile.document_id in selected
        )


__all__ = ["MemoryDocumentProfileRepository"]
