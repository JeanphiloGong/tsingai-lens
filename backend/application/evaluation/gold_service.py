from __future__ import annotations

from types import ModuleType
from typing import Any, Sequence

from domain.evaluation import EvaluationGoldItem, EvaluationGoldSet
from domain.evaluation.records import (
    EVALUATION_TARGET_LAYERS,
)
from repositories.evaluation_repository import EvaluationRepository


class EvaluationGoldService:
    """Register collection-bound gold answers for evaluation runs."""

    def __init__(
        self,
        collection_service: ModuleType,
        evaluation_repository: EvaluationRepository,
    ) -> None:
        self.collection_service = collection_service
        self.evaluation_repository = evaluation_repository

    async def register_gold_set(
        self,
        *,
        collection_id: str,
        gold_id: str,
        version: str = "v1",
        target_layer: str = "core",
        metric_profile: str = "materials_core_v1",
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        items: Sequence[EvaluationGoldItem],
    ) -> EvaluationGoldSet:
        await self.collection_service.get_collection(collection_id)
        collection_document_ids = await self._collection_document_ids(collection_id)
        if target_layer not in EVALUATION_TARGET_LAYERS:
            raise ValueError(f"unsupported evaluation target layer: {target_layer}")
        gold_set = EvaluationGoldSet(
            gold_id=gold_id,
            collection_id=collection_id,
            version=version,
            target_layer=target_layer,
            metric_profile=metric_profile,
            description=description,
            metadata=metadata,
        )
        gold_items = tuple(items)
        self._validate_gold_item_documents(
            collection_id=collection_id,
            collection_document_ids=collection_document_ids,
            gold_items=gold_items,
        )
        await self.evaluation_repository.upsert_gold_set(gold_set, gold_items)
        return gold_set

    async def _collection_document_ids(self, collection_id: str) -> set[str]:
        keys: set[str] = set()
        collection = await self.collection_service.get_collection(collection_id)
        for record in collection["documents"]:
            for field in (
                "document_id",
                "original_filename",
                "stored_filename",
                "storage_key",
            ):
                value = record.get(field)
                if value is not None:
                    keys.add(value)
        return keys

    def _validate_gold_item_documents(
        self,
        *,
        collection_id: str,
        collection_document_ids: set[str],
        gold_items: tuple[EvaluationGoldItem, ...],
    ) -> None:
        if not collection_document_ids:
            return
        for item in gold_items:
            document_id = item.document_id
            if document_id and document_id in collection_document_ids:
                continue
            raise ValueError(
                "gold item document is not in collection: "
                f"{collection_id}/{item.document_id}"
            )
