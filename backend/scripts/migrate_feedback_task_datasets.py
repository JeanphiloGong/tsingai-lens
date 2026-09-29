#!/usr/bin/env python3
"""Migrate legacy feedback snapshots and annotations into task datasets.

The migration is deliberately one way.  Legacy snapshots are read as input,
while the product read path is owned by Dataset, DatasetSample, and
DatasetExport.  A migrated sample is never confirmed automatically.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


MIGRATION_VERSION = "feedback-task-datasets.v1"
LEGACY_SNAPSHOT_TABLE = "feedback_dataset_snapshots"


@dataclass(frozen=True)
class DatasetMigrationSpec:
    dataset_id: str
    collection_id: str
    owner_id: str
    name: str
    task_type: str
    construction_spec: dict[str, Any]
    created_at: str

    def to_record(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "collection_id": self.collection_id,
            "owner_id": self.owner_id,
            "name": self.name,
            "task_type": self.task_type,
            "construction_spec": dict(self.construction_spec),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class DatasetMigrationItem:
    import_key: str
    dataset_id: str
    sample_id: str
    source_case_id: str
    task_type: str
    source_digest: str
    status: str
    missing_reasons: tuple[str, ...]
    revision_id: str | None
    content: dict[str, Any] | None
    provenance: dict[str, Any]
    created_at: str

    def to_record(self) -> dict[str, Any]:
        return {
            "import_key": self.import_key,
            "dataset_id": self.dataset_id,
            "sample_id": self.sample_id,
            "source_case_id": self.source_case_id,
            "task_type": self.task_type,
            "source_digest": self.source_digest,
            "status": self.status,
            "missing_reasons": list(self.missing_reasons),
            "revision_id": self.revision_id,
            "content_digest": _digest(self.content) if self.content else None,
            "provenance": dict(self.provenance),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class DatasetMigrationPlan:
    run_id: str
    datasets: tuple[DatasetMigrationSpec, ...]
    items: tuple[DatasetMigrationItem, ...]
    skipped: tuple[dict[str, Any], ...]

    def summary(self) -> dict[str, Any]:
        legacy_snapshot_ids = {
            str(item.construction_spec.get("legacy_identity"))
            for item in self.datasets
            if item.construction_spec.get("source") == "legacy_snapshot"
            and item.construction_spec.get("legacy_identity")
        }
        legacy_snapshot_ids.update(
            str(item.provenance.get("legacy_snapshot_id"))
            for item in self.items
            if item.provenance.get("legacy_snapshot_id")
        )
        return {
            "run_id": self.run_id,
            "migration_version": MIGRATION_VERSION,
            "legacy_snapshot_count": len(legacy_snapshot_ids),
            "dataset_candidates": len(self.datasets),
            "sample_candidates": len(self.items),
            "needs_confirmation": sum(
                item.status == "needs_confirmation" for item in self.items
            ),
            "needs_input": sum(item.status == "needs_input" for item in self.items),
            "skipped": len(self.skipped),
            "created_datasets": 0,
            "created_samples": 0,
            "created_revisions": 0,
            "existing_datasets": 0,
            "existing_samples": 0,
        }


def stable_id(prefix: str, *parts: object) -> str:
    """Create a deterministic identity without reusing a legacy primary key."""

    encoded = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:32]}"


def legacy_row_to_content(
    task_type: str,
    row: Mapping[str, Any] | None,
    *,
    fallback_criteria: Iterable[str] = (),
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    """Translate an old model-facing row into the new revision union.

    Old snapshots used ``quote`` in evidence and used ``prompt`` plus
    ``chosen/rejected`` for preference rows.  New revisions have one stable
    shape per task and keep only readable text in model content.
    """

    if task_type not in {"sft", "preference", "evaluation"}:
        return None, ("legacy_task_type_invalid",)
    if not isinstance(row, Mapping):
        return None, ("legacy_row_missing",)

    evidence, evidence_errors = _legacy_evidence(row.get("evidence"))
    if evidence_errors:
        return None, evidence_errors
    messages, message_errors = _legacy_messages(task_type, row)
    if message_errors:
        return None, message_errors
    assert messages is not None
    assert evidence is not None

    if task_type == "sft":
        target = _text(row.get("target"))
        if not target:
            return None, ("legacy_target_missing",)
        content: dict[str, Any] = {
            "schema_version": "literature-sft.v1",
            "messages": messages,
            "context": evidence,
            "target": target,
            "evidence": evidence,
        }
    elif task_type == "preference":
        chosen = _text(row.get("chosen"))
        rejected = _text(row.get("rejected"))
        if not chosen or not rejected:
            return None, ("legacy_preference_pair_missing",)
        if chosen == rejected:
            return None, ("legacy_preference_pair_equal",)
        content = {
            "schema_version": "literature-preference.v1",
            "messages": messages,
            "context": evidence,
            "response_a": chosen,
            "response_b": rejected,
            # A previous accept is not a new human preference confirmation.
            "suggested_preference": None,
            "rationale": _text(row.get("comparison_reason")),
            "evidence": evidence,
            "human_preference": None,
        }
    else:
        reference = _text(row.get("reference"))
        criteria = _texts(row.get("criteria"))
        criteria = tuple(dict.fromkeys((*criteria, *fallback_criteria)))
        if not criteria:
            return None, ("legacy_evaluation_criteria_missing",)
        mode = "reference" if reference else "rubric"
        content = {
            "schema_version": "literature-evaluation.v1",
            "messages": messages,
            "context": evidence,
            "reference": reference,
            "criteria": list(criteria),
            "evaluation_mode": mode,
            "evidence": evidence,
        }

    try:
        # Import lazily so this pure conversion remains easy to exercise from
        # the migration unit tests.
        from domain.feedback.sample_revision import parse_revision_content

        parsed = parse_revision_content(content)
    except (TypeError, ValueError) as exc:
        return None, (f"legacy_content_invalid:{str(exc)}",)
    return parsed.to_record(), ()


def build_plan_from_records(
    *,
    snapshots: Iterable[Mapping[str, Any]],
    cases: Iterable[Mapping[str, Any]],
    annotations: Iterable[Mapping[str, Any]],
    reviews: Iterable[Mapping[str, Any]],
    now: str | None = None,
) -> DatasetMigrationPlan:
    """Build a deterministic plan from legacy records.

    This function has no database writes.  It is the dry-run contract and is
    also the main unit-test seam for the migration mapping rules.
    """

    timestamp = now or datetime.now(timezone.utc).isoformat()
    case_map = {str(item.get("case_id")): dict(item) for item in cases if item.get("case_id")}
    annotation_map = _latest_annotations(annotations)
    review_map = _accepted_reviews(reviews)
    datasets: dict[str, DatasetMigrationSpec] = {}
    items: dict[str, DatasetMigrationItem] = {}
    skipped: list[dict[str, Any]] = []
    covered_case_tasks: set[tuple[str, str]] = set()

    for snapshot in sorted(snapshots, key=lambda item: str(item.get("dataset_id") or "")):
        legacy_id = _text(snapshot.get("dataset_id"))
        if not legacy_id:
            skipped.append({"reason": "legacy_snapshot_id_missing"})
            continue
        task_type = _text(snapshot.get("dataset_type"))
        owner_id = _text(snapshot.get("owner_id"))
        collection_id = _text(snapshot.get("collection_id"))
        if task_type not in {"sft", "preference", "evaluation"}:
            skipped.append({"legacy_snapshot_id": legacy_id, "reason": "legacy_task_type_invalid"})
            continue
        if not owner_id or not collection_id:
            skipped.append({"legacy_snapshot_id": legacy_id, "reason": "legacy_snapshot_scope_missing"})
            continue
        dataset_id = stable_id("fdset_mig", legacy_id)
        dataset_key = f"snapshot:{legacy_id}"
        datasets.setdefault(
            dataset_key,
            _dataset_spec(
                dataset_id=dataset_id,
                owner_id=owner_id,
                collection_id=collection_id,
                task_type=task_type,
                created_at=_text(snapshot.get("created_at")) or timestamp,
                legacy_id=legacy_id,
                source="legacy_snapshot",
            ),
        )
        rows = tuple(snapshot.get("rows") or ())
        provenance_items = tuple(
            (snapshot.get("provenance") or {}).get("items") or ()
        )
        if not provenance_items:
            if rows:
                skipped.append(
                    {
                        "legacy_snapshot_id": legacy_id,
                        "reason": "legacy_provenance_items_missing",
                    }
                )
            continue
        rows_by_digest: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            # P5 snapshots were written with ensure_ascii=True. Keep that
            # exact digest as a migration-only lookup key so non-ASCII rows
            # do not fall back to positional matching or become false gaps.
            rows_by_digest.setdefault(_digest(row), row)
            rows_by_digest.setdefault(_legacy_digest(row), row)
        for index, raw_provenance in enumerate(provenance_items):
            if not isinstance(raw_provenance, Mapping):
                skipped.append(
                    {
                        "legacy_snapshot_id": legacy_id,
                        "reason": "legacy_provenance_item_invalid",
                        "index": index,
                    }
                )
                continue
            provenance = dict(raw_provenance)
            case_id = _text(provenance.get("case_id"))
            if not case_id:
                skipped.append(
                    {
                        "legacy_snapshot_id": legacy_id,
                        "reason": "legacy_case_id_missing",
                        "index": index,
                    }
                )
                continue
            case = case_map.get(case_id)
            if case is None:
                skipped.append(
                    {
                        "legacy_snapshot_id": legacy_id,
                        "case_id": case_id,
                        "reason": "legacy_case_missing",
                    }
                )
                continue
            row = rows_by_digest.get(_text(provenance.get("row_digest")))
            if row is None and index < len(rows) and isinstance(rows[index], Mapping):
                row = rows[index]
            annotation = annotation_map.get(case_id)
            fallback_criteria = _texts((annotation or {}).get("reason"))
            content, errors = legacy_row_to_content(
                task_type,
                row,
                fallback_criteria=fallback_criteria,
            )
            if content is None and not errors:
                errors = ("legacy_content_missing",)
            item = _make_item(
                dataset_id=dataset_id,
                source_case_id=case_id,
                task_type=task_type,
                case=case,
                content=content,
                missing_reasons=errors,
                provenance={
                    **provenance,
                    "legacy_snapshot_id": legacy_id,
                    "legacy_dataset_type": task_type,
                    "migration_version": MIGRATION_VERSION,
                },
                created_at=_text(snapshot.get("created_at")) or timestamp,
            )
            if item.import_key in items:
                continue
            items[item.import_key] = item
            covered_case_tasks.add((case_id, task_type))

    # Preserve annotated cases that were never present in a legacy snapshot.
    # They are still candidates, but their new content must be checked by a
    # human before it can be confirmed or exported.
    for case_id, annotation in sorted(annotation_map.items()):
        case = case_map.get(case_id)
        if case is None or _text(case.get("status")) in {"withdrawn", "rejected", "insufficient"}:
            continue
        if not _accepted_review(case_id, annotation, review_map):
            continue
        owner_id = _text(annotation.get("created_by"))
        collection_id = _text(case.get("collection_id"))
        if not owner_id or not collection_id:
            skipped.append({"case_id": case_id, "reason": "legacy_case_scope_missing"})
            continue
        for task_type in _texts(annotation.get("dataset_uses")):
            if task_type not in {"sft", "preference", "evaluation"}:
                continue
            dataset_key = f"case:{owner_id}:{collection_id}:{task_type}"
            dataset_id = stable_id("fdset_mig_case", owner_id, collection_id, task_type)
            if (case_id, task_type) in covered_case_tasks:
                continue
            datasets.setdefault(
                dataset_key,
                _dataset_spec(
                    dataset_id=dataset_id,
                    owner_id=owner_id,
                    collection_id=collection_id,
                    task_type=task_type,
                    created_at=_text(case.get("created_at")) or timestamp,
                    legacy_id=case_id,
                    source="legacy_case",
                ),
            )
            row = _row_from_case(case, annotation, task_type)
            content, errors = legacy_row_to_content(
                task_type,
                row,
                fallback_criteria=_texts(annotation.get("reason")),
            )
            item = _make_item(
                dataset_id=dataset_id,
                source_case_id=case_id,
                task_type=task_type,
                case=case,
                content=content,
                missing_reasons=errors or ("legacy_snapshot_row_missing",),
                provenance={
                    "legacy_case_id": case_id,
                    "legacy_annotation_digest": _text(annotation.get("annotation_digest")),
                    "legacy_review_id": _text(review_map.get(case_id, {}).get("decision_id")),
                    "migration_version": MIGRATION_VERSION,
                },
                created_at=_text(case.get("created_at")) or timestamp,
            )
            items.setdefault(item.import_key, item)

    return DatasetMigrationPlan(
        run_id=f"migration_{uuid4().hex[:32]}",
        datasets=tuple(sorted(datasets.values(), key=lambda item: item.dataset_id)),
        items=tuple(sorted(items.values(), key=lambda item: item.import_key)),
        skipped=tuple(skipped),
    )


async def build_migration_plan(
    session: AsyncSession,
    *,
    now: str | None = None,
) -> DatasetMigrationPlan:
    """Read the legacy tables without exposing them through product APIs."""

    from infra.persistence.postgres.models.feedback import (
        FeedbackAnnotationRow,
        FeedbackCaseRow,
        FeedbackDatasetSnapshotRow,
        FeedbackReviewDecisionRow,
    )

    snapshots = await session.scalars(
        select(FeedbackDatasetSnapshotRow).order_by(FeedbackDatasetSnapshotRow.dataset_id)
    )
    cases = await session.scalars(select(FeedbackCaseRow).order_by(FeedbackCaseRow.case_id))
    annotations = await session.scalars(
        select(FeedbackAnnotationRow).order_by(
            FeedbackAnnotationRow.case_id,
            FeedbackAnnotationRow.version,
        )
    )
    reviews = await session.scalars(
        select(FeedbackReviewDecisionRow).order_by(
            FeedbackReviewDecisionRow.case_id,
            FeedbackReviewDecisionRow.seq,
        )
    )
    return build_plan_from_records(
        snapshots=[_snapshot_record(item) for item in snapshots],
        cases=[_case_record(item) for item in cases],
        annotations=[_annotation_record(item) for item in annotations],
        reviews=[_review_record(item) for item in reviews],
        now=now,
    )


async def apply_plan(
    session: AsyncSession,
    plan: DatasetMigrationPlan,
) -> dict[str, int]:
    """Insert the plan idempotently in the caller's transaction."""

    from infra.persistence.postgres.models.feedback_dataset import (
        FeedbackDatasetRow,
        FeedbackDatasetSampleRow,
        FeedbackSampleRevisionRow,
    )

    counts = {
        "created_datasets": 0,
        "created_samples": 0,
        "created_revisions": 0,
        "existing_datasets": 0,
        "existing_samples": 0,
    }
    datasets_by_id = {item.dataset_id: item for item in plan.datasets}
    for spec in datasets_by_id.values():
        row = await session.get(FeedbackDatasetRow, spec.dataset_id, with_for_update=True)
        if row is None:
            session.add(
                FeedbackDatasetRow(
                    dataset_id=spec.dataset_id,
                    collection_id=spec.collection_id,
                    name=spec.name,
                    task_type=spec.task_type,
                    construction_spec=dict(spec.construction_spec),
                    spec_version=1,
                    created_by=spec.owner_id,
                    created_at=_datetime(spec.created_at),
                    updated_at=_datetime(spec.created_at),
                )
            )
            counts["created_datasets"] += 1
        else:
            counts["existing_datasets"] += 1
            _assert_dataset_identity(row, spec)
    await session.flush()

    for item in plan.items:
        row = await session.scalar(
            select(FeedbackDatasetSampleRow)
            .where(
                FeedbackDatasetSampleRow.dataset_id == item.dataset_id,
                FeedbackDatasetSampleRow.source_case_id == item.source_case_id,
            )
            .with_for_update()
        )
        if row is None:
            row = FeedbackDatasetSampleRow(
                sample_id=item.sample_id,
                dataset_id=item.dataset_id,
                source_case_id=item.source_case_id,
                status=item.status,
                current_revision_id=None,
                confirmed_revision_id=None,
                generation=1,
                source_digest=item.source_digest,
                active_job_id=None,
                missing_reasons=list(item.missing_reasons),
                created_at=_datetime(item.created_at),
                updated_at=_datetime(item.created_at),
                confirmed_by=None,
                confirmed_at=None,
            )
            session.add(row)
            await session.flush()
            counts["created_samples"] += 1
            if item.content is not None and item.revision_id is not None:
                session.add(
                    FeedbackSampleRevisionRow(
                        revision_id=item.revision_id,
                        sample_id=item.sample_id,
                        revision_no=1,
                        author_kind="worker",
                        content=dict(item.content),
                        content_digest=_digest(item.content),
                        input_digest=_input_digest(item.content),
                        construction_spec_version=1,
                        provenance=dict(item.provenance),
                        created_by=None,
                        job_id=None,
                        created_at=_datetime(item.created_at),
                    )
                )
                await session.flush()
                row.current_revision_id = item.revision_id
                row.status = "needs_confirmation"
                row.missing_reasons = []
                await session.flush()
                counts["created_revisions"] += 1
            continue

        counts["existing_samples"] += 1
        if (
            row.current_revision_id is None
            and row.status == "needs_input"
            and item.content is not None
            and item.revision_id is not None
        ):
            revision = await session.get(
                FeedbackSampleRevisionRow,
                item.revision_id,
                with_for_update=True,
            )
            if revision is None:
                session.add(
                    FeedbackSampleRevisionRow(
                        revision_id=item.revision_id,
                        sample_id=row.sample_id,
                        revision_no=1,
                        author_kind="worker",
                        content=dict(item.content),
                        content_digest=_digest(item.content),
                        input_digest=_input_digest(item.content),
                        construction_spec_version=1,
                        provenance=dict(item.provenance),
                        created_by=None,
                        job_id=None,
                        created_at=_datetime(item.created_at),
                    )
                )
                await session.flush()
                counts["created_revisions"] += 1
            row.current_revision_id = item.revision_id
            row.status = "needs_confirmation"
            row.missing_reasons = []
            row.updated_at = _datetime(item.created_at)
            await session.flush()
    return counts


async def run_migration(*, apply: bool) -> dict[str, Any]:
    from config import ENV_FILE_PATH
    from infra.persistence.database import (
        DatabaseSettings,
        build_database_engine,
        build_session_factory,
    )
    from infra.persistence.postgres.models.feedback_dataset import FeedbackDatasetMigrationRunRow

    del ENV_FILE_PATH  # Settings resolves the configured env file itself.
    engine = build_database_engine(DatabaseSettings())
    session_factory = build_session_factory(engine)
    mode = "apply" if apply else "dry_run"
    plan: DatasetMigrationPlan | None = None
    try:
        async with session_factory.begin() as session:
            plan = await build_migration_plan(session)
            summary = plan.summary()
            if apply:
                summary.update(await apply_plan(session, plan))
            session.add(
                FeedbackDatasetMigrationRunRow(
                    run_id=plan.run_id,
                    migration_version=MIGRATION_VERSION,
                    mode=mode,
                    status="applied" if apply else "planned",
                    summary=summary,
                    items=[*map(DatasetMigrationItem.to_record, plan.items), *plan.skipped],
                    created_at=_datetime(datetime.now(timezone.utc).isoformat()),
                )
            )
            await session.flush()
            summary["mode"] = mode
            return summary
    except Exception as exc:
        if plan is not None:
            # A failed run is useful evidence, but it must not share the
            # transaction that rolled back any partial data writes.
            try:
                async with session_factory.begin() as session:
                    session.add(
                        FeedbackDatasetMigrationRunRow(
                            run_id=plan.run_id,
                            migration_version=MIGRATION_VERSION,
                            mode=mode,
                            status="failed",
                            summary={
                                **plan.summary(),
                                "mode": mode,
                                "error_code": _error_code(exc),
                            },
                            items=[*map(DatasetMigrationItem.to_record, plan.items), *plan.skipped],
                            created_at=_datetime(datetime.now(timezone.utc).isoformat()),
                        )
                    )
            except Exception:
                # The original error is more actionable if the audit table is
                # unavailable during an upgrade.
                pass
        raise
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy feedback datasets")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write maintained datasets and samples; without it only a dry-run plan is built",
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(run_migration(apply=args.apply))
    except KeyboardInterrupt:
        return
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


def _dataset_spec(
    *,
    dataset_id: str,
    owner_id: str,
    collection_id: str,
    task_type: str,
    created_at: str,
    legacy_id: str,
    source: str,
) -> DatasetMigrationSpec:
    label = {"sft": "SFT", "preference": "Preference", "evaluation": "Evaluation"}[task_type]
    name = f"Migrated {label} {legacy_id[-24:]}"[:120]
    return DatasetMigrationSpec(
        dataset_id=dataset_id,
        collection_id=collection_id,
        owner_id=owner_id,
        name=name,
        task_type=task_type,
        construction_spec={
            "schema_version": MIGRATION_VERSION,
            "source": source,
            "legacy_identity": legacy_id,
            "language": "unknown",
        },
        created_at=created_at,
    )


def _make_item(
    *,
    dataset_id: str,
    source_case_id: str,
    task_type: str,
    case: Mapping[str, Any],
    content: dict[str, Any] | None,
    missing_reasons: Iterable[str],
    provenance: Mapping[str, Any],
    created_at: str,
) -> DatasetMigrationItem:
    source_digest = _digest(dict(case))
    import_key = f"{MIGRATION_VERSION}:{dataset_id}:{source_case_id}:{task_type}"
    sample_id = stable_id("sample_mig", import_key)
    revision_id = stable_id("revision_mig", import_key) if content is not None else None
    reasons = tuple(dict.fromkeys(str(item).strip() for item in missing_reasons if str(item).strip()))
    return DatasetMigrationItem(
        import_key=import_key,
        dataset_id=dataset_id,
        sample_id=sample_id,
        source_case_id=source_case_id,
        task_type=task_type,
        source_digest=source_digest,
        status="needs_confirmation" if content is not None and not reasons else "needs_input",
        missing_reasons=reasons,
        revision_id=revision_id,
        content=content,
        provenance=dict(provenance),
        created_at=created_at,
    )


def _row_from_case(
    case: Mapping[str, Any], annotation: Mapping[str, Any], task_type: str
) -> dict[str, Any]:
    snapshot = case.get("context_snapshot") or {}
    if not isinstance(snapshot, Mapping):
        snapshot = {}
    evidence = snapshot.get("inspected_sources") or (
        (snapshot.get("evidence_coverage") or {}).get("inspected_sources")
        if isinstance(snapshot.get("evidence_coverage"), Mapping)
        else ()
    )
    question = _text(snapshot.get("question"))
    answer = _text(snapshot.get("answer"))
    target = _text(annotation.get("target"))
    base: dict[str, Any] = {"evidence": evidence}
    if task_type == "sft":
        return {**base, "messages": [{"role": "user", "content": question}], "target": target}
    if task_type == "preference":
        return {
            **base,
            "prompt": [{"role": "user", "content": question}],
            "chosen": target,
            "rejected": answer,
            "comparison_reason": _text(annotation.get("reason")),
        }
    return {
        **base,
        "input": question,
        "reference": target,
        "criteria": [_text(annotation.get("reason")), *_texts(snapshot.get("gaps"))],
    }


def _legacy_evidence(value: Any) -> tuple[list[dict[str, str]] | None, tuple[str, ...]]:
    if not isinstance(value, (list, tuple)) or not value:
        return None, ("legacy_evidence_missing",)
    records: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None, ("legacy_evidence_invalid",)
        title = _text(item.get("document_title") or item.get("title"))
        text = _text(item.get("text") or item.get("quote") or item.get("content"))
        if not title or not text:
            return None, ("legacy_evidence_text_missing",)
        records.append({"document_title": title, "text": text})
    return records, ()


def _legacy_messages(
    task_type: str, row: Mapping[str, Any]
) -> tuple[list[dict[str, str]] | None, tuple[str, ...]]:
    value = row.get("messages") if task_type == "sft" else row.get("messages") or row.get("prompt")
    if task_type == "evaluation" and not value:
        value = [{"role": "user", "content": row.get("input")}]
    if not isinstance(value, (list, tuple)) or not value:
        return None, ("legacy_input_missing",)
    messages: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None, ("legacy_input_invalid",)
        role = _text(item.get("role"))
        content = _text(item.get("content"))
        if role not in {"system", "user", "assistant"} or not content:
            return None, ("legacy_input_invalid",)
        messages.append({"role": role, "content": content})
    if not any(item["role"] == "user" for item in messages):
        return None, ("legacy_user_message_missing",)
    return messages, ()


def _latest_annotations(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        case_id = _text(record.get("case_id"))
        if not case_id:
            continue
        previous = result.get(case_id)
        if previous is None or int(record.get("version") or 0) >= int(previous.get("version") or 0):
            result[case_id] = dict(record)
    return result


def _accepted_reviews(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if _text(record.get("decision")) != "accept":
            continue
        case_id = _text(record.get("case_id"))
        if not case_id:
            continue
        previous = result.get(case_id)
        if previous is None or int(record.get("seq") or 0) >= int(previous.get("seq") or 0):
            result[case_id] = dict(record)
    return result


def _accepted_review(
    case_id: str,
    annotation: Mapping[str, Any],
    reviews: Mapping[str, Mapping[str, Any]],
) -> bool:
    review = reviews.get(case_id)
    return bool(review and _text(review.get("annotation_digest")) == _text(annotation.get("annotation_digest")))


def _snapshot_record(row: Any) -> dict[str, Any]:
    return {
        "dataset_id": row.dataset_id,
        "owner_id": row.owner_id,
        "collection_id": row.collection_id,
        "dataset_type": row.dataset_type,
        "rows": row.rows or [],
        "provenance": row.provenance or {},
        "created_at": _iso(row.created_at),
    }


def _case_record(row: Any) -> dict[str, Any]:
    return {
        "case_id": row.case_id,
        "collection_id": row.collection_id,
        "session_id": row.session_id,
        "anchor_message_id": row.anchor_message_id,
        "context_snapshot": row.context_snapshot or {},
        "status": row.status,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _annotation_record(row: Any) -> dict[str, Any]:
    return {
        "annotation_id": row.annotation_id,
        "case_id": row.case_id,
        "version": row.version,
        "target": row.target,
        "dataset_uses": row.dataset_uses or [],
        "reason": row.reason,
        "annotation_digest": row.annotation_digest,
        "created_by": row.created_by,
    }


def _review_record(row: Any) -> dict[str, Any]:
    return {
        "decision_id": row.decision_id,
        "case_id": row.case_id,
        "annotation_digest": row.annotation_digest,
        "decision": row.decision,
        "seq": row.seq,
    }


def _assert_dataset_identity(row: Any, spec: DatasetMigrationSpec) -> None:
    expected = {
        "collection_id": spec.collection_id,
        "task_type": spec.task_type,
        "created_by": spec.owner_id,
    }
    for field, value in expected.items():
        if getattr(row, field) != value:
            raise RuntimeError(f"migration_dataset_identity_conflict:{spec.dataset_id}:{field}")


def _input_digest(content: Mapping[str, Any]) -> str:
    return _digest(
        {
            "messages": content.get("messages") or content.get("prompt") or (),
            "context": content.get("context") or (),
        }
    )


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _legacy_digest(value: Any) -> str:
    """Reproduce the P5 snapshot digest for migration lookup only."""

    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _texts(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _datetime(value: str) -> datetime:
    text = _text(value)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00")) if text else datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = _datetime(str(value))
    return parsed.isoformat()


def _error_code(exc: Exception) -> str:
    return f"{type(exc).__name__}:{str(exc)[:240]}"


__all__ = [
    "DatasetMigrationItem",
    "DatasetMigrationPlan",
    "DatasetMigrationSpec",
    "MIGRATION_VERSION",
    "apply_plan",
    "build_migration_plan",
    "build_plan_from_records",
    "legacy_row_to_content",
    "run_migration",
    "stable_id",
]


if __name__ == "__main__":
    main()
