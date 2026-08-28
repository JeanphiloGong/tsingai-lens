from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from domain.pipeline import PipelineNodeRun


_TASK_FIELDS = {
    "task_id",
    "collection_id",
    "document_id",
    "task_type",
    "mode",
    "input_fingerprint",
    "status",
    "current_stage",
    "progress_percent",
    "progress_detail",
    "output_path",
    "errors",
    "warnings",
    "created_at",
    "updated_at",
    "started_at",
    "finished_at",
}


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    collection_id: str
    task_type: str
    mode: str
    status: str
    current_stage: str
    progress_percent: int
    progress_detail: Mapping[str, Any] | None
    output_path: str | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    document_id: str | None = None
    input_fingerprint: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TaskRecord":
        source = dict(payload)
        progress_detail = source.get("progress_detail")
        return cls(
            task_id=str(source["task_id"]),
            collection_id=str(source["collection_id"]),
            document_id=_optional_text(source.get("document_id")),
            task_type=str(source.get("task_type") or "document_preparation"),
            mode=str(source.get("mode") or "standard"),
            input_fingerprint=_optional_text(source.get("input_fingerprint")),
            status=str(source.get("status") or "queued"),
            current_stage=str(source.get("current_stage") or "queued"),
            progress_percent=int(source.get("progress_percent") or 0),
            progress_detail=(
                dict(progress_detail) if isinstance(progress_detail, Mapping) else None
            ),
            output_path=_optional_text(source.get("output_path")),
            errors=tuple(str(item) for item in source.get("errors") or ()),
            warnings=tuple(str(item) for item in source.get("warnings") or ()),
            created_at=str(source["created_at"]),
            updated_at=str(source["updated_at"]),
            started_at=_optional_text(source.get("started_at")),
            finished_at=_optional_text(source.get("finished_at")),
            details={
                key: value for key, value in source.items() if key not in _TASK_FIELDS
            },
        )

    def to_record(self) -> dict[str, Any]:
        record = dict(self.details)
        record.update(
            {
                "task_id": self.task_id,
                "collection_id": self.collection_id,
                "document_id": self.document_id,
                "task_type": self.task_type,
                "mode": self.mode,
                "input_fingerprint": self.input_fingerprint,
                "status": self.status,
                "current_stage": self.current_stage,
                "progress_percent": self.progress_percent,
                "progress_detail": (
                    dict(self.progress_detail)
                    if self.progress_detail is not None
                    else None
                ),
                "output_path": self.output_path,
                "errors": list(self.errors),
                "warnings": list(self.warnings),
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }
        )
        return record


@dataclass(frozen=True)
class TaskStageRecord:
    stage_id: str
    task_id: str
    stage_order: int
    node: PipelineNodeRun

    def to_pipeline_state(self) -> dict[str, Any]:
        return self.node.to_record()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["TaskRecord", "TaskStageRecord"]
