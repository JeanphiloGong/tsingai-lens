from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


_TASK_FIELDS = {
    "task_id",
    "collection_id",
    "task_type",
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
    details: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TaskRecord":
        source = dict(payload)
        progress_detail = source.get("progress_detail")
        return cls(
            task_id=str(source["task_id"]),
            collection_id=str(source["collection_id"]),
            task_type=str(source.get("task_type") or "build"),
            status=str(source.get("status") or "queued"),
            current_stage=str(source.get("current_stage") or "queued"),
            progress_percent=int(source.get("progress_percent") or 0),
            progress_detail=(
                dict(progress_detail) if isinstance(progress_detail, Mapping) else None
            ),
            output_path=(
                str(source["output_path"])
                if source.get("output_path") is not None
                else None
            ),
            errors=tuple(str(item) for item in source.get("errors") or ()),
            warnings=tuple(str(item) for item in source.get("warnings") or ()),
            created_at=str(source["created_at"]),
            updated_at=str(source["updated_at"]),
            started_at=(
                str(source["started_at"])
                if source.get("started_at") is not None
                else None
            ),
            finished_at=(
                str(source["finished_at"])
                if source.get("finished_at") is not None
                else None
            ),
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
                "task_type": self.task_type,
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
class CollectionBuildRecord:
    build_id: str
    task_id: str
    collection_id: str
    build_number: int
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True)
class BuildStageRecord:
    stage_id: str
    build_id: str
    stage_kind: str
    stage_version: int
    stage_order: int
    status: str
    started_at: str | None
    finished_at: str | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    skip_reason: str | None

    def to_pipeline_state(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "skip_reason": self.skip_reason,
        }


@dataclass(frozen=True)
class ArtifactVersionRecord:
    artifact_version_id: str
    build_stage_id: str
    artifact_kind: str
    schema_version: int
    content_version: int
    status: str
    object_id: str | None
    details: Mapping[str, Any]
    created_at: str


__all__ = [
    "ArtifactVersionRecord",
    "BuildStageRecord",
    "CollectionBuildRecord",
    "TaskRecord",
]
