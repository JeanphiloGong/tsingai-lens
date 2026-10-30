"""PostgreSQL repository for pipeline run."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from infra.persistence.database import AsyncSessionLocal
from infra.persistence.postgres.models.collection import Collection
from infra.persistence.postgres.models.document import Document
from infra.persistence.postgres.models.pipeline_run import PipelineRunRow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class PipelineRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {
            type(self).COMPLETED,
            type(self).PARTIAL_SUCCESS,
            type(self).FAILED,
        }


class PipelineNodeStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def is_terminal(self) -> bool:
        return self in {
            type(self).SUCCEEDED,
            type(self).FAILED,
            type(self).SKIPPED,
        }


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(
        f"{value[:-1]}+00:00" if value.endswith("Z") else value
    )
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ExecutionTimestamps:
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        if (
            self.started_at is not None
            and self.finished_at is not None
            and _timestamp(self.finished_at) < _timestamp(self.started_at)
        ):
            raise ValueError("finished_at cannot be earlier than started_at")

    def duration_ms(self) -> int | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return round(
            (_timestamp(self.finished_at) - _timestamp(self.started_at)).total_seconds()
            * 1000
        )


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int

    @classmethod
    def sum(cls, values: Iterable["TokenUsage | None"]) -> "TokenUsage | None":
        available = tuple(value for value in values if value is not None)
        if not available:
            return None
        return cls(
            input_tokens=sum(value.input_tokens for value in available),
            output_tokens=sum(value.output_tokens for value in available),
            total_tokens=sum(value.total_tokens for value in available),
        )


@dataclass(frozen=True)
class ModelUsage:
    model_name: str
    request_count: int
    token_usage: TokenUsage | None = None
    unreported_request_count: int = 0

    def __post_init__(self) -> None:
        if self.request_count < 0:
            raise ValueError("request_count cannot be negative")
        if not 0 <= self.unreported_request_count <= self.request_count:
            raise ValueError(
                "unreported_request_count must be between zero and request_count"
            )

    @classmethod
    def aggregate(cls, values: Iterable["ModelUsage"]) -> "ModelUsage":
        usages = tuple(values)
        if not usages:
            raise ValueError("cannot aggregate empty model usage")
        model_name = usages[0].model_name
        if any(usage.model_name != model_name for usage in usages):
            raise ValueError("cannot aggregate usage from different models")
        return cls(
            model_name=model_name,
            request_count=sum(usage.request_count for usage in usages),
            token_usage=TokenUsage.sum(usage.token_usage for usage in usages),
            unreported_request_count=sum(
                usage.unreported_request_count for usage in usages
            ),
        )


@dataclass(frozen=True)
class ExecutionStats:
    duration_ms: int | None = None
    model_usage: tuple[ModelUsage, ...] = ()
    prompt_versions: Mapping[str, str] = field(default_factory=dict)

    @property
    def token_usage(self) -> TokenUsage | None:
        return TokenUsage.sum(usage.token_usage for usage in self.model_usage)

    @property
    def unreported_request_count(self) -> int:
        return sum(usage.unreported_request_count for usage in self.model_usage)

    @classmethod
    def aggregate(
        cls,
        values: Iterable["ExecutionStats"],
        *,
        duration_ms: int | None = None,
    ) -> "ExecutionStats":
        stats = tuple(values)
        usage_by_model: dict[str, list[ModelUsage]] = {}
        prompt_versions: dict[str, str] = {}
        for item in stats:
            for model in item.model_usage:
                usage_by_model.setdefault(model.model_name, []).append(model)
            for task_type, version in item.prompt_versions.items():
                previous = prompt_versions.get(task_type)
                if previous is not None and previous != version:
                    raise ValueError(
                        f"multiple prompt versions recorded for {task_type}: "
                        f"{previous}, {version}"
                    )
                prompt_versions[task_type] = version
        return cls(
            duration_ms=duration_ms,
            model_usage=tuple(
                ModelUsage.aggregate(models) for models in usage_by_model.values()
            ),
            prompt_versions=prompt_versions,
        )


@dataclass(frozen=True)
class PipelineNodeRun:
    name: str
    dependencies: tuple[str, ...] = ()
    status: PipelineNodeStatus = PipelineNodeStatus.QUEUED
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    stats: ExecutionStats = field(default_factory=ExecutionStats)
    timestamps: ExecutionTimestamps = field(default_factory=ExecutionTimestamps)
    output_summary: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineRun:
    pipeline_name: str
    mode: str
    run_id: str
    collection_id: str
    scope_type: str
    scope_id: str
    status: PipelineRunStatus
    nodes: tuple[PipelineNodeRun, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    stats: ExecutionStats
    timestamps: ExecutionTimestamps
    input_fingerprint: str | None = None
    current_node: str | None = None
    progress_percent: int = 0
    progress_detail: Mapping[str, Any] | None = None
    context: Mapping[str, Any] = field(default_factory=dict)
    resumed_from_run_id: str | None = None


@dataclass(frozen=True)
class PipelineRunSummary:
    run_id: str
    collection_id: str
    pipeline_name: str
    scope_type: str
    scope_id: str
    status: str
    current_node: str | None
    progress_percent: int
    progress_detail: dict[str, Any] | None
    errors: list[str]
    warnings: list[str]
    updated_at: str


_ACTIVE_STATUSES = ("queued", "running")

_SUCCESS_STATUSES = ("completed", "partial_success")


class PipelineRunRepository:
    async def add_run(self, run: PipelineRun) -> PipelineRun:
        async with AsyncSessionLocal() as db, db.begin():
            created_at = run.timestamps.created_at
            if created_at is None:
                raise ValueError("persisted pipeline run requires created_at")
            db.add(
                PipelineRunRow(
                    run_id=run.run_id,
                    collection_id=run.collection_id,
                    pipeline_name=run.pipeline_name,
                    scope_type=run.scope_type,
                    scope_id=run.scope_id,
                    mode=run.mode,
                    input_fingerprint=run.input_fingerprint,
                    status=run.status.value,
                    record_json={
                        **asdict(run),
                        "status": run.status.value,
                        "nodes": {
                            node.name: {
                                **asdict(node),
                                "dependencies": list(node.dependencies),
                                "status": node.status.value,
                                "errors": list(node.errors),
                                "warnings": list(node.warnings),
                                "stats": {
                                    "duration_ms": node.stats.duration_ms,
                                    "token_usage": (
                                        asdict(node.stats.token_usage)
                                        if node.stats.token_usage is not None
                                        else None
                                    ),
                                    "model_usage": [
                                        asdict(item) for item in node.stats.model_usage
                                    ],
                                    "unreported_request_count": node.stats.unreported_request_count,
                                    "prompt_versions": dict(node.stats.prompt_versions),
                                },
                                "timestamps": {
                                    key: value
                                    for key, value in asdict(node.timestamps).items()
                                    if value is not None
                                    or key in ("started_at", "finished_at")
                                },
                            }
                            for node in run.nodes
                        },
                        "errors": list(run.errors),
                        "warnings": list(run.warnings),
                        "stats": {
                            "duration_ms": run.stats.duration_ms,
                            "token_usage": (
                                asdict(run.stats.token_usage)
                                if run.stats.token_usage is not None
                                else None
                            ),
                            "model_usage": [
                                asdict(item) for item in run.stats.model_usage
                            ],
                            "unreported_request_count": run.stats.unreported_request_count,
                            "prompt_versions": dict(run.stats.prompt_versions),
                        },
                        "timestamps": {
                            key: value
                            for key, value in asdict(run.timestamps).items()
                            if value is not None or key in ("started_at", "finished_at")
                        },
                    },
                    created_at=_datetime(created_at),
                    updated_at=_datetime(run.timestamps.updated_at or created_at),
                )
            )
        return run

    async def get_or_create_collection_run(
        self,
        run: PipelineRun,
    ) -> tuple[PipelineRun, bool]:
        if run.scope_type != "collection" or run.scope_id != run.collection_id:
            raise ValueError("collection run must use its collection as scope")
        async with AsyncSessionLocal() as db, db.begin():
            collection = await db.scalar(
                select(Collection)
                .where(Collection.collection_id == run.collection_id)
                .with_for_update()
            )
            if collection is None:
                raise FileNotFoundError(f"collection not found: {run.collection_id}")
            active = await self._active_run(db, run)
            if active is not None:
                payload = active.record_json
                return (
                    PipelineRun(
                        pipeline_name=active.pipeline_name,
                        mode=active.mode,
                        run_id=active.run_id,
                        collection_id=active.collection_id,
                        scope_type=active.scope_type,
                        scope_id=active.scope_id,
                        status=PipelineRunStatus(active.status),
                        nodes=tuple(
                            PipelineNodeRun(
                                name=name,
                                dependencies=tuple(node.get("dependencies", ())),
                                status=PipelineNodeStatus(node["status"]),
                                errors=tuple(node.get("errors", ())),
                                warnings=tuple(node.get("warnings", ())),
                                stats=ExecutionStats(
                                    duration_ms=(node.get("stats") or {}).get(
                                        "duration_ms"
                                    ),
                                    model_usage=tuple(
                                        ModelUsage(
                                            model_name=item["model_name"],
                                            request_count=item["request_count"],
                                            token_usage=(
                                                TokenUsage(**item["token_usage"])
                                                if item.get("token_usage") is not None
                                                else None
                                            ),
                                            unreported_request_count=item.get(
                                                "unreported_request_count", 0
                                            ),
                                        )
                                        for item in (node.get("stats") or {}).get(
                                            "model_usage", ()
                                        )
                                    ),
                                    prompt_versions=(node.get("stats") or {}).get(
                                        "prompt_versions", {}
                                    ),
                                ),
                                timestamps=ExecutionTimestamps(
                                    **node.get("timestamps", {})
                                ),
                                output_summary=node.get("output_summary", {}),
                            )
                            for name, node in payload.get("nodes", {}).items()
                        ),
                        errors=tuple(payload.get("errors", ())),
                        warnings=tuple(payload.get("warnings", ())),
                        stats=ExecutionStats(
                            duration_ms=(payload.get("stats") or {}).get("duration_ms"),
                            model_usage=tuple(
                                ModelUsage(
                                    model_name=item["model_name"],
                                    request_count=item["request_count"],
                                    token_usage=(
                                        TokenUsage(**item["token_usage"])
                                        if item.get("token_usage") is not None
                                        else None
                                    ),
                                    unreported_request_count=item.get(
                                        "unreported_request_count", 0
                                    ),
                                )
                                for item in (payload.get("stats") or {}).get(
                                    "model_usage", ()
                                )
                            ),
                            prompt_versions=(payload.get("stats") or {}).get(
                                "prompt_versions", {}
                            ),
                        ),
                        timestamps=ExecutionTimestamps(
                            created_at=_iso(active.created_at),
                            updated_at=_iso(active.updated_at),
                            started_at=payload.get("timestamps", {}).get("started_at"),
                            finished_at=payload.get("timestamps", {}).get(
                                "finished_at"
                            ),
                        ),
                        input_fingerprint=active.input_fingerprint,
                        current_node=payload.get("current_node"),
                        progress_percent=payload.get("progress_percent", 0),
                        progress_detail=payload.get("progress_detail"),
                        context=payload.get("context", {}),
                        resumed_from_run_id=payload.get("resumed_from_run_id"),
                    ),
                    False,
                )
            created_at = run.timestamps.created_at
            if created_at is None:
                raise ValueError("persisted pipeline run requires created_at")
            db.add(
                PipelineRunRow(
                    run_id=run.run_id,
                    collection_id=run.collection_id,
                    pipeline_name=run.pipeline_name,
                    scope_type=run.scope_type,
                    scope_id=run.scope_id,
                    mode=run.mode,
                    input_fingerprint=run.input_fingerprint,
                    status=run.status.value,
                    record_json={
                        **asdict(run),
                        "status": run.status.value,
                        "nodes": {
                            node.name: {
                                **asdict(node),
                                "dependencies": list(node.dependencies),
                                "status": node.status.value,
                                "errors": list(node.errors),
                                "warnings": list(node.warnings),
                                "stats": {
                                    "duration_ms": node.stats.duration_ms,
                                    "token_usage": (
                                        asdict(node.stats.token_usage)
                                        if node.stats.token_usage is not None
                                        else None
                                    ),
                                    "model_usage": [
                                        asdict(item) for item in node.stats.model_usage
                                    ],
                                    "unreported_request_count": node.stats.unreported_request_count,
                                    "prompt_versions": dict(node.stats.prompt_versions),
                                },
                                "timestamps": {
                                    key: value
                                    for key, value in asdict(node.timestamps).items()
                                    if value is not None
                                    or key in ("started_at", "finished_at")
                                },
                            }
                            for node in run.nodes
                        },
                        "errors": list(run.errors),
                        "warnings": list(run.warnings),
                        "stats": {
                            "duration_ms": run.stats.duration_ms,
                            "token_usage": (
                                asdict(run.stats.token_usage)
                                if run.stats.token_usage is not None
                                else None
                            ),
                            "model_usage": [
                                asdict(item) for item in run.stats.model_usage
                            ],
                            "unreported_request_count": run.stats.unreported_request_count,
                            "prompt_versions": dict(run.stats.prompt_versions),
                        },
                        "timestamps": {
                            key: value
                            for key, value in asdict(run.timestamps).items()
                            if value is not None or key in ("started_at", "finished_at")
                        },
                    },
                    created_at=_datetime(created_at),
                    updated_at=_datetime(run.timestamps.updated_at or created_at),
                )
            )
            return run, True

    async def get_or_create_document_run(
        self,
        run: PipelineRun,
        *,
        reuse_completed: bool = True,
    ) -> tuple[PipelineRun, bool]:
        if run.scope_type != "document" or run.input_fingerprint is None:
            raise ValueError(
                "document run requires document scope and input fingerprint"
            )
        async with AsyncSessionLocal() as db, db.begin():
            document = await db.scalar(
                select(Document)
                .where(
                    Document.collection_id == run.collection_id,
                    Document.document_id == run.scope_id,
                )
                .with_for_update()
            )
            if document is None:
                raise FileNotFoundError(
                    f"document not found: {run.collection_id}/{run.scope_id}"
                )
            existing = await self._active_run(db, run)
            if existing is None and reuse_completed:
                existing = await db.scalar(
                    select(PipelineRunRow)
                    .where(
                        PipelineRunRow.pipeline_name == run.pipeline_name,
                        PipelineRunRow.scope_type == run.scope_type,
                        PipelineRunRow.scope_id == run.scope_id,
                        PipelineRunRow.input_fingerprint == run.input_fingerprint,
                        PipelineRunRow.status.in_(_SUCCESS_STATUSES),
                    )
                    .order_by(
                        PipelineRunRow.updated_at.desc(), PipelineRunRow.run_id.desc()
                    )
                    .limit(1)
                )
            if existing is not None:
                payload = existing.record_json
                return (
                    PipelineRun(
                        pipeline_name=existing.pipeline_name,
                        mode=existing.mode,
                        run_id=existing.run_id,
                        collection_id=existing.collection_id,
                        scope_type=existing.scope_type,
                        scope_id=existing.scope_id,
                        status=PipelineRunStatus(existing.status),
                        nodes=tuple(
                            PipelineNodeRun(
                                name=name,
                                dependencies=tuple(node.get("dependencies", ())),
                                status=PipelineNodeStatus(node["status"]),
                                errors=tuple(node.get("errors", ())),
                                warnings=tuple(node.get("warnings", ())),
                                stats=ExecutionStats(
                                    duration_ms=(node.get("stats") or {}).get(
                                        "duration_ms"
                                    ),
                                    model_usage=tuple(
                                        ModelUsage(
                                            model_name=item["model_name"],
                                            request_count=item["request_count"],
                                            token_usage=(
                                                TokenUsage(**item["token_usage"])
                                                if item.get("token_usage") is not None
                                                else None
                                            ),
                                            unreported_request_count=item.get(
                                                "unreported_request_count", 0
                                            ),
                                        )
                                        for item in (node.get("stats") or {}).get(
                                            "model_usage", ()
                                        )
                                    ),
                                    prompt_versions=(node.get("stats") or {}).get(
                                        "prompt_versions", {}
                                    ),
                                ),
                                timestamps=ExecutionTimestamps(
                                    **node.get("timestamps", {})
                                ),
                                output_summary=node.get("output_summary", {}),
                            )
                            for name, node in payload.get("nodes", {}).items()
                        ),
                        errors=tuple(payload.get("errors", ())),
                        warnings=tuple(payload.get("warnings", ())),
                        stats=ExecutionStats(
                            duration_ms=(payload.get("stats") or {}).get("duration_ms"),
                            model_usage=tuple(
                                ModelUsage(
                                    model_name=item["model_name"],
                                    request_count=item["request_count"],
                                    token_usage=(
                                        TokenUsage(**item["token_usage"])
                                        if item.get("token_usage") is not None
                                        else None
                                    ),
                                    unreported_request_count=item.get(
                                        "unreported_request_count", 0
                                    ),
                                )
                                for item in (payload.get("stats") or {}).get(
                                    "model_usage", ()
                                )
                            ),
                            prompt_versions=(payload.get("stats") or {}).get(
                                "prompt_versions", {}
                            ),
                        ),
                        timestamps=ExecutionTimestamps(
                            created_at=_iso(existing.created_at),
                            updated_at=_iso(existing.updated_at),
                            started_at=payload.get("timestamps", {}).get("started_at"),
                            finished_at=payload.get("timestamps", {}).get(
                                "finished_at"
                            ),
                        ),
                        input_fingerprint=existing.input_fingerprint,
                        current_node=payload.get("current_node"),
                        progress_percent=payload.get("progress_percent", 0),
                        progress_detail=payload.get("progress_detail"),
                        context=payload.get("context", {}),
                        resumed_from_run_id=payload.get("resumed_from_run_id"),
                    ),
                    False,
                )
            created_at = run.timestamps.created_at
            if created_at is None:
                raise ValueError("persisted pipeline run requires created_at")
            db.add(
                PipelineRunRow(
                    run_id=run.run_id,
                    collection_id=run.collection_id,
                    pipeline_name=run.pipeline_name,
                    scope_type=run.scope_type,
                    scope_id=run.scope_id,
                    mode=run.mode,
                    input_fingerprint=run.input_fingerprint,
                    status=run.status.value,
                    record_json={
                        **asdict(run),
                        "status": run.status.value,
                        "nodes": {
                            node.name: {
                                **asdict(node),
                                "dependencies": list(node.dependencies),
                                "status": node.status.value,
                                "errors": list(node.errors),
                                "warnings": list(node.warnings),
                                "stats": {
                                    "duration_ms": node.stats.duration_ms,
                                    "token_usage": (
                                        asdict(node.stats.token_usage)
                                        if node.stats.token_usage is not None
                                        else None
                                    ),
                                    "model_usage": [
                                        asdict(item) for item in node.stats.model_usage
                                    ],
                                    "unreported_request_count": node.stats.unreported_request_count,
                                    "prompt_versions": dict(node.stats.prompt_versions),
                                },
                                "timestamps": {
                                    key: value
                                    for key, value in asdict(node.timestamps).items()
                                    if value is not None
                                    or key in ("started_at", "finished_at")
                                },
                            }
                            for node in run.nodes
                        },
                        "errors": list(run.errors),
                        "warnings": list(run.warnings),
                        "stats": {
                            "duration_ms": run.stats.duration_ms,
                            "token_usage": (
                                asdict(run.stats.token_usage)
                                if run.stats.token_usage is not None
                                else None
                            ),
                            "model_usage": [
                                asdict(item) for item in run.stats.model_usage
                            ],
                            "unreported_request_count": run.stats.unreported_request_count,
                            "prompt_versions": dict(run.stats.prompt_versions),
                        },
                        "timestamps": {
                            key: value
                            for key, value in asdict(run.timestamps).items()
                            if value is not None or key in ("started_at", "finished_at")
                        },
                    },
                    created_at=_datetime(created_at),
                    updated_at=_datetime(run.timestamps.updated_at or created_at),
                )
            )
            return run, True

    async def read_run(self, run_id: str) -> PipelineRun | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(PipelineRunRow, run_id)
            if row is None:
                return None
            payload = row.record_json
            return PipelineRun(
                pipeline_name=row.pipeline_name,
                mode=row.mode,
                run_id=row.run_id,
                collection_id=row.collection_id,
                scope_type=row.scope_type,
                scope_id=row.scope_id,
                status=PipelineRunStatus(row.status),
                nodes=tuple(
                    PipelineNodeRun(
                        name=name,
                        dependencies=tuple(node.get("dependencies", ())),
                        status=PipelineNodeStatus(node["status"]),
                        errors=tuple(node.get("errors", ())),
                        warnings=tuple(node.get("warnings", ())),
                        stats=ExecutionStats(
                            duration_ms=(node.get("stats") or {}).get("duration_ms"),
                            model_usage=tuple(
                                ModelUsage(
                                    model_name=item["model_name"],
                                    request_count=item["request_count"],
                                    token_usage=(
                                        TokenUsage(**item["token_usage"])
                                        if item.get("token_usage") is not None
                                        else None
                                    ),
                                    unreported_request_count=item.get(
                                        "unreported_request_count", 0
                                    ),
                                )
                                for item in (node.get("stats") or {}).get(
                                    "model_usage", ()
                                )
                            ),
                            prompt_versions=(node.get("stats") or {}).get(
                                "prompt_versions", {}
                            ),
                        ),
                        timestamps=ExecutionTimestamps(**node.get("timestamps", {})),
                        output_summary=node.get("output_summary", {}),
                    )
                    for name, node in payload.get("nodes", {}).items()
                ),
                errors=tuple(payload.get("errors", ())),
                warnings=tuple(payload.get("warnings", ())),
                stats=ExecutionStats(
                    duration_ms=(payload.get("stats") or {}).get("duration_ms"),
                    model_usage=tuple(
                        ModelUsage(
                            model_name=item["model_name"],
                            request_count=item["request_count"],
                            token_usage=(
                                TokenUsage(**item["token_usage"])
                                if item.get("token_usage") is not None
                                else None
                            ),
                            unreported_request_count=item.get(
                                "unreported_request_count", 0
                            ),
                        )
                        for item in (payload.get("stats") or {}).get("model_usage", ())
                    ),
                    prompt_versions=(payload.get("stats") or {}).get(
                        "prompt_versions", {}
                    ),
                ),
                timestamps=ExecutionTimestamps(
                    created_at=_iso(row.created_at),
                    updated_at=_iso(row.updated_at),
                    started_at=payload.get("timestamps", {}).get("started_at"),
                    finished_at=payload.get("timestamps", {}).get("finished_at"),
                ),
                input_fingerprint=row.input_fingerprint,
                current_node=payload.get("current_node"),
                progress_percent=payload.get("progress_percent", 0),
                progress_detail=payload.get("progress_detail"),
                context=payload.get("context", {}),
                resumed_from_run_id=payload.get("resumed_from_run_id"),
            )

    async def list_runs(
        self,
        *,
        collection_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[PipelineRunSummary, ...]:
        statement = select(
            PipelineRunRow.run_id,
            PipelineRunRow.collection_id,
            PipelineRunRow.pipeline_name,
            PipelineRunRow.scope_type,
            PipelineRunRow.scope_id,
            PipelineRunRow.status,
            PipelineRunRow.updated_at,
            PipelineRunRow.record_json["current_node"]
            .as_string()
            .label("current_node"),
            PipelineRunRow.record_json["progress_percent"]
            .as_integer()
            .label("progress_percent"),
            PipelineRunRow.record_json["progress_detail"].label("progress_detail"),
            PipelineRunRow.record_json["errors"].label("errors"),
            PipelineRunRow.record_json["warnings"].label("warnings"),
        )
        if collection_id is not None:
            statement = statement.where(PipelineRunRow.collection_id == collection_id)
        if status is not None:
            statement = statement.where(PipelineRunRow.status == status)
        statement = statement.order_by(
            PipelineRunRow.updated_at.desc(),
            PipelineRunRow.run_id.desc(),
        )
        if offset:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        async with AsyncSessionLocal() as db:
            rows = await db.execute(statement)
            return tuple(
                PipelineRunSummary(
                    run_id=row.run_id,
                    collection_id=row.collection_id,
                    pipeline_name=row.pipeline_name,
                    scope_type=row.scope_type,
                    scope_id=row.scope_id,
                    status=row.status,
                    current_node=row.current_node,
                    progress_percent=row.progress_percent or 0,
                    progress_detail=row.progress_detail,
                    errors=row.errors or [],
                    warnings=row.warnings or [],
                    updated_at=_iso(row.updated_at),
                )
                for row in rows
            )

    async def update_run(self, run: PipelineRun) -> bool:
        async with AsyncSessionLocal() as db, db.begin():
            row = await db.get(PipelineRunRow, run.run_id)
            if row is None:
                return False
            row.collection_id = run.collection_id
            row.pipeline_name = run.pipeline_name
            row.scope_type = run.scope_type
            row.scope_id = run.scope_id
            row.mode = run.mode
            row.input_fingerprint = run.input_fingerprint
            row.status = run.status.value
            row.record_json = {
                **asdict(run),
                "status": run.status.value,
                "nodes": {
                    node.name: {
                        **asdict(node),
                        "dependencies": list(node.dependencies),
                        "status": node.status.value,
                        "errors": list(node.errors),
                        "warnings": list(node.warnings),
                        "stats": {
                            "duration_ms": node.stats.duration_ms,
                            "token_usage": (
                                asdict(node.stats.token_usage)
                                if node.stats.token_usage is not None
                                else None
                            ),
                            "model_usage": [
                                asdict(item) for item in node.stats.model_usage
                            ],
                            "unreported_request_count": node.stats.unreported_request_count,
                            "prompt_versions": dict(node.stats.prompt_versions),
                        },
                        "timestamps": {
                            key: value
                            for key, value in asdict(node.timestamps).items()
                            if value is not None or key in ("started_at", "finished_at")
                        },
                    }
                    for node in run.nodes
                },
                "errors": list(run.errors),
                "warnings": list(run.warnings),
                "stats": {
                    "duration_ms": run.stats.duration_ms,
                    "token_usage": (
                        asdict(run.stats.token_usage)
                        if run.stats.token_usage is not None
                        else None
                    ),
                    "model_usage": [asdict(item) for item in run.stats.model_usage],
                    "unreported_request_count": run.stats.unreported_request_count,
                    "prompt_versions": dict(run.stats.prompt_versions),
                },
                "timestamps": {
                    key: value
                    for key, value in asdict(run.timestamps).items()
                    if value is not None or key in ("started_at", "finished_at")
                },
            }
            row.updated_at = _datetime(
                run.timestamps.updated_at or datetime.now(timezone.utc)
            )
            return True

    @staticmethod
    async def _active_run(
        db: AsyncSession,
        run: PipelineRun,
    ) -> PipelineRunRow | None:
        return await db.scalar(
            select(PipelineRunRow)
            .where(
                PipelineRunRow.pipeline_name == run.pipeline_name,
                PipelineRunRow.scope_type == run.scope_type,
                PipelineRunRow.scope_id == run.scope_id,
                PipelineRunRow.status.in_(_ACTIVE_STATUSES),
            )
            .order_by(PipelineRunRow.updated_at.desc(), PipelineRunRow.run_id.desc())
            .limit(1)
        )


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text_value = str(value)
        parsed = datetime.fromisoformat(
            f"{text_value[:-1]}+00:00" if text_value.endswith("Z") else text_value
        )
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _datetime(value).isoformat()


__all__ = ["PipelineRunRepository"]


PipelineRunRepo = PipelineRunRepository()
