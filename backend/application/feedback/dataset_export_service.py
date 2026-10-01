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
    DatasetSampleRevisionConflict,
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
from domain.feedback.dataset import DatasetTaskType
from domain.feedback.sample_revision import (
    EvaluationRevisionContent,
    PreferenceRevisionContent,
    SftRevisionContent,
)


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
        self, *, user_id: str, dataset_id: str, sample_ids: list[str] | None = None
    ) -> ExportPreview:
        dataset = await self._read_dataset(user_id, dataset_id)
        members = await self._read_confirmed_members(dataset_id)
        if sample_ids is not None:
            selected = set(sample_ids)
            available = {item.sample.sample_id for item in members}
            if not selected or len(selected) != len(sample_ids) or not selected <= available:
                raise DatasetExportError("export_sample_selection_invalid")
            members = tuple(item for item in members if item.sample.sample_id in selected)
        export_members = tuple(_export_member(item) for item in members)
        issues = tuple(
            issue
            for member in export_members
            for issue in _validate_member(member, dataset.task_type)
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
            for item in await self._read_confirmed_members(dataset_id)
        )
        selected = {member.sample_id for member in preview.members}
        current = tuple(member for member in current if member.sample_id in selected)
        if member_digest(current) != member_digest(preview.members):
            raise DatasetExportError("export_preview_stale")
        issues_by_sample = {issue.sample_id for issue in preview.issues}
        included = tuple(member for member in current if member.sample_id not in issues_by_sample)
        if not included:
            raise DatasetExportError("empty_export")

        rows: list[dict[str, Any]] = []
        provenance: list[dict[str, Any]] = []
        for member in included:
            row, trace = _serialize_member(member, dataset.task_type)
            rows.append(row)
            provenance.append(trace)
        row_tuple = tuple(rows)
        provenance_tuple = tuple(provenance)
        content_digest = content_digest_for_rows(row_tuple)
        provenance_digest = provenance_digest_for_rows(provenance_tuple)
        export_id = f"export_{uuid4().hex[:32]}"
        created_at = datetime.now(timezone.utc).isoformat()
        manifest = {
            "manifest_schema_version": "feedback-dataset-export-manifest.v1",
            "schema_version": _schema_for_task(dataset.task_type),
            "dataset_type": dataset.task_type,
            "dataset_id": dataset_id,
            "dataset_name": dataset.name,
            "collection_id": dataset.collection_id,
            "export_id": export_id,
            "preview_id": preview_id,
            "preview_digest": preview_digest,
            "member_digest": member_digest(current),
            "row_count": len(row_tuple),
            "main_file": "data.jsonl",
            "provenance_file": "provenance.jsonl",
            "content_digest": content_digest,
            "provenance_digest": provenance_digest,
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
            content_digest=content_digest,
            provenance_digest=provenance_digest,
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
        if format == "manifest":
            manifest = {**export.manifest, "manifest_digest": export.manifest_digest}
            payload = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
                "utf-8"
            )
            return export, payload, "application/json", "manifest.json"
        raise DatasetExportError("export_format_invalid")

    async def _read_dataset(self, user_id: str, dataset_id: str):
        return await self.dataset_service.read_for_user(
            user_id=user_id, dataset_id=dataset_id
        )

    async def _read_confirmed_members(
        self, dataset_id: str
    ) -> tuple[ConfirmedDatasetMember, ...]:
        try:
            return await self.sample_repository.read_confirmed_members(
                dataset_id=dataset_id
            )
        except DatasetSampleRevisionConflict as exc:
            raise DatasetExportError(str(exc)) from exc


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


def _validate_member(
    member: ExportMember, task_type: DatasetTaskType
) -> tuple[ExportIssue, ...]:
    content = member.content
    expected = _schema_for_task(task_type)
    if content.schema_version != expected:
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
    if isinstance(content, PreferenceRevisionContent) and content.human_preference not in {"a", "b"}:
        issues.append(
            ExportIssue(
                sample_id=member.sample_id,
                revision_id=member.revision_id,
                code="preference_not_pairwise",
                message="只有人工明确选择 A 或 B 的偏好样本才能导出 pairwise 数据。",
                question=question,
            )
        )
    return tuple(issues)


def _serialize_member(
    member: ExportMember, task_type: DatasetTaskType
) -> tuple[dict[str, Any], dict[str, Any]]:
    if task_type == "sft":
        return _serialize_sft(member)
    if task_type == "preference":
        return _serialize_preference(member)
    if task_type == "evaluation":
        return _serialize_evaluation(member)
    raise DatasetExportError("dataset_task_type_not_available")


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
        "evidence": [dict(item) for item in content.evidence],
    }
    trace = _trace(member, row)
    return row, trace


def _serialize_preference(member: ExportMember) -> tuple[dict[str, Any], dict[str, Any]]:
    content = member.content
    if not isinstance(content, PreferenceRevisionContent) or content.human_preference not in {"a", "b"}:
        raise DatasetExportError("preference_not_pairwise")
    chosen, rejected = (
        (content.response_a, content.response_b)
        if content.human_preference == "a"
        else (content.response_b, content.response_a)
    )
    row = {
        "messages": [dict(message) for message in content.messages],
        "context": [dict(item) for item in content.context],
        "chosen": chosen,
        "rejected": rejected,
        "evidence": [dict(item) for item in content.evidence],
    }
    trace = _trace(member, row)
    trace.update(
        {
            "task_type": "preference",
            "human_preference": content.human_preference,
            "suggested_preference": content.suggested_preference,
        }
    )
    return row, trace


def _serialize_evaluation(member: ExportMember) -> tuple[dict[str, Any], dict[str, Any]]:
    content = member.content
    if not isinstance(content, EvaluationRevisionContent):
        raise DatasetExportError("unsupported_schema")
    row = {
        "messages": [dict(message) for message in content.messages],
        "context": [dict(item) for item in content.context],
        "reference": content.reference,
        "criteria": list(content.criteria),
        "evaluation_mode": content.evaluation_mode,
        "evidence": [dict(item) for item in content.evidence],
    }
    trace = _trace(member, row)
    trace.update({"task_type": "evaluation", "evaluation_mode": content.evaluation_mode})
    return row, trace


def _trace(member: ExportMember, row: dict[str, Any]) -> dict[str, Any]:
    evidence_records = member.provenance.get("evidence_records", [])
    document_ids = sorted(
        {
            str(item.get("document_id"))
            for item in evidence_records
            if isinstance(item, dict) and item.get("document_id")
        }
    )
    return {
        "schema_version": "feedback-dataset-provenance.v1",
        "row_key": member.row_key,
        "row_digest": digest_for_value(row),
        "sample_id": member.sample_id,
        "source_case_id": member.source_case_id,
        "revision_id": member.revision_id,
        "revision_no": member.revision_no,
        "input_digest": member.input_digest,
        "session_id": member.provenance.get("session_id"),
        "anchor_message_id": member.provenance.get("anchor_message_id"),
        "message_ids": member.provenance.get("related_message_ids", []),
        "source_refs": member.provenance.get("source_refs", []),
        "document_ids": document_ids,
        "session_tree_id": member.provenance.get("session_tree_id"),
        "evidence_records": evidence_records,
    }


def _schema_for_task(task_type: DatasetTaskType) -> str:
    return {
        "sft": "literature-sft.v1",
        "preference": "literature-preference.v1",
        "evaluation": "literature-evaluation.v1",
    }[task_type]
__all__ = [
    "DatasetExportError",
    "DatasetExportListResult",
    "FeedbackDatasetExportService",
]
