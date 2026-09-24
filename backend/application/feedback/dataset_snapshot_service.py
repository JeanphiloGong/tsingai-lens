"""Freeze reviewed feedback cases into reproducible dataset snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable
from uuid import uuid4

from application.repositories.chat_repository import ChatRepository
from application.repositories.dataset_snapshot_repository import DatasetSnapshotRepository
from application.repositories.feedback_case_repository import FeedbackCaseRepository
from application.source.collection_service import CollectionService
from domain.chat import ChatMessageRole
from domain.feedback import DatasetSnapshot, DatasetType, FeedbackCase


@dataclass(frozen=True)
class DatasetSelection:
    case_id: str
    split: str


class DatasetSnapshotError(ValueError):
    """A user-correctable dataset selection or provenance error."""


class DatasetSnapshotService:
    """Build immutable rows from the current reviewed case projection."""

    def __init__(
        self,
        *,
        repository: DatasetSnapshotRepository,
        case_repository: FeedbackCaseRepository,
        chat_repository: ChatRepository,
        collection_service: CollectionService,
    ) -> None:
        self.repository = repository
        self.case_repository = case_repository
        self.chat_repository = chat_repository
        self.collection_service = collection_service

    async def create_for_user(
        self,
        *,
        owner_id: str,
        collection_id: str,
        dataset_type: DatasetType | str,
        selections: tuple[DatasetSelection, ...],
        paper_families: dict[str, str] | None = None,
        now: str | None = None,
    ) -> DatasetSnapshot:
        await self.collection_service.get_collection_for_user(collection_id, owner_id)
        if dataset_type not in {"evaluation", "sft", "preference"}:
            raise DatasetSnapshotError("dataset_type_invalid")
        if len(selections) > 500:
            raise DatasetSnapshotError("dataset_selection_too_large")
        timestamp = now or datetime.now(timezone.utc).isoformat()
        families = _normalise_families(paper_families or {})
        rows: list[dict[str, Any]] = []
        exclusions: list[dict[str, Any]] = []
        provenance_items: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for selection in selections:
            key = (selection.case_id, selection.split)
            if key in seen:
                exclusions.append(_exclusion(selection, "duplicate_selection"))
                continue
            seen.add(key)
            if selection.split not in {"train", "eval"}:
                exclusions.append(_exclusion(selection, "split_invalid"))
                continue
            try:
                candidate = await self._candidate(
                    owner_id=owner_id,
                    collection_id=collection_id,
                    dataset_type=dataset_type,  # type: ignore[arg-type]
                    selection=selection,
                    paper_families=families,
                )
            except DatasetSnapshotError as exc:
                exclusions.append(_exclusion(selection, str(exc)))
                continue
            rows.append(candidate.row)
            provenance_items.append(candidate.provenance)

        # Selection order is a UI detail. Canonical ordering keeps repeated
        # exports of the same reviewed material on the same digest.
        rows.sort(key=lambda item: (str(item.get("split")), str(item.get("row_id"))))
        exclusions.sort(
            key=lambda item: (
                str(item.get("case_id")),
                str(item.get("split")),
                str(item.get("reason")),
                str(item.get("detail")),
            )
        )
        provenance_items.sort(
            key=lambda item: (
                str(item.get("case_id")),
                str(item.get("split")),
            )
        )
        _ensure_split_isolation(rows)
        provenance = {
            "schema_version": "feedback-dataset-provenance.v1",
            "collection_id": collection_id,
            "dataset_type": dataset_type,
            "paper_families": families,
            "items": provenance_items,
        }
        provenance_digest = _digest(provenance)
        digest_basis = {
            "schema_version": "feedback-dataset.v1",
            "owner_id": owner_id,
            "collection_id": collection_id,
            "dataset_type": dataset_type,
            "rows": rows,
            "exclusions": exclusions,
            "provenance_digest": provenance_digest,
        }
        manifest_digest = _digest(digest_basis)
        dataset_id = f"dataset_{uuid4().hex[:32]}"
        content = jsonl_bytes_for_rows(rows)
        content_digest = hashlib.sha256(content).hexdigest()
        manifest = {
            **digest_basis,
            "dataset_id": dataset_id,
            "row_count": len(rows),
            "excluded_count": len(exclusions),
            "empty": not rows,
            "manifest_digest": manifest_digest,
            "content_digest": content_digest,
            "created_at": timestamp,
        }
        snapshot = DatasetSnapshot(
            dataset_id=dataset_id,
            owner_id=owner_id,
            collection_id=collection_id,
            dataset_type=dataset_type,  # type: ignore[arg-type]
            rows=tuple(rows),
            exclusions=tuple(exclusions),
            provenance=provenance,
            manifest=manifest,
            manifest_digest=manifest_digest,
            provenance_digest=provenance_digest,
            content_digest=content_digest,
            created_at=timestamp,
        )
        return await self.repository.save(snapshot)

    async def list_for_user(
        self,
        *,
        owner_id: str,
        collection_id: str | None = None,
        dataset_type: DatasetType | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[DatasetSnapshot, ...]:
        if limit < 1 or limit > 200 or offset < 0:
            raise DatasetSnapshotError("pagination_invalid")
        if dataset_type is not None and dataset_type not in {
            "evaluation", "sft", "preference"
        }:
            raise DatasetSnapshotError("dataset_type_invalid")
        if collection_id is not None:
            await self.collection_service.get_collection_for_user(collection_id, owner_id)
        else:
            # Listing without a collection still needs to be bounded to the
            # user's owned collections; the repository applies owner scope.
            pass
        return await self.repository.list_for_owner(
            owner_id=owner_id,
            collection_id=collection_id,
            dataset_type=dataset_type,  # type: ignore[arg-type]
            limit=limit,
            offset=offset,
        )

    async def read_for_user(self, *, owner_id: str, dataset_id: str) -> DatasetSnapshot:
        snapshot = await self.repository.read(dataset_id)
        if snapshot is None or snapshot.owner_id != owner_id:
            raise FileNotFoundError(f"dataset snapshot not found: {dataset_id}")
        await self.collection_service.get_collection_for_user(snapshot.collection_id, owner_id)
        return snapshot

    async def jsonl_for_user(self, *, owner_id: str, dataset_id: str) -> tuple[DatasetSnapshot, bytes]:
        snapshot = await self.read_for_user(owner_id=owner_id, dataset_id=dataset_id)
        payload = jsonl_bytes_for_rows(snapshot.rows)
        if hashlib.sha256(payload).hexdigest() != snapshot.content_digest:
            raise RuntimeError("dataset_snapshot_content_digest_mismatch")
        return snapshot, payload

    async def _candidate(
        self,
        *,
        owner_id: str,
        collection_id: str,
        dataset_type: DatasetType,
        selection: DatasetSelection,
        paper_families: dict[str, str],
    ) -> "_Candidate":
        case = await self.case_repository.read_case(selection.case_id)
        if case is None or case.collection_id != collection_id:
            raise DatasetSnapshotError("case_not_in_collection")
        session = await self.chat_repository.read_session(case.session_id)
        if (
            session is None
            or session.user_id != owner_id
            or session.collection_id != collection_id
        ):
            raise DatasetSnapshotError("case_not_accessible")
        annotation = await self.case_repository.read_annotation(case.case_id)
        if annotation is None or case.annotation_digest != annotation.annotation_digest:
            raise DatasetSnapshotError("annotation_stale")
        decisions = await self.case_repository.read_review_decisions(case.case_id)
        current_decisions = [
            item for item in decisions if item.annotation_digest == annotation.annotation_digest
        ]
        current = max(
            current_decisions,
            key=lambda item: (item.seq, item.created_at, item.decision_id),
            default=None,
        )
        if case.status != "accepted" or current is None or current.decision != "accept":
            raise DatasetSnapshotError("review_not_accepted")
        if dataset_type not in annotation.dataset_uses:
            raise DatasetSnapshotError("dataset_use_not_authorized")
        messages = await self.chat_repository.read_messages(case.session_id)
        answer = next(
            (item for item in messages if item.message_id == case.anchor_message_id), None
        )
        if answer is None or answer.role is not ChatMessageRole.ASSISTANT:
            raise DatasetSnapshotError("anchor_answer_missing")
        question = _question_before(messages, answer.created_at)
        if not question:
            question = str(case.context_snapshot.get("question") or "").strip()
        if not question:
            raise DatasetSnapshotError("input_missing")
        answer_text = answer.content.strip()
        if not answer_text:
            raise DatasetSnapshotError("answer_missing")
        results = await self.case_repository.read_analysis_results(case.analysis_result_ids)
        coverage = _latest_coverage(results, case.context_snapshot)
        document_ids = _document_ids(coverage, messages)
        missing_families = sorted(document_id for document_id in document_ids if document_id not in paper_families)
        if missing_families:
            raise DatasetSnapshotError("paper_family_missing:" + ",".join(missing_families))
        source_refs = tuple(dict.fromkeys(annotation.support_source_refs))
        allowed_source_refs = _coverage_source_refs(
            coverage,
            case.context_snapshot,
            suggested_evidence=(
                source_ref
                for result in results
                for source_ref in result.suggested_evidence
            ),
        )
        if any(source_ref not in allowed_source_refs for source_ref in source_refs):
            raise DatasetSnapshotError("source_not_in_case")
        if dataset_type in {"sft", "preference"}:
            if not annotation.target:
                raise DatasetSnapshotError("target_missing")
            if not source_refs:
                raise DatasetSnapshotError("support_source_missing")
        target = annotation.target.strip() if annotation.target else None
        if dataset_type == "preference" and (not target or target == answer_text):
            raise DatasetSnapshotError("preference_pair_missing")
        session_tree_id = session.root_session_id or session.session_id
        family_values = tuple(sorted({paper_families[item] for item in document_ids}))
        base: dict[str, Any] = {
            "case_id": case.case_id,
            "session_id": case.session_id,
            "collection_id": collection_id,
            "anchor_message_id": case.anchor_message_id,
            "annotation_digest": annotation.annotation_digest,
            "review_id": current.decision_id,
            "review_digest": current.annotation_digest,
            "source_refs": list(source_refs),
            "paper_families": {item: paper_families[item] for item in sorted(document_ids)},
            "paper_family_keys": list(family_values),
            "session_tree_id": session_tree_id,
            "split": selection.split,
        }
        if dataset_type == "evaluation":
            row = {
                **base,
                "record_type": "evaluation",
                "input": question,
                "reference": target,
                "evidence": list(source_refs),
                "criteria": [annotation.reason, *_as_texts(coverage.get("gaps"))],
            }
        elif dataset_type == "sft":
            row = {
                **base,
                "record_type": "sft",
                "messages": [{"role": "user", "content": question}],
                "target": target,
            }
        else:
            row = {
                **base,
                "record_type": "preference",
                "prompt": [{"role": "user", "content": question}],
                "chosen": target,
                "rejected": answer_text,
                "comparison_reason": annotation.reason,
            }
        row["content_digest"] = _digest(row)
        row["row_id"] = f"row_{row['content_digest'][:32]}"
        provenance = {
            "case_id": case.case_id,
            "annotation_digest": annotation.annotation_digest,
            "review_id": current.decision_id,
            "review_digest": current.annotation_digest,
            "session_id": case.session_id,
            "session_tree_id": session_tree_id,
            "split": selection.split,
            "source_refs": list(source_refs),
            "document_ids": sorted(document_ids),
            "paper_families": {item: paper_families[item] for item in sorted(document_ids)},
        }
        return _Candidate(row=row, provenance=provenance)


@dataclass(frozen=True)
class _Candidate:
    row: dict[str, Any]
    provenance: dict[str, Any]


def jsonl_bytes_for_rows(rows: Iterable[dict[str, Any]]) -> bytes:
    encoded = [
        json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        for row in rows
    ]
    return ("\n".join(encoded) + ("\n" if encoded else "")).encode("utf-8")


def _normalise_families(values: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in values.items():
        document_id = str(key).strip()
        family = str(value).strip()
        if document_id and family:
            result[document_id] = family
    return result


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _exclusion(selection: DatasetSelection, reason: str) -> dict[str, Any]:
    return {
        "case_id": selection.case_id,
        "split": selection.split,
        "reason": reason.split(":", 1)[0],
        "detail": reason,
    }


def _question_before(messages: tuple[Any, ...], answer_created_at: str) -> str:
    candidates = [
        item.content.strip()
        for item in messages
        if item.role is ChatMessageRole.USER and item.created_at <= answer_created_at
    ]
    return candidates[-1] if candidates else ""


def _latest_coverage(results: tuple[Any, ...], context: dict[str, Any]) -> dict[str, Any]:
    if results:
        latest = max(results, key=lambda item: (item.created_at, item.result_id))
        return latest.evidence_coverage.to_record()
    return dict(context.get("evidence_coverage") or context)


def _document_ids(coverage: dict[str, Any], messages: tuple[Any, ...]) -> set[str]:
    ids: set[str] = set()
    for field in ("requested_scope", "inspected_sources", "omitted_candidates", "claim_support"):
        for item in coverage.get(field) or ():
            if isinstance(item, dict):
                value = item.get("document_id")
                if value:
                    ids.add(str(value))
    for message in messages:
        for source in getattr(message, "source_contexts", ()):
            value = getattr(source, "document_id", None)
            if value:
                ids.add(str(value))
    return ids


def _coverage_source_refs(
    coverage: dict[str, Any],
    context: dict[str, Any],
    *,
    suggested_evidence: Iterable[Any] = (),
) -> set[str]:
    refs: set[str] = set()
    for field in ("inspected_sources", "omitted_candidates", "claim_support"):
        for item in coverage.get(field) or ():
            if isinstance(item, dict):
                value = item.get("source_ref") or item.get("source_id")
                if value:
                    refs.add(str(value))
    for item in context.get("source_refs") or ():
        if isinstance(item, dict):
            value = item.get("source_ref") or item.get("source_id")
        else:
            value = item
        if value:
            refs.add(str(value))
    refs.update(str(value) for value in suggested_evidence if str(value).strip())
    return refs


def _as_texts(values: Any) -> list[str]:
    return [str(value) for value in values or () if str(value).strip()]


def _ensure_split_isolation(rows: list[dict[str, Any]]) -> None:
    for field in ("paper_family_keys", "session_tree_id"):
        seen: dict[str, set[str]] = {}
        for row in rows:
            values = row.get(field) if field == "paper_family_keys" else [row.get(field)]
            for value in values or ():
                if value:
                    seen.setdefault(str(value), set()).add(str(row["split"]))
        leaked = sorted(key for key, splits in seen.items() if len(splits) > 1)
        if leaked:
            raise DatasetSnapshotError("dataset_split_leakage:" + ",".join(leaked))


__all__ = [
    "DatasetSelection",
    "DatasetSnapshotError",
    "DatasetSnapshotService",
    "jsonl_bytes_for_rows",
]
