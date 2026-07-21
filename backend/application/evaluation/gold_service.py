from __future__ import annotations

from typing import Any, Mapping

from application.source.collection_service import CollectionService
from domain.evaluation import EvaluationGoldItem, EvaluationGoldSet
from domain.ports import EvaluationRepository


class EvaluationGoldService:
    """Register collection-bound gold answers for evaluation runs."""

    def __init__(
        self,
        collection_service: CollectionService,
        evaluation_repository: EvaluationRepository,
    ) -> None:
        self.collection_service = collection_service
        self.evaluation_repository = evaluation_repository

    def register_gold_set(
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
        self.collection_service.get_collection(collection_id)
        collection_document_ids = self._collection_document_ids(collection_id)
        gold_set = EvaluationGoldSet.from_mapping(
            {
                "gold_id": gold_id,
                "collection_id": collection_id,
                "version": version,
                "target_layer": target_layer,
                "metric_profile": metric_profile,
                "description": description,
                "metadata": metadata or {},
            }
        )
        gold_items = tuple(
            self._gold_item_from_input(gold_set.gold_id, item) for item in items
        )
        self._validate_gold_item_documents(
            collection_id=collection_id,
            collection_document_ids=collection_document_ids,
            gold_items=gold_items,
        )
        self.evaluation_repository.upsert_gold_set(gold_set, gold_items)
        return gold_set

    def _gold_item_from_input(
        self,
        gold_id: str,
        item: Mapping[str, Any],
    ) -> EvaluationGoldItem:
        payload = dict(item)
        payload["gold_id"] = gold_id
        return EvaluationGoldItem.from_mapping(payload)

    def _collection_document_ids(self, collection_id: str) -> set[str]:
        keys: set[str] = set()
        for record in self.collection_service.list_files(collection_id):
            for field in (
                "document_id",
                "source_document_id",
                "file_id",
                "original_filename",
                "stored_filename",
                "storage_key",
            ):
                self._add_document_key(keys, record.get(field))
        manifest = self.collection_service.get_import_manifest(collection_id)
        for import_record in manifest.get("imports", []):
            if not isinstance(import_record, Mapping):
                continue
            documents = import_record.get("documents")
            if not isinstance(documents, list):
                continue
            for document in documents:
                if not isinstance(document, Mapping):
                    continue
                for field in (
                    "document_id",
                    "source_document_id",
                    "original_filename",
                    "stored_filename",
                    "storage_key",
                ):
                    self._add_document_key(keys, document.get(field))
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
