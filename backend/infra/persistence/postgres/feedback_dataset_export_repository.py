"""PostgreSQL persistence for task-dataset export previews and releases."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.repositories.feedback_dataset_export_repository import (
    DatasetExportConflict,
    DatasetExportDraft,
    DatasetExportIdempotencyConflict,
    DatasetExportSummary,
)
from domain.feedback.dataset_export import (
    EXPORT_SCHEMA_VERSION,
    DatasetExport,
    ExportIssue,
    ExportMember,
    ExportPreview,
    member_digest,
    provenance_digest_for_rows,
)
from domain.feedback.sample_revision import parse_revision_content
from infra.persistence.postgres.models.feedback_dataset import (
    FeedbackDatasetExportMemberRow,
    FeedbackDatasetExportPreviewRow,
    FeedbackDatasetExportRow,
    FeedbackDatasetRow,
    FeedbackDatasetSampleRow,
    FeedbackSampleRevisionRow,
)


class PostgresFeedbackDatasetExportRepository:
    backend_name = "postgresql"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def save_preview(self, preview: ExportPreview) -> ExportPreview:
        async with self.session_factory.begin() as session:
            session.add(
                FeedbackDatasetExportPreviewRow(
                    preview_id=preview.preview_id,
                    dataset_id=preview.dataset_id,
                    members=[member.to_record() for member in preview.members],
                    issues=[issue.to_record() for issue in preview.issues],
                    preview_digest=preview.preview_digest,
                    requested_count=preview.requested_count,
                    exportable_count=preview.exportable_count,
                    created_at=_datetime(preview.created_at),
                    expires_at=_datetime(preview.expires_at),
                )
            )
            await session.flush()
        return preview

    async def read_preview(self, preview_id: str) -> ExportPreview | None:
        async with self.session_factory() as session:
            row = await session.get(FeedbackDatasetExportPreviewRow, preview_id)
            if row is None:
                return None
            return _preview(row)

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
        async with self.session_factory() as session:
            rows = await session.scalars(statement)
            return tuple(_summary(row) for row in rows)

    async def publish_if_current(self, *, draft: DatasetExportDraft) -> DatasetExport:
        async with self.session_factory.begin() as session:
            existing = await session.scalar(
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
                return await _read_export_locked(session, existing)

            preview = await session.scalar(
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

            current_members = await _read_current_members(session, draft.dataset_id)
            if member_digest(current_members) != draft.member_digest:
                raise DatasetExportConflict("export_preview_stale")
            preview_members = tuple(_member(record) for record in (preview.members or ()))
            if member_digest(preview_members) != draft.member_digest:
                raise DatasetExportConflict("export_preview_stale")

            await session.execute(
                select(FeedbackDatasetRow)
                .where(FeedbackDatasetRow.dataset_id == draft.dataset_id)
                .with_for_update()
            )
            max_no = await session.scalar(
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
            session.add(row)
            # The ORM models intentionally keep the export/member relationship
            # explicit rather than relying on implicit unit-of-work ordering.
            # Flush the parent first so PostgreSQL can satisfy the member FK.
            await session.flush()
            for member in draft.members:
                session.add(
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
            await session.flush()
            return await _read_export_locked(session, row)

    async def read_export(self, export_id: str) -> DatasetExport | None:
        async with self.session_factory() as session:
            row = await session.get(FeedbackDatasetExportRow, export_id)
            return await _read_export_locked(session, row) if row is not None else None


async def _read_current_members(
    session: AsyncSession, dataset_id: str
) -> tuple[ExportMember, ...]:
    statement = (
        select(FeedbackDatasetSampleRow, FeedbackSampleRevisionRow)
        .join(
            FeedbackSampleRevisionRow,
            FeedbackDatasetSampleRow.confirmed_revision_id
            == FeedbackSampleRevisionRow.revision_id,
        )
        .where(
            FeedbackDatasetSampleRow.dataset_id == dataset_id,
            FeedbackDatasetSampleRow.status == "confirmed",
            FeedbackDatasetSampleRow.current_revision_id
            == FeedbackDatasetSampleRow.confirmed_revision_id,
        )
        .with_for_update()
    )
    rows = (await session.execute(statement)).all()
    return tuple(
        ExportMember(
            sample_id=sample.sample_id,
            source_case_id=sample.source_case_id,
            revision_id=revision.revision_id,
            revision_no=revision.revision_no,
            content=parse_revision_content(revision.content),
            content_digest=revision.content_digest,
            input_digest=revision.input_digest,
            provenance=deepcopy(revision.provenance or {}),
        )
        for sample, revision in rows
    )


async def _read_export_locked(
    session: AsyncSession, row: FeedbackDatasetExportRow
) -> DatasetExport:
    member_rows = list(await session.scalars(
        select(FeedbackDatasetExportMemberRow)
        .where(FeedbackDatasetExportMemberRow.export_id == row.export_id)
        .order_by(FeedbackDatasetExportMemberRow.row_key)
    ))
    revisions = {}
    if member_rows:
        revision_ids = [member.revision_id for member in member_rows]
        revision_rows = await session.scalars(
            select(FeedbackSampleRevisionRow).where(
                FeedbackSampleRevisionRow.revision_id.in_(revision_ids)
            )
        )
        revisions = {revision.revision_id: revision for revision in revision_rows}
        sample_ids = [member.sample_id for member in member_rows]
        sample_rows = await session.scalars(
            select(FeedbackDatasetSampleRow).where(
                FeedbackDatasetSampleRow.sample_id.in_(sample_ids)
            )
        )
        samples = {sample.sample_id: sample for sample in sample_rows}
        members = tuple(
            ExportMember(
                sample_id=member.sample_id,
                source_case_id=samples[member.sample_id].source_case_id,
                revision_id=member.revision_id,
                revision_no=revisions[member.revision_id].revision_no,
                content=parse_revision_content(revisions[member.revision_id].content),
                content_digest=member.content_digest,
                input_digest=member.input_digest,
                provenance=deepcopy(revisions[member.revision_id].provenance or {}),
            )
            for member in member_rows
        )
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


def _preview(row: FeedbackDatasetExportPreviewRow) -> ExportPreview:
    return ExportPreview(
        preview_id=row.preview_id,
        dataset_id=row.dataset_id,
        members=tuple(_member(item) for item in (row.members or ())),
        issues=tuple(_issue(item) for item in (row.issues or ())),
        preview_digest=row.preview_digest,
        created_at=_iso(row.created_at),
        expires_at=_iso(row.expires_at),
    )


def _member(value: dict[str, Any]) -> ExportMember:
    return ExportMember(
        sample_id=str(value["sample_id"]),
        source_case_id=str(value["source_case_id"]),
        revision_id=str(value["revision_id"]),
        revision_no=int(value["revision_no"]),
        content=parse_revision_content(value["content"]),
        content_digest=str(value["content_digest"]),
        input_digest=str(value["input_digest"]),
        provenance=deepcopy(value.get("provenance") or {}),
    )


def _issue(value: dict[str, Any]) -> ExportIssue:
    return ExportIssue(
        sample_id=str(value["sample_id"]),
        revision_id=str(value.get("revision_id")) if value.get("revision_id") else None,
        code=str(value["code"]),
        message=str(value["message"]),
        question=str(value.get("question") or ""),
    )


def _summary(row: FeedbackDatasetExportRow) -> DatasetExportSummary:
    return DatasetExportSummary(
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


__all__ = ["PostgresFeedbackDatasetExportRepository"]
