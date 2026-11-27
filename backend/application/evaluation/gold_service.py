from __future__ import annotations

from typing import Any, Sequence

from domain.evaluation import EvaluationGoldItem, EvaluationGoldSet
from domain.evaluation.records import (
    EVALUATION_TARGET_LAYERS,
)


from repositories.evaluation_repository import EvaluationRepo
from application.source import workspace_service


async def register_gold_set(
    *,
    workspace_id: str,
    gold_id: str,
    version: str = "v1",
    target_layer: str = "core",
    metric_profile: str = "materials_core_v1",
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
    items: Sequence[EvaluationGoldItem],
) -> EvaluationGoldSet:
    await workspace_service.get_workspace(workspace_id)
    workspace_document_ids = await _workspace_document_ids(workspace_id)
    if target_layer not in EVALUATION_TARGET_LAYERS:
        raise ValueError(f"unsupported evaluation target layer: {target_layer}")
    gold_set = EvaluationGoldSet(
        gold_id=gold_id,
        workspace_id=workspace_id,
        version=version,
        target_layer=target_layer,
        metric_profile=metric_profile,
        description=description,
        metadata=metadata,
    )
    gold_items = tuple(items)
    _validate_gold_item_documents(
        workspace_id=workspace_id,
        workspace_document_ids=workspace_document_ids,
        gold_items=gold_items,
    )
    await EvaluationRepo.upsert_gold_set(gold_set, gold_items)
    return gold_set


async def _workspace_document_ids(workspace_id: str) -> set[str]:
    keys: set[str] = set()
    workspace = await workspace_service.get_workspace(workspace_id)
    for record in workspace.documents:
        keys.update((record.document.document_id, record.document.filename,
                     record.storage_key, record.storage_key))
    return keys


def _validate_gold_item_documents(
    *,
    workspace_id: str,
    workspace_document_ids: set[str],
    gold_items: tuple[EvaluationGoldItem, ...],
) -> None:
    if not workspace_document_ids:
        return
    for item in gold_items:
        document_id = item.document_id
        if document_id and document_id in workspace_document_ids:
            continue
        raise ValueError(
            "gold item document is not in workspace: "
            f"{workspace_id}/{item.document_id}"
        )
