"""Freeze accepted Chat correction samples into auditable dataset manifests."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from application.chat.session_service import ChatSessionNotFoundError
from application.evaluation.chat_correction_review_service import (
    ChatCorrectionReviewService,
    ChatCorrectionReviewStaleError,
    ChatCorrectionSampleNotFoundError,
)
from application.repositories.chat_correction_dataset_repository import (
    ChatCorrectionDatasetRepository,
)
from domain.evaluation import (
    ChatCorrectionDatasetExclusion,
    ChatCorrectionDatasetExclusionReason,
    ChatCorrectionDatasetManifest,
    ChatCorrectionDatasetRow,
    ChatCorrectionDatasetSelection,
    ChatCorrectionReviewDecision,
    canonical_json,
    sample_digest,
)


class ChatCorrectionDatasetAccessError(PermissionError):
    """The requested session or sample is outside the caller's collection."""


class ChatCorrectionDatasetInvalidError(ValueError):
    """The requested dataset freeze cannot be represented safely."""


class ChatCorrectionDatasetService:
    def __init__(
        self,
        *,
        chat_session_service: Any,
        review_service: ChatCorrectionReviewService,
        repository: ChatCorrectionDatasetRepository,
        source_artifact_repository: Any,
    ) -> None:
        self.chat_session_service = chat_session_service
        self.review_service = review_service
        self.repository = repository
        self.source_artifact_repository = source_artifact_repository

    async def create_dataset_for_user(
        self,
        *,
        user_id: str,
        collection_id: str,
        selections: Iterable[ChatCorrectionDatasetSelection | Mapping[str, Any]],
        paper_families: Mapping[str, str],
    ) -> ChatCorrectionDatasetManifest:
        collection_id = str(collection_id or "").strip()
        user_id = str(user_id or "").strip()
        if not collection_id or not user_id:
            raise ChatCorrectionDatasetInvalidError("collection_id and user_id are required")
        await self.chat_session_service.collection_service.get_collection_for_user(
            collection_id, user_id
        )
        normalized_inventory = _normalize_inventory(paper_families)
        normalized_selections = _normalize_selections(selections)
        provenance_selections = [item.to_record() for item in normalized_selections]
        exclusions: list[ChatCorrectionDatasetExclusion] = []
        candidates: list[_AcceptedCandidate] = []

        for selection in normalized_selections:
            try:
                session = await self.chat_session_service.get_session_for_user(
                    selection.session_id, user_id
                )
            except (ChatSessionNotFoundError, FileNotFoundError) as exc:
                raise ChatCorrectionDatasetAccessError(
                    f"Chat session is not owned by this user: {selection.session_id}"
                ) from exc
            if session.collection_id != collection_id:
                raise ChatCorrectionDatasetAccessError(
                    "dataset selections must belong to the requested collection"
                )

            stored = await self.review_service.repository.read_sample(
                selection.session_id, selection.sample_id
            )
            if stored is None:
                exclusions.append(
                    _exclusion(
                        selection,
                        ChatCorrectionDatasetExclusionReason.UNRESOLVED,
                        "the requested sample is not present in this owned session",
                    )
                )
                continue
            if stored.collection_id != collection_id:
                raise ChatCorrectionDatasetAccessError(
                    "a correction sample cannot cross collections"
                )
            if not stored.validate_digest():
                exclusions.append(
                    _exclusion(
                        selection,
                        ChatCorrectionDatasetExclusionReason.INVALID_SAMPLE,
                        "the stored correction sample digest is invalid",
                        case_id=stored.case_id,
                    )
                )
                continue

            try:
                current = await self.review_service.current_sample_for_user(
                    selection.session_id, selection.sample_id, user_id
                )
            except ChatCorrectionReviewStaleError as exc:
                exclusions.append(
                    _exclusion(
                        selection,
                        ChatCorrectionDatasetExclusionReason.STALE,
                        str(exc),
                        case_id=stored.case_id,
                    )
                )
                continue
            except (ChatCorrectionSampleNotFoundError, ValueError) as exc:
                exclusions.append(
                    _exclusion(
                        selection,
                        ChatCorrectionDatasetExclusionReason.UNRESOLVED,
                        str(exc),
                        case_id=stored.case_id,
                    )
                )
                continue
            if current.digest != stored.digest:
                exclusions.append(
                    _exclusion(
                        selection,
                        ChatCorrectionDatasetExclusionReason.STALE,
                        "the current Chat trajectory differs from the frozen sample",
                        case_id=stored.case_id,
                    )
                )
                continue

            history = await self.review_service.repository.list_reviews(
                selection.session_id, selection.sample_id
            )
            effective = _effective_review(history)
            if effective is None:
                exclusions.append(
                    _exclusion(
                        selection,
                        ChatCorrectionDatasetExclusionReason.UNRESOLVED,
                        "the sample has no effective human review",
                        case_id=stored.case_id,
                    )
                )
                continue
            if effective.sample_digest != stored.digest:
                exclusions.append(
                    _exclusion(
                        selection,
                        ChatCorrectionDatasetExclusionReason.STALE,
                        "the review points at a different sample digest",
                        case_id=stored.case_id,
                    )
                )
                continue
            exclusion_reason = _review_exclusion_reason(effective.decision)
            if exclusion_reason is not None:
                exclusions.append(
                    _exclusion(
                        selection,
                        exclusion_reason,
                        f"effective review decision is {effective.decision.value}",
                        case_id=stored.case_id,
                    )
                )
                continue

            source_documents, source_error = await self._source_documents(
                collection_id, stored.source_refs
            )
            if source_error is not None:
                exclusions.append(
                    _exclusion(
                        selection,
                        ChatCorrectionDatasetExclusionReason.MISSING_SOURCE,
                        source_error,
                        case_id=stored.case_id,
                    )
                )
                continue
            families = []
            missing_family = []
            for document_id in source_documents:
                family_id = normalized_inventory.get(document_id)
                if family_id is None:
                    missing_family.append(document_id)
                else:
                    families.append({"document_id": document_id, "family_id": family_id})
            if missing_family:
                exclusions.append(
                    _exclusion(
                        selection,
                        ChatCorrectionDatasetExclusionReason.MISSING_PAPER_FAMILY,
                        "paper family is missing for Source document(s): "
                        + ", ".join(sorted(missing_family)),
                        case_id=stored.case_id,
                    )
                )
                continue

            row_content = {
                "sample_id": stored.sample_id,
                "case_id": stored.case_id,
                "session_id": stored.session_id,
                "collection_id": stored.collection_id,
                "model_call_id": stored.model_call_id,
                "input": deepcopy(stored.input),
                "observations": [deepcopy(item) for item in stored.observations],
                "target": stored.target,
                "review_id": effective.review_id,
                "review_digest": effective.sample_digest,
                "source_refs": [deepcopy(item) for item in stored.source_refs],
                "paper_families": sorted(families, key=lambda item: item["document_id"]),
                "session_tree_id": session.root_session_id or session.session_id,
                "split": selection.split.value,
            }
            content_digest = sample_digest(row_content)
            row = ChatCorrectionDatasetRow(
                row_id=f"chat_dataset_row_{content_digest[:40]}",
                content_digest=content_digest,
                **row_content,
            )
            candidates.append(
                _AcceptedCandidate(
                    selection=selection,
                    row=row,
                    family_ids=tuple(item["family_id"] for item in families),
                )
            )

        accepted, partition_exclusions = _remove_partition_conflicts(candidates)
        exclusions.extend(partition_exclusions)
        provenance = {
            "schema": "chat-correction-dataset.v1",
            "collection_id": collection_id,
            "owner_id": user_id,
            "selections": provenance_selections,
            "paper_families": [
                {"document_id": key, "family_id": value}
                for key, value in sorted(normalized_inventory.items())
            ],
            "source_policy": "exact_p3_source_refs",
        }
        manifest = ChatCorrectionDatasetManifest.create(
            owner_id=user_id,
            collection_id=collection_id,
            provenance=provenance,
            rows=tuple(item.row for item in accepted),
            exclusions=tuple(exclusions),
            created_at=_now_iso(),
        )
        return await self.repository.save_manifest(manifest)

    async def freeze_for_user(self, **kwargs: Any) -> ChatCorrectionDatasetManifest:
        """Readable alias used by callers that treat a dataset as a freeze."""

        return await self.create_dataset_for_user(**kwargs)

    async def get_dataset_for_user(
        self, dataset_id: str, user_id: str
    ) -> ChatCorrectionDatasetManifest | None:
        try:
            manifest = await self.repository.read_manifest_for_user(dataset_id, user_id)
        except (TypeError, ValueError, KeyError) as exc:
            raise ChatCorrectionDatasetInvalidError(
                "stored Chat correction dataset is malformed"
            ) from exc
        if manifest is None:
            return None
        _validate_manifest(manifest)
        await self.chat_session_service.collection_service.get_collection_for_user(
            manifest.collection_id, user_id
        )
        return manifest

    async def list_datasets_for_user(
        self,
        user_id: str,
        *,
        collection_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ChatCorrectionDatasetManifest, ...]:
        if collection_id:
            await self.chat_session_service.collection_service.get_collection_for_user(
                collection_id, user_id
            )
        try:
            manifests = await self.repository.list_manifests_for_user(
                user_id, collection_id=collection_id, limit=limit, offset=offset
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise ChatCorrectionDatasetInvalidError(
                "stored Chat correction dataset is malformed"
            ) from exc
        for manifest in manifests:
            _validate_manifest(manifest)
            await self.chat_session_service.collection_service.get_collection_for_user(
                manifest.collection_id, user_id
            )
        return manifests

    async def jsonl_for_user(self, dataset_id: str, user_id: str) -> str:
        manifest = await self.get_dataset_for_user(dataset_id, user_id)
        if manifest is None:
            raise FileNotFoundError(f"chat correction dataset not found: {dataset_id}")
        lines = [
            canonical_json(
                {
                    "record_type": "manifest",
                    "dataset_id": manifest.dataset_id,
                    "collection_id": manifest.collection_id,
                    "manifest_digest": manifest.digest,
                    "provenance_digest": manifest.provenance_digest,
                    "provenance": manifest.provenance,
                }
            )
        ]
        lines.extend(
            canonical_json({"record_type": "sample", **row.to_record()})
            for row in manifest.rows
        )
        lines.extend(
            canonical_json({"record_type": "excluded", **item.to_record()})
            for item in manifest.exclusions
        )
        return "\n".join(lines) + "\n"

    async def _source_documents(
        self, collection_id: str, source_refs: Iterable[Mapping[str, Any]]
    ) -> tuple[tuple[str, ...], str | None]:
        documents: set[str] = set()
        for source in source_refs:
            kind = str(source.get("kind") or "")
            if kind == "message_source":
                if str(source.get("collection_id") or "") != collection_id:
                    return (), "Source reference belongs to another collection"
                document_id = str(source.get("document_id") or "").strip()
                source_ref = str(source.get("source_ref") or "").strip()
                if not document_id or not source_ref:
                    return (), "Source reference is missing its document or locator"
                documents.add(document_id)
            elif kind == "tool_resource":
                # ChatToolResult serializes resource refs as flat records. Older
                # callers may still wrap that record under ``resource_ref``.
                resource = source.get("resource_ref") or source
                if not isinstance(resource, Mapping) or resource.get("resource_type") != "source":
                    continue
                resource_id = str(resource.get("resource_id") or "")
                document_id = resource_id.split(":", 1)[0].strip()
                if document_id:
                    documents.add(document_id)
        if not documents:
            return (), "the accepted sample has no Source identity"
        for document_id in sorted(documents):
            try:
                document = await self.source_artifact_repository.read_document(
                    collection_id, document_id
                )
            except (FileNotFoundError, ValueError):
                document = None
            if document is None:
                return (), f"Source document is not available in this collection: {document_id}"
        return tuple(sorted(documents)), None


class _AcceptedCandidate:
    def __init__(
        self,
        *,
        selection: ChatCorrectionDatasetSelection,
        row: ChatCorrectionDatasetRow,
        family_ids: tuple[str, ...],
    ) -> None:
        self.selection = selection
        self.row = row
        self.family_ids = family_ids


def _normalize_selections(
    selections: Iterable[ChatCorrectionDatasetSelection | Mapping[str, Any]],
) -> tuple[ChatCorrectionDatasetSelection, ...]:
    values: dict[tuple[str, str], ChatCorrectionDatasetSelection] = {}
    conflicts: list[tuple[str, str]] = []
    for value in selections:
        item = value if isinstance(value, ChatCorrectionDatasetSelection) else ChatCorrectionDatasetSelection.from_mapping(value)
        key = (item.session_id, item.sample_id)
        existing = values.get(key)
        if existing is None:
            values[key] = item
        elif existing.split is not item.split:
            conflicts.append(key)
    if conflicts:
        raise ChatCorrectionDatasetInvalidError(
            "a sample cannot be assigned to both train and eval: "
            + ", ".join(f"{session}/{sample}" for session, sample in conflicts)
        )
    return tuple(sorted(values.values(), key=lambda item: (item.session_id, item.sample_id)))


def _normalize_inventory(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ChatCorrectionDatasetInvalidError("paper_families must be a document-to-family mapping")
    result: dict[str, str] = {}
    for raw_document, raw_family in value.items():
        document = str(raw_document or "").strip()
        family = str(raw_family or "").strip()
        if not document or not family:
            raise ChatCorrectionDatasetInvalidError(
                "paper family inventory entries require document_id and family_id"
            )
        result[document] = family
    return result


def _exclusion(
    selection: ChatCorrectionDatasetSelection,
    reason: ChatCorrectionDatasetExclusionReason,
    detail: str,
    *,
    case_id: str | None = None,
) -> ChatCorrectionDatasetExclusion:
    return ChatCorrectionDatasetExclusion(
        sample_id=selection.sample_id,
        session_id=selection.session_id,
        case_id=case_id,
        reason=reason,
        detail=str(detail or reason.value),
    )


def _review_exclusion_reason(
    decision: ChatCorrectionReviewDecision,
) -> ChatCorrectionDatasetExclusionReason | None:
    return {
        ChatCorrectionReviewDecision.WITHDRAW: ChatCorrectionDatasetExclusionReason.WITHDRAWN,
        ChatCorrectionReviewDecision.INSUFFICIENT: ChatCorrectionDatasetExclusionReason.INSUFFICIENT,
        ChatCorrectionReviewDecision.REJECT: ChatCorrectionDatasetExclusionReason.REJECTED,
    }.get(decision)


def _effective_review(reviews: Iterable[Any]) -> Any | None:
    ordered = sorted(reviews, key=lambda item: (item.seq, item.created_at, item.review_id))
    withdrawals = [item for item in ordered if item.decision is ChatCorrectionReviewDecision.WITHDRAW]
    if withdrawals:
        return withdrawals[-1]
    return ordered[-1] if ordered else None


def _remove_partition_conflicts(
    candidates: Iterable[_AcceptedCandidate],
) -> tuple[tuple[_AcceptedCandidate, ...], tuple[ChatCorrectionDatasetExclusion, ...]]:
    values = tuple(candidates)
    conflicts: dict[tuple[str, str], set[ChatCorrectionDatasetSplit]] = defaultdict(set)
    for candidate in values:
        for family_id in candidate.family_ids:
            conflicts[("paper_family", family_id)].add(candidate.row.split)
        conflicts[("session_tree", candidate.row.session_tree_id)].add(candidate.row.split)
    conflicting_keys = {key for key, splits in conflicts.items() if len(splits) > 1}
    accepted: list[_AcceptedCandidate] = []
    excluded: list[ChatCorrectionDatasetExclusion] = []
    for candidate in values:
        keys = {
            *(('paper_family', family_id) for family_id in candidate.family_ids),
            ("session_tree", candidate.row.session_tree_id),
        }
        hit = sorted(key[1] for key in keys if key in conflicting_keys)
        if hit:
            excluded.append(
                ChatCorrectionDatasetExclusion(
                    sample_id=candidate.row.sample_id,
                    session_id=candidate.row.session_id,
                    case_id=candidate.row.case_id,
                    reason=ChatCorrectionDatasetExclusionReason.PARTITION_CONFLICT,
                    detail="paper family or session tree spans train and eval: " + ", ".join(hit),
                )
            )
        else:
            accepted.append(candidate)
    return tuple(accepted), tuple(excluded)


def _validate_manifest(manifest: ChatCorrectionDatasetManifest) -> None:
    if not manifest.validate_digest():
        raise ChatCorrectionDatasetInvalidError("stored dataset manifest digest is invalid")
    for row in manifest.rows:
        if row.collection_id != manifest.collection_id:
            raise ChatCorrectionDatasetInvalidError("dataset row crosses collections")
        if not row.content_digest == sample_digest(row.content_for_digest()):
            raise ChatCorrectionDatasetInvalidError("stored dataset row digest is invalid")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "ChatCorrectionDatasetAccessError",
    "ChatCorrectionDatasetInvalidError",
    "ChatCorrectionDatasetService",
]
