from __future__ import annotations

from copy import deepcopy
from threading import RLock

from domain.source import TaskRecord, TaskStageRecord


class MemoryTaskRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._tasks: dict[str, TaskRecord] = {}
        self._stages: dict[str, TaskStageRecord] = {}

    async def add_task(self, record: TaskRecord) -> TaskRecord:
        with self._lock:
            if record.task_id in self._tasks:
                raise ValueError(f"duplicate task: {record.task_id}")
            self._tasks[record.task_id] = deepcopy(record)
            return deepcopy(record)

    async def get_or_create_collection_task(
        self,
        record: TaskRecord,
    ) -> tuple[TaskRecord, bool]:
        if record.document_id is not None:
            raise ValueError("collection task must not identify one document")
        with self._lock:
            active = sorted(
                (
                    task
                    for task in self._tasks.values()
                    if task.collection_id == record.collection_id
                    and task.document_id is None
                    and task.task_type == record.task_type
                    and task.status in {"queued", "running"}
                ),
                key=lambda task: (task.updated_at, task.task_id),
                reverse=True,
            )
            if active:
                return deepcopy(active[0]), False
            self._tasks[record.task_id] = deepcopy(record)
            return deepcopy(record), True

    async def get_or_create_document_task(
        self,
        record: TaskRecord,
    ) -> tuple[TaskRecord, bool]:
        if record.document_id is None or record.input_fingerprint is None:
            raise ValueError("document task requires document and input fingerprint")
        with self._lock:
            active = sorted(
                (
                    task
                    for task in self._tasks.values()
                    if task.collection_id == record.collection_id
                    and task.document_id == record.document_id
                    and task.task_type == record.task_type
                    and task.status in {"queued", "running"}
                ),
                key=lambda task: (task.updated_at, task.task_id),
                reverse=True,
            )
            if active:
                return deepcopy(active[0]), False
            candidates = sorted(
                (
                    task
                    for task in self._tasks.values()
                    if task.collection_id == record.collection_id
                    and task.document_id == record.document_id
                    and task.task_type == record.task_type
                    and task.input_fingerprint == record.input_fingerprint
                    and task.status in {"completed", "partial_success"}
                ),
                key=lambda task: (task.updated_at, task.task_id),
                reverse=True,
            )
            if candidates:
                return deepcopy(candidates[0]), False
            self._tasks[record.task_id] = deepcopy(record)
            return deepcopy(record), True

    async def read_task(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            record = self._tasks.get(task_id)
            return deepcopy(record) if record is not None else None

    async def list_tasks(
        self,
        *,
        collection_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[TaskRecord, ...]:
        with self._lock:
            records = [
                record
                for record in self._tasks.values()
                if (collection_id is None or record.collection_id == collection_id)
                and (status is None or record.status == status)
            ]
            records.sort(
                key=lambda record: (record.updated_at, record.task_id),
                reverse=True,
            )
            if offset:
                records = records[offset:]
            if limit is not None:
                records = records[:limit]
            return tuple(deepcopy(records))

    async def update_task(
        self,
        record: TaskRecord,
        *,
        stages: tuple[TaskStageRecord, ...] | None = None,
    ) -> bool:
        with self._lock:
            if record.task_id not in self._tasks:
                return False
            self._tasks[record.task_id] = deepcopy(record)
            if stages is not None:
                for stage in stages:
                    if stage.task_id != record.task_id:
                        raise ValueError(f"stage task mismatch: {stage.stage_id}")
                    self._stages[stage.stage_id] = deepcopy(stage)
            return True

    async def list_stages(self, task_id: str) -> tuple[TaskStageRecord, ...]:
        with self._lock:
            records = [
                stage for stage in self._stages.values() if stage.task_id == task_id
            ]
            records.sort(key=lambda stage: (stage.stage_order, stage.stage_id))
            return tuple(deepcopy(records))


__all__ = ["MemoryTaskRepository"]
