"""PostgreSQL repository for feedback dataset export."""

from __future__ import annotations


import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.persistence.database import AsyncSessionLocal

from domain.feedback.dataset_export import (
    EXPORT_SCHEMA_VERSION,
    DatasetExport,
    ExportIssue,
    ExportMember,
    ExportPreview,
    member_digest,
)
from domain.feedback.sample_revision import (
    SftRevisionContent, PreferenceRevisionContent, EvaluationRevisionContent,
    SFT_SCHEMA_VERSION, PREFERENCE_SCHEMA_VERSION, EVALUATION_SCHEMA_VERSION,
)
from infra.persistence.postgres.models.feedback import FeedbackCaseRow
from infra.persistence.postgres.models.feedback_dataset import (
    FeedbackDatasetExportMemberRow,
    FeedbackDatasetExportPreviewRow,
    FeedbackDatasetExportRow,
    FeedbackDatasetRow,
    FeedbackDatasetSampleRow,
    FeedbackSampleRevisionRow,
)
from repositories.feedback_dataset_sample_repository import source_digest_for_case


@dataclass(frozen=True)
class DatasetExportDraft:
    dataset_id: str
    preview_id: str
    preview_digest: str
    member_digest: str
    rows: tuple[dict, ...]
    provenance: tuple[dict, ...]
    members: tuple[ExportMember, ...]
    content_digest: str
    provenance_digest: str
    manifest_digest: str
    manifest: dict
    created_by: str
    idempotency_key: str
    created_at: str


@dataclass(frozen=True)
class DatasetExportSummary:
    export_id: str
    dataset_id: str
    export_no: int
    schema_version: str
    row_count: int
    content_digest: str
    provenance_digest: str
    manifest_digest: str
    created_at: str


class DatasetExportConflict(ValueError):
    """The preview or confirmed member set changed before publication."""


class DatasetExportIdempotencyConflict(ValueError):
    """An idempotency key was reused with a different publication request."""


class FeedbackDatasetExportRepository:
    backend_name = "postgresql"

    async def save_preview(self, preview: ExportPreview) -> ExportPreview:
        async with AsyncSessionLocal() as db, db.begin():
            member_values = []
            for member in preview.members:
                content_value = member.content
                if isinstance(content_value, SftRevisionContent):
                    content_payload = {
                        "schema_version": content_value.schema_version,
                        "messages": [dict(item) for item in content_value.messages],
                        "context": [dict(item) for item in content_value.context],
                        "evidence": [dict(item) for item in content_value.evidence],
                        "target": content_value.target,
                    }
                elif isinstance(content_value, PreferenceRevisionContent):
                    content_payload = {
                        "schema_version": content_value.schema_version,
                        "messages": [dict(item) for item in content_value.messages],
                        "context": [dict(item) for item in content_value.context],
                        "evidence": [dict(item) for item in content_value.evidence],
                        "response_a": content_value.response_a,
                        "response_b": content_value.response_b,
                        "suggested_preference": content_value.suggested_preference,
                        "rationale": content_value.rationale,
                        "human_preference": content_value.human_preference,
                    }
                else:
                    content_payload = {
                        "schema_version": content_value.schema_version,
                        "messages": [dict(item) for item in content_value.messages],
                        "context": [dict(item) for item in content_value.context],
                        "evidence": [dict(item) for item in content_value.evidence],
                        "reference": content_value.reference,
                        "criteria": list(content_value.criteria),
                        "evaluation_mode": content_value.evaluation_mode,
                    }
                member_values.append(
                    {
                        "sample_id": member.sample_id,
                        "source_case_id": member.source_case_id,
                        "revision_id": member.revision_id,
                        "revision_no": member.revision_no,
                        "content": content_payload,
                        "content_digest": member.content_digest,
                        "input_digest": member.input_digest,
                        "provenance": deepcopy(member.provenance),
                        "row_key": member.row_key,
                    }
                )
            db.add(
                FeedbackDatasetExportPreviewRow(
                    preview_id=preview.preview_id,
                    dataset_id=preview.dataset_id,
                    members=member_values,
                    issues=[
                        {
                            "sample_id": issue.sample_id,
                            "revision_id": issue.revision_id,
                            "code": issue.code,
                            "message": issue.message,
                            "question": issue.question,
                        }
                        for issue in preview.issues
                    ],
                    preview_digest=preview.preview_digest,
                    requested_count=preview.requested_count,
                    exportable_count=preview.exportable_count,
                    created_at=_datetime(preview.created_at),
                    expires_at=_datetime(preview.expires_at),
                )
            )
            await db.flush()
        return preview

    async def read_preview(self, preview_id: str) -> ExportPreview | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(FeedbackDatasetExportPreviewRow, preview_id)
            if row is None:
                return None
            member_values = []
            for item in row.members or ():
                content_value = item["content"]
                if content_value["schema_version"] == SFT_SCHEMA_VERSION:
                    content = SftRevisionContent(
                        schema_version=content_value["schema_version"],
                        messages=tuple(content_value["messages"]),
                        context=tuple(content_value["context"]),
                        evidence=tuple(content_value["evidence"]),
                        target=content_value["target"],
                    )
                elif content_value["schema_version"] == PREFERENCE_SCHEMA_VERSION:
                    content = PreferenceRevisionContent(
                        schema_version=content_value["schema_version"],
                        messages=tuple(content_value["messages"]),
                        context=tuple(content_value["context"]),
                        evidence=tuple(content_value["evidence"]),
                        response_a=content_value["response_a"],
                        response_b=content_value["response_b"],
                        suggested_preference=content_value["suggested_preference"],
                        rationale=content_value["rationale"],
                        human_preference=content_value["human_preference"],
                    )
                elif content_value["schema_version"] == EVALUATION_SCHEMA_VERSION:
                    content = EvaluationRevisionContent(
                        schema_version=content_value["schema_version"],
                        messages=tuple(content_value["messages"]),
                        context=tuple(content_value["context"]),
                        evidence=tuple(content_value["evidence"]),
                        reference=content_value["reference"],
                        criteria=tuple(content_value["criteria"]),
                        evaluation_mode=content_value["evaluation_mode"],
                    )
                else:
                    raise ValueError("unsupported sample revision schema")
                member_values.append(
                    ExportMember(
                        sample_id=item["sample_id"],
                        source_case_id=item["source_case_id"],
                        revision_id=item["revision_id"],
                        revision_no=item["revision_no"],
                        content=content,
                        content_digest=item["content_digest"],
                        input_digest=item["input_digest"],
                        provenance=deepcopy(item["provenance"]),
                    )
                )
            return ExportPreview(
                preview_id=row.preview_id,
                dataset_id=row.dataset_id,
                members=tuple(member_values),
                issues=tuple(
                    (
                        ExportIssue(
                            sample_id=item["sample_id"],
                            revision_id=item["revision_id"],
                            code=item["code"],
                            message=item["message"],
                            question=item["question"],
                        )
                        for item in row.issues or ()
                    )
                ),
                preview_digest=row.preview_digest,
                created_at=_iso(row.created_at),
                expires_at=_iso(row.expires_at),
            )

    async def list_exports(
        self, *, dataset_id: str, limit: int = 50, offset: int = 0
    ) -> tuple[DatasetExportSummary, ...]:
        statement = (
            select(FeedbackDatasetExportRow)
            .where(FeedbackDatasetExportRow.dataset_id == dataset_id)
            .order_by(
                FeedbackDatasetExportRow.created_at.desc(),
                FeedbackDatasetExportRow.export_no.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        async with AsyncSessionLocal() as db:
            rows = await db.scalars(statement)
            return tuple(
                DatasetExportSummary(
                    export_id=row.export_id,
                    dataset_id=row.dataset_id,
                    export_no=row.export_no,
                    schema_version=row.schema_version,
                    row_count=row.row_count,
                    content_digest=row.content_digest,
                    provenance_digest=row.provenance_digest,
                    manifest_digest=row.manifest_digest,
                    created_at=_iso(row.created_at),
                )
                for row in rows
            )

    async def publish_if_current(self, *, draft: DatasetExportDraft) -> DatasetExport:
        async with AsyncSessionLocal() as db, db.begin():
            existing = await db.scalar(
                select(FeedbackDatasetExportRow)
                .where(
                    FeedbackDatasetExportRow.dataset_id == draft.dataset_id,
                    FeedbackDatasetExportRow.idempotency_key == draft.idempotency_key,
                )
                .with_for_update()
            )
            if existing is not None:
                if not _same_publication(existing, draft):
                    raise DatasetExportIdempotencyConflict(
                        "export_idempotency_identity_conflict"
                    )
                return await _read_export_locked(db, existing)

            preview = await db.scalar(
                select(FeedbackDatasetExportPreviewRow)
                .where(
                    FeedbackDatasetExportPreviewRow.preview_id == draft.preview_id,
                    FeedbackDatasetExportPreviewRow.dataset_id == draft.dataset_id,
                )
                .with_for_update()
            )
            if preview is None or preview.preview_digest != draft.preview_digest:
                raise DatasetExportConflict("export_preview_stale")
            now = _datetime(draft.created_at)
            if preview.expires_at <= now:
                raise DatasetExportConflict("export_preview_expired")

            member_values = []
            for record in preview.members or ():
                content_value = record["content"]
                if content_value["schema_version"] == SFT_SCHEMA_VERSION:
                    content = SftRevisionContent(
                        schema_version=content_value["schema_version"],
                        messages=tuple(content_value["messages"]),
                        context=tuple(content_value["context"]),
                        evidence=tuple(content_value["evidence"]),
                        target=content_value["target"],
                    )
                elif content_value["schema_version"] == PREFERENCE_SCHEMA_VERSION:
                    content = PreferenceRevisionContent(
                        schema_version=content_value["schema_version"],
                        messages=tuple(content_value["messages"]),
                        context=tuple(content_value["context"]),
                        evidence=tuple(content_value["evidence"]),
                        response_a=content_value["response_a"],
                        response_b=content_value["response_b"],
                        suggested_preference=content_value["suggested_preference"],
                        rationale=content_value["rationale"],
                        human_preference=content_value["human_preference"],
                    )
                elif content_value["schema_version"] == EVALUATION_SCHEMA_VERSION:
                    content = EvaluationRevisionContent(
                        schema_version=content_value["schema_version"],
                        messages=tuple(content_value["messages"]),
                        context=tuple(content_value["context"]),
                        evidence=tuple(content_value["evidence"]),
                        reference=content_value["reference"],
                        criteria=tuple(content_value["criteria"]),
                        evaluation_mode=content_value["evaluation_mode"],
                    )
                else:
                    raise ValueError("unsupported sample revision schema")
                member_values.append(
                    ExportMember(
                        sample_id=record["sample_id"],
                        source_case_id=record["source_case_id"],
                        revision_id=record["revision_id"],
                        revision_no=record["revision_no"],
                        content=content,
                        content_digest=record["content_digest"],
                        input_digest=record["input_digest"],
                        provenance=deepcopy(record["provenance"]),
                    )
                )
            preview_members = tuple(member_values)
            selected = {member.sample_id for member in preview_members}
            current_members = await _read_current_members(db, draft.dataset_id, sample_ids=tuple(selected))
            if member_digest(current_members) != draft.member_digest:
                raise DatasetExportConflict("export_preview_stale")
            if member_digest(preview_members) != draft.member_digest:
                raise DatasetExportConflict("export_preview_stale")

            await db.execute(
                select(FeedbackDatasetRow)
                .where(FeedbackDatasetRow.dataset_id == draft.dataset_id)
                .with_for_update()
            )
            max_no = await db.scalar(
                select(func.max(FeedbackDatasetExportRow.export_no)).where(
                    FeedbackDatasetExportRow.dataset_id == draft.dataset_id
                )
            )
            export_no = int(max_no or 0) + 1
            export_id = draft.manifest.get("export_id") or draft.preview_id
            manifest = {
                **deepcopy(draft.manifest),
                "export_id": export_id,
                "export_no": export_no,
                "created_at": draft.created_at,
                "row_count": len(draft.rows),
            }
            manifest_digest = _digest(manifest)
            row = FeedbackDatasetExportRow(
                export_id=export_id,
                dataset_id=draft.dataset_id,
                export_no=export_no,
                schema_version=str(draft.manifest.get("schema_version") or EXPORT_SCHEMA_VERSION),
                rows=deepcopy(list(draft.rows)),
                provenance=deepcopy(list(draft.provenance)),
                manifest=manifest,
                preview_id=draft.preview_id,
                preview_digest=draft.preview_digest,
                member_digest=draft.member_digest,
                content_digest=draft.content_digest,
                provenance_digest=draft.provenance_digest,
                manifest_digest=manifest_digest,
                row_count=len(draft.rows),
                created_by=draft.created_by,
                idempotency_key=draft.idempotency_key,
                created_at=now,
            )
            db.add(row)
            # The ORM models intentionally keep the export/member relationship
            # explicit rather than relying on implicit unit-of-work ordering.
            # Flush the parent first so PostgreSQL can satisfy the member FK.
            await db.flush()
            for member in draft.members:
                db.add(
                    FeedbackDatasetExportMemberRow(
                        export_id=export_id,
                        row_key=member.row_key,
                        sample_id=member.sample_id,
                        revision_id=member.revision_id,
                        content_digest=member.content_digest,
                        input_digest=member.input_digest,
                        provenance_digest=_digest(member.provenance),
                    )
                )
            await db.flush()
            return await _read_export_locked(db, row)

    async def read_export(self, export_id: str) -> DatasetExport | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(FeedbackDatasetExportRow, export_id)
            return await _read_export_locked(db, row) if row is not None else None


async def _read_current_members(
    db: AsyncSession, dataset_id: str, *, sample_ids: tuple[str, ...]
) -> tuple[ExportMember, ...]:
    statement = (
        select(FeedbackDatasetSampleRow, FeedbackSampleRevisionRow, FeedbackCaseRow)
        .join(
            FeedbackSampleRevisionRow,
            FeedbackDatasetSampleRow.confirmed_revision_id
            == FeedbackSampleRevisionRow.revision_id,
        )
        .join(
            FeedbackCaseRow,
            FeedbackCaseRow.case_id == FeedbackDatasetSampleRow.source_case_id,
        )
        .where(
            FeedbackDatasetSampleRow.dataset_id == dataset_id,
            FeedbackDatasetSampleRow.sample_id.in_(sample_ids),
            FeedbackDatasetSampleRow.status == "confirmed",
            FeedbackDatasetSampleRow.current_revision_id
            == FeedbackDatasetSampleRow.confirmed_revision_id,
        )
        .order_by(FeedbackCaseRow.case_id, FeedbackDatasetSampleRow.sample_id)
    )
    # Case writers lock the source before its samples; publication uses the same order.
    await db.execute(statement.with_for_update(of=FeedbackCaseRow))
    statement = statement.with_for_update(of=(FeedbackDatasetSampleRow, FeedbackSampleRevisionRow))
    rows = (await db.execute(statement)).all()
    for sample, _revision_row, case in rows:
        if case.status == "withdrawn":
            raise DatasetExportConflict("sample_source_stale")
        if source_digest_for_case(case) != sample.source_digest:
            raise DatasetExportConflict("sample_source_stale")
    member_values = []
    for sample, revision, _case in rows:
        content_value = revision.content
        if content_value["schema_version"] == SFT_SCHEMA_VERSION:
            content = SftRevisionContent(
                schema_version=content_value["schema_version"],
                messages=tuple(content_value["messages"]),
                context=tuple(content_value["context"]),
                evidence=tuple(content_value["evidence"]),
                target=content_value["target"],
            )
        elif content_value["schema_version"] == PREFERENCE_SCHEMA_VERSION:
            content = PreferenceRevisionContent(
                schema_version=content_value["schema_version"],
                messages=tuple(content_value["messages"]),
                context=tuple(content_value["context"]),
                evidence=tuple(content_value["evidence"]),
                response_a=content_value["response_a"],
                response_b=content_value["response_b"],
                suggested_preference=content_value["suggested_preference"],
                rationale=content_value["rationale"],
                human_preference=content_value["human_preference"],
            )
        elif content_value["schema_version"] == EVALUATION_SCHEMA_VERSION:
            content = EvaluationRevisionContent(
                schema_version=content_value["schema_version"],
                messages=tuple(content_value["messages"]),
                context=tuple(content_value["context"]),
                evidence=tuple(content_value["evidence"]),
                reference=content_value["reference"],
                criteria=tuple(content_value["criteria"]),
                evaluation_mode=content_value["evaluation_mode"],
            )
        else:
            raise ValueError("unsupported sample revision schema")
        member_values.append(
            ExportMember(
                sample_id=sample.sample_id,
                source_case_id=sample.source_case_id,
                revision_id=revision.revision_id,
                revision_no=revision.revision_no,
                content=content,
                content_digest=revision.content_digest,
                input_digest=revision.input_digest,
                provenance=deepcopy(revision.provenance or {}),
            )
        )
    return tuple(member_values)


async def _read_export_locked(
    db: AsyncSession, row: FeedbackDatasetExportRow
) -> DatasetExport:
    member_rows = list(await db.scalars(
        select(FeedbackDatasetExportMemberRow)
        .where(FeedbackDatasetExportMemberRow.export_id == row.export_id)
        .order_by(FeedbackDatasetExportMemberRow.row_key)
    ))
    revisions = {}
    if member_rows:
        revision_ids = [member.revision_id for member in member_rows]
        revision_rows = await db.scalars(
            select(FeedbackSampleRevisionRow).where(
                FeedbackSampleRevisionRow.revision_id.in_(revision_ids)
            )
        )
        revisions = {revision.revision_id: revision for revision in revision_rows}
        sample_ids = [member.sample_id for member in member_rows]
        sample_rows = await db.scalars(
            select(FeedbackDatasetSampleRow).where(
                FeedbackDatasetSampleRow.sample_id.in_(sample_ids)
            )
        )
        samples = {sample.sample_id: sample for sample in sample_rows}
        member_values = []
        for member in member_rows:
            content_value = revisions[member.revision_id].content
            if content_value["schema_version"] == SFT_SCHEMA_VERSION:
                content = SftRevisionContent(
                    schema_version=content_value["schema_version"],
                    messages=tuple(content_value["messages"]),
                    context=tuple(content_value["context"]),
                    evidence=tuple(content_value["evidence"]),
                    target=content_value["target"],
                )
            elif content_value["schema_version"] == PREFERENCE_SCHEMA_VERSION:
                content = PreferenceRevisionContent(
                    schema_version=content_value["schema_version"],
                    messages=tuple(content_value["messages"]),
                    context=tuple(content_value["context"]),
                    evidence=tuple(content_value["evidence"]),
                    response_a=content_value["response_a"],
                    response_b=content_value["response_b"],
                    suggested_preference=content_value["suggested_preference"],
                    rationale=content_value["rationale"],
                    human_preference=content_value["human_preference"],
                )
            elif content_value["schema_version"] == EVALUATION_SCHEMA_VERSION:
                content = EvaluationRevisionContent(
                    schema_version=content_value["schema_version"],
                    messages=tuple(content_value["messages"]),
                    context=tuple(content_value["context"]),
                    evidence=tuple(content_value["evidence"]),
                    reference=content_value["reference"],
                    criteria=tuple(content_value["criteria"]),
                    evaluation_mode=content_value["evaluation_mode"],
                )
            else:
                raise ValueError("unsupported sample revision schema")
            member_values.append(
                ExportMember(
                    sample_id=member.sample_id,
                    source_case_id=samples[member.sample_id].source_case_id,
                    revision_id=member.revision_id,
                    revision_no=revisions[member.revision_id].revision_no,
                    content=content,
                    content_digest=member.content_digest,
                    input_digest=member.input_digest,
                    provenance=deepcopy(revisions[member.revision_id].provenance or {}),
                )
            )
        members = tuple(member_values)
    else:
        members = ()
    return DatasetExport(
        export_id=row.export_id,
        dataset_id=row.dataset_id,
        export_no=row.export_no,
        schema_version=row.schema_version,
        rows=tuple(deepcopy(row.rows or ())),
        provenance=tuple(deepcopy(row.provenance or ())),
        members=members,
        preview_id=row.preview_id,
        preview_digest=row.preview_digest,
        member_digest=row.member_digest,
        content_digest=row.content_digest,
        provenance_digest=row.provenance_digest,
        manifest_digest=row.manifest_digest,
        manifest=deepcopy(row.manifest or {}),
        created_by=row.created_by,
        idempotency_key=row.idempotency_key,
        created_at=_iso(row.created_at),
    )


def _same_publication(row: FeedbackDatasetExportRow, draft: DatasetExportDraft) -> bool:
    return (
        row.preview_id == draft.preview_id
        and row.preview_digest == draft.preview_digest
        and row.member_digest == draft.member_digest
        and row.content_digest == draft.content_digest
        and row.provenance_digest == draft.provenance_digest
    )


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


__all__ = ['DatasetExportConflict', 'DatasetExportDraft', 'DatasetExportIdempotencyConflict', 'DatasetExportSummary', 'FeedbackDatasetExportRepository']
