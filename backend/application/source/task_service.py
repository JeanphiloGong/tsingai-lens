from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from domain.ports import TaskRepository
from domain.source import TaskRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskService:
    """Durable execution state without owning scientific artifact versions."""

    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository

    async def create_task(
        self,
        collection_id: str,
        task_type: str = "document_preparation",
        *,
        mode: str = "standard",
        document_id: str | None = None,
        input_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        record = self._new_task(
            collection_id=collection_id,
            document_id=document_id,
            task_type=task_type,
            mode=mode,
            input_fingerprint=input_fingerprint,
        )
        return (await self.repository.add_task(record)).to_record()

    async def get_or_create_document_task(
        self,
        *,
        collection_id: str,
        document_id: str,
        task_type: str,
        input_fingerprint: str,
        mode: str = "standard",
    ) -> tuple[dict[str, Any], bool]:
        if not str(document_id).strip() or not str(input_fingerprint).strip():
            raise ValueError("document task requires document and input fingerprint")
        record, created = await self.repository.get_or_create_document_task(
            self._new_task(
                collection_id=collection_id,
                document_id=document_id,
                task_type=task_type,
                mode=mode,
                input_fingerprint=input_fingerprint,
            )
        )
        return await self._project_task(record), created

    async def get_or_create_collection_task(
        self,
        *,
        collection_id: str,
        task_type: str,
        input_fingerprint: str,
        mode: str = "standard",
        details: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if not str(input_fingerprint).strip():
            raise ValueError("collection task requires an input fingerprint")
        record, created = await self.repository.get_or_create_collection_task(
            self._new_task(
                collection_id=collection_id,
                document_id=None,
                task_type=task_type,
                mode=mode,
                input_fingerprint=input_fingerprint,
                details=details,
            )
        )
        return await self._project_task(record), created

    async def get_task(self, task_id: str) -> dict[str, Any]:
        record = await self.repository.read_task(task_id)
        if record is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        return await self._project_task(record)

    async def list_tasks(
        self,
        collection_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return [
            await self._project_task(record)
            for record in await self.repository.list_tasks(
                collection_id=collection_id,
                status=status,
                limit=limit,
                offset=offset,
            )
        ]

    async def update_task(self, task_id: str, **fields: Any) -> dict[str, Any]:
        stored = await self.repository.read_task(task_id)
        if stored is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        now = _now_iso()
        payload = {**stored.to_record(), **fields, "updated_at": now}
        if not stored.started_at and fields.get("status") == "running":
            payload["started_at"] = now
        record = TaskRecord.from_mapping(payload)
        if not await self.repository.update_task(record):
            raise FileNotFoundError(f"task not found: {task_id}")
        return await self._project_task(record)

    async def finish_task(
        self,
        task_id: str,
        *,
        status: str,
        **fields: Any,
    ) -> dict[str, Any]:
        stored = await self.repository.read_task(task_id)
        if stored is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        now = _now_iso()
        successful = status in {"completed", "partial_success"}
        record = TaskRecord.from_mapping(
            {
                **stored.to_record(),
                **fields,
                "status": status,
                "current_stage": fields.get(
                    "current_stage",
                    "artifacts_ready" if successful else "failed",
                ),
                "progress_percent": fields.get("progress_percent", 100),
                "updated_at": now,
                "finished_at": fields.get("finished_at", now),
            }
        )
        if not await self.repository.update_task(record):
            raise FileNotFoundError(f"task not found: {task_id}")
        return await self._project_task(record)

    async def append_error(self, task_id: str, error: str) -> dict[str, Any]:
        stored = await self.repository.read_task(task_id)
        if stored is None:
            raise FileNotFoundError(f"task not found: {task_id}")
        return await self.update_task(
            task_id,
            errors=[*stored.errors, str(error)],
        )

    def _new_task(
        self,
        *,
        collection_id: str,
        document_id: str | None,
        task_type: str,
        mode: str,
        input_fingerprint: str | None,
        details: Mapping[str, Any] | None = None,
    ) -> TaskRecord:
        now = _now_iso()
        return TaskRecord(
            task_id=f"task_{uuid4().hex[:12]}",
            collection_id=str(collection_id),
            document_id=str(document_id) if document_id is not None else None,
            task_type=str(task_type),
            mode=str(mode).strip() or "standard",
            input_fingerprint=(
                str(input_fingerprint).strip() if input_fingerprint else None
            ),
            status="queued",
            current_stage="queued",
            progress_percent=0,
            progress_detail=None,
            errors=(),
            warnings=(),
            created_at=now,
            updated_at=now,
            started_at=None,
            finished_at=None,
            details=dict(details or {}),
        )

    async def _project_task(
        self,
        record: TaskRecord,
        *,
        stages: tuple[TaskStageRecord, ...] | None = None,
    ) -> dict[str, Any]:
        payload = record.to_record()
        resolved_stages = (
            stages
            if stages is not None
            else await self.repository.list_stages(record.task_id)
        )
        if resolved_stages:
            payload["pipeline_nodes"] = {
                stage.node.name: stage.to_pipeline_state() for stage in resolved_stages
            }
        return payload


__all__ = ["TaskService"]
