from __future__ import annotations

from typing import Any, Mapping

from application.source.collection_service import CollectionService
from domain.evaluation import EvaluationGoldItem, EvaluationGoldSet
from domain.evaluation.records import (
    EVALUATION_TARGET_LAYERS,
    _normalize_choice,
    _normalize_mapping,
    _normalize_mapping_tuple,
    _normalize_text,
)
from repositories.evaluation_repository import EvaluationRepository


class EvaluationGoldService:
    """Register collection-bound gold answers for evaluation runs."""

    def __init__(
        self,
        collection_service: CollectionService,
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
        metadata: Mapping[str, Any] | None = None,
        items: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    ) -> EvaluationGoldSet:
        await self.collection_service.get_collection(collection_id)
        collection_document_ids = await self._collection_document_ids(
            collection_id
        )
        gold_set = EvaluationGoldSet(
            gold_id=_normalize_text(gold_id) or "",
            collection_id=_normalize_text(collection_id) or "",
            version=_normalize_text(version) or "v1",
            target_layer=_normalize_choice(
                target_layer, allowed=EVALUATION_TARGET_LAYERS, default="core",
            ),
            metric_profile=_normalize_text(metric_profile) or "materials_core_v1",
            description=_normalize_text(description),
            metadata=_normalize_mapping(metadata),
        )
        gold_items = tuple(
            EvaluationGoldItem(
                gold_item_id=_normalize_text(item.get("gold_item_id")) or "",
                gold_id=gold_set.gold_id,
                document_id=_normalize_text(item.get("document_id")) or "",
                family=_normalize_text(item.get("family")) or "",
                item_key=_normalize_text(item.get("item_key")) or "",
                payload=_normalize_mapping(item.get("payload")),
                evidence_refs=_normalize_mapping_tuple(item.get("evidence_refs")),
                metadata=_normalize_mapping(item.get("metadata")),
            )
            for item in items
        )
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
                self._add_document_key(keys, record.get(field))
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
            document_id = self._document_key(item.document_id)
            if document_id and document_id in collection_document_ids:
                continue
            raise ValueError(
                "gold item document is not in collection: "
                f"{collection_id}/{item.document_id}"
            )

    def _add_document_key(self, keys: set[str], value: Any) -> None:
        key = self._document_key(value)
        if key:
            keys.add(key)

    def _document_key(self, value: Any) -> str:
        return str(value or "").strip()
