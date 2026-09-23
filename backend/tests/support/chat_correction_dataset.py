from __future__ import annotations

from domain.evaluation import ChatCorrectionDatasetManifest


class MemoryChatCorrectionDatasetRepository:
    backend_name = "memory"

    def __init__(self) -> None:
        self.manifests: dict[str, ChatCorrectionDatasetManifest] = {}

    async def save_manifest(self, manifest: ChatCorrectionDatasetManifest) -> ChatCorrectionDatasetManifest:
        existing = self.manifests.get(manifest.dataset_id)
        if existing is not None:
            if (
                existing.owner_id != manifest.owner_id
                or existing.collection_id != manifest.collection_id
                or existing.digest != manifest.digest
            ):
                raise ValueError("dataset identity cannot be reassigned")
            return existing
        by_digest = next(
            (item for item in self.manifests.values()
             if item.owner_id == manifest.owner_id and item.digest == manifest.digest),
            None,
        )
        if by_digest is not None:
            return by_digest
        self.manifests[manifest.dataset_id] = manifest
        return manifest

    async def read_manifest_for_user(self, dataset_id: str, user_id: str):
        manifest = self.manifests.get(dataset_id)
        return manifest if manifest is not None and manifest.owner_id == user_id else None

    async def list_manifests_for_user(self, user_id: str, *, collection_id=None, limit=50, offset=0):
        values = sorted(
            (item for item in self.manifests.values()
             if item.owner_id == user_id and (collection_id is None or item.collection_id == collection_id)),
            key=lambda item: (item.created_at, item.dataset_id),
        )
        start = max(0, int(offset))
        return tuple(values[start : start + max(1, min(int(limit), 200))])


__all__ = ["MemoryChatCorrectionDatasetRepository"]
