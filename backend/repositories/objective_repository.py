"""PostgreSQL repository for objective."""

from __future__ import annotations

from repositories.pipeline_run_repository import execution_stats_record

from repositories.pipeline_run_repository import execution_stats_from_json

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Final, Mapping

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.core import PaperStudyDisposition
from domain.core.finding import Finding
from domain.core.research_objective import (
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PreparedDocumentInput,
    ResearchObjective,
)
from infra.persistence.postgres.models.collection import Collection
from infra.persistence.postgres.models.document_preparation import (
    DocumentPreparationRow,
)
from infra.persistence.postgres.models.objective import (
    ObjectiveAnalysisRecord,
    ObjectiveResearchRecord,
)
from infra.persistence.postgres.transaction import database_session_scope
from repositories.pipeline_run_repository import ExecutionStats

OBJECTIVE_ANALYSIS_STATUSES: Final[frozenset[str]] = frozenset(
    {"queued", "running", "succeeded", "failed"}
)

OBJECTIVE_ANALYSIS_ORIGINS: Final[frozenset[str]] = frozenset(
    {"system_generated", "human_authored", "agent_authored", "hybrid"}
)

OBJECTIVE_ANALYSIS_RECORD_SOURCES: Final[frozenset[str]] = frozenset(
    {"experiment_graph", "authored_snapshot", "legacy_snapshot"}
)

OBJECTIVE_ANALYSIS_ABSTENTION_REASONS: Final[frozenset[str]] = frozenset(
    {"no_comparable_evidence", "no_grounded_evidence", "insufficient_evidence"}
)

OBJECTIVE_ANALYSIS_STATUS_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "queued": frozenset({"running", "failed"}),
    "running": frozenset({"succeeded", "failed"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_text(value: Any, message: str) -> str:
    text = _text(value)
    if text is None:
        raise ValueError(message)
    return text


def _choice(value: Any, allowed: frozenset[str], default: str) -> str:
    normalized = (_text(value) or "").lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in allowed else default


def _positive_int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = _text(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid datetime value: {text}") from exc


def _datetime_record(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True)
class ObjectiveAnalysis:
    collection_id: str
    objective_id: str
    analysis_version: int
    document_inputs: tuple[PreparedDocumentInput, ...]
    pipeline_version: str
    model_name: str | None
    prompt_versions: dict[str, str]
    stats: ExecutionStats = field(default_factory=ExecutionStats)
    status: str = "queued"
    phase: str = "queued"
    processed_document_count: int = 0
    total_document_count: int = 0
    current_document_id: str | None = None
    progress_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    diagnostics: tuple[Mapping[str, Any], ...] = ()
    origin: str = "system_generated"
    scientific_record_source: str = "experiment_graph"
    source_analysis_version: int | None = None
    created_by_user_id: str | None = None
    created_by_tool_call_id: str | None = None
    abstention_reason: str | None = None
    abstention_note: str | None = None

    def __post_init__(self) -> None:
        if not _text(self.collection_id) or not _text(self.objective_id):
            raise ValueError("objective analysis requires collection and objective IDs")
        if self.analysis_version < 1:
            raise ValueError("analysis_version must be a positive integer")
        object.__setattr__(self, "document_inputs", tuple(self.document_inputs))
        document_ids = [item.document_id for item in self.document_inputs]
        if not document_ids:
            raise ValueError("objective analysis requires prepared document inputs")
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("objective analysis document inputs must be unique")
        if not _text(self.pipeline_version):
            raise ValueError("objective analysis requires pipeline_version")
        if self.status not in OBJECTIVE_ANALYSIS_STATUSES:
            raise ValueError(f"unsupported objective analysis status: {self.status}")
        if self.origin not in OBJECTIVE_ANALYSIS_ORIGINS:
            raise ValueError(f"unsupported objective analysis origin: {self.origin}")
        if self.scientific_record_source not in OBJECTIVE_ANALYSIS_RECORD_SOURCES:
            raise ValueError(
                "unsupported objective analysis scientific record source: "
                f"{self.scientific_record_source}"
            )
        if self.origin == "system_generated":
            if self.scientific_record_source == "authored_snapshot":
                raise ValueError(
                    "system-generated analysis cannot use authored_snapshot"
                )
            if any(
                value is not None
                for value in (
                    self.source_analysis_version,
                    self.created_by_user_id,
                    self.created_by_tool_call_id,
                )
            ):
                raise ValueError(
                    "system-generated analysis cannot have authoring provenance"
                )
        elif self.origin == "agent_authored":
            if self.scientific_record_source not in {
                "authored_snapshot",
                "experiment_graph",
            }:
                raise ValueError(
                    "authored analysis requires authored_snapshot or experiment_graph"
                )
            if not _text(self.created_by_user_id) or not _text(
                self.created_by_tool_call_id
            ):
                raise ValueError(
                    "agent-authored analysis requires user and tool-call provenance"
                )
            if (
                self.source_analysis_version is not None
                and self.source_analysis_version >= self.analysis_version
            ):
                raise ValueError("authored analysis source must be an older version")
        else:
            if self.scientific_record_source not in {
                "authored_snapshot",
                "experiment_graph",
            }:
                raise ValueError(
                    "authored analysis requires authored_snapshot or experiment_graph"
                )
            if self.source_analysis_version is None:
                raise ValueError("authored analysis requires source_analysis_version")
            if self.source_analysis_version >= self.analysis_version:
                raise ValueError("authored analysis source must be an older version")
            if not _text(self.created_by_user_id):
                raise ValueError("authored analysis requires created_by_user_id")
        if (
            self.abstention_reason is not None
            and self.abstention_reason not in OBJECTIVE_ANALYSIS_ABSTENTION_REASONS
        ):
            raise ValueError(
                f"unsupported objective analysis abstention: {self.abstention_reason}"
            )
        if self.abstention_reason is not None and not _text(self.abstention_note):
            raise ValueError("analysis abstention requires an explanation")
        if self.abstention_reason is None and self.abstention_note is not None:
            raise ValueError("abstention note requires an abstention reason")
        if self.processed_document_count < 0 or self.total_document_count < 0:
            raise ValueError("analysis document counts cannot be negative")
        if self.processed_document_count > self.total_document_count:
            raise ValueError("processed document count exceeds total")
        if self.total_document_count != len(self.document_inputs):
            raise ValueError("analysis document input count must match total")
        if self.status == "failed" and not _text(self.error_message):
            raise ValueError("failed objective analysis requires error_message")
        if self.status == "succeeded" and self.error_message is not None:
            raise ValueError("succeeded objective analysis cannot have an error")
        object.__setattr__(
            self,
            "diagnostics",
            tuple(deepcopy(dict(item)) for item in self.diagnostics),
        )

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.collection_id, self.objective_id, self.analysis_version)

    @property
    def uses_experiment_records(self) -> bool:
        """Whether scientific records are owned by the PaperExperiment graph.

        Automatic analyses are published by ``ExperimentAnalysisWriter``.  An
        authored or hybrid version is a new immutable snapshot of the prior
        published records and therefore continues to use the authored record
        contract. Keeping this decision on the analysis snapshot prevents query
        callers from treating the mere presence of a projection dependency as
        proof that every analysis version is experiment-backed.
        """

        return (
            self.origin == "system_generated"
            and self.scientific_record_source == "experiment_graph"
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObjectiveAnalysis":
        origin = _choice(
            payload.get("origin"),
            OBJECTIVE_ANALYSIS_ORIGINS,
            "system_generated",
        )
        default_record_source = (
            "experiment_graph" if origin == "system_generated" else "authored_snapshot"
        )
        return cls(
            collection_id=_text(payload.get("collection_id")) or "",
            objective_id=_text(payload.get("objective_id")) or "",
            analysis_version=int(payload.get("analysis_version") or 0),
            document_inputs=tuple(
                PreparedDocumentInput.from_mapping(item)
                for item in payload.get("document_inputs") or ()
                if isinstance(item, Mapping)
            ),
            pipeline_version=_text(payload.get("pipeline_version")) or "",
            model_name=_text(payload.get("model_name")),
            prompt_versions={
                str(key): str(value)
                for key, value in dict(payload.get("prompt_versions") or {}).items()
            },
            stats=execution_stats_from_json(payload.get("stats")),
            status=_text(payload.get("status")) or "queued",
            phase=_text(payload.get("phase")) or "queued",
            processed_document_count=int(payload.get("processed_document_count") or 0),
            total_document_count=int(payload.get("total_document_count") or 0),
            current_document_id=_text(payload.get("current_document_id")),
            progress_message=_text(payload.get("progress_message")),
            error_code=_text(payload.get("error_code")),
            error_message=_text(payload.get("error_message")),
            created_at=_datetime_or_none(payload.get("created_at")),
            started_at=_datetime_or_none(payload.get("started_at")),
            completed_at=_datetime_or_none(payload.get("completed_at")),
            diagnostics=tuple(
                dict(item)
                for item in payload.get("diagnostics") or ()
                if isinstance(item, Mapping)
            ),
            origin=origin,
            scientific_record_source=_choice(
                payload.get("scientific_record_source"),
                OBJECTIVE_ANALYSIS_RECORD_SOURCES,
                default_record_source,
            ),
            source_analysis_version=_positive_int_or_none(
                payload.get("source_analysis_version")
            ),
            created_by_user_id=_text(payload.get("created_by_user_id")),
            created_by_tool_call_id=_text(payload.get("created_by_tool_call_id")),
            abstention_reason=_text(payload.get("abstention_reason")),
            abstention_note=_text(payload.get("abstention_note")),
        )

    def start(self, *, started_at: datetime | None = None) -> "ObjectiveAnalysis":
        return self._transition(
            "running",
            phase="started",
            started_at=started_at or self.started_at,
            error_code=None,
            error_message=None,
        )

    def update_progress(
        self,
        *,
        phase: str,
        processed_document_count: int,
        total_document_count: int,
        current_document_id: str | None = None,
        progress_message: str | None = None,
    ) -> "ObjectiveAnalysis":
        if self.status != "running":
            raise ValueError(
                f"cannot update analysis progress while status is {self.status}"
            )
        if total_document_count != self.total_document_count:
            raise ValueError("analysis progress cannot change total document count")
        return replace(
            self,
            phase=_required_text(phase, "analysis progress requires phase"),
            processed_document_count=processed_document_count,
            total_document_count=total_document_count,
            current_document_id=_text(current_document_id),
            progress_message=_text(progress_message),
        )

    def succeed(
        self,
        *,
        completed_at: datetime | None = None,
        abstention_reason: str | None = None,
        abstention_note: str | None = None,
    ) -> "ObjectiveAnalysis":
        return self._transition(
            "succeeded",
            phase="completed",
            processed_document_count=self.total_document_count,
            current_document_id=None,
            progress_message="Objective analysis completed.",
            error_code=None,
            error_message=None,
            completed_at=completed_at or self.completed_at,
            abstention_reason=_text(abstention_reason),
            abstention_note=_text(abstention_note),
        )

    def fail(
        self,
        *,
        error_code: str,
        error_message: str,
        completed_at: datetime | None = None,
    ) -> "ObjectiveAnalysis":
        return self._transition(
            "failed",
            phase="failed",
            current_document_id=None,
            error_code=_required_text(
                error_code, "analysis failure requires error_code"
            ),
            error_message=_required_text(
                error_message, "analysis failure requires error_message"
            ),
            completed_at=completed_at or self.completed_at,
        )

    def _transition(self, target: str, **changes: Any) -> "ObjectiveAnalysis":
        if target not in OBJECTIVE_ANALYSIS_STATUS_TRANSITIONS[self.status]:
            raise ValueError(
                f"invalid objective analysis transition: {self.status} -> {target}"
            )
        return replace(self, status=target, **changes)

    def to_record(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "objective_id": self.objective_id,
            "analysis_version": self.analysis_version,
            "document_inputs": [item.to_record() for item in self.document_inputs],
            "pipeline_version": self.pipeline_version,
            "model_name": self.model_name,
            "prompt_versions": dict(self.prompt_versions),
            "stats": execution_stats_record(self.stats),
            "status": self.status,
            "phase": self.phase,
            "processed_document_count": self.processed_document_count,
            "total_document_count": self.total_document_count,
            "current_document_id": self.current_document_id,
            "progress_message": self.progress_message,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "created_at": _datetime_record(self.created_at),
            "started_at": _datetime_record(self.started_at),
            "completed_at": _datetime_record(self.completed_at),
            "origin": self.origin,
            "scientific_record_source": self.scientific_record_source,
            "source_analysis_version": self.source_analysis_version,
            "created_by_user_id": self.created_by_user_id,
            "created_by_tool_call_id": self.created_by_tool_call_id,
            "abstention_reason": self.abstention_reason,
            "abstention_note": self.abstention_note,
        }


@dataclass(frozen=True)
class StoredObjective:
    objective: ResearchObjective
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ObjectiveRepository:
    backend_name = "postgres"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def replace(
        self,
        collection_id: str,
        facts: ObjectiveFactSet,
    ) -> None:
        for objective in facts.research_objectives:
            if objective.collection_id != collection_id:
                raise ValueError("objective belongs to another collection")
            if objective.origin != "system_discovered":
                raise ValueError("Objective discovery can only replace system candidates")

        now = datetime.now(timezone.utc)
        objective_ids = [item.objective_id for item in facts.research_objectives]
        async with self.session_factory.begin() as session:
            collection = await session.get(Collection, collection_id, with_for_update=True)
            if collection is None:
                raise FileNotFoundError(f"collection not found: {collection_id}")
            collection.discovery_ready = facts.research_objectives_ready
            collection.discovery_document_inputs = [
                item.to_record() for item in facts.document_inputs
            ]
            collection.discovery_objective_ids = objective_ids
            collection.discovery_study_dispositions = [
                item.to_record() for item in facts.study_dispositions
            ]
            collection.discovery_updated_at = now

            existing_system_rows = tuple(
                await session.scalars(
                    select(ObjectiveResearchRecord).where(
                        ObjectiveResearchRecord.collection_id == collection_id,
                        ObjectiveResearchRecord.origin == "system_discovered",
                    )
                )
            )
            retained_ids = set(objective_ids)
            for row in existing_system_rows:
                existing = self._objective_from_row(row)
                if (
                    existing.confirmation_status == "candidate"
                    and row.objective_id not in retained_ids
                ):
                    await session.delete(row)

            for objective in facts.research_objectives:
                row = await session.get(
                    ObjectiveResearchRecord,
                    (collection_id, objective.objective_id),
                )
                if row is not None:
                    existing = self._objective_from_row(row)
                    if existing.origin != "system_discovered":
                        raise ValueError("research objective identity collision")
                    objective = replace(
                        objective,
                        confirmation_status=existing.confirmation_status,
                        active_analysis_version=existing.active_analysis_version,
                        published_analysis_version=existing.published_analysis_version,
                    )
                    self._write_objective(row, objective, now=now)
                    continue
                session.add(self._new_objective_row(objective, now=now))

    async def read(self, collection_id: str) -> ObjectiveFactSet:
        async with self.session_factory() as session:
            collection = await session.get(Collection, collection_id)
            if collection is None or not collection.discovery_objective_ids:
                return ObjectiveFactSet()
            rows = tuple(
                await session.scalars(
                    select(ObjectiveResearchRecord).where(
                        ObjectiveResearchRecord.collection_id == collection_id,
                        ObjectiveResearchRecord.objective_id.in_(
                            collection.discovery_objective_ids or [""]
                        ),
                    )
                )
            )
            by_id = {row.objective_id: self._objective_from_row(row) for row in rows}
            return ObjectiveFactSet(
                research_objectives_ready=collection.discovery_ready,
                document_inputs=tuple(
                    PreparedDocumentInput.from_mapping(item)
                    for item in collection.discovery_document_inputs
                ),
                research_objectives=tuple(
                    by_id[objective_id]
                    for objective_id in collection.discovery_objective_ids
                    if objective_id in by_id
                ),
                study_dispositions=tuple(
                    PaperStudyDisposition.from_mapping(item)
                    for item in collection.discovery_study_dispositions
                ),
            )

    async def list_objectives(
        self,
        collection_id: str,
    ) -> tuple[ResearchObjective, ...]:
        async with self.session_factory() as session:
            rows = tuple(
                await session.scalars(
                    select(ObjectiveResearchRecord)
                    .where(ObjectiveResearchRecord.collection_id == collection_id)
                    .order_by(
                        ObjectiveResearchRecord.rank,
                        ObjectiveResearchRecord.created_at,
                        ObjectiveResearchRecord.objective_id,
                    )
                )
            )
            return tuple(self._objective_from_row(row) for row in rows)

    async def list_objective_records(
        self,
        collection_id: str,
    ) -> tuple[StoredObjective, ...]:
        async with self.session_factory() as session:
            rows = tuple(
                await session.scalars(
                    select(ObjectiveResearchRecord)
                    .where(ObjectiveResearchRecord.collection_id == collection_id)
                    .order_by(
                        ObjectiveResearchRecord.rank,
                        ObjectiveResearchRecord.created_at,
                        ObjectiveResearchRecord.objective_id,
                    )
                )
            )
            return tuple(self._objective_record_from_row(row) for row in rows)

    async def create_authored_candidate(
        self,
        objective: ResearchObjective,
        *,
        created_by_user_id: str,
        created_by_tool_call_id: str,
    ) -> ResearchObjective:
        if objective.origin != "chat_assisted":
            raise ValueError("authored candidate must have chat_assisted origin")
        if objective.created_by_user_id != created_by_user_id or (
            objective.created_by_tool_call_id != created_by_tool_call_id
        ):
            raise ValueError("authored candidate provenance does not match the request")
        now = datetime.now(timezone.utc)
        async with self.session_factory.begin() as session:
            prior = await session.scalar(
                select(ObjectiveResearchRecord).where(
                    ObjectiveResearchRecord.created_by_tool_call_id
                    == created_by_tool_call_id
                )
            )
            if prior is not None:
                existing = self._objective_from_row(prior)
                if (
                    existing.collection_id != objective.collection_id
                    or existing.objective_id != objective.objective_id
                    or existing.created_by_user_id != created_by_user_id
                    or replace(existing, rank=None) != replace(objective, rank=None)
                ):
                    raise ValueError(
                        "authored candidate tool call already created a different objective"
                    )
                return existing
            collision = await session.get(
                ObjectiveResearchRecord,
                (objective.collection_id, objective.objective_id),
            )
            if collision is not None:
                raise ValueError("research objective identity collision")
            maximum_rank = await session.scalar(
                select(func.max(ObjectiveResearchRecord.rank)).where(
                    ObjectiveResearchRecord.collection_id == objective.collection_id
                )
            )
            created = replace(
                objective,
                rank=int(maximum_rank or 0) + 1,
            )
            session.add(self._new_objective_row(created, now=now))
            return created

    async def read_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective | None:
        async with self.session_factory() as session:
            row = await session.get(
                ObjectiveResearchRecord,
                (collection_id, objective_id),
            )
            return self._objective_from_row(row) if row is not None else None

    async def read_objective_record(
        self,
        collection_id: str,
        objective_id: str,
    ) -> StoredObjective | None:
        async with self.session_factory() as session:
            row = await session.get(
                ObjectiveResearchRecord,
                (collection_id, objective_id),
            )
            return self._objective_record_from_row(row) if row is not None else None

    async def confirm_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective:
        async with self.session_factory.begin() as session:
            row = await self._locked_objective(session, collection_id, objective_id)
            objective = self._objective_from_row(row)
            if objective.confirmation_status == "confirmed":
                return objective
            confirmed = objective.confirm()
            self._write_objective(row, confirmed, now=datetime.now(timezone.utc))
            return confirmed

    async def queue_analysis(
        self,
        collection_id: str,
        objective_id: str,
        *,
        document_inputs: tuple[PreparedDocumentInput, ...],
        pipeline_version: str,
        model_name: str | None,
        prompt_versions: dict[str, str],
        origin: str = "system_generated",
        created_by_user_id: str | None = None,
        created_by_tool_call_id: str | None = None,
        source_analysis_version: int | None = None,
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]:
        now = datetime.now(timezone.utc)
        async with self.session_factory.begin() as session:
            row = await self._locked_objective(session, collection_id, objective_id)
            objective = self._objective_from_row(row)
            if (
                source_analysis_version is not None
                and objective.published_analysis_version != source_analysis_version
            ):
                raise ValueError("source analysis version is stale")
            if objective.confirmation_status == "candidate":
                objective = objective.confirm()
            active_row = await session.scalar(
                select(ObjectiveAnalysisRecord)
                .where(
                    ObjectiveAnalysisRecord.collection_id == collection_id,
                    ObjectiveAnalysisRecord.objective_id == objective_id,
                    ObjectiveAnalysisRecord.status.in_(("queued", "running")),
                )
                .order_by(ObjectiveAnalysisRecord.analysis_version.desc())
                .with_for_update()
            )
            if active_row is not None:
                active = self._analysis_from_row(active_row)
                if active.document_inputs != document_inputs:
                    raise ValueError(
                        "an active analysis already uses a different document scope"
                    )
                if (
                    active.origin != origin
                    or active.source_analysis_version != source_analysis_version
                    or active.created_by_user_id != created_by_user_id
                    or active.created_by_tool_call_id != created_by_tool_call_id
                ):
                    raise ValueError(
                        "an active analysis already uses different authoring provenance"
                    )
                self._write_objective(row, objective, now=now)
                return objective, active
            maximum_version = await session.scalar(
                select(func.max(ObjectiveAnalysisRecord.analysis_version)).where(
                    ObjectiveAnalysisRecord.collection_id == collection_id,
                    ObjectiveAnalysisRecord.objective_id == objective_id,
                )
            )
            version = int(maximum_version or 0) + 1
            analysis = ObjectiveAnalysis(
                collection_id=collection_id,
                objective_id=objective_id,
                analysis_version=version,
                document_inputs=document_inputs,
                pipeline_version=pipeline_version,
                model_name=model_name,
                prompt_versions=dict(prompt_versions),
                total_document_count=len(document_inputs),
                progress_message="Objective analysis is queued.",
                created_at=now,
                origin=origin,
                scientific_record_source=(
                    "experiment_graph"
                    if origin == "system_generated"
                    else "authored_snapshot"
                ),
                created_by_user_id=created_by_user_id,
                created_by_tool_call_id=created_by_tool_call_id,
                source_analysis_version=source_analysis_version,
            )
            objective = objective.queue_analysis(version)
            self._write_objective(row, objective, now=now)
            session.add(self._new_analysis_row(analysis, now=now))
            return objective, analysis

    async def claim_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ObjectiveAnalysis | None:
        async with self.session_factory.begin() as session:
            row = await self._locked_analysis(
                session,
                collection_id,
                objective_id,
                analysis_version,
            )
            analysis = self._analysis_from_row(row)
            if analysis.status != "queued":
                return None
            analysis = analysis.start(started_at=datetime.now(timezone.utc))
            self._write_analysis(row, analysis)
            return analysis

    async def update_analysis_progress(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        phase: str,
        processed_document_count: int,
        total_document_count: int,
        current_document_id: str | None,
        progress_message: str | None,
    ) -> ObjectiveAnalysis:
        async with self.session_factory.begin() as session:
            row = await self._locked_analysis(
                session, collection_id, objective_id, analysis_version
            )
            analysis = self._analysis_from_row(row).update_progress(
                phase=phase,
                processed_document_count=processed_document_count,
                total_document_count=total_document_count,
                current_document_id=current_document_id,
                progress_message=progress_message,
            )
            self._write_analysis(row, analysis)
            return analysis

    async def update_analysis_execution_stats(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        stats: ExecutionStats,
        model_name: str | None,
        prompt_versions: dict[str, str],
        diagnostics: tuple[dict[str, Any], ...],
    ) -> ObjectiveAnalysis:
        async with self.session_factory.begin() as session:
            row = await self._locked_analysis(
                session, collection_id, objective_id, analysis_version
            )
            analysis = replace(
                self._analysis_from_row(row),
                stats=stats,
                model_name=model_name,
                prompt_versions=dict(prompt_versions),
                diagnostics=diagnostics,
            )
            self._write_analysis(row, analysis)
            return analysis

    async def fail_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        error_code: str,
        error_message: str,
        expected_status: str | None = None,
        contributions: tuple[PaperContribution, ...] = (),
    ) -> ObjectiveAnalysis:
        async with self.session_factory.begin() as session:
            row = await self._locked_analysis(
                session, collection_id, objective_id, analysis_version
            )
            analysis = self._analysis_from_row(row)
            if expected_status is not None and analysis.status != expected_status:
                return analysis
            key = (collection_id, objective_id, analysis_version)
            if contributions:
                if any(item.key[:3] != key for item in contributions):
                    raise ValueError("analysis artifact belongs to another version")
                input_documents = {
                    item.document_id for item in analysis.document_inputs
                }
                if {item.document_id for item in contributions} != input_documents:
                    raise ValueError(
                        "paper contributions must cover every analysis input"
                    )
                self._write_contributions(row, contributions)
            analysis = analysis.fail(
                error_code=error_code,
                error_message=error_message,
                completed_at=datetime.now(timezone.utc),
            )
            self._write_analysis(row, analysis)
            return analysis

    async def interrupt_active_analyses(self) -> int:
        now = datetime.now(timezone.utc)
        async with self.session_factory.begin() as session:
            rows = tuple(
                await session.scalars(
                    select(ObjectiveAnalysisRecord)
                    .where(ObjectiveAnalysisRecord.status.in_(("queued", "running")))
                    .with_for_update()
                )
            )
            for row in rows:
                analysis = self._analysis_from_row(row).fail(
                    error_code="analysis_interrupted",
                    error_message=(
                        "Objective analysis was interrupted by a backend restart. "
                        "Retry the analysis."
                    ),
                    completed_at=now,
                )
                self._write_analysis(row, analysis)
            return len(rows)

    async def publish_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        contributions: tuple[PaperContribution, ...],
        evidence_records: tuple[ObjectiveEvidence, ...],
        findings: tuple[Finding, ...],
        abstention_reason: str | None = None,
        abstention_note: str | None = None,
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]:
        key = (collection_id, objective_id, analysis_version)
        async with self.session_factory.begin() as session:
            analysis_row = await self._locked_analysis(session, *key)
            objective_row = await self._locked_objective(
                session, collection_id, objective_id
            )
            analysis = self._analysis_from_row(analysis_row)
            if analysis.status != "running":
                raise ValueError("only running objective analysis can be published")
            for record in (*contributions, *evidence_records, *findings):
                if record.key[:3] != key:
                    raise ValueError("analysis artifact belongs to another version")
            input_documents = {item.document_id for item in analysis.document_inputs}
            contribution_documents = {item.document_id for item in contributions}
            if contribution_documents != input_documents:
                raise ValueError("paper contributions must cover every analysis input")
            if {item.document_id for item in evidence_records} - contribution_documents:
                raise ValueError("objective evidence lacks owning paper contribution")
            for evidence in evidence_records:
                await self._require_source_locator(session, collection_id, evidence)
            for finding in findings:
                finding.validate_sources(evidence_records, contributions)

            self._write_contributions(analysis_row, contributions)
            self._write_result_records(analysis_row, evidence_records, findings)
            analysis = replace(
                analysis,
                scientific_record_source=(
                    "legacy_snapshot"
                    if analysis.origin == "system_generated"
                    else "authored_snapshot"
                ),
            )
            analysis = analysis.succeed(
                completed_at=datetime.now(timezone.utc),
                abstention_reason=abstention_reason,
                abstention_note=abstention_note,
            )
            objective = self._objective_from_row(objective_row).publish_analysis(
                collection_id=analysis.collection_id,
                objective_id=analysis.objective_id,
                analysis_version=analysis.analysis_version,
                status=analysis.status,
            )
            self._write_analysis(analysis_row, analysis)
            self._write_objective(
                objective_row,
                objective,
                now=datetime.now(timezone.utc),
            )
            return objective, analysis

    async def publish_experiment_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        contributions: tuple[PaperContribution, ...] = (),
        abstention_reason: str | None = None,
        abstention_note: str | None = None,
        transaction: AsyncSession | None = None,
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]:
        """Publish the Objective lifecycle after experiment records are written.

        PaperExperiment, selections, groups, and Findings own the scientific
        records.  This transaction only advances the existing Objective
        analysis state and deliberately does not copy legacy Evidence payloads.
        """

        async with database_session_scope(
            self.session_factory, transaction, write=True
        ) as session:
            analysis_row = await self._locked_analysis(
                session,
                collection_id,
                objective_id,
                analysis_version,
            )
            objective_row = await self._locked_objective(
                session,
                collection_id,
                objective_id,
            )
            analysis = self._analysis_from_row(analysis_row)
            if analysis.status != "running":
                raise ValueError("only running objective analysis can be published")
            if contributions:
                input_documents = {item.document_id for item in analysis.document_inputs}
                contribution_documents = {item.document_id for item in contributions}
                if contribution_documents != input_documents:
                    raise ValueError("paper contributions must cover every analysis input")
                if any(item.key[:3] != (collection_id, objective_id, analysis_version) for item in contributions):
                    raise ValueError("paper contribution belongs to another analysis")
                self._write_contributions(analysis_row, contributions)
            analysis = replace(
                analysis,
                scientific_record_source="experiment_graph",
            )
            analysis = analysis.succeed(
                completed_at=datetime.now(timezone.utc),
                abstention_reason=abstention_reason,
                abstention_note=abstention_note,
            )
            objective = self._objective_from_row(objective_row).publish_analysis(
                collection_id=analysis.collection_id,
                objective_id=analysis.objective_id,
                analysis_version=analysis.analysis_version,
                status=analysis.status,
            )
            self._write_analysis(analysis_row, analysis)
            self._write_objective(
                objective_row,
                objective,
                now=datetime.now(timezone.utc),
            )
            return objective, analysis

    async def publish_authored_analysis(
        self,
        collection_id: str,
        objective_id: str,
        source_analysis_version: int,
        *,
        analysis: ObjectiveAnalysis,
        contributions: tuple[PaperContribution, ...],
        evidence_records: tuple[ObjectiveEvidence, ...],
        findings: tuple[Finding, ...],
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]:
        async with self.session_factory.begin() as session:
            objective_row = await self._locked_objective(
                session, collection_id, objective_id
            )
            objective = self._objective_from_row(objective_row)
            if objective.published_analysis_version != source_analysis_version:
                raise ValueError("source analysis version is stale")
            source_row = await self._locked_analysis(
                session, collection_id, objective_id, source_analysis_version
            )
            source = self._analysis_from_row(source_row)
            active_version = (
                objective.active_analysis_version or source_analysis_version
            )
            if active_version != source_analysis_version:
                active_row = await self._locked_analysis(
                    session, collection_id, objective_id, active_version
                )
                if self._analysis_from_row(active_row).status in {"queued", "running"}:
                    raise ValueError("objective analysis is currently running")
            if analysis.analysis_version != active_version + 1:
                raise ValueError("authored analysis version is no longer current")
            if analysis.status != "succeeded" or analysis.origin == "system_generated":
                raise ValueError(
                    "authored analysis must be a completed authored version"
                )
            if analysis.source_analysis_version != source_analysis_version:
                raise ValueError(
                    "authored analysis source version differs from request"
                )
            if source.status != "succeeded":
                raise ValueError(
                    "authored analysis requires a succeeded source version"
                )
            for record in (*contributions, *evidence_records, *findings):
                if record.key[:3] != analysis.key:
                    raise ValueError("analysis artifact belongs to another version")
            input_documents = {item.document_id for item in analysis.document_inputs}
            contribution_documents = {item.document_id for item in contributions}
            if contribution_documents != input_documents:
                raise ValueError(
                    "paper contributions must cover every analysis input"
                )
            if {item.document_id for item in evidence_records} - contribution_documents:
                raise ValueError(
                    "objective evidence lacks owning paper contribution"
                )
            for evidence in evidence_records:
                await self._require_source_locator(session, collection_id, evidence)
            for finding in findings:
                finding.validate_sources(evidence_records, contributions)

            now = datetime.now(timezone.utc)
            analysis_row = self._new_analysis_row(analysis, now=now)
            self._write_contributions(analysis_row, contributions)
            self._write_result_records(analysis_row, evidence_records, findings)
            session.add(analysis_row)
            objective = objective.queue_analysis(analysis.analysis_version)
            objective = objective.publish_analysis(
                collection_id=analysis.collection_id,
                objective_id=analysis.objective_id,
                analysis_version=analysis.analysis_version,
                status=analysis.status,
            )
            self._write_objective(objective_row, objective, now=now)
            return objective, analysis

    async def read_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int | None = None,
    ) -> ObjectiveAnalysis | None:
        async with self.session_factory() as session:
            if analysis_version is None:
                objective_row = await session.get(
                    ObjectiveResearchRecord,
                    (collection_id, objective_id),
                )
                if objective_row is None:
                    return None
                analysis_version = self._objective_from_row(
                    objective_row
                ).active_analysis_version
            if analysis_version is None:
                return None
            row = await session.get(
                ObjectiveAnalysisRecord,
                (collection_id, objective_id, analysis_version),
            )
            return self._analysis_from_row(row) if row is not None else None

    async def read_published_analysis(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveAnalysis | None:
        async with self.session_factory() as session:
            objective_row = await session.get(
                ObjectiveResearchRecord,
                (collection_id, objective_id),
            )
            if objective_row is None:
                return None
            version = self._objective_from_row(
                objective_row
            ).published_analysis_version
            if version is None:
                return None
            row = await session.get(
                ObjectiveAnalysisRecord,
                (collection_id, objective_id, version),
            )
            return self._analysis_from_row(row) if row is not None else None

    async def list_contributions(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[PaperContribution, ...]:
        async with self.session_factory() as session:
            row = await session.get(
                ObjectiveAnalysisRecord,
                (collection_id, objective_id, analysis_version),
            )
            if row is None:
                return ()
            return tuple(
                PaperContribution.from_mapping(item)
                for item in (row.payload or {}).get("paper_contributions", ())
            )

    async def list_findings(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[tuple[Finding, ...], int]:
        async with self.session_factory() as session:
            row = await session.get(
                ObjectiveAnalysisRecord,
                (collection_id, objective_id, analysis_version),
            )
            if row is None:
                return (), 0
            records = _sorted_finding_records((row.payload or {}).get("findings", ()))
            total = len(records)
            page = records[max(0, offset) : max(0, offset) + max(1, min(limit, 200))]
            return tuple(Finding.from_mapping(item) for item in page), total

    async def read_finding(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
    ) -> Finding | None:
        async with self.session_factory() as session:
            row = await session.get(
                ObjectiveAnalysisRecord,
                (collection_id, objective_id, analysis_version),
            )
            if row is None:
                return None
            for item in (row.payload or {}).get("findings", ()):
                if item.get("finding_id") == finding_id:
                    return Finding.from_mapping(item)
            return None

    async def list_evidence(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        finding_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[tuple[ObjectiveEvidence, ...], int]:
        async with self.session_factory() as session:
            evidence_ids: set[str] | None = None
            row = await session.get(
                ObjectiveAnalysisRecord,
                (collection_id, objective_id, analysis_version),
            )
            if row is None:
                return (), 0
            payload = row.payload or {}
            if finding_id is not None:
                finding = next(
                    (
                        item
                        for item in payload.get("findings", ())
                        if item.get("finding_id") == finding_id
                    ),
                    None,
                )
                if finding is None:
                    return (), 0
                finding = Finding.from_mapping(finding)
                evidence_ids = {
                    *finding.supporting_evidence_ids,
                    *finding.contradicting_evidence_ids,
                    *finding.context_evidence_ids,
                }
            records = list(payload.get("evidence_records", ()))
            if evidence_ids is not None:
                if not evidence_ids:
                    return (), 0
                records = [
                    item for item in records if item.get("evidence_id") in evidence_ids
                ]
            records.sort(key=lambda item: str(item.get("evidence_id") or ""))
            total = len(records)
            page = records[max(0, offset) : max(0, offset) + max(1, min(limit, 500))]
            return tuple(ObjectiveEvidence.from_mapping(item) for item in page), total

    @staticmethod
    def _objective_from_row(row: ObjectiveResearchRecord) -> ResearchObjective:
        return ResearchObjective.from_mapping(row.payload)

    @staticmethod
    def _objective_record_from_row(
        row: ObjectiveResearchRecord,
    ) -> StoredObjective:
        return StoredObjective(
            objective=ObjectiveRepository._objective_from_row(row),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _analysis_from_row(row: ObjectiveAnalysisRecord) -> ObjectiveAnalysis:
        return ObjectiveAnalysis.from_mapping(row.payload)

    @staticmethod
    def _new_objective_row(
        objective: ResearchObjective,
        *,
        now: datetime,
    ) -> ObjectiveResearchRecord:
        return ObjectiveResearchRecord(
            collection_id=objective.collection_id,
            objective_id=objective.objective_id,
            rank=objective.rank or 1,
            origin=objective.origin,
            created_by_tool_call_id=objective.created_by_tool_call_id,
            payload=ObjectiveRepository._objective_payload(objective),
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _write_objective(
        row: ObjectiveResearchRecord,
        objective: ResearchObjective,
        *,
        now: datetime,
    ) -> None:
        row.rank = objective.rank or row.rank
        row.origin = objective.origin
        row.created_by_tool_call_id = objective.created_by_tool_call_id
        row.payload = ObjectiveRepository._objective_payload(objective)
        row.updated_at = now

    @staticmethod
    def _objective_payload(objective: ResearchObjective) -> dict[str, Any]:
        return {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in asdict(objective).items()
        }

    @staticmethod
    def _new_analysis_row(
        analysis: ObjectiveAnalysis,
        *,
        now: datetime,
    ) -> ObjectiveAnalysisRecord:
        payload = analysis.to_record()
        payload["diagnostics"] = [dict(item) for item in analysis.diagnostics]
        return ObjectiveAnalysisRecord(
            collection_id=analysis.collection_id,
            objective_id=analysis.objective_id,
            analysis_version=analysis.analysis_version,
            status=analysis.status,
            payload=payload,
            created_at=analysis.created_at or now,
            updated_at=now,
        )

    @staticmethod
    def _write_contributions(
        row: ObjectiveAnalysisRecord,
        contributions: tuple[PaperContribution, ...],
    ) -> None:
        payload = dict(row.payload or {})
        payload["paper_contributions"] = [item.to_record() for item in contributions]
        row.payload = payload

    @staticmethod
    def _write_result_records(
        row: ObjectiveAnalysisRecord,
        evidence_records: tuple[ObjectiveEvidence, ...],
        findings: tuple[Finding, ...],
    ) -> None:
        payload = dict(row.payload or {})
        payload["evidence_records"] = [item.to_record() for item in evidence_records]
        payload["findings"] = [item.to_record() for item in findings]
        row.payload = payload

    @staticmethod
    def _write_analysis(
        row: ObjectiveAnalysisRecord,
        analysis: ObjectiveAnalysis,
    ) -> None:
        row.status = analysis.status
        previous = dict(row.payload or {})
        payload = analysis.to_record()
        payload["diagnostics"] = [dict(item) for item in analysis.diagnostics]
        for key in (
            "paper_contributions",
            "evidence_records",
            "findings",
        ):
            if key in previous:
                payload[key] = previous[key]
        row.payload = payload
        row.updated_at = datetime.now(timezone.utc)

    @staticmethod
    async def _locked_objective(
        session: AsyncSession,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveResearchRecord:
        row = await session.scalar(
            select(ObjectiveResearchRecord)
            .where(
                ObjectiveResearchRecord.collection_id == collection_id,
                ObjectiveResearchRecord.objective_id == objective_id,
            )
            .with_for_update()
        )
        if row is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        return row

    @staticmethod
    async def _locked_analysis(
        session: AsyncSession,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ObjectiveAnalysisRecord:
        row = await session.scalar(
            select(ObjectiveAnalysisRecord)
            .where(
                ObjectiveAnalysisRecord.collection_id == collection_id,
                ObjectiveAnalysisRecord.objective_id == objective_id,
                ObjectiveAnalysisRecord.analysis_version == analysis_version,
            )
            .with_for_update()
        )
        if row is None:
            raise FileNotFoundError(
                "objective analysis not found: "
                f"{collection_id}/{objective_id}/{analysis_version}"
            )
        return row

    @staticmethod
    async def _require_source_locator(
        session: AsyncSession,
        collection_id: str,
        evidence: ObjectiveEvidence,
    ) -> None:
        row = await session.scalar(
            select(DocumentPreparationRow).where(
                DocumentPreparationRow.document_id == evidence.document_id,
            )
        )
        if row is None:
            raise FileNotFoundError(
                f"source document not found: {collection_id}/{evidence.document_id}"
            )
        artifact = dict(row.artifact_json or {})
        source_rows = {
            "text_window": artifact.get("blocks") or [],
            "table": artifact.get("tables") or [],
            "figure": artifact.get("figures") or [],
        }.get(evidence.source_kind)
        if source_rows is None:
            raise ValueError(f"unsupported objective evidence source kind: {evidence.source_kind}")
        identity_key = {
            "text_window": "block_id",
            "table": "table_id",
            "figure": "figure_id",
        }[evidence.source_kind]
        if not any(str(item.get(identity_key)) == evidence.source_ref for item in source_rows):
            raise FileNotFoundError(
                "objective evidence source not found: "
                f"{collection_id}/{evidence.document_id}/"
                f"{evidence.source_kind}/{evidence.source_ref}"
            )


def _sorted_finding_records(values: Any) -> list[dict[str, Any]]:
    return sorted(
        (dict(item) for item in values or ()),
        key=lambda item: (
            int(item.get("display_rank") or 0),
            str(item.get("finding_id") or ""),
        ),
    )


__all__ = ['ObjectiveRepository']
