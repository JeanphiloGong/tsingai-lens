"""Execution state for application pipelines and their runtime nodes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


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


def _run_status(value: Any) -> PipelineRunStatus:
    if isinstance(value, PipelineRunStatus):
        return value
    try:
        return PipelineRunStatus(str(value or PipelineRunStatus.QUEUED.value))
    except ValueError as exc:
        raise ValueError(f"invalid pipeline run status: {value}") from exc


def _node_status(value: Any) -> PipelineNodeStatus:
    if isinstance(value, PipelineNodeStatus):
        return value
    try:
        return PipelineNodeStatus(str(value or PipelineNodeStatus.QUEUED.value))
    except ValueError as exc:
        raise ValueError(f"invalid pipeline node status: {value}") from exc


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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

    def __post_init__(self) -> None:
        if self.created_at is not None:
            _timestamp(self.created_at)
        if self.started_at is not None:
            _timestamp(self.started_at)
        if self.finished_at is not None:
            _timestamp(self.finished_at)
        if (
            self.started_at is not None
            and self.finished_at is not None
            and _timestamp(self.finished_at) < _timestamp(self.started_at)
        ):
            raise ValueError("finished_at cannot be earlier than started_at")

    @classmethod
    def from_mapping(cls, payload: Any) -> "ExecutionTimestamps":
        source = payload if isinstance(payload, Mapping) else {}
        return cls(
            created_at=_optional_text(source.get("created_at")),
            started_at=_optional_text(source.get("started_at")),
            finished_at=_optional_text(source.get("finished_at")),
        )

    def duration_ms(self) -> int | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return round(
            (_timestamp(self.finished_at) - _timestamp(self.started_at)).total_seconds()
            * 1000
        )

    def to_record(self) -> dict[str, str | None]:
        record: dict[str, str | None] = {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
        if self.created_at is not None:
            return {"created_at": self.created_at, **record}
        return record


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        if min(self.input_tokens, self.output_tokens, self.total_tokens) < 0:
            raise ValueError("token usage cannot be negative")

    @classmethod
    def from_mapping(cls, payload: Any) -> "TokenUsage | None":
        if not isinstance(payload, Mapping):
            return None
        return cls(
            input_tokens=int(payload.get("input_tokens") or 0),
            output_tokens=int(payload.get("output_tokens") or 0),
            total_tokens=int(payload.get("total_tokens") or 0),
        )

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

    def to_record(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class ModelUsage:
    model_name: str
    request_count: int
    token_usage: TokenUsage | None = None

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise ValueError("model_name cannot be empty")
        if self.request_count < 0:
            raise ValueError("request_count cannot be negative")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ModelUsage":
        return cls(
            model_name=str(payload.get("model_name") or "").strip(),
            request_count=int(payload.get("request_count") or 0),
            token_usage=TokenUsage.from_mapping(payload.get("token_usage")),
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
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "request_count": self.request_count,
            "token_usage": (
                self.token_usage.to_record() if self.token_usage is not None else None
            ),
        }


@dataclass(frozen=True)
class ExecutionStats:
    duration_ms: int | None = None
    model_usage: tuple[ModelUsage, ...] = ()

    def __post_init__(self) -> None:
        if self.duration_ms is not None and self.duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")
        object.__setattr__(self, "model_usage", tuple(self.model_usage))

    @property
    def token_usage(self) -> TokenUsage | None:
        return TokenUsage.sum(usage.token_usage for usage in self.model_usage)

    @classmethod
    def from_mapping(cls, payload: Any) -> "ExecutionStats":
        source = payload if isinstance(payload, Mapping) else {}
        duration_ms = source.get("duration_ms")
        return cls(
            duration_ms=int(duration_ms) if duration_ms is not None else None,
            model_usage=tuple(
                ModelUsage.from_mapping(item)
                for item in source.get("model_usage") or ()
                if isinstance(item, Mapping)
            ),
        )

    @classmethod
    def aggregate(
        cls,
        values: Iterable["ExecutionStats"],
        *,
        duration_ms: int | None = None,
    ) -> "ExecutionStats":
        stats = tuple(values)
        usage_by_model: dict[str, list[ModelUsage]] = {}
        for item in stats:
            for model in item.model_usage:
                usage_by_model.setdefault(model.model_name, []).append(model)
        return cls(
            duration_ms=duration_ms,
            model_usage=tuple(
                ModelUsage.aggregate(models) for models in usage_by_model.values()
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "duration_ms": self.duration_ms,
            "token_usage": (
                self.token_usage.to_record() if self.token_usage is not None else None
            ),
            "model_usage": [item.to_record() for item in self.model_usage],
        }


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

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("pipeline node name cannot be empty")
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(self, "status", _node_status(self.status))
        object.__setattr__(self, "errors", tuple(self.errors))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "output_summary", deepcopy(dict(self.output_summary)))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PipelineNodeRun":
        return cls(
            name=str(payload.get("name") or "").strip(),
            dependencies=tuple(
                str(item) for item in payload.get("dependencies") or ()
            ),
            status=_node_status(payload.get("status")),
            errors=tuple(str(item) for item in payload.get("errors") or ()),
            warnings=tuple(str(item) for item in payload.get("warnings") or ()),
            stats=ExecutionStats.from_mapping(payload.get("stats")),
            timestamps=ExecutionTimestamps.from_mapping(payload.get("timestamps")),
            output_summary=(
                dict(payload["output_summary"])
                if isinstance(payload.get("output_summary"), Mapping)
                else {}
            ),
        )

    def start(self, started_at: str) -> "PipelineNodeRun":
        return replace(
            self,
            status=PipelineNodeStatus.RUNNING,
            errors=(),
            timestamps=ExecutionTimestamps(started_at=started_at),
        )

    def succeed(
        self,
        finished_at: str,
        *,
        output_summary: Mapping[str, Any] | None = None,
        warnings: Iterable[str] = (),
        stats: ExecutionStats | None = None,
    ) -> "PipelineNodeRun":
        timestamps = replace(self.timestamps, finished_at=finished_at)
        execution_stats = stats or ExecutionStats()
        if execution_stats.duration_ms is None:
            execution_stats = replace(
                execution_stats,
                duration_ms=timestamps.duration_ms(),
            )
        return replace(
            self,
            status=PipelineNodeStatus.SUCCEEDED,
            warnings=tuple(str(item) for item in warnings),
            stats=execution_stats,
            timestamps=timestamps,
            output_summary=output_summary or {},
        )

    def fail(self, error: str, finished_at: str) -> "PipelineNodeRun":
        timestamps = replace(self.timestamps, finished_at=finished_at)
        return replace(
            self,
            status=PipelineNodeStatus.FAILED,
            errors=(str(error),),
            stats=replace(self.stats, duration_ms=timestamps.duration_ms()),
            timestamps=timestamps,
        )

    def skip(
        self,
        *,
        finished_at: str,
    ) -> "PipelineNodeRun":
        return replace(
            self,
            status=PipelineNodeStatus.SKIPPED,
            timestamps=ExecutionTimestamps(finished_at=finished_at),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dependencies": list(self.dependencies),
            "status": _node_status(self.status).value,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "stats": self.stats.to_record(),
            "timestamps": self.timestamps.to_record(),
            "output_summary": deepcopy(dict(self.output_summary)),
        }


@dataclass(frozen=True)
class PipelineRun:
    pipeline_name: str
    mode: str
    run_id: str
    scope_type: str
    scope_id: str
    status: PipelineRunStatus
    nodes: tuple[PipelineNodeRun, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    stats: ExecutionStats
    timestamps: ExecutionTimestamps
    output_build_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "pipeline_name",
            "mode",
            "run_id",
            "scope_type",
            "scope_id",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} cannot be empty")
        object.__setattr__(self, "status", _run_status(self.status))
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "errors", tuple(self.errors))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        names = tuple(node.name for node in self.nodes)
        if len(set(names)) != len(names):
            raise ValueError("pipeline node names must be unique")
        unknown_dependencies = {
            dependency
            for node in self.nodes
            for dependency in node.dependencies
            if dependency not in names
        }
        if unknown_dependencies:
            raise ValueError(
                "pipeline node dependencies are not part of the run: "
                + ", ".join(sorted(unknown_dependencies))
            )
        for node in self.nodes:
            if node.name in node.dependencies:
                raise ValueError(f"pipeline node cannot depend on itself: {node.name}")
            if len(set(node.dependencies)) != len(node.dependencies):
                raise ValueError(
                    f"pipeline node dependencies must be unique: {node.name}"
                )
        remaining = {node.name: set(node.dependencies) for node in self.nodes}
        while remaining:
            ready = {name for name, dependencies in remaining.items() if not dependencies}
            if not ready:
                raise ValueError("pipeline node dependencies contain a cycle")
            remaining = {
                name: dependencies - ready
                for name, dependencies in remaining.items()
                if name not in ready
            }

    @classmethod
    def create(
        cls,
        *,
        pipeline_name: str,
        mode: str,
        run_id: str,
        scope_type: str,
        scope_id: str,
        node_dependencies: Mapping[str, Iterable[str]],
        created_at: str,
        output_build_id: str | None = None,
    ) -> "PipelineRun":
        return cls(
            pipeline_name=pipeline_name,
            mode=mode,
            run_id=run_id,
            scope_type=scope_type,
            scope_id=scope_id,
            status=PipelineRunStatus.QUEUED,
            nodes=tuple(
                PipelineNodeRun(name=name, dependencies=tuple(dependencies))
                for name, dependencies in node_dependencies.items()
            ),
            errors=(),
            warnings=(),
            stats=ExecutionStats(),
            timestamps=ExecutionTimestamps(created_at=created_at),
            output_build_id=output_build_id,
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PipelineRun":
        nodes_payload = payload.get("nodes") or {}
        if isinstance(nodes_payload, Mapping):
            nodes = tuple(
                PipelineNodeRun.from_mapping(
                    {**dict(node_payload), "name": name}
                    if isinstance(node_payload, Mapping)
                    else {"name": name}
                )
                for name, node_payload in nodes_payload.items()
            )
        else:
            nodes = tuple(
                PipelineNodeRun.from_mapping(item)
                for item in nodes_payload
                if isinstance(item, Mapping)
            )
        return cls(
            pipeline_name=str(payload.get("pipeline_name") or "").strip(),
            mode=str(payload.get("mode") or "").strip(),
            run_id=str(payload.get("run_id") or "").strip(),
            scope_type=str(payload.get("scope_type") or "").strip(),
            scope_id=str(payload.get("scope_id") or "").strip(),
            status=_run_status(payload.get("status")),
            nodes=nodes,
            errors=tuple(str(item) for item in payload.get("errors") or ()),
            warnings=tuple(str(item) for item in payload.get("warnings") or ()),
            stats=ExecutionStats.from_mapping(payload.get("stats")),
            timestamps=ExecutionTimestamps.from_mapping(payload.get("timestamps")),
            output_build_id=_optional_text(payload.get("output_build_id")),
        )

    def node(self, name: str) -> PipelineNodeRun:
        for node in self.nodes:
            if node.name == name:
                return node
        raise KeyError(f"pipeline node not found: {name}")

    def start(self, started_at: str) -> "PipelineRun":
        return replace(
            self,
            status=PipelineRunStatus.RUNNING,
            timestamps=replace(self.timestamps, started_at=started_at),
        )

    def with_node(self, updated: PipelineNodeRun) -> "PipelineRun":
        if all(node.name != updated.name for node in self.nodes):
            raise KeyError(f"pipeline node not found: {updated.name}")
        nodes = tuple(
            updated if node.name == updated.name else node for node in self.nodes
        )
        return replace(
            self,
            nodes=nodes,
            errors=self._node_messages(nodes, "errors"),
            warnings=self._node_messages(nodes, "warnings"),
            stats=ExecutionStats.aggregate(
                (node.stats for node in nodes),
                duration_ms=self.timestamps.duration_ms(),
            ),
        )

    def finish(
        self,
        status: PipelineRunStatus,
        finished_at: str,
    ) -> "PipelineRun":
        resolved_status = _run_status(status)
        if not resolved_status.is_terminal:
            raise ValueError("finished pipeline run requires a terminal status")
        timestamps = replace(self.timestamps, finished_at=finished_at)
        return replace(
            self,
            status=resolved_status,
            errors=self._node_messages(self.nodes, "errors"),
            warnings=self._node_messages(self.nodes, "warnings"),
            stats=ExecutionStats.aggregate(
                (node.stats for node in self.nodes),
                duration_ms=timestamps.duration_ms(),
            ),
            timestamps=timestamps,
        )

    @staticmethod
    def _node_messages(
        nodes: Iterable[PipelineNodeRun],
        field_name: str,
    ) -> tuple[str, ...]:
        return tuple(
            f"{node.name}: {message}"
            for node in nodes
            for message in getattr(node, field_name)
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "pipeline_name": self.pipeline_name,
            "mode": self.mode,
            "run_id": self.run_id,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "status": _run_status(self.status).value,
            "nodes": {node.name: node.to_record() for node in self.nodes},
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "stats": self.stats.to_record(),
            "timestamps": self.timestamps.to_record(),
            "output_build_id": self.output_build_id,
        }


__all__ = [
    "ExecutionStats",
    "ExecutionTimestamps",
    "ModelUsage",
    "PipelineNodeRun",
    "PipelineNodeStatus",
    "PipelineRun",
    "PipelineRunStatus",
    "TokenUsage",
]
