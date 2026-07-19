from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from threading import RLock

from domain.source import (
    ArtifactVersionRecord,
    BuildStageRecord,
    CollectionBuildRecord,
    TaskRecord,
)


class MemoryBuildRepository:
    """In-memory task/build aggregate for explicitly isolated tests."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._tasks: dict[str, TaskRecord] = {}
        self._builds: dict[str, CollectionBuildRecord] = {}
        self._task_build_ids: dict[str, str] = {}
        self._stages: dict[str, BuildStageRecord] = {}
        self._artifacts: dict[str, ArtifactVersionRecord] = {}
        self._active_build_ids: dict[str, str] = {}

    def add_task(
        self,
        record: TaskRecord,
        *,
        build_id: str,
    ) -> CollectionBuildRecord:
        with self._lock:
            if record.task_id in self._tasks or build_id in self._builds:
                raise ValueError(f"duplicate task/build: {record.task_id}/{build_id}")
            build_number = 1 + max(
                (
                    build.build_number
                    for build in self._builds.values()
                    if build.collection_id == record.collection_id
                ),
                default=0,
            )
            build = CollectionBuildRecord(
                build_id=build_id,
                task_id=record.task_id,
                collection_id=record.collection_id,
                build_number=build_number,
                status="queued",
                created_at=record.created_at,
                started_at=None,
                finished_at=None,
            )
            self._tasks[record.task_id] = deepcopy(record)
            self._builds[build_id] = build
            self._task_build_ids[record.task_id] = build_id
            return deepcopy(build)

    def read_task(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            record = self._tasks.get(task_id)
            return deepcopy(record) if record is not None else None

    def list_tasks(
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
            if offset > 0:
                records = records[offset:]
            if limit is not None:
                records = records[:limit]
            return tuple(deepcopy(records))

    def update_task(
        self,
        record: TaskRecord,
        *,
        stages: tuple[BuildStageRecord, ...] | None = None,
    ) -> bool:
        with self._lock:
            if record.task_id not in self._tasks:
                return False
            self._tasks[record.task_id] = deepcopy(record)
            build_id = self._task_build_ids[record.task_id]
            build = self._builds[build_id]
            if record.status == "running" and build.status == "queued":
                self._builds[build_id] = replace(
                    build,
                    status="building",
                    started_at=record.started_at or record.updated_at,
                )
            if stages is not None:
                for stage in stages:
                    if stage.build_id != build_id:
                        raise ValueError(f"stage build mismatch: {stage.stage_id}")
                    self._stages[stage.stage_id] = deepcopy(stage)
            return True

    def read_build(self, task_id: str) -> CollectionBuildRecord | None:
        with self._lock:
            build_id = self._task_build_ids.get(task_id)
            return deepcopy(self._builds[build_id]) if build_id is not None else None

    def list_stages(self, task_id: str) -> tuple[BuildStageRecord, ...]:
        with self._lock:
            build_id = self._task_build_ids.get(task_id)
            if build_id is None:
                return ()
            records = [
                stage for stage in self._stages.values() if stage.build_id == build_id
            ]
            records.sort(key=lambda stage: (stage.stage_order, stage.stage_id))
            return tuple(deepcopy(records))

    def add_artifact_versions(
        self,
        task_id: str,
        records: tuple[ArtifactVersionRecord, ...],
    ) -> None:
        with self._lock:
            build_id = self._task_build_ids.get(task_id)
            if build_id is None:
                raise FileNotFoundError(f"build not found for task: {task_id}")
            stage_ids = {
                stage.stage_id
                for stage in self._stages.values()
                if stage.build_id == build_id
            }
            for record in records:
                if record.build_stage_id not in stage_ids:
                    raise ValueError(
                        f"artifact stage does not belong to task: {task_id}"
                    )
                if record.artifact_version_id in self._artifacts:
                    raise ValueError(
                        f"duplicate artifact: {record.artifact_version_id}"
                    )
                self._artifacts[record.artifact_version_id] = deepcopy(record)

    def list_artifact_versions(
        self,
        task_id: str,
    ) -> tuple[ArtifactVersionRecord, ...]:
        with self._lock:
            stage_ids = {stage.stage_id for stage in self.list_stages(task_id)}
            records = [
                artifact
                for artifact in self._artifacts.values()
                if artifact.build_stage_id in stage_ids
            ]
            records.sort(
                key=lambda artifact: (
                    artifact.artifact_kind,
                    artifact.artifact_version_id,
                )
            )
            return tuple(deepcopy(records))

    def finish_build(
        self,
        record: TaskRecord,
        *,
        build_status: str,
        activate: bool,
    ) -> CollectionBuildRecord:
        with self._lock:
            if record.task_id not in self._tasks:
                raise FileNotFoundError(f"task not found: {record.task_id}")
            self._tasks[record.task_id] = deepcopy(record)
            build_id = self._task_build_ids[record.task_id]
            build = replace(
                self._builds[build_id],
                status=build_status,
                started_at=(self._builds[build_id].started_at or record.started_at),
                finished_at=record.finished_at,
            )
            self._builds[build_id] = build
            if activate:
                if build_status != "succeeded":
                    raise ValueError("only succeeded builds can become active")
                active_id = self._active_build_ids.get(build.collection_id)
                active = self._builds.get(active_id) if active_id is not None else None
                if active is None or active.build_number < build.build_number:
                    self._active_build_ids[build.collection_id] = build.build_id
            return deepcopy(build)

    def read_active_build(
        self,
        collection_id: str,
    ) -> CollectionBuildRecord | None:
        with self._lock:
            build_id = self._active_build_ids.get(collection_id)
            return deepcopy(self._builds[build_id]) if build_id is not None else None


__all__ = ["MemoryBuildRepository"]
