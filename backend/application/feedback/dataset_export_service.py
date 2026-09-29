"""Preview and publish model-facing files from confirmed task samples."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any
from uuid import uuid4

from application.feedback.dataset_service import FeedbackDatasetError, FeedbackDatasetService
from application.repositories.feedback_dataset_export_repository import (
    DatasetExportConflict,
    DatasetExportDraft,
    DatasetExportIdempotencyConflict,
    DatasetExportSummary,
    FeedbackDatasetExportRepository,
)
from application.repositories.feedback_dataset_sample_repository import (
    ConfirmedDatasetMember,
    FeedbackDatasetSampleRepository,
)
from domain.feedback.dataset_export import (
    EXPORT_SCHEMA_VERSION,
    DatasetExport,
    ExportFormat,
    ExportIssue,
    ExportMember,
    ExportPreview,
    content_digest_for_rows,
    digest_for_value,
    jsonl_bytes_for_rows,
    member_digest,
    provenance_digest_for_rows,
)
from domain.feedback.sample_revision import SftRevisionContent


class DatasetExportError(ValueError):
    """A user-correctable preview or publication request."""


@dataclass(frozen=True)
class DatasetExportListResult:
    items: tuple[DatasetExportSummary, ...]
    limit: int
    offset: int


class FeedbackDatasetExportService:
    def __init__(
        self,
        *,
        dataset_service: FeedbackDatasetService,
        sample_repository: FeedbackDatasetSampleRepository,
        repository: FeedbackDatasetExportRepository,
    ) -> None:
        self.dataset_service = dataset_service
        self.sample_repository = sample_repository
        self.repository = repository

    async def preview_for_user(
        self, *, user_id: str, dataset_id: str
    ) -> ExportPreview:
        dataset = await self._read_dataset(user_id, dataset_id)
        if dataset.task_type != "sft":
            raise DatasetExportError("dataset_task_type_not_available")
        members = await self.sample_repository.read_confirmed_members(dataset_id=dataset_id)
        export_members = tuple(_export_member(item) for item in members)
        issues = tuple(
            issue
            for member in export_members
            for issue in _validate_member(member)
        )
        created = datetime.now(timezone.utc)
        preview = ExportPreview.build(
            preview_id=f"preview_{uuid4().hex[:32]}",
            dataset_id=dataset_id,
            members=export_members,
            issues=issues,
            created_at=created.isoformat(),
            expires_at=(created + timedelta(minutes=15)).isoformat(),
        )
        return await self.repository.save_preview(preview)

    async def publish_for_user(
        self,
        *,
        user_id: str,
        dataset_id: str,
        preview_id: str,
        preview_digest: str,
        allow_partial: bool,
        idempotency_key: str,
    ) -> DatasetExport:
        dataset = await self._read_dataset(user_id, dataset_id)
        if dataset.task_type != "sft":
            raise DatasetExportError("dataset_task_type_not_available")
        if not idempotency_key.strip() or len(idempotency_key) > 128:
            raise DatasetExportError("export_idempotency_key_invalid")
        preview = await self.repository.read_preview(preview_id)
        if preview is None or preview.dataset_id != dataset_id:
            raise DatasetExportError("export_preview_not_found")
        if preview.preview_digest != preview_digest:
            raise DatasetExportError("export_preview_stale")
        if datetime.fromisoformat(preview.expires_at.replace("Z", "+00:00")) <= datetime.now(
            timezone.utc
        ):
            raise DatasetExportError("export_preview_expired")
        if preview.issues and not allow_partial:
            raise DatasetExportError("export_preview_has_issues")

        current = tuple(
            _export_member(item)
            for item in await self.sample_repository.read_confirmed_members(dataset_id=dataset_id)
        )
        if member_digest(current) != member_digest(preview.members):
            raise DatasetExportError("export_preview_stale")
        issues_by_sample = {issue.sample_id for issue in preview.issues}
        included = tuple(member for member in current if member.sample_id not in issues_by_sample)
        if not included:
            raise DatasetExportError("empty_export")

        rows: list[dict[str, Any]] = []
        provenance: list[dict[str, Any]] = []
        for member in included:
            row, trace = _serialize_sft(member)
            rows.append(row)
            provenance.append(trace)
        row_tuple = tuple(rows)
        provenance_tuple = tuple(provenance)
        export_id = f"export_{uuid4().hex[:32]}"
        created_at = datetime.now(timezone.utc).isoformat()
        manifest = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "dataset_id": dataset_id,
            "dataset_name": dataset.name,
            "export_id": export_id,
            "preview_id": preview_id,
            "preview_digest": preview_digest,
            "member_digest": member_digest(current),
            "row_count": len(row_tuple),
            "main_file": "data.jsonl",
            "provenance_file": "provenance.jsonl",
            "created_at": created_at,
        }
        draft = DatasetExportDraft(
            dataset_id=dataset_id,
            preview_id=preview_id,
            preview_digest=preview_digest,
            member_digest=member_digest(current),
            rows=row_tuple,
            provenance=provenance_tuple,
            members=included,
            content_digest=content_digest_for_rows(row_tuple),
            provenance_digest=provenance_digest_for_rows(provenance_tuple),
            manifest_digest=digest_for_value(manifest),
            manifest=manifest,
            created_by=user_id,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )
        try:
            return await self.repository.publish_if_current(draft=draft)
        except DatasetExportIdempotencyConflict as exc:
            raise DatasetExportError(str(exc)) from exc
        except DatasetExportConflict as exc:
            raise DatasetExportError(str(exc)) from exc

    async def list_for_user(
        self, *, user_id: str, dataset_id: str, limit: int = 50, offset: int = 0
    ) -> DatasetExportListResult:
        await self._read_dataset(user_id, dataset_id)
        if limit < 1 or limit > 200 or offset < 0:
            raise DatasetExportError("pagination_invalid")
        items = await self.repository.list_exports(
            dataset_id=dataset_id, limit=limit, offset=offset
        )
        return DatasetExportListResult(items=items, limit=limit, offset=offset)

    async def read_for_user(
        self, *, user_id: str, dataset_id: str, export_id: str
    ) -> DatasetExport:
        await self._read_dataset(user_id, dataset_id)
        export = await self.repository.read_export(export_id)
        if export is None or export.dataset_id != dataset_id:
            raise FileNotFoundError("dataset export not found")
        return export

    async def download_for_user(
        self,
        *,
        user_id: str,
        dataset_id: str,
        export_id: str,
        format: ExportFormat,
    ) -> tuple[DatasetExport, bytes, str, str]:
        export = await self.read_for_user(
            user_id=user_id, dataset_id=dataset_id, export_id=export_id
        )
        if format == "jsonl":
            return export, jsonl_bytes_for_rows(export.rows), "application/x-ndjson", "data.jsonl"
        if format == "json":
            payload = json.dumps(
                list(export.rows), ensure_ascii=False, sort_keys=True, indent=2
            ).encode("utf-8")
            return export, payload, "application/json", "data.json"
        if format == "provenance":
            return (
                export,
                jsonl_bytes_for_rows(export.provenance),
                "application/x-ndjson",
                "provenance.jsonl",
            )
        raise DatasetExportError("export_format_invalid")

    async def _read_dataset(self, user_id: str, dataset_id: str):
        return await self.dataset_service.read_for_user(
            user_id=user_id, dataset_id=dataset_id
        )


def _export_member(item: ConfirmedDatasetMember) -> ExportMember:
    return ExportMember(
        sample_id=item.sample.sample_id,
        source_case_id=item.sample.source_case_id,
        revision_id=item.revision.revision_id,
        revision_no=item.revision.revision_no,
        content=item.revision.content,
        content_digest=item.revision.content_digest,
        input_digest=item.revision.input_digest,
        provenance=item.revision.provenance,
    )


def _validate_member(member: ExportMember) -> tuple[ExportIssue, ...]:
    content = member.content
    if not isinstance(content, SftRevisionContent):
        return (
            ExportIssue(
                sample_id=member.sample_id,
                revision_id=member.revision_id,
                code="unsupported_schema",
                message="当前导出器不支持该样本结构。",
            ),
        )
    question = next(
        (item["content"] for item in content.messages if item["role"] == "user"), ""
    )
    issues: list[ExportIssue] = []
    if not member.provenance.get("evidence_records"):
        issues.append(
            ExportIssue(
                sample_id=member.sample_id,
                revision_id=member.revision_id,
                code="provenance_evidence_missing",
                message="样本没有可冻结的来源追溯记录。",
                question=question,
            )
        )
    if not member.provenance.get("session_id") or not member.provenance.get(
        "anchor_message_id"
    ):
        issues.append(
            ExportIssue(
                sample_id=member.sample_id,
                revision_id=member.revision_id,
                code="provenance_message_missing",
                message="样本缺少原始会话或回答消息追溯。",
                question=question,
            )
        )
    return tuple(issues)


def _serialize_sft(member: ExportMember) -> tuple[dict[str, Any], dict[str, Any]]:
    content = member.content
    if not isinstance(content, SftRevisionContent):
        raise DatasetExportError("unsupported_schema")
    row = {
        "messages": [
            *[dict(message) for message in content.messages],
            {"role": "assistant", "content": content.target},
        ],
        "context": [dict(item) for item in content.context],
    }
    trace = {
        "schema_version": "feedback-dataset-provenance.v1",
        "row_key": member.row_key,
        "sample_id": member.sample_id,
        "source_case_id": member.source_case_id,
        "revision_id": member.revision_id,
        "revision_no": member.revision_no,
        "input_digest": member.input_digest,
        "session_id": member.provenance.get("session_id"),
        "anchor_message_id": member.provenance.get("anchor_message_id"),
        "message_ids": member.provenance.get("related_message_ids", []),
        "source_refs": member.provenance.get("source_refs", []),
        "evidence_records": member.provenance.get("evidence_records", []),
    }
    return row, trace
__all__ = [
    "DatasetExportError",
    "DatasetExportListResult",
    "FeedbackDatasetExportService",
]
