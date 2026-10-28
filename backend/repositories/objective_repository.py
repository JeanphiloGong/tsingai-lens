"""PostgreSQL repository for objective."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import (
    Any,
    Final,
    Mapping,
)

from domain.core import PaperStudyDisposition
from domain.core.finding import (
    Finding,
    FindingMechanismRelation,
    FindingPaperContribution,
)
from domain.core.finding import _stable_id as finding_stable_id
from domain.core.research_objective import (
    InspectedObjectiveSourceRef,
    Mapping,
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PaperStudyDisposition,
    PreparedDocumentInput,
    ResearchObjective,
    _choice,
)
from domain.core.research_objective import (
    _objective_derivation_basis,
)
from domain.core.research_objective import _positive_int_or_none
from domain.core.research_objective import _scoped_id as objective_scoped_id
from domain.core.research_objective import (
    _text,
)
from domain.core.scientific_fact import (
    ScientificAttribute,
    ScientificComparison,
    ScientificContext,
    ScientificResult,
    ScientificVariable,
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
from repositories.pipeline_run_repository import (
    ExecutionStats,
    ModelUsage,
    TokenUsage,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
                {
                    "document_id": item.document_id,
                    "preparation_fingerprint": item.preparation_fingerprint,
                }
                for item in facts.document_inputs
            ]
            collection.discovery_objective_ids = objective_ids
            collection.discovery_study_dispositions = [
                {
                    "document_id": item.document_id,
                    "study_id": item.study_id,
                    "relationship_id": item.relationship_id,
                    "status": item.status.value,
                    "objective_id": item.objective_id,
                    "reason": item.reason,
                }
                for item in facts.study_dispositions
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
                if (
                    row.payload.get("confirmation_status", "candidate") == "candidate"
                    and row.objective_id not in retained_ids
                ):
                    await session.delete(row)

            for objective in facts.research_objectives:
                row = await session.get(
                    ObjectiveResearchRecord,
                    (collection_id, objective.objective_id),
                )
                if row is not None:
                    if row.origin != "system_discovered":
                        raise ValueError("research objective identity collision")
                    objective = replace(
                        objective,
                        confirmation_status=row.payload.get("confirmation_status", "candidate"),
                        active_analysis_version=row.payload.get("active_analysis_version"),
                        published_analysis_version=row.payload.get("published_analysis_version"),
                    )
                    row.rank = objective.rank or row.rank
                    row.origin = objective.origin
                    row.created_by_tool_call_id = objective.created_by_tool_call_id
                    row.payload = {
                        key: list(value) if isinstance(value, tuple) else value
                        for key, value in asdict(objective).items()
                    }
                    row.updated_at = now
                    continue
                session.add(
                    ObjectiveResearchRecord(
                        collection_id=objective.collection_id,
                        objective_id=objective.objective_id,
                        rank=objective.rank or 1,
                        origin=objective.origin,
                        created_by_tool_call_id=objective.created_by_tool_call_id,
                        payload={
                            key: list(value) if isinstance(value, tuple) else value
                            for key, value in asdict(objective).items()
                        },
                        created_at=now,
                        updated_at=now,
                    )
                )

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
            by_id = {
                row.objective_id: ResearchObjective(
                    collection_id=row.collection_id,
                    objective_id=row.objective_id,
                    question=row.payload.get("question", ""),
                    material_scope=tuple(row.payload.get("material_scope", ())),
                    variables=tuple(row.payload.get("variables", ())),
                    outcomes=tuple(row.payload.get("outcomes", ())),
                    mechanisms=tuple(row.payload.get("mechanisms", ())),
                    constraints=tuple(row.payload.get("constraints", ())),
                    requested_comparator=row.payload.get("requested_comparator"),
                    seed_document_ids=tuple(row.payload.get("seed_document_ids", ())),
                    excluded_document_ids=tuple(
                        row.payload.get("excluded_document_ids", ())
                    ),
                    confidence=row.payload.get("confidence", 0.0),
                    reason=row.payload.get("reason"),
                    source_relationship_ids=tuple(
                        row.payload.get("source_relationship_ids", ())
                    ),
                    parent_objective_id=row.payload.get("parent_objective_id"),
                    parent_analysis_version=row.payload.get("parent_analysis_version"),
                    derivation_basis=_objective_derivation_basis(
                        row.payload.get("derivation_basis")
                    ),
                    rank=row.payload.get("rank"),
                    confirmation_status=row.payload.get(
                        "confirmation_status", "candidate"
                    ),
                    active_analysis_version=row.payload.get("active_analysis_version"),
                    published_analysis_version=row.payload.get(
                        "published_analysis_version"
                    ),
                    origin=row.payload.get("origin", "system_discovered"),
                    created_by_user_id=row.payload.get("created_by_user_id"),
                    created_by_tool_call_id=row.payload.get("created_by_tool_call_id"),
                )
                for row in rows
            }
            return ObjectiveFactSet(
                research_objectives_ready=collection.discovery_ready,
                document_inputs=tuple(
                    PreparedDocumentInput(
                        document_id=_text(item.get("document_id")) or "",
                        preparation_fingerprint=_text(
                            item.get("preparation_fingerprint")
                        )
                        or "",
                    )
                    for item in collection.discovery_document_inputs
                ),
                research_objectives=tuple(
                    by_id[objective_id]
                    for objective_id in collection.discovery_objective_ids
                    if objective_id in by_id
                ),
                study_dispositions=tuple(
                    PaperStudyDisposition(
                        document_id=_text(item.get("document_id")) or "",
                        study_id=_text(item.get("study_id")) or "",
                        relationship_id=_text(item.get("relationship_id")) or "",
                        status=PaperStudyDisposition._status(
                            item.get("status") or "pending"
                        ),
                        objective_id=_text(item.get("objective_id")),
                        reason=_text(item.get("reason")),
                    )
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
            return tuple(
                ResearchObjective(
                    collection_id=row.collection_id,
                    objective_id=row.objective_id,
                    question=row.payload.get("question", ""),
                    material_scope=tuple(row.payload.get("material_scope", ())),
                    variables=tuple(row.payload.get("variables", ())),
                    outcomes=tuple(row.payload.get("outcomes", ())),
                    mechanisms=tuple(row.payload.get("mechanisms", ())),
                    constraints=tuple(row.payload.get("constraints", ())),
                    requested_comparator=row.payload.get("requested_comparator"),
                    seed_document_ids=tuple(row.payload.get("seed_document_ids", ())),
                    excluded_document_ids=tuple(
                        row.payload.get("excluded_document_ids", ())
                    ),
                    confidence=row.payload.get("confidence", 0.0),
                    reason=row.payload.get("reason"),
                    source_relationship_ids=tuple(
                        row.payload.get("source_relationship_ids", ())
                    ),
                    parent_objective_id=row.payload.get("parent_objective_id"),
                    parent_analysis_version=row.payload.get("parent_analysis_version"),
                    derivation_basis=_objective_derivation_basis(
                        row.payload.get("derivation_basis")
                    ),
                    rank=row.payload.get("rank"),
                    confirmation_status=row.payload.get(
                        "confirmation_status", "candidate"
                    ),
                    active_analysis_version=row.payload.get("active_analysis_version"),
                    published_analysis_version=row.payload.get(
                        "published_analysis_version"
                    ),
                    origin=row.payload.get("origin", "system_discovered"),
                    created_by_user_id=row.payload.get("created_by_user_id"),
                    created_by_tool_call_id=row.payload.get("created_by_tool_call_id"),
                )
                for row in rows
            )

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
            return tuple(
                StoredObjective(
                    objective=ResearchObjective(
                        collection_id=row.collection_id,
                        objective_id=row.objective_id,
                        question=row.payload.get("question", ""),
                        material_scope=tuple(row.payload.get("material_scope", ())),
                        variables=tuple(row.payload.get("variables", ())),
                        outcomes=tuple(row.payload.get("outcomes", ())),
                        mechanisms=tuple(row.payload.get("mechanisms", ())),
                        constraints=tuple(row.payload.get("constraints", ())),
                        requested_comparator=row.payload.get("requested_comparator"),
                        seed_document_ids=tuple(
                            row.payload.get("seed_document_ids", ())
                        ),
                        excluded_document_ids=tuple(
                            row.payload.get("excluded_document_ids", ())
                        ),
                        confidence=row.payload.get("confidence", 0.0),
                        reason=row.payload.get("reason"),
                        source_relationship_ids=tuple(
                            row.payload.get("source_relationship_ids", ())
                        ),
                        parent_objective_id=row.payload.get("parent_objective_id"),
                        parent_analysis_version=row.payload.get(
                            "parent_analysis_version"
                        ),
                        derivation_basis=_objective_derivation_basis(
                            row.payload.get("derivation_basis")
                        ),
                        rank=row.payload.get("rank"),
                        confirmation_status=row.payload.get(
                            "confirmation_status", "candidate"
                        ),
                        active_analysis_version=row.payload.get(
                            "active_analysis_version"
                        ),
                        published_analysis_version=row.payload.get(
                            "published_analysis_version"
                        ),
                        origin=row.payload.get("origin", "system_discovered"),
                        created_by_user_id=row.payload.get("created_by_user_id"),
                        created_by_tool_call_id=row.payload.get(
                            "created_by_tool_call_id"
                        ),
                    ),
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            )

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
                existing = ResearchObjective(
                    collection_id=prior.collection_id,
                    objective_id=prior.objective_id,
                    question=prior.payload.get("question", ""),
                    material_scope=tuple(prior.payload.get("material_scope", ())),
                    variables=tuple(prior.payload.get("variables", ())),
                    outcomes=tuple(prior.payload.get("outcomes", ())),
                    mechanisms=tuple(prior.payload.get("mechanisms", ())),
                    constraints=tuple(prior.payload.get("constraints", ())),
                    requested_comparator=prior.payload.get("requested_comparator"),
                    seed_document_ids=tuple(prior.payload.get("seed_document_ids", ())),
                    excluded_document_ids=tuple(
                        prior.payload.get("excluded_document_ids", ())
                    ),
                    confidence=prior.payload.get("confidence", 0.0),
                    reason=prior.payload.get("reason"),
                    source_relationship_ids=tuple(
                        prior.payload.get("source_relationship_ids", ())
                    ),
                    parent_objective_id=prior.payload.get("parent_objective_id"),
                    parent_analysis_version=prior.payload.get(
                        "parent_analysis_version"
                    ),
                    derivation_basis=_objective_derivation_basis(
                        prior.payload.get("derivation_basis")
                    ),
                    rank=prior.payload.get("rank"),
                    confirmation_status=prior.payload.get(
                        "confirmation_status", "candidate"
                    ),
                    active_analysis_version=prior.payload.get(
                        "active_analysis_version"
                    ),
                    published_analysis_version=prior.payload.get(
                        "published_analysis_version"
                    ),
                    origin=prior.payload.get("origin", "system_discovered"),
                    created_by_user_id=prior.payload.get("created_by_user_id"),
                    created_by_tool_call_id=prior.payload.get(
                        "created_by_tool_call_id"
                    ),
                )
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
            session.add(
                ObjectiveResearchRecord(
                    collection_id=created.collection_id,
                    objective_id=created.objective_id,
                    rank=created.rank or 1,
                    origin=created.origin,
                    created_by_tool_call_id=created.created_by_tool_call_id,
                    payload={
                        key: list(value) if isinstance(value, tuple) else value
                        for key, value in asdict(created).items()
                    },
                    created_at=now,
                    updated_at=now,
                )
            )
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
            return (
                ResearchObjective(
                    collection_id=row.collection_id,
                    objective_id=row.objective_id,
                    question=row.payload.get("question", ""),
                    material_scope=tuple(row.payload.get("material_scope", ())),
                    variables=tuple(row.payload.get("variables", ())),
                    outcomes=tuple(row.payload.get("outcomes", ())),
                    mechanisms=tuple(row.payload.get("mechanisms", ())),
                    constraints=tuple(row.payload.get("constraints", ())),
                    requested_comparator=row.payload.get("requested_comparator"),
                    seed_document_ids=tuple(row.payload.get("seed_document_ids", ())),
                    excluded_document_ids=tuple(
                        row.payload.get("excluded_document_ids", ())
                    ),
                    confidence=row.payload.get("confidence", 0.0),
                    reason=row.payload.get("reason"),
                    source_relationship_ids=tuple(
                        row.payload.get("source_relationship_ids", ())
                    ),
                    parent_objective_id=row.payload.get("parent_objective_id"),
                    parent_analysis_version=row.payload.get("parent_analysis_version"),
                    derivation_basis=_objective_derivation_basis(
                        row.payload.get("derivation_basis")
                    ),
                    rank=row.payload.get("rank"),
                    confirmation_status=row.payload.get(
                        "confirmation_status", "candidate"
                    ),
                    active_analysis_version=row.payload.get("active_analysis_version"),
                    published_analysis_version=row.payload.get(
                        "published_analysis_version"
                    ),
                    origin=row.payload.get("origin", "system_discovered"),
                    created_by_user_id=row.payload.get("created_by_user_id"),
                    created_by_tool_call_id=row.payload.get("created_by_tool_call_id"),
                )
                if row is not None
                else None
            )

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
            return (
                StoredObjective(
                    objective=ResearchObjective(
                        collection_id=row.collection_id,
                        objective_id=row.objective_id,
                        question=row.payload.get("question", ""),
                        material_scope=tuple(row.payload.get("material_scope", ())),
                        variables=tuple(row.payload.get("variables", ())),
                        outcomes=tuple(row.payload.get("outcomes", ())),
                        mechanisms=tuple(row.payload.get("mechanisms", ())),
                        constraints=tuple(row.payload.get("constraints", ())),
                        requested_comparator=row.payload.get("requested_comparator"),
                        seed_document_ids=tuple(
                            row.payload.get("seed_document_ids", ())
                        ),
                        excluded_document_ids=tuple(
                            row.payload.get("excluded_document_ids", ())
                        ),
                        confidence=row.payload.get("confidence", 0.0),
                        reason=row.payload.get("reason"),
                        source_relationship_ids=tuple(
                            row.payload.get("source_relationship_ids", ())
                        ),
                        parent_objective_id=row.payload.get("parent_objective_id"),
                        parent_analysis_version=row.payload.get(
                            "parent_analysis_version"
                        ),
                        derivation_basis=_objective_derivation_basis(
                            row.payload.get("derivation_basis")
                        ),
                        rank=row.payload.get("rank"),
                        confirmation_status=row.payload.get(
                            "confirmation_status", "candidate"
                        ),
                        active_analysis_version=row.payload.get(
                            "active_analysis_version"
                        ),
                        published_analysis_version=row.payload.get(
                            "published_analysis_version"
                        ),
                        origin=row.payload.get("origin", "system_discovered"),
                        created_by_user_id=row.payload.get("created_by_user_id"),
                        created_by_tool_call_id=row.payload.get(
                            "created_by_tool_call_id"
                        ),
                    ),
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                if row is not None
                else None
            )

    async def confirm_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective:
        async with self.session_factory.begin() as session:
            row = await self._locked_objective(session, collection_id, objective_id)
            objective = ResearchObjective(
                collection_id=row.collection_id,
                objective_id=row.objective_id,
                question=row.payload.get("question", ""),
                material_scope=tuple(row.payload.get("material_scope", ())),
                variables=tuple(row.payload.get("variables", ())),
                outcomes=tuple(row.payload.get("outcomes", ())),
                mechanisms=tuple(row.payload.get("mechanisms", ())),
                constraints=tuple(row.payload.get("constraints", ())),
                requested_comparator=row.payload.get("requested_comparator"),
                seed_document_ids=tuple(row.payload.get("seed_document_ids", ())),
                excluded_document_ids=tuple(
                    row.payload.get("excluded_document_ids", ())
                ),
                confidence=row.payload.get("confidence", 0.0),
                reason=row.payload.get("reason"),
                source_relationship_ids=tuple(
                    row.payload.get("source_relationship_ids", ())
                ),
                parent_objective_id=row.payload.get("parent_objective_id"),
                parent_analysis_version=row.payload.get("parent_analysis_version"),
                derivation_basis=_objective_derivation_basis(
                    row.payload.get("derivation_basis")
                ),
                rank=row.payload.get("rank"),
                confirmation_status=row.payload.get("confirmation_status", "candidate"),
                active_analysis_version=row.payload.get("active_analysis_version"),
                published_analysis_version=row.payload.get(
                    "published_analysis_version"
                ),
                origin=row.payload.get("origin", "system_discovered"),
                created_by_user_id=row.payload.get("created_by_user_id"),
                created_by_tool_call_id=row.payload.get("created_by_tool_call_id"),
            )
            if objective.confirmation_status == "confirmed":
                return objective
            confirmed = objective.confirm()
            row.rank = confirmed.rank or row.rank
            row.origin = confirmed.origin
            row.created_by_tool_call_id = confirmed.created_by_tool_call_id
            row.payload = {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in asdict(confirmed).items()
            }
            row.updated_at = datetime.now(timezone.utc)
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
            objective = ResearchObjective(
                collection_id=row.collection_id,
                objective_id=row.objective_id,
                question=row.payload.get("question", ""),
                material_scope=tuple(row.payload.get("material_scope", ())),
                variables=tuple(row.payload.get("variables", ())),
                outcomes=tuple(row.payload.get("outcomes", ())),
                mechanisms=tuple(row.payload.get("mechanisms", ())),
                constraints=tuple(row.payload.get("constraints", ())),
                requested_comparator=row.payload.get("requested_comparator"),
                seed_document_ids=tuple(row.payload.get("seed_document_ids", ())),
                excluded_document_ids=tuple(
                    row.payload.get("excluded_document_ids", ())
                ),
                confidence=row.payload.get("confidence", 0.0),
                reason=row.payload.get("reason"),
                source_relationship_ids=tuple(
                    row.payload.get("source_relationship_ids", ())
                ),
                parent_objective_id=row.payload.get("parent_objective_id"),
                parent_analysis_version=row.payload.get("parent_analysis_version"),
                derivation_basis=_objective_derivation_basis(
                    row.payload.get("derivation_basis")
                ),
                rank=row.payload.get("rank"),
                confirmation_status=row.payload.get("confirmation_status", "candidate"),
                active_analysis_version=row.payload.get("active_analysis_version"),
                published_analysis_version=row.payload.get(
                    "published_analysis_version"
                ),
                origin=row.payload.get("origin", "system_discovered"),
                created_by_user_id=row.payload.get("created_by_user_id"),
                created_by_tool_call_id=row.payload.get("created_by_tool_call_id"),
            )
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
                active = ObjectiveAnalysis(
                    collection_id=active_row.payload.get("collection_id", ""),
                    objective_id=active_row.payload.get("objective_id", ""),
                    analysis_version=active_row.payload.get("analysis_version", 0),
                    document_inputs=tuple(
                        (
                            PreparedDocumentInput(
                                document_id=item.get("document_id", ""),
                                preparation_fingerprint=item.get(
                                    "preparation_fingerprint", ""
                                ),
                            )
                            for item in active_row.payload.get("document_inputs", ())
                        )
                    ),
                    pipeline_version=active_row.payload.get("pipeline_version", ""),
                    model_name=active_row.payload.get("model_name"),
                    prompt_versions={
                        str(key): str(value)
                        for key, value in dict(
                            active_row.payload.get("prompt_versions", {})
                        ).items()
                    },
                    stats=ExecutionStats(
                        duration_ms=(active_row.payload.get("stats") or {}).get(
                            "duration_ms"
                        ),
                        model_usage=tuple(
                            ModelUsage(
                                model_name=item["model_name"],
                                request_count=item["request_count"],
                                token_usage=(
                                    TokenUsage(
                                        input_tokens=item["token_usage"][
                                            "input_tokens"
                                        ],
                                        output_tokens=item["token_usage"][
                                            "output_tokens"
                                        ],
                                        total_tokens=item["token_usage"][
                                            "total_tokens"
                                        ],
                                    )
                                    if item.get("token_usage") is not None
                                    else None
                                ),
                                unreported_request_count=item.get(
                                    "unreported_request_count", 0
                                ),
                            )
                            for item in (active_row.payload.get("stats") or {}).get(
                                "model_usage", ()
                            )
                        ),
                        prompt_versions=(active_row.payload.get("stats") or {}).get(
                            "prompt_versions", {}
                        ),
                    ),
                    status=active_row.payload.get("status", "queued"),
                    phase=active_row.payload.get("phase", "queued"),
                    processed_document_count=active_row.payload.get(
                        "processed_document_count", 0
                    ),
                    total_document_count=active_row.payload.get(
                        "total_document_count", 0
                    ),
                    current_document_id=active_row.payload.get("current_document_id"),
                    progress_message=active_row.payload.get("progress_message"),
                    error_code=active_row.payload.get("error_code"),
                    error_message=active_row.payload.get("error_message"),
                    created_at=_datetime_or_none(active_row.payload.get("created_at")),
                    started_at=_datetime_or_none(active_row.payload.get("started_at")),
                    completed_at=_datetime_or_none(
                        active_row.payload.get("completed_at")
                    ),
                    diagnostics=tuple(
                        (
                            dict(item)
                            for item in active_row.payload.get("diagnostics", ())
                        )
                    ),
                    origin=active_row.payload.get("origin", "system_generated"),
                    scientific_record_source=active_row.payload.get(
                        "scientific_record_source",
                        (
                            "experiment_graph"
                            if active_row.payload.get("origin", "system_generated")
                            == "system_generated"
                            else "authored_snapshot"
                        ),
                    ),
                    source_analysis_version=active_row.payload.get(
                        "source_analysis_version"
                    ),
                    created_by_user_id=active_row.payload.get("created_by_user_id"),
                    created_by_tool_call_id=active_row.payload.get(
                        "created_by_tool_call_id"
                    ),
                    abstention_reason=active_row.payload.get("abstention_reason"),
                    abstention_note=active_row.payload.get("abstention_note"),
                )
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
                row.rank = objective.rank or row.rank
                row.origin = objective.origin
                row.created_by_tool_call_id = objective.created_by_tool_call_id
                row.payload = {
                    key: list(value) if isinstance(value, tuple) else value
                    for key, value in asdict(objective).items()
                }
                row.updated_at = now
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
            row.rank = objective.rank or row.rank
            row.origin = objective.origin
            row.created_by_tool_call_id = objective.created_by_tool_call_id
            row.payload = {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in asdict(objective).items()
            }
            row.updated_at = now
            next_analysis_payload = {
                "collection_id": analysis.collection_id,
                "objective_id": analysis.objective_id,
                "analysis_version": analysis.analysis_version,
                "document_inputs": [
                    {
                        "document_id": document_input.document_id,
                        "preparation_fingerprint": document_input.preparation_fingerprint,
                    }
                    for document_input in analysis.document_inputs
                ],
                "pipeline_version": analysis.pipeline_version,
                "model_name": analysis.model_name,
                "prompt_versions": dict(analysis.prompt_versions),
                "stats": {
                    "duration_ms": analysis.stats.duration_ms,
                    "token_usage": (
                        asdict(analysis.stats.token_usage)
                        if analysis.stats.token_usage is not None
                        else None
                    ),
                    "model_usage": [
                        asdict(item) for item in analysis.stats.model_usage
                    ],
                    "unreported_request_count": analysis.stats.unreported_request_count,
                    "prompt_versions": dict(analysis.stats.prompt_versions),
                },
                "status": analysis.status,
                "phase": analysis.phase,
                "processed_document_count": analysis.processed_document_count,
                "total_document_count": analysis.total_document_count,
                "current_document_id": analysis.current_document_id,
                "progress_message": analysis.progress_message,
                "error_code": analysis.error_code,
                "error_message": analysis.error_message,
                "created_at": (
                    analysis.created_at.isoformat()
                    if analysis.created_at is not None
                    else None
                ),
                "started_at": (
                    analysis.started_at.isoformat()
                    if analysis.started_at is not None
                    else None
                ),
                "completed_at": (
                    analysis.completed_at.isoformat()
                    if analysis.completed_at is not None
                    else None
                ),
                "origin": analysis.origin,
                "scientific_record_source": analysis.scientific_record_source,
                "source_analysis_version": analysis.source_analysis_version,
                "created_by_user_id": analysis.created_by_user_id,
                "created_by_tool_call_id": analysis.created_by_tool_call_id,
                "abstention_reason": analysis.abstention_reason,
                "abstention_note": analysis.abstention_note,
            }
            next_analysis_payload['diagnostics'] = [dict(item) for item in analysis.diagnostics]
            session.add(
                ObjectiveAnalysisRecord(
                    collection_id=analysis.collection_id,
                    objective_id=analysis.objective_id,
                    analysis_version=analysis.analysis_version,
                    status=analysis.status,
                    payload=next_analysis_payload,
                    created_at=analysis.created_at or now,
                    updated_at=now,
                )
            )
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
            if row.status != "queued":
                return None
            analysis = ObjectiveAnalysis(
                collection_id=row.payload.get("collection_id", ""),
                objective_id=row.payload.get("objective_id", ""),
                analysis_version=row.payload.get("analysis_version", 0),
                document_inputs=tuple(
                    (
                        PreparedDocumentInput(
                            document_id=item.get("document_id", ""),
                            preparation_fingerprint=item.get(
                                "preparation_fingerprint", ""
                            ),
                        )
                        for item in row.payload.get("document_inputs", ())
                    )
                ),
                pipeline_version=row.payload.get("pipeline_version", ""),
                model_name=row.payload.get("model_name"),
                prompt_versions={
                    str(key): str(value)
                    for key, value in dict(
                        row.payload.get("prompt_versions", {})
                    ).items()
                },
                stats=ExecutionStats(
                    duration_ms=(row.payload.get("stats") or {}).get("duration_ms"),
                    model_usage=tuple(
                        ModelUsage(
                            model_name=item["model_name"],
                            request_count=item["request_count"],
                            token_usage=(
                                TokenUsage(
                                    input_tokens=item["token_usage"]["input_tokens"],
                                    output_tokens=item["token_usage"]["output_tokens"],
                                    total_tokens=item["token_usage"]["total_tokens"],
                                )
                                if item.get("token_usage") is not None
                                else None
                            ),
                            unreported_request_count=item.get(
                                "unreported_request_count", 0
                            ),
                        )
                        for item in (row.payload.get("stats") or {}).get(
                            "model_usage", ()
                        )
                    ),
                    prompt_versions=(row.payload.get("stats") or {}).get(
                        "prompt_versions", {}
                    ),
                ),
                status=row.payload.get("status", "queued"),
                phase=row.payload.get("phase", "queued"),
                processed_document_count=row.payload.get("processed_document_count", 0),
                total_document_count=row.payload.get("total_document_count", 0),
                current_document_id=row.payload.get("current_document_id"),
                progress_message=row.payload.get("progress_message"),
                error_code=row.payload.get("error_code"),
                error_message=row.payload.get("error_message"),
                created_at=_datetime_or_none(row.payload.get("created_at")),
                started_at=_datetime_or_none(row.payload.get("started_at")),
                completed_at=_datetime_or_none(row.payload.get("completed_at")),
                diagnostics=tuple(
                    (dict(item) for item in row.payload.get("diagnostics", ()))
                ),
                origin=row.payload.get("origin", "system_generated"),
                scientific_record_source=row.payload.get(
                    "scientific_record_source",
                    (
                        "experiment_graph"
                        if row.payload.get("origin", "system_generated")
                        == "system_generated"
                        else "authored_snapshot"
                    ),
                ),
                source_analysis_version=row.payload.get("source_analysis_version"),
                created_by_user_id=row.payload.get("created_by_user_id"),
                created_by_tool_call_id=row.payload.get("created_by_tool_call_id"),
                abstention_reason=row.payload.get("abstention_reason"),
                abstention_note=row.payload.get("abstention_note"),
            )
            analysis = analysis.start(started_at=datetime.now(timezone.utc))
            row.status = analysis.status
            previous = dict(row.payload or {})
            next_analysis_payload = {
                "collection_id": analysis.collection_id,
                "objective_id": analysis.objective_id,
                "analysis_version": analysis.analysis_version,
                "document_inputs": [
                    {
                        "document_id": document_input.document_id,
                        "preparation_fingerprint": document_input.preparation_fingerprint,
                    }
                    for document_input in analysis.document_inputs
                ],
                "pipeline_version": analysis.pipeline_version,
                "model_name": analysis.model_name,
                "prompt_versions": dict(analysis.prompt_versions),
                "stats": {
                    "duration_ms": analysis.stats.duration_ms,
                    "token_usage": (
                        asdict(analysis.stats.token_usage)
                        if analysis.stats.token_usage is not None
                        else None
                    ),
                    "model_usage": [
                        asdict(item) for item in analysis.stats.model_usage
                    ],
                    "unreported_request_count": analysis.stats.unreported_request_count,
                    "prompt_versions": dict(analysis.stats.prompt_versions),
                },
                "status": analysis.status,
                "phase": analysis.phase,
                "processed_document_count": analysis.processed_document_count,
                "total_document_count": analysis.total_document_count,
                "current_document_id": analysis.current_document_id,
                "progress_message": analysis.progress_message,
                "error_code": analysis.error_code,
                "error_message": analysis.error_message,
                "created_at": (
                    analysis.created_at.isoformat()
                    if analysis.created_at is not None
                    else None
                ),
                "started_at": (
                    analysis.started_at.isoformat()
                    if analysis.started_at is not None
                    else None
                ),
                "completed_at": (
                    analysis.completed_at.isoformat()
                    if analysis.completed_at is not None
                    else None
                ),
                "origin": analysis.origin,
                "scientific_record_source": analysis.scientific_record_source,
                "source_analysis_version": analysis.source_analysis_version,
                "created_by_user_id": analysis.created_by_user_id,
                "created_by_tool_call_id": analysis.created_by_tool_call_id,
                "abstention_reason": analysis.abstention_reason,
                "abstention_note": analysis.abstention_note,
            }
            next_analysis_payload['diagnostics'] = [dict(item) for item in analysis.diagnostics]
            for key in ('paper_contributions', 'evidence_records', 'findings'):
                if key in previous:
                    next_analysis_payload[key] = previous[key]
            row.payload = next_analysis_payload
            row.updated_at = datetime.now(timezone.utc)
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
            analysis = ObjectiveAnalysis(
                collection_id=row.payload.get("collection_id", ""),
                objective_id=row.payload.get("objective_id", ""),
                analysis_version=row.payload.get("analysis_version", 0),
                document_inputs=tuple(
                    (
                        PreparedDocumentInput(
                            document_id=item.get("document_id", ""),
                            preparation_fingerprint=item.get(
                                "preparation_fingerprint", ""
                            ),
                        )
                        for item in row.payload.get("document_inputs", ())
                    )
                ),
                pipeline_version=row.payload.get("pipeline_version", ""),
                model_name=row.payload.get("model_name"),
                prompt_versions={
                    str(key): str(value)
                    for key, value in dict(
                        row.payload.get("prompt_versions", {})
                    ).items()
                },
                stats=ExecutionStats(
                    duration_ms=(row.payload.get("stats") or {}).get("duration_ms"),
                    model_usage=tuple(
                        ModelUsage(
                            model_name=item["model_name"],
                            request_count=item["request_count"],
                            token_usage=(
                                TokenUsage(
                                    input_tokens=item["token_usage"]["input_tokens"],
                                    output_tokens=item["token_usage"]["output_tokens"],
                                    total_tokens=item["token_usage"]["total_tokens"],
                                )
                                if item.get("token_usage") is not None
                                else None
                            ),
                            unreported_request_count=item.get(
                                "unreported_request_count", 0
                            ),
                        )
                        for item in (row.payload.get("stats") or {}).get(
                            "model_usage", ()
                        )
                    ),
                    prompt_versions=(row.payload.get("stats") or {}).get(
                        "prompt_versions", {}
                    ),
                ),
                status=row.payload.get("status", "queued"),
                phase=row.payload.get("phase", "queued"),
                processed_document_count=row.payload.get("processed_document_count", 0),
                total_document_count=row.payload.get("total_document_count", 0),
                current_document_id=row.payload.get("current_document_id"),
                progress_message=row.payload.get("progress_message"),
                error_code=row.payload.get("error_code"),
                error_message=row.payload.get("error_message"),
                created_at=_datetime_or_none(row.payload.get("created_at")),
                started_at=_datetime_or_none(row.payload.get("started_at")),
                completed_at=_datetime_or_none(row.payload.get("completed_at")),
                diagnostics=tuple(
                    (dict(item) for item in row.payload.get("diagnostics", ()))
                ),
                origin=row.payload.get("origin", "system_generated"),
                scientific_record_source=row.payload.get(
                    "scientific_record_source",
                    (
                        "experiment_graph"
                        if row.payload.get("origin", "system_generated")
                        == "system_generated"
                        else "authored_snapshot"
                    ),
                ),
                source_analysis_version=row.payload.get("source_analysis_version"),
                created_by_user_id=row.payload.get("created_by_user_id"),
                created_by_tool_call_id=row.payload.get("created_by_tool_call_id"),
                abstention_reason=row.payload.get("abstention_reason"),
                abstention_note=row.payload.get("abstention_note"),
            ).update_progress(
                phase=phase,
                processed_document_count=processed_document_count,
                total_document_count=total_document_count,
                current_document_id=current_document_id,
                progress_message=progress_message,
            )
            row.status = analysis.status
            previous = dict(row.payload or {})
            next_analysis_payload = {
                "collection_id": analysis.collection_id,
                "objective_id": analysis.objective_id,
                "analysis_version": analysis.analysis_version,
                "document_inputs": [
                    {
                        "document_id": document_input.document_id,
                        "preparation_fingerprint": document_input.preparation_fingerprint,
                    }
                    for document_input in analysis.document_inputs
                ],
                "pipeline_version": analysis.pipeline_version,
                "model_name": analysis.model_name,
                "prompt_versions": dict(analysis.prompt_versions),
                "stats": {
                    "duration_ms": analysis.stats.duration_ms,
                    "token_usage": (
                        asdict(analysis.stats.token_usage)
                        if analysis.stats.token_usage is not None
                        else None
                    ),
                    "model_usage": [
                        asdict(item) for item in analysis.stats.model_usage
                    ],
                    "unreported_request_count": analysis.stats.unreported_request_count,
                    "prompt_versions": dict(analysis.stats.prompt_versions),
                },
                "status": analysis.status,
                "phase": analysis.phase,
                "processed_document_count": analysis.processed_document_count,
                "total_document_count": analysis.total_document_count,
                "current_document_id": analysis.current_document_id,
                "progress_message": analysis.progress_message,
                "error_code": analysis.error_code,
                "error_message": analysis.error_message,
                "created_at": (
                    analysis.created_at.isoformat()
                    if analysis.created_at is not None
                    else None
                ),
                "started_at": (
                    analysis.started_at.isoformat()
                    if analysis.started_at is not None
                    else None
                ),
                "completed_at": (
                    analysis.completed_at.isoformat()
                    if analysis.completed_at is not None
                    else None
                ),
                "origin": analysis.origin,
                "scientific_record_source": analysis.scientific_record_source,
                "source_analysis_version": analysis.source_analysis_version,
                "created_by_user_id": analysis.created_by_user_id,
                "created_by_tool_call_id": analysis.created_by_tool_call_id,
                "abstention_reason": analysis.abstention_reason,
                "abstention_note": analysis.abstention_note,
            }
            next_analysis_payload['diagnostics'] = [dict(item) for item in analysis.diagnostics]
            for key in ('paper_contributions', 'evidence_records', 'findings'):
                if key in previous:
                    next_analysis_payload[key] = previous[key]
            row.payload = next_analysis_payload
            row.updated_at = datetime.now(timezone.utc)
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
                ObjectiveAnalysis(
                    collection_id=row.payload.get("collection_id", ""),
                    objective_id=row.payload.get("objective_id", ""),
                    analysis_version=row.payload.get("analysis_version", 0),
                    document_inputs=tuple(
                        (
                            PreparedDocumentInput(
                                document_id=item.get("document_id", ""),
                                preparation_fingerprint=item.get(
                                    "preparation_fingerprint", ""
                                ),
                            )
                            for item in row.payload.get("document_inputs", ())
                        )
                    ),
                    pipeline_version=row.payload.get("pipeline_version", ""),
                    model_name=row.payload.get("model_name"),
                    prompt_versions={
                        str(key): str(value)
                        for key, value in dict(
                            row.payload.get("prompt_versions", {})
                        ).items()
                    },
                    stats=ExecutionStats(
                        duration_ms=(row.payload.get("stats") or {}).get("duration_ms"),
                        model_usage=tuple(
                            ModelUsage(
                                model_name=item["model_name"],
                                request_count=item["request_count"],
                                token_usage=(
                                    TokenUsage(
                                        input_tokens=item["token_usage"][
                                            "input_tokens"
                                        ],
                                        output_tokens=item["token_usage"][
                                            "output_tokens"
                                        ],
                                        total_tokens=item["token_usage"][
                                            "total_tokens"
                                        ],
                                    )
                                    if item.get("token_usage") is not None
                                    else None
                                ),
                                unreported_request_count=item.get(
                                    "unreported_request_count", 0
                                ),
                            )
                            for item in (row.payload.get("stats") or {}).get(
                                "model_usage", ()
                            )
                        ),
                        prompt_versions=(row.payload.get("stats") or {}).get(
                            "prompt_versions", {}
                        ),
                    ),
                    status=row.payload.get("status", "queued"),
                    phase=row.payload.get("phase", "queued"),
                    processed_document_count=row.payload.get(
                        "processed_document_count", 0
                    ),
                    total_document_count=row.payload.get("total_document_count", 0),
                    current_document_id=row.payload.get("current_document_id"),
                    progress_message=row.payload.get("progress_message"),
                    error_code=row.payload.get("error_code"),
                    error_message=row.payload.get("error_message"),
                    created_at=_datetime_or_none(row.payload.get("created_at")),
                    started_at=_datetime_or_none(row.payload.get("started_at")),
                    completed_at=_datetime_or_none(row.payload.get("completed_at")),
                    diagnostics=tuple(
                        (dict(item) for item in row.payload.get("diagnostics", ()))
                    ),
                    origin=row.payload.get("origin", "system_generated"),
                    scientific_record_source=row.payload.get(
                        "scientific_record_source",
                        (
                            "experiment_graph"
                            if row.payload.get("origin", "system_generated")
                            == "system_generated"
                            else "authored_snapshot"
                        ),
                    ),
                    source_analysis_version=row.payload.get("source_analysis_version"),
                    created_by_user_id=row.payload.get("created_by_user_id"),
                    created_by_tool_call_id=row.payload.get("created_by_tool_call_id"),
                    abstention_reason=row.payload.get("abstention_reason"),
                    abstention_note=row.payload.get("abstention_note"),
                ),
                stats=stats,
                model_name=model_name,
                prompt_versions=dict(prompt_versions),
                diagnostics=diagnostics,
            )
            row.status = analysis.status
            previous = dict(row.payload or {})
            next_analysis_payload = {
                "collection_id": analysis.collection_id,
                "objective_id": analysis.objective_id,
                "analysis_version": analysis.analysis_version,
                "document_inputs": [
                    {
                        "document_id": document_input.document_id,
                        "preparation_fingerprint": document_input.preparation_fingerprint,
                    }
                    for document_input in analysis.document_inputs
                ],
                "pipeline_version": analysis.pipeline_version,
                "model_name": analysis.model_name,
                "prompt_versions": dict(analysis.prompt_versions),
                "stats": {
                    "duration_ms": analysis.stats.duration_ms,
                    "token_usage": (
                        asdict(analysis.stats.token_usage)
                        if analysis.stats.token_usage is not None
                        else None
                    ),
                    "model_usage": [
                        asdict(item) for item in analysis.stats.model_usage
                    ],
                    "unreported_request_count": analysis.stats.unreported_request_count,
                    "prompt_versions": dict(analysis.stats.prompt_versions),
                },
                "status": analysis.status,
                "phase": analysis.phase,
                "processed_document_count": analysis.processed_document_count,
                "total_document_count": analysis.total_document_count,
                "current_document_id": analysis.current_document_id,
                "progress_message": analysis.progress_message,
                "error_code": analysis.error_code,
                "error_message": analysis.error_message,
                "created_at": (
                    analysis.created_at.isoformat()
                    if analysis.created_at is not None
                    else None
                ),
                "started_at": (
                    analysis.started_at.isoformat()
                    if analysis.started_at is not None
                    else None
                ),
                "completed_at": (
                    analysis.completed_at.isoformat()
                    if analysis.completed_at is not None
                    else None
                ),
                "origin": analysis.origin,
                "scientific_record_source": analysis.scientific_record_source,
                "source_analysis_version": analysis.source_analysis_version,
                "created_by_user_id": analysis.created_by_user_id,
                "created_by_tool_call_id": analysis.created_by_tool_call_id,
                "abstention_reason": analysis.abstention_reason,
                "abstention_note": analysis.abstention_note,
            }
            next_analysis_payload['diagnostics'] = [dict(item) for item in analysis.diagnostics]
            for key in ('paper_contributions', 'evidence_records', 'findings'):
                if key in previous:
                    next_analysis_payload[key] = previous[key]
            row.payload = next_analysis_payload
            row.updated_at = datetime.now(timezone.utc)
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
            analysis = ObjectiveAnalysis(
                collection_id=row.payload.get("collection_id", ""),
                objective_id=row.payload.get("objective_id", ""),
                analysis_version=row.payload.get("analysis_version", 0),
                document_inputs=tuple(
                    (
                        PreparedDocumentInput(
                            document_id=item.get("document_id", ""),
                            preparation_fingerprint=item.get(
                                "preparation_fingerprint", ""
                            ),
                        )
                        for item in row.payload.get("document_inputs", ())
                    )
                ),
                pipeline_version=row.payload.get("pipeline_version", ""),
                model_name=row.payload.get("model_name"),
                prompt_versions={
                    str(key): str(value)
                    for key, value in dict(
                        row.payload.get("prompt_versions", {})
                    ).items()
                },
                stats=ExecutionStats(
                    duration_ms=(row.payload.get("stats") or {}).get("duration_ms"),
                    model_usage=tuple(
                        ModelUsage(
                            model_name=item["model_name"],
                            request_count=item["request_count"],
                            token_usage=(
                                TokenUsage(
                                    input_tokens=item["token_usage"]["input_tokens"],
                                    output_tokens=item["token_usage"]["output_tokens"],
                                    total_tokens=item["token_usage"]["total_tokens"],
                                )
                                if item.get("token_usage") is not None
                                else None
                            ),
                            unreported_request_count=item.get(
                                "unreported_request_count", 0
                            ),
                        )
                        for item in (row.payload.get("stats") or {}).get(
                            "model_usage", ()
                        )
                    ),
                    prompt_versions=(row.payload.get("stats") or {}).get(
                        "prompt_versions", {}
                    ),
                ),
                status=row.payload.get("status", "queued"),
                phase=row.payload.get("phase", "queued"),
                processed_document_count=row.payload.get("processed_document_count", 0),
                total_document_count=row.payload.get("total_document_count", 0),
                current_document_id=row.payload.get("current_document_id"),
                progress_message=row.payload.get("progress_message"),
                error_code=row.payload.get("error_code"),
                error_message=row.payload.get("error_message"),
                created_at=_datetime_or_none(row.payload.get("created_at")),
                started_at=_datetime_or_none(row.payload.get("started_at")),
                completed_at=_datetime_or_none(row.payload.get("completed_at")),
                diagnostics=tuple(
                    (dict(item) for item in row.payload.get("diagnostics", ()))
                ),
                origin=row.payload.get("origin", "system_generated"),
                scientific_record_source=row.payload.get(
                    "scientific_record_source",
                    (
                        "experiment_graph"
                        if row.payload.get("origin", "system_generated")
                        == "system_generated"
                        else "authored_snapshot"
                    ),
                ),
                source_analysis_version=row.payload.get("source_analysis_version"),
                created_by_user_id=row.payload.get("created_by_user_id"),
                created_by_tool_call_id=row.payload.get("created_by_tool_call_id"),
                abstention_reason=row.payload.get("abstention_reason"),
                abstention_note=row.payload.get("abstention_note"),
            )
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
            row.status = analysis.status
            previous = dict(row.payload or {})
            next_analysis_payload = {
                "collection_id": analysis.collection_id,
                "objective_id": analysis.objective_id,
                "analysis_version": analysis.analysis_version,
                "document_inputs": [
                    {
                        "document_id": document_input.document_id,
                        "preparation_fingerprint": document_input.preparation_fingerprint,
                    }
                    for document_input in analysis.document_inputs
                ],
                "pipeline_version": analysis.pipeline_version,
                "model_name": analysis.model_name,
                "prompt_versions": dict(analysis.prompt_versions),
                "stats": {
                    "duration_ms": analysis.stats.duration_ms,
                    "token_usage": (
                        asdict(analysis.stats.token_usage)
                        if analysis.stats.token_usage is not None
                        else None
                    ),
                    "model_usage": [
                        asdict(item) for item in analysis.stats.model_usage
                    ],
                    "unreported_request_count": analysis.stats.unreported_request_count,
                    "prompt_versions": dict(analysis.stats.prompt_versions),
                },
                "status": analysis.status,
                "phase": analysis.phase,
                "processed_document_count": analysis.processed_document_count,
                "total_document_count": analysis.total_document_count,
                "current_document_id": analysis.current_document_id,
                "progress_message": analysis.progress_message,
                "error_code": analysis.error_code,
                "error_message": analysis.error_message,
                "created_at": (
                    analysis.created_at.isoformat()
                    if analysis.created_at is not None
                    else None
                ),
                "started_at": (
                    analysis.started_at.isoformat()
                    if analysis.started_at is not None
                    else None
                ),
                "completed_at": (
                    analysis.completed_at.isoformat()
                    if analysis.completed_at is not None
                    else None
                ),
                "origin": analysis.origin,
                "scientific_record_source": analysis.scientific_record_source,
                "source_analysis_version": analysis.source_analysis_version,
                "created_by_user_id": analysis.created_by_user_id,
                "created_by_tool_call_id": analysis.created_by_tool_call_id,
                "abstention_reason": analysis.abstention_reason,
                "abstention_note": analysis.abstention_note,
            }
            next_analysis_payload['diagnostics'] = [dict(item) for item in analysis.diagnostics]
            for key in ('paper_contributions', 'evidence_records', 'findings'):
                if key in previous:
                    next_analysis_payload[key] = previous[key]
            row.payload = next_analysis_payload
            row.updated_at = datetime.now(timezone.utc)
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
                analysis = ObjectiveAnalysis(
                    collection_id=row.payload.get("collection_id", ""),
                    objective_id=row.payload.get("objective_id", ""),
                    analysis_version=row.payload.get("analysis_version", 0),
                    document_inputs=tuple(
                        (
                            PreparedDocumentInput(
                                document_id=item.get("document_id", ""),
                                preparation_fingerprint=item.get(
                                    "preparation_fingerprint", ""
                                ),
                            )
                            for item in row.payload.get("document_inputs", ())
                        )
                    ),
                    pipeline_version=row.payload.get("pipeline_version", ""),
                    model_name=row.payload.get("model_name"),
                    prompt_versions={
                        str(key): str(value)
                        for key, value in dict(
                            row.payload.get("prompt_versions", {})
                        ).items()
                    },
                    stats=ExecutionStats(
                        duration_ms=(row.payload.get("stats") or {}).get("duration_ms"),
                        model_usage=tuple(
                            ModelUsage(
                                model_name=item["model_name"],
                                request_count=item["request_count"],
                                token_usage=(
                                    TokenUsage(
                                        input_tokens=item["token_usage"][
                                            "input_tokens"
                                        ],
                                        output_tokens=item["token_usage"][
                                            "output_tokens"
                                        ],
                                        total_tokens=item["token_usage"][
                                            "total_tokens"
                                        ],
                                    )
                                    if item.get("token_usage") is not None
                                    else None
                                ),
                                unreported_request_count=item.get(
                                    "unreported_request_count", 0
                                ),
                            )
                            for item in (row.payload.get("stats") or {}).get(
                                "model_usage", ()
                            )
                        ),
                        prompt_versions=(row.payload.get("stats") or {}).get(
                            "prompt_versions", {}
                        ),
                    ),
                    status=row.payload.get("status", "queued"),
                    phase=row.payload.get("phase", "queued"),
                    processed_document_count=row.payload.get(
                        "processed_document_count", 0
                    ),
                    total_document_count=row.payload.get("total_document_count", 0),
                    current_document_id=row.payload.get("current_document_id"),
                    progress_message=row.payload.get("progress_message"),
                    error_code=row.payload.get("error_code"),
                    error_message=row.payload.get("error_message"),
                    created_at=_datetime_or_none(row.payload.get("created_at")),
                    started_at=_datetime_or_none(row.payload.get("started_at")),
                    completed_at=_datetime_or_none(row.payload.get("completed_at")),
                    diagnostics=tuple(
                        (dict(item) for item in row.payload.get("diagnostics", ()))
                    ),
                    origin=row.payload.get("origin", "system_generated"),
                    scientific_record_source=row.payload.get(
                        "scientific_record_source",
                        (
                            "experiment_graph"
                            if row.payload.get("origin", "system_generated")
                            == "system_generated"
                            else "authored_snapshot"
                        ),
                    ),
                    source_analysis_version=row.payload.get("source_analysis_version"),
                    created_by_user_id=row.payload.get("created_by_user_id"),
                    created_by_tool_call_id=row.payload.get("created_by_tool_call_id"),
                    abstention_reason=row.payload.get("abstention_reason"),
                    abstention_note=row.payload.get("abstention_note"),
                ).fail(
                    error_code="analysis_interrupted",
                    error_message=(
                        "Objective analysis was interrupted by a backend restart. "
                        "Retry the analysis."
                    ),
                    completed_at=now,
                )
                row.status = analysis.status
                previous = dict(row.payload or {})
                next_analysis_payload = {
                    "collection_id": analysis.collection_id,
                    "objective_id": analysis.objective_id,
                    "analysis_version": analysis.analysis_version,
                    "document_inputs": [
                        {
                            "document_id": document_input.document_id,
                            "preparation_fingerprint": document_input.preparation_fingerprint,
                        }
                        for document_input in analysis.document_inputs
                    ],
                    "pipeline_version": analysis.pipeline_version,
                    "model_name": analysis.model_name,
                    "prompt_versions": dict(analysis.prompt_versions),
                    "stats": {
                        "duration_ms": analysis.stats.duration_ms,
                        "token_usage": (
                            asdict(analysis.stats.token_usage)
                            if analysis.stats.token_usage is not None
                            else None
                        ),
                        "model_usage": [
                            asdict(item) for item in analysis.stats.model_usage
                        ],
                        "unreported_request_count": analysis.stats.unreported_request_count,
                        "prompt_versions": dict(analysis.stats.prompt_versions),
                    },
                    "status": analysis.status,
                    "phase": analysis.phase,
                    "processed_document_count": analysis.processed_document_count,
                    "total_document_count": analysis.total_document_count,
                    "current_document_id": analysis.current_document_id,
                    "progress_message": analysis.progress_message,
                    "error_code": analysis.error_code,
                    "error_message": analysis.error_message,
                    "created_at": (
                        analysis.created_at.isoformat()
                        if analysis.created_at is not None
                        else None
                    ),
                    "started_at": (
                        analysis.started_at.isoformat()
                        if analysis.started_at is not None
                        else None
                    ),
                    "completed_at": (
                        analysis.completed_at.isoformat()
                        if analysis.completed_at is not None
                        else None
                    ),
                    "origin": analysis.origin,
                    "scientific_record_source": analysis.scientific_record_source,
                    "source_analysis_version": analysis.source_analysis_version,
                    "created_by_user_id": analysis.created_by_user_id,
                    "created_by_tool_call_id": analysis.created_by_tool_call_id,
                    "abstention_reason": analysis.abstention_reason,
                    "abstention_note": analysis.abstention_note,
                }
                next_analysis_payload['diagnostics'] = [dict(item) for item in analysis.diagnostics]
                for key in ('paper_contributions', 'evidence_records', 'findings'):
                    if key in previous:
                        next_analysis_payload[key] = previous[key]
                row.payload = next_analysis_payload
                row.updated_at = datetime.now(timezone.utc)
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
            analysis = ObjectiveAnalysis(
                collection_id=analysis_row.payload.get("collection_id", ""),
                objective_id=analysis_row.payload.get("objective_id", ""),
                analysis_version=analysis_row.payload.get("analysis_version", 0),
                document_inputs=tuple(
                    (
                        PreparedDocumentInput(
                            document_id=item.get("document_id", ""),
                            preparation_fingerprint=item.get(
                                "preparation_fingerprint", ""
                            ),
                        )
                        for item in analysis_row.payload.get("document_inputs", ())
                    )
                ),
                pipeline_version=analysis_row.payload.get("pipeline_version", ""),
                model_name=analysis_row.payload.get("model_name"),
                prompt_versions={
                    str(key): str(value)
                    for key, value in dict(
                        analysis_row.payload.get("prompt_versions", {})
                    ).items()
                },
                stats=ExecutionStats(
                    duration_ms=(analysis_row.payload.get("stats") or {}).get(
                        "duration_ms"
                    ),
                    model_usage=tuple(
                        ModelUsage(
                            model_name=item["model_name"],
                            request_count=item["request_count"],
                            token_usage=(
                                TokenUsage(
                                    input_tokens=item["token_usage"]["input_tokens"],
                                    output_tokens=item["token_usage"]["output_tokens"],
                                    total_tokens=item["token_usage"]["total_tokens"],
                                )
                                if item.get("token_usage") is not None
                                else None
                            ),
                            unreported_request_count=item.get(
                                "unreported_request_count", 0
                            ),
                        )
                        for item in (analysis_row.payload.get("stats") or {}).get(
                            "model_usage", ()
                        )
                    ),
                    prompt_versions=(analysis_row.payload.get("stats") or {}).get(
                        "prompt_versions", {}
                    ),
                ),
                status=analysis_row.payload.get("status", "queued"),
                phase=analysis_row.payload.get("phase", "queued"),
                processed_document_count=analysis_row.payload.get(
                    "processed_document_count", 0
                ),
                total_document_count=analysis_row.payload.get(
                    "total_document_count", 0
                ),
                current_document_id=analysis_row.payload.get("current_document_id"),
                progress_message=analysis_row.payload.get("progress_message"),
                error_code=analysis_row.payload.get("error_code"),
                error_message=analysis_row.payload.get("error_message"),
                created_at=_datetime_or_none(analysis_row.payload.get("created_at")),
                started_at=_datetime_or_none(analysis_row.payload.get("started_at")),
                completed_at=_datetime_or_none(
                    analysis_row.payload.get("completed_at")
                ),
                diagnostics=tuple(
                    (dict(item) for item in analysis_row.payload.get("diagnostics", ()))
                ),
                origin=analysis_row.payload.get("origin", "system_generated"),
                scientific_record_source=analysis_row.payload.get(
                    "scientific_record_source",
                    (
                        "experiment_graph"
                        if analysis_row.payload.get("origin", "system_generated")
                        == "system_generated"
                        else "authored_snapshot"
                    ),
                ),
                source_analysis_version=analysis_row.payload.get(
                    "source_analysis_version"
                ),
                created_by_user_id=analysis_row.payload.get("created_by_user_id"),
                created_by_tool_call_id=analysis_row.payload.get(
                    "created_by_tool_call_id"
                ),
                abstention_reason=analysis_row.payload.get("abstention_reason"),
                abstention_note=analysis_row.payload.get("abstention_note"),
            )
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
            objective = ResearchObjective(
                collection_id=objective_row.collection_id,
                objective_id=objective_row.objective_id,
                question=objective_row.payload.get("question", ""),
                material_scope=tuple(objective_row.payload.get("material_scope", ())),
                variables=tuple(objective_row.payload.get("variables", ())),
                outcomes=tuple(objective_row.payload.get("outcomes", ())),
                mechanisms=tuple(objective_row.payload.get("mechanisms", ())),
                constraints=tuple(objective_row.payload.get("constraints", ())),
                requested_comparator=objective_row.payload.get("requested_comparator"),
                seed_document_ids=tuple(
                    objective_row.payload.get("seed_document_ids", ())
                ),
                excluded_document_ids=tuple(
                    objective_row.payload.get("excluded_document_ids", ())
                ),
                confidence=objective_row.payload.get("confidence", 0.0),
                reason=objective_row.payload.get("reason"),
                source_relationship_ids=tuple(
                    objective_row.payload.get("source_relationship_ids", ())
                ),
                parent_objective_id=objective_row.payload.get("parent_objective_id"),
                parent_analysis_version=objective_row.payload.get(
                    "parent_analysis_version"
                ),
                derivation_basis=_objective_derivation_basis(
                    objective_row.payload.get("derivation_basis")
                ),
                rank=objective_row.payload.get("rank"),
                confirmation_status=objective_row.payload.get(
                    "confirmation_status", "candidate"
                ),
                active_analysis_version=objective_row.payload.get(
                    "active_analysis_version"
                ),
                published_analysis_version=objective_row.payload.get(
                    "published_analysis_version"
                ),
                origin=objective_row.payload.get("origin", "system_discovered"),
                created_by_user_id=objective_row.payload.get("created_by_user_id"),
                created_by_tool_call_id=objective_row.payload.get(
                    "created_by_tool_call_id"
                ),
            ).publish_analysis(
                collection_id=analysis.collection_id,
                objective_id=analysis.objective_id,
                analysis_version=analysis.analysis_version,
                status=analysis.status,
            )
            analysis_row.status = analysis.status
            previous = dict(analysis_row.payload or {})
            next_analysis_payload = {
                "collection_id": analysis.collection_id,
                "objective_id": analysis.objective_id,
                "analysis_version": analysis.analysis_version,
                "document_inputs": [
                    {
                        "document_id": document_input.document_id,
                        "preparation_fingerprint": document_input.preparation_fingerprint,
                    }
                    for document_input in analysis.document_inputs
                ],
                "pipeline_version": analysis.pipeline_version,
                "model_name": analysis.model_name,
                "prompt_versions": dict(analysis.prompt_versions),
                "stats": {
                    "duration_ms": analysis.stats.duration_ms,
                    "token_usage": (
                        asdict(analysis.stats.token_usage)
                        if analysis.stats.token_usage is not None
                        else None
                    ),
                    "model_usage": [
                        asdict(item) for item in analysis.stats.model_usage
                    ],
                    "unreported_request_count": analysis.stats.unreported_request_count,
                    "prompt_versions": dict(analysis.stats.prompt_versions),
                },
                "status": analysis.status,
                "phase": analysis.phase,
                "processed_document_count": analysis.processed_document_count,
                "total_document_count": analysis.total_document_count,
                "current_document_id": analysis.current_document_id,
                "progress_message": analysis.progress_message,
                "error_code": analysis.error_code,
                "error_message": analysis.error_message,
                "created_at": (
                    analysis.created_at.isoformat()
                    if analysis.created_at is not None
                    else None
                ),
                "started_at": (
                    analysis.started_at.isoformat()
                    if analysis.started_at is not None
                    else None
                ),
                "completed_at": (
                    analysis.completed_at.isoformat()
                    if analysis.completed_at is not None
                    else None
                ),
                "origin": analysis.origin,
                "scientific_record_source": analysis.scientific_record_source,
                "source_analysis_version": analysis.source_analysis_version,
                "created_by_user_id": analysis.created_by_user_id,
                "created_by_tool_call_id": analysis.created_by_tool_call_id,
                "abstention_reason": analysis.abstention_reason,
                "abstention_note": analysis.abstention_note,
            }
            next_analysis_payload['diagnostics'] = [dict(item) for item in analysis.diagnostics]
            for key in ('paper_contributions', 'evidence_records', 'findings'):
                if key in previous:
                    next_analysis_payload[key] = previous[key]
            analysis_row.payload = next_analysis_payload
            analysis_row.updated_at = datetime.now(timezone.utc)
            objective_row.rank = objective.rank or objective_row.rank
            objective_row.origin = objective.origin
            objective_row.created_by_tool_call_id = objective.created_by_tool_call_id
            objective_row.payload = {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in asdict(objective).items()
            }
            objective_row.updated_at = datetime.now(timezone.utc)
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
            analysis = ObjectiveAnalysis(
                collection_id=analysis_row.payload.get("collection_id", ""),
                objective_id=analysis_row.payload.get("objective_id", ""),
                analysis_version=analysis_row.payload.get("analysis_version", 0),
                document_inputs=tuple(
                    (
                        PreparedDocumentInput(
                            document_id=item.get("document_id", ""),
                            preparation_fingerprint=item.get(
                                "preparation_fingerprint", ""
                            ),
                        )
                        for item in analysis_row.payload.get("document_inputs", ())
                    )
                ),
                pipeline_version=analysis_row.payload.get("pipeline_version", ""),
                model_name=analysis_row.payload.get("model_name"),
                prompt_versions={
                    str(key): str(value)
                    for key, value in dict(
                        analysis_row.payload.get("prompt_versions", {})
                    ).items()
                },
                stats=ExecutionStats(
                    duration_ms=(analysis_row.payload.get("stats") or {}).get(
                        "duration_ms"
                    ),
                    model_usage=tuple(
                        ModelUsage(
                            model_name=item["model_name"],
                            request_count=item["request_count"],
                            token_usage=(
                                TokenUsage(
                                    input_tokens=item["token_usage"]["input_tokens"],
                                    output_tokens=item["token_usage"]["output_tokens"],
                                    total_tokens=item["token_usage"]["total_tokens"],
                                )
                                if item.get("token_usage") is not None
                                else None
                            ),
                            unreported_request_count=item.get(
                                "unreported_request_count", 0
                            ),
                        )
                        for item in (analysis_row.payload.get("stats") or {}).get(
                            "model_usage", ()
                        )
                    ),
                    prompt_versions=(analysis_row.payload.get("stats") or {}).get(
                        "prompt_versions", {}
                    ),
                ),
                status=analysis_row.payload.get("status", "queued"),
                phase=analysis_row.payload.get("phase", "queued"),
                processed_document_count=analysis_row.payload.get(
                    "processed_document_count", 0
                ),
                total_document_count=analysis_row.payload.get(
                    "total_document_count", 0
                ),
                current_document_id=analysis_row.payload.get("current_document_id"),
                progress_message=analysis_row.payload.get("progress_message"),
                error_code=analysis_row.payload.get("error_code"),
                error_message=analysis_row.payload.get("error_message"),
                created_at=_datetime_or_none(analysis_row.payload.get("created_at")),
                started_at=_datetime_or_none(analysis_row.payload.get("started_at")),
                completed_at=_datetime_or_none(
                    analysis_row.payload.get("completed_at")
                ),
                diagnostics=tuple(
                    (dict(item) for item in analysis_row.payload.get("diagnostics", ()))
                ),
                origin=analysis_row.payload.get("origin", "system_generated"),
                scientific_record_source=analysis_row.payload.get(
                    "scientific_record_source",
                    (
                        "experiment_graph"
                        if analysis_row.payload.get("origin", "system_generated")
                        == "system_generated"
                        else "authored_snapshot"
                    ),
                ),
                source_analysis_version=analysis_row.payload.get(
                    "source_analysis_version"
                ),
                created_by_user_id=analysis_row.payload.get("created_by_user_id"),
                created_by_tool_call_id=analysis_row.payload.get(
                    "created_by_tool_call_id"
                ),
                abstention_reason=analysis_row.payload.get("abstention_reason"),
                abstention_note=analysis_row.payload.get("abstention_note"),
            )
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
            objective = ResearchObjective(
                collection_id=objective_row.collection_id,
                objective_id=objective_row.objective_id,
                question=objective_row.payload.get("question", ""),
                material_scope=tuple(objective_row.payload.get("material_scope", ())),
                variables=tuple(objective_row.payload.get("variables", ())),
                outcomes=tuple(objective_row.payload.get("outcomes", ())),
                mechanisms=tuple(objective_row.payload.get("mechanisms", ())),
                constraints=tuple(objective_row.payload.get("constraints", ())),
                requested_comparator=objective_row.payload.get("requested_comparator"),
                seed_document_ids=tuple(
                    objective_row.payload.get("seed_document_ids", ())
                ),
                excluded_document_ids=tuple(
                    objective_row.payload.get("excluded_document_ids", ())
                ),
                confidence=objective_row.payload.get("confidence", 0.0),
                reason=objective_row.payload.get("reason"),
                source_relationship_ids=tuple(
                    objective_row.payload.get("source_relationship_ids", ())
                ),
                parent_objective_id=objective_row.payload.get("parent_objective_id"),
                parent_analysis_version=objective_row.payload.get(
                    "parent_analysis_version"
                ),
                derivation_basis=_objective_derivation_basis(
                    objective_row.payload.get("derivation_basis")
                ),
                rank=objective_row.payload.get("rank"),
                confirmation_status=objective_row.payload.get(
                    "confirmation_status", "candidate"
                ),
                active_analysis_version=objective_row.payload.get(
                    "active_analysis_version"
                ),
                published_analysis_version=objective_row.payload.get(
                    "published_analysis_version"
                ),
                origin=objective_row.payload.get("origin", "system_discovered"),
                created_by_user_id=objective_row.payload.get("created_by_user_id"),
                created_by_tool_call_id=objective_row.payload.get(
                    "created_by_tool_call_id"
                ),
            ).publish_analysis(
                collection_id=analysis.collection_id,
                objective_id=analysis.objective_id,
                analysis_version=analysis.analysis_version,
                status=analysis.status,
            )
            analysis_row.status = analysis.status
            previous = dict(analysis_row.payload or {})
            next_analysis_payload = {
                "collection_id": analysis.collection_id,
                "objective_id": analysis.objective_id,
                "analysis_version": analysis.analysis_version,
                "document_inputs": [
                    {
                        "document_id": document_input.document_id,
                        "preparation_fingerprint": document_input.preparation_fingerprint,
                    }
                    for document_input in analysis.document_inputs
                ],
                "pipeline_version": analysis.pipeline_version,
                "model_name": analysis.model_name,
                "prompt_versions": dict(analysis.prompt_versions),
                "stats": {
                    "duration_ms": analysis.stats.duration_ms,
                    "token_usage": (
                        asdict(analysis.stats.token_usage)
                        if analysis.stats.token_usage is not None
                        else None
                    ),
                    "model_usage": [
                        asdict(item) for item in analysis.stats.model_usage
                    ],
                    "unreported_request_count": analysis.stats.unreported_request_count,
                    "prompt_versions": dict(analysis.stats.prompt_versions),
                },
                "status": analysis.status,
                "phase": analysis.phase,
                "processed_document_count": analysis.processed_document_count,
                "total_document_count": analysis.total_document_count,
                "current_document_id": analysis.current_document_id,
                "progress_message": analysis.progress_message,
                "error_code": analysis.error_code,
                "error_message": analysis.error_message,
                "created_at": (
                    analysis.created_at.isoformat()
                    if analysis.created_at is not None
                    else None
                ),
                "started_at": (
                    analysis.started_at.isoformat()
                    if analysis.started_at is not None
                    else None
                ),
                "completed_at": (
                    analysis.completed_at.isoformat()
                    if analysis.completed_at is not None
                    else None
                ),
                "origin": analysis.origin,
                "scientific_record_source": analysis.scientific_record_source,
                "source_analysis_version": analysis.source_analysis_version,
                "created_by_user_id": analysis.created_by_user_id,
                "created_by_tool_call_id": analysis.created_by_tool_call_id,
                "abstention_reason": analysis.abstention_reason,
                "abstention_note": analysis.abstention_note,
            }
            next_analysis_payload['diagnostics'] = [dict(item) for item in analysis.diagnostics]
            for key in ('paper_contributions', 'evidence_records', 'findings'):
                if key in previous:
                    next_analysis_payload[key] = previous[key]
            analysis_row.payload = next_analysis_payload
            analysis_row.updated_at = datetime.now(timezone.utc)
            objective_row.rank = objective.rank or objective_row.rank
            objective_row.origin = objective.origin
            objective_row.created_by_tool_call_id = objective.created_by_tool_call_id
            objective_row.payload = {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in asdict(objective).items()
            }
            objective_row.updated_at = datetime.now(timezone.utc)
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
            objective = ResearchObjective(
                collection_id=objective_row.collection_id,
                objective_id=objective_row.objective_id,
                question=objective_row.payload.get("question", ""),
                material_scope=tuple(objective_row.payload.get("material_scope", ())),
                variables=tuple(objective_row.payload.get("variables", ())),
                outcomes=tuple(objective_row.payload.get("outcomes", ())),
                mechanisms=tuple(objective_row.payload.get("mechanisms", ())),
                constraints=tuple(objective_row.payload.get("constraints", ())),
                requested_comparator=objective_row.payload.get("requested_comparator"),
                seed_document_ids=tuple(
                    objective_row.payload.get("seed_document_ids", ())
                ),
                excluded_document_ids=tuple(
                    objective_row.payload.get("excluded_document_ids", ())
                ),
                confidence=objective_row.payload.get("confidence", 0.0),
                reason=objective_row.payload.get("reason"),
                source_relationship_ids=tuple(
                    objective_row.payload.get("source_relationship_ids", ())
                ),
                parent_objective_id=objective_row.payload.get("parent_objective_id"),
                parent_analysis_version=objective_row.payload.get(
                    "parent_analysis_version"
                ),
                derivation_basis=_objective_derivation_basis(
                    objective_row.payload.get("derivation_basis")
                ),
                rank=objective_row.payload.get("rank"),
                confirmation_status=objective_row.payload.get(
                    "confirmation_status", "candidate"
                ),
                active_analysis_version=objective_row.payload.get(
                    "active_analysis_version"
                ),
                published_analysis_version=objective_row.payload.get(
                    "published_analysis_version"
                ),
                origin=objective_row.payload.get("origin", "system_discovered"),
                created_by_user_id=objective_row.payload.get("created_by_user_id"),
                created_by_tool_call_id=objective_row.payload.get(
                    "created_by_tool_call_id"
                ),
            )
            if objective.published_analysis_version != source_analysis_version:
                raise ValueError("source analysis version is stale")
            source_row = await self._locked_analysis(
                session, collection_id, objective_id, source_analysis_version
            )
            active_version = (
                objective.active_analysis_version or source_analysis_version
            )
            if active_version != source_analysis_version:
                active_row = await self._locked_analysis(
                    session, collection_id, objective_id, active_version
                )
                if active_row.status in {"queued", "running"}:
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
            if source_row.status != "succeeded":
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
            next_analysis_payload = {
                "collection_id": analysis.collection_id,
                "objective_id": analysis.objective_id,
                "analysis_version": analysis.analysis_version,
                "document_inputs": [
                    {
                        "document_id": document_input.document_id,
                        "preparation_fingerprint": document_input.preparation_fingerprint,
                    }
                    for document_input in analysis.document_inputs
                ],
                "pipeline_version": analysis.pipeline_version,
                "model_name": analysis.model_name,
                "prompt_versions": dict(analysis.prompt_versions),
                "stats": {
                    "duration_ms": analysis.stats.duration_ms,
                    "token_usage": (
                        asdict(analysis.stats.token_usage)
                        if analysis.stats.token_usage is not None
                        else None
                    ),
                    "model_usage": [
                        asdict(item) for item in analysis.stats.model_usage
                    ],
                    "unreported_request_count": analysis.stats.unreported_request_count,
                    "prompt_versions": dict(analysis.stats.prompt_versions),
                },
                "status": analysis.status,
                "phase": analysis.phase,
                "processed_document_count": analysis.processed_document_count,
                "total_document_count": analysis.total_document_count,
                "current_document_id": analysis.current_document_id,
                "progress_message": analysis.progress_message,
                "error_code": analysis.error_code,
                "error_message": analysis.error_message,
                "created_at": (
                    analysis.created_at.isoformat()
                    if analysis.created_at is not None
                    else None
                ),
                "started_at": (
                    analysis.started_at.isoformat()
                    if analysis.started_at is not None
                    else None
                ),
                "completed_at": (
                    analysis.completed_at.isoformat()
                    if analysis.completed_at is not None
                    else None
                ),
                "origin": analysis.origin,
                "scientific_record_source": analysis.scientific_record_source,
                "source_analysis_version": analysis.source_analysis_version,
                "created_by_user_id": analysis.created_by_user_id,
                "created_by_tool_call_id": analysis.created_by_tool_call_id,
                "abstention_reason": analysis.abstention_reason,
                "abstention_note": analysis.abstention_note,
            }
            next_analysis_payload['diagnostics'] = [dict(item) for item in analysis.diagnostics]
            analysis_row = ObjectiveAnalysisRecord(
                collection_id=analysis.collection_id,
                objective_id=analysis.objective_id,
                analysis_version=analysis.analysis_version,
                status=analysis.status,
                payload=next_analysis_payload,
                created_at=analysis.created_at or now,
                updated_at=now,
            )
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
            objective_row.rank = objective.rank or objective_row.rank
            objective_row.origin = objective.origin
            objective_row.created_by_tool_call_id = objective.created_by_tool_call_id
            objective_row.payload = {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in asdict(objective).items()
            }
            objective_row.updated_at = now
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
                analysis_version = objective_row.payload.get('active_analysis_version')
            if analysis_version is None:
                return None
            row = await session.get(
                ObjectiveAnalysisRecord,
                (collection_id, objective_id, analysis_version),
            )
            return (
                ObjectiveAnalysis(
                    collection_id=row.payload.get("collection_id", ""),
                    objective_id=row.payload.get("objective_id", ""),
                    analysis_version=row.payload.get("analysis_version", 0),
                    document_inputs=tuple(
                        (
                            PreparedDocumentInput(
                                document_id=item.get("document_id", ""),
                                preparation_fingerprint=item.get(
                                    "preparation_fingerprint", ""
                                ),
                            )
                            for item in row.payload.get("document_inputs", ())
                        )
                    ),
                    pipeline_version=row.payload.get("pipeline_version", ""),
                    model_name=row.payload.get("model_name"),
                    prompt_versions={
                        str(key): str(value)
                        for key, value in dict(
                            row.payload.get("prompt_versions", {})
                        ).items()
                    },
                    stats=ExecutionStats(
                        duration_ms=(row.payload.get("stats") or {}).get("duration_ms"),
                        model_usage=tuple(
                            ModelUsage(
                                model_name=item["model_name"],
                                request_count=item["request_count"],
                                token_usage=(
                                    TokenUsage(
                                        input_tokens=item["token_usage"][
                                            "input_tokens"
                                        ],
                                        output_tokens=item["token_usage"][
                                            "output_tokens"
                                        ],
                                        total_tokens=item["token_usage"][
                                            "total_tokens"
                                        ],
                                    )
                                    if item.get("token_usage") is not None
                                    else None
                                ),
                                unreported_request_count=item.get(
                                    "unreported_request_count", 0
                                ),
                            )
                            for item in (row.payload.get("stats") or {}).get(
                                "model_usage", ()
                            )
                        ),
                        prompt_versions=(row.payload.get("stats") or {}).get(
                            "prompt_versions", {}
                        ),
                    ),
                    status=row.payload.get("status", "queued"),
                    phase=row.payload.get("phase", "queued"),
                    processed_document_count=row.payload.get(
                        "processed_document_count", 0
                    ),
                    total_document_count=row.payload.get("total_document_count", 0),
                    current_document_id=row.payload.get("current_document_id"),
                    progress_message=row.payload.get("progress_message"),
                    error_code=row.payload.get("error_code"),
                    error_message=row.payload.get("error_message"),
                    created_at=_datetime_or_none(row.payload.get("created_at")),
                    started_at=_datetime_or_none(row.payload.get("started_at")),
                    completed_at=_datetime_or_none(row.payload.get("completed_at")),
                    diagnostics=tuple(
                        (dict(item) for item in row.payload.get("diagnostics", ()))
                    ),
                    origin=row.payload.get("origin", "system_generated"),
                    scientific_record_source=row.payload.get(
                        "scientific_record_source",
                        (
                            "experiment_graph"
                            if row.payload.get("origin", "system_generated")
                            == "system_generated"
                            else "authored_snapshot"
                        ),
                    ),
                    source_analysis_version=row.payload.get("source_analysis_version"),
                    created_by_user_id=row.payload.get("created_by_user_id"),
                    created_by_tool_call_id=row.payload.get("created_by_tool_call_id"),
                    abstention_reason=row.payload.get("abstention_reason"),
                    abstention_note=row.payload.get("abstention_note"),
                )
                if row is not None
                else None
            )

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
            version = objective_row.payload.get('published_analysis_version')
            if version is None:
                return None
            row = await session.get(
                ObjectiveAnalysisRecord,
                (collection_id, objective_id, version),
            )
            return (
                ObjectiveAnalysis(
                    collection_id=row.payload.get("collection_id", ""),
                    objective_id=row.payload.get("objective_id", ""),
                    analysis_version=row.payload.get("analysis_version", 0),
                    document_inputs=tuple(
                        (
                            PreparedDocumentInput(
                                document_id=item.get("document_id", ""),
                                preparation_fingerprint=item.get(
                                    "preparation_fingerprint", ""
                                ),
                            )
                            for item in row.payload.get("document_inputs", ())
                        )
                    ),
                    pipeline_version=row.payload.get("pipeline_version", ""),
                    model_name=row.payload.get("model_name"),
                    prompt_versions={
                        str(key): str(value)
                        for key, value in dict(
                            row.payload.get("prompt_versions", {})
                        ).items()
                    },
                    stats=ExecutionStats(
                        duration_ms=(row.payload.get("stats") or {}).get("duration_ms"),
                        model_usage=tuple(
                            ModelUsage(
                                model_name=item["model_name"],
                                request_count=item["request_count"],
                                token_usage=(
                                    TokenUsage(
                                        input_tokens=item["token_usage"][
                                            "input_tokens"
                                        ],
                                        output_tokens=item["token_usage"][
                                            "output_tokens"
                                        ],
                                        total_tokens=item["token_usage"][
                                            "total_tokens"
                                        ],
                                    )
                                    if item.get("token_usage") is not None
                                    else None
                                ),
                                unreported_request_count=item.get(
                                    "unreported_request_count", 0
                                ),
                            )
                            for item in (row.payload.get("stats") or {}).get(
                                "model_usage", ()
                            )
                        ),
                        prompt_versions=(row.payload.get("stats") or {}).get(
                            "prompt_versions", {}
                        ),
                    ),
                    status=row.payload.get("status", "queued"),
                    phase=row.payload.get("phase", "queued"),
                    processed_document_count=row.payload.get(
                        "processed_document_count", 0
                    ),
                    total_document_count=row.payload.get("total_document_count", 0),
                    current_document_id=row.payload.get("current_document_id"),
                    progress_message=row.payload.get("progress_message"),
                    error_code=row.payload.get("error_code"),
                    error_message=row.payload.get("error_message"),
                    created_at=_datetime_or_none(row.payload.get("created_at")),
                    started_at=_datetime_or_none(row.payload.get("started_at")),
                    completed_at=_datetime_or_none(row.payload.get("completed_at")),
                    diagnostics=tuple(
                        (dict(item) for item in row.payload.get("diagnostics", ()))
                    ),
                    origin=row.payload.get("origin", "system_generated"),
                    scientific_record_source=row.payload.get(
                        "scientific_record_source",
                        (
                            "experiment_graph"
                            if row.payload.get("origin", "system_generated")
                            == "system_generated"
                            else "authored_snapshot"
                        ),
                    ),
                    source_analysis_version=row.payload.get("source_analysis_version"),
                    created_by_user_id=row.payload.get("created_by_user_id"),
                    created_by_tool_call_id=row.payload.get("created_by_tool_call_id"),
                    abstention_reason=row.payload.get("abstention_reason"),
                    abstention_note=row.payload.get("abstention_note"),
                )
                if row is not None
                else None
            )

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
                PaperContribution(
                    collection_id=item.get("collection_id", ""),
                    objective_id=item.get("objective_id", ""),
                    analysis_version=item.get("analysis_version", 0),
                    document_id=item.get("document_id", ""),
                    analysis_status=item.get("analysis_status", "pending"),
                    relevance=item.get("relevance", "uncertain"),
                    paper_role=item.get("paper_role", "uncertain"),
                    contribution_summary=item.get("contribution_summary"),
                    material_match=tuple(item.get("material_match", ())),
                    changed_variables=tuple(item.get("changed_variables", ())),
                    measured_property_scope=tuple(item.get("measured_property_scope", ())),
                    test_environment_scope=tuple(item.get("test_environment_scope", ())),
                    exclusion_reason=item.get("exclusion_reason"),
                    warnings=tuple(item.get("warnings", ())),
                    confidence=round(item.get("confidence", 0.0), 4),
                    evidence_disposition=item.get("evidence_disposition"),
                    routed_source_count=item.get("routed_source_count"),
                    extracted_source_count=item.get("extracted_source_count"),
                    comparable_evidence_count=item.get("comparable_evidence_count"),
                    failed_source_count=item.get("failed_source_count"),
                    uninspected_source_count=item.get("uninspected_source_count"),
                    evidence_disposition_reason=item.get("evidence_disposition_reason"),
                    evidence_status_counts=tuple(
                        sorted(item.get("evidence_status_counts", {}).items())
                    ),
                    inspected_source_refs=tuple(
                        (
                            InspectedObjectiveSourceRef(
                                source_kind=source["source_kind"],
                                source_ref=source["source_ref"],
                                source_digest=source.get("source_digest"),
                            )
                            for source in item.get("inspected_source_refs", ())
                        )
                    ),
                )
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
            return (
                tuple(
                    Finding(
                        collection_id=item.get("collection_id") or "",
                        objective_id=item.get("objective_id") or "",
                        analysis_version=item.get("analysis_version"),
                        finding_id=item.get("finding_id")
                        or finding_stable_id(
                            "finding",
                            item.get("objective_id"),
                            item.get("analysis_version"),
                            tuple(item.get("factors", ())),
                            item.get("outcome") or "",
                            item.get("supporting_evidence_ids"),
                        ),
                        statement=item.get("statement") or "",
                        factors=tuple(item.get("factors", ())),
                        outcome=item.get("outcome") or "",
                        direction=item.get("direction", "unknown"),
                        assertion_strength=item.get(
                            "assertion_strength", "descriptive"
                        ),
                        attribution_scope=item.get(
                            "attribution_scope", "descriptive_only"
                        ),
                        synthesis_status=item.get(
                            "synthesis_status", "insufficient_confirmation"
                        ),
                        certainty=round(item.get("certainty", 0.0), 2),
                        display_rank=item.get("display_rank"),
                        mechanisms=tuple(
                            (
                                FindingMechanismRelation(
                                    source_term=item.get("source_term") or "",
                                    relation_type=item.get("relation_type") or "",
                                    target_term=item.get("target_term") or "",
                                    direction=item.get("direction"),
                                    assertion_strength=item.get(
                                        "assertion_strength", "descriptive"
                                    ),
                                    supporting_evidence_ids=tuple(
                                        item.get("supporting_evidence_ids", ())
                                    ),
                                )
                                for item in tuple(
                                    (dict(item) for item in item.get("mechanisms", ()))
                                )
                            )
                        ),
                        scientific_context=ScientificContext(
                            material=tuple(
                                (
                                    ScientificAttribute(
                                        name=attribute["name"],
                                        value=attribute["value"],
                                        unit=attribute.get("unit"),
                                        context_scope=attribute.get(
                                            "context_scope", "unknown"
                                        ),
                                        applies_to_outcomes=tuple(
                                            attribute.get("applies_to_outcomes", ())
                                        ),
                                    )
                                    for attribute in (
                                        item.get("scientific_context") or {}
                                    ).get("material", ())
                                )
                            ),
                            sample=tuple(
                                (
                                    ScientificAttribute(
                                        name=attribute["name"],
                                        value=attribute["value"],
                                        unit=attribute.get("unit"),
                                        context_scope=attribute.get(
                                            "context_scope", "unknown"
                                        ),
                                        applies_to_outcomes=tuple(
                                            attribute.get("applies_to_outcomes", ())
                                        ),
                                    )
                                    for attribute in (
                                        item.get("scientific_context") or {}
                                    ).get("sample", ())
                                )
                            ),
                            process=tuple(
                                (
                                    ScientificAttribute(
                                        name=attribute["name"],
                                        value=attribute["value"],
                                        unit=attribute.get("unit"),
                                        context_scope=attribute.get(
                                            "context_scope", "unknown"
                                        ),
                                        applies_to_outcomes=tuple(
                                            attribute.get("applies_to_outcomes", ())
                                        ),
                                    )
                                    for attribute in (
                                        item.get("scientific_context") or {}
                                    ).get("process", ())
                                )
                            ),
                            test=tuple(
                                (
                                    ScientificAttribute(
                                        name=attribute["name"],
                                        value=attribute["value"],
                                        unit=attribute.get("unit"),
                                        context_scope=attribute.get(
                                            "context_scope", "unknown"
                                        ),
                                        applies_to_outcomes=tuple(
                                            attribute.get("applies_to_outcomes", ())
                                        ),
                                    )
                                    for attribute in (
                                        item.get("scientific_context") or {}
                                    ).get("test", ())
                                )
                            ),
                        ),
                        limitations=tuple(item.get("limitations", ())),
                        paper_contributions=tuple(
                            (
                                FindingPaperContribution(
                                    document_id=item.get("document_id") or "",
                                    analysis_status=item.get(
                                        "analysis_status", "pending"
                                    ),
                                    supporting_evidence_ids=tuple(
                                        item.get("supporting_evidence_ids", ())
                                    ),
                                    contradicting_evidence_ids=tuple(
                                        item.get("contradicting_evidence_ids", ())
                                    ),
                                    context_evidence_ids=tuple(
                                        item.get("context_evidence_ids", ())
                                    ),
                                    condition_boundary_evidence_ids=tuple(
                                        item.get("condition_boundary_evidence_ids", ())
                                    ),
                                )
                                for item in tuple(
                                    (
                                        dict(item)
                                        for item in item.get("paper_contributions", ())
                                    )
                                )
                            )
                        ),
                        origin=item.get("origin", "system_generated"),
                        source_analysis_version=item.get("source_analysis_version")
                        or None,
                        parent_finding_id=item.get("parent_finding_id"),
                        created_by_user_id=item.get("created_by_user_id"),
                        created_by_tool_call_id=item.get("created_by_tool_call_id"),
                        created_at=_finding_creation_time(item.get("created_at")),
                        warnings=tuple(item.get("warnings", ())),
                        selection_ids=tuple(item.get("selection_ids", ())),
                        comparison_group_ids=tuple(
                            item.get("comparison_group_ids", ())
                        ),
                    )
                    for item in page
                ),
                total,
            )

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
                    return Finding(
                        collection_id=item.get("collection_id") or "",
                        objective_id=item.get("objective_id") or "",
                        analysis_version=item.get("analysis_version"),
                        finding_id=item.get("finding_id")
                        or finding_stable_id(
                            "finding",
                            item.get("objective_id"),
                            item.get("analysis_version"),
                            tuple(item.get("factors", ())),
                            item.get("outcome") or "",
                            item.get("supporting_evidence_ids"),
                        ),
                        statement=item.get("statement") or "",
                        factors=tuple(item.get("factors", ())),
                        outcome=item.get("outcome") or "",
                        direction=item.get("direction", "unknown"),
                        assertion_strength=item.get(
                            "assertion_strength", "descriptive"
                        ),
                        attribution_scope=item.get(
                            "attribution_scope", "descriptive_only"
                        ),
                        synthesis_status=item.get(
                            "synthesis_status", "insufficient_confirmation"
                        ),
                        certainty=round(item.get("certainty", 0.0), 2),
                        display_rank=item.get("display_rank"),
                        mechanisms=tuple(
                            (
                                FindingMechanismRelation(
                                    source_term=item.get("source_term") or "",
                                    relation_type=item.get("relation_type") or "",
                                    target_term=item.get("target_term") or "",
                                    direction=item.get("direction"),
                                    assertion_strength=item.get(
                                        "assertion_strength", "descriptive"
                                    ),
                                    supporting_evidence_ids=tuple(
                                        item.get("supporting_evidence_ids", ())
                                    ),
                                )
                                for item in tuple(
                                    (dict(item) for item in item.get("mechanisms", ()))
                                )
                            )
                        ),
                        scientific_context=ScientificContext(
                            material=tuple(
                                (
                                    ScientificAttribute(
                                        name=attribute["name"],
                                        value=attribute["value"],
                                        unit=attribute.get("unit"),
                                        context_scope=attribute.get(
                                            "context_scope", "unknown"
                                        ),
                                        applies_to_outcomes=tuple(
                                            attribute.get("applies_to_outcomes", ())
                                        ),
                                    )
                                    for attribute in (
                                        item.get("scientific_context") or {}
                                    ).get("material", ())
                                )
                            ),
                            sample=tuple(
                                (
                                    ScientificAttribute(
                                        name=attribute["name"],
                                        value=attribute["value"],
                                        unit=attribute.get("unit"),
                                        context_scope=attribute.get(
                                            "context_scope", "unknown"
                                        ),
                                        applies_to_outcomes=tuple(
                                            attribute.get("applies_to_outcomes", ())
                                        ),
                                    )
                                    for attribute in (
                                        item.get("scientific_context") or {}
                                    ).get("sample", ())
                                )
                            ),
                            process=tuple(
                                (
                                    ScientificAttribute(
                                        name=attribute["name"],
                                        value=attribute["value"],
                                        unit=attribute.get("unit"),
                                        context_scope=attribute.get(
                                            "context_scope", "unknown"
                                        ),
                                        applies_to_outcomes=tuple(
                                            attribute.get("applies_to_outcomes", ())
                                        ),
                                    )
                                    for attribute in (
                                        item.get("scientific_context") or {}
                                    ).get("process", ())
                                )
                            ),
                            test=tuple(
                                (
                                    ScientificAttribute(
                                        name=attribute["name"],
                                        value=attribute["value"],
                                        unit=attribute.get("unit"),
                                        context_scope=attribute.get(
                                            "context_scope", "unknown"
                                        ),
                                        applies_to_outcomes=tuple(
                                            attribute.get("applies_to_outcomes", ())
                                        ),
                                    )
                                    for attribute in (
                                        item.get("scientific_context") or {}
                                    ).get("test", ())
                                )
                            ),
                        ),
                        limitations=tuple(item.get("limitations", ())),
                        paper_contributions=tuple(
                            (
                                FindingPaperContribution(
                                    document_id=item.get("document_id") or "",
                                    analysis_status=item.get(
                                        "analysis_status", "pending"
                                    ),
                                    supporting_evidence_ids=tuple(
                                        item.get("supporting_evidence_ids", ())
                                    ),
                                    contradicting_evidence_ids=tuple(
                                        item.get("contradicting_evidence_ids", ())
                                    ),
                                    context_evidence_ids=tuple(
                                        item.get("context_evidence_ids", ())
                                    ),
                                    condition_boundary_evidence_ids=tuple(
                                        item.get("condition_boundary_evidence_ids", ())
                                    ),
                                )
                                for item in tuple(
                                    (
                                        dict(item)
                                        for item in item.get("paper_contributions", ())
                                    )
                                )
                            )
                        ),
                        origin=item.get("origin", "system_generated"),
                        source_analysis_version=item.get("source_analysis_version")
                        or None,
                        parent_finding_id=item.get("parent_finding_id"),
                        created_by_user_id=item.get("created_by_user_id"),
                        created_by_tool_call_id=item.get("created_by_tool_call_id"),
                        created_at=_finding_creation_time(item.get("created_at")),
                        warnings=tuple(item.get("warnings", ())),
                        selection_ids=tuple(item.get("selection_ids", ())),
                        comparison_group_ids=tuple(
                            item.get("comparison_group_ids", ())
                        ),
                    )
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
                evidence_ids = {
                    evidence_id
                    for contribution in finding.get("paper_contributions", ())
                    for field_name in ("supporting_evidence_ids", "contradicting_evidence_ids", "context_evidence_ids")
                    for evidence_id in contribution.get(field_name, ())
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
            evidence = []
            for item in page:
                stored_result = item.get("reported_result")
                result = (
                    ScientificResult(
                        outcome=stored_result["outcome"],
                        value=stored_result.get("value"),
                        unit=stored_result.get("unit"),
                        direction=stored_result.get("direction", "unknown"),
                        result_text=stored_result["result_text"],
                        baseline_value=stored_result.get("baseline_value"),
                        target_value=stored_result.get("target_value"),
                        result_kind=stored_result.get("result_kind", "observed"),
                    )
                    if stored_result is not None else None
                )
                comparison = item.get("comparison")
                context = item.get("scientific_context") or {}
                evidence.append(ObjectiveEvidence(
                    collection_id=item.get("collection_id", ""),
                    objective_id=item.get("objective_id", ""),
                    analysis_version=item.get("analysis_version", 0),
                    evidence_id=item.get("evidence_id") or objective_scoped_id(
                        "oev",
                        item.get("collection_id", ""),
                        item.get("objective_id", ""),
                        item.get("analysis_version", 0),
                        item.get("document_id", ""),
                        item.get("source_kind", "text_window"),
                        item.get("source_ref", ""),
                        item.get("evidence_role", "irrelevant"),
                        item.get("semantic_slot") or (result.outcome if result else None),
                    ),
                    document_id=item.get("document_id", ""),
                    source_kind=item.get("source_kind", "text_window"),
                    source_ref=item.get("source_ref", ""),
                    source_excerpt=item.get("source_excerpt", ""),
                    page_numbers=tuple(item.get("page_numbers", ())),
                    related_source_refs=tuple(
                        dict(ref) for ref in item.get("related_source_refs", ())
                    ),
                    evidence_role=item.get("evidence_role", "irrelevant"),
                    selection_status=item.get("selection_status", "candidate"),
                    selection_reason=item.get("selection_reason"),
                    changed_variables=tuple(
                        ScientificVariable(
                            name=variable["name"],
                            baseline_value=variable.get("baseline_value"),
                            target_value=variable.get("target_value"),
                            unit=variable.get("unit"),
                        )
                        for variable in item.get("changed_variables", ())
                    ),
                    comparison=(
                        ScientificComparison(
                            baseline_label=comparison["baseline_label"],
                            target_label=comparison["target_label"],
                            axis_names=tuple(comparison["axis_names"]),
                            comparable=comparison["comparable"],
                            incomparability_reasons=tuple(
                                comparison.get("incomparability_reasons", ())
                            ),
                        )
                        if comparison is not None else None
                    ),
                    reported_result=result,
                    attribution_scope=item.get("attribution_scope", "not_attributable"),
                    scientific_context=ScientificContext(**{
                        group: tuple(
                            ScientificAttribute(
                                name=attribute["name"],
                                value=attribute["value"],
                                unit=attribute.get("unit"),
                                context_scope=attribute.get("context_scope", "unknown"),
                                applies_to_outcomes=tuple(
                                    attribute.get("applies_to_outcomes", ())
                                ),
                            )
                            for attribute in context.get(group, ())
                        )
                        for group in ("material", "sample", "process", "test")
                    }),
                    resolution_status=item.get("resolution_status", "unknown"),
                    failure_reason=item.get("failure_reason"),
                    confidence=round(item.get("confidence", 0.0), 4),
                    related_source_refs_explicit="related_source_refs" in item,
                    origin=item.get("origin", "system_generated"),
                    source_analysis_version=item.get("source_analysis_version"),
                    supersedes_evidence_id=item.get("supersedes_evidence_id"),
                    superseded_by_evidence_id=item.get("superseded_by_evidence_id"),
                    created_by_user_id=item.get("created_by_user_id"),
                    created_by_tool_call_id=item.get("created_by_tool_call_id"),
                    created_at=_finding_creation_time(item.get("created_at")),
                    authoring_note=item.get("authoring_note"),
                    warnings=tuple(item.get("warnings", ())),
                ))
            return tuple(evidence), total

    @staticmethod
    def _write_contributions(
        row: ObjectiveAnalysisRecord,
        contributions: tuple[PaperContribution, ...],
    ) -> None:
        payload = dict(row.payload or {})
        payload["paper_contributions"] = [
            {
                "collection_id": item.collection_id,
                "objective_id": item.objective_id,
                "analysis_version": item.analysis_version,
                "document_id": item.document_id,
                "analysis_status": item.analysis_status,
                "relevance": item.relevance,
                "paper_role": item.paper_role,
                "contribution_summary": item.contribution_summary,
                "material_match": list(item.material_match),
                "changed_variables": list(item.changed_variables),
                "measured_property_scope": list(item.measured_property_scope),
                "test_environment_scope": list(item.test_environment_scope),
                "exclusion_reason": item.exclusion_reason,
                "warnings": list(item.warnings),
                "confidence": item.confidence,
                "evidence_disposition": item.evidence_disposition,
                "routed_source_count": item.routed_source_count,
                "extracted_source_count": item.extracted_source_count,
                "comparable_evidence_count": item.comparable_evidence_count,
                "failed_source_count": item.failed_source_count,
                "uninspected_source_count": item.uninspected_source_count,
                "evidence_disposition_reason": item.evidence_disposition_reason,
                "evidence_status_counts": {
                    status: count for status, count in item.evidence_status_counts
                },
                "inspected_source_refs": [
                    {
                        "source_kind": source_ref.source_kind,
                        "source_ref": source_ref.source_ref,
                        "source_digest": source_ref.source_digest,
                    }
                    for source_ref in item.inspected_source_refs
                ],
            }
            for item in contributions
        ]
        row.payload = payload

    @staticmethod
    def _write_result_records(
        row: ObjectiveAnalysisRecord,
        evidence_records: tuple[ObjectiveEvidence, ...],
        findings: tuple[Finding, ...],
    ) -> None:
        payload = dict(row.payload or {})
        payload["evidence_records"] = [
            {
                "collection_id": item.collection_id,
                "objective_id": item.objective_id,
                "analysis_version": item.analysis_version,
                "evidence_id": item.evidence_id,
                "document_id": item.document_id,
                "source_kind": item.source_kind,
                "source_ref": item.source_ref,
                "source_excerpt": item.source_excerpt,
                "page_numbers": list(item.page_numbers),
                "evidence_role": item.evidence_role,
                "selection_status": item.selection_status,
                "selection_reason": item.selection_reason,
                "evidence_status": item.evidence_status,
                "evidence_status_reason": item.evidence_status_reason,
                "changed_variables": [
                    {
                        "name": variable.name,
                        "baseline_value": variable.baseline_value,
                        "target_value": variable.target_value,
                        "unit": variable.unit,
                    }
                    for variable in item.changed_variables
                ],
                "comparison": (
                    {
                        "baseline_label": item.comparison.baseline_label,
                        "target_label": item.comparison.target_label,
                        "axis_names": list(item.comparison.axis_names),
                        "comparable": item.comparison.comparable,
                        "incomparability_reasons": list(
                            item.comparison.incomparability_reasons
                        ),
                    }
                    if item.comparison
                    else None
                ),
                "reported_result": (
                    {
                        "outcome": item.reported_result.outcome,
                        "value": item.reported_result.value,
                        "baseline_value": item.reported_result.baseline_value,
                        "target_value": item.reported_result.target_value,
                        "unit": item.reported_result.unit,
                        "direction": item.reported_result.direction,
                        "result_text": item.reported_result.result_text,
                        "result_kind": item.reported_result.result_kind,
                    }
                    if item.reported_result
                    else None
                ),
                "attribution_scope": item.attribution_scope,
                "scientific_context": {
                    "material": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in item.scientific_context.material
                    ],
                    "sample": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in item.scientific_context.sample
                    ],
                    "process": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in item.scientific_context.process
                    ],
                    "test": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in item.scientific_context.test
                    ],
                },
                "resolution_status": item.resolution_status,
                "failure_reason": item.failure_reason,
                "confidence": item.confidence,
                "origin": item.origin,
                "source_analysis_version": item.source_analysis_version,
                "supersedes_evidence_id": item.supersedes_evidence_id,
                "superseded_by_evidence_id": item.superseded_by_evidence_id,
                "created_by_user_id": item.created_by_user_id,
                "created_by_tool_call_id": item.created_by_tool_call_id,
                "created_at": (
                    item.created_at.isoformat() if item.created_at is not None else None
                ),
                "authoring_note": item.authoring_note,
                **({"warnings": list(item.warnings)} if item.warnings else {}),
                **(
                    {
                        "related_source_refs": [
                            dict(item) for item in item.related_source_refs
                        ]
                    }
                    if item.related_source_refs or item.related_source_refs_explicit
                    else {}
                ),
            }
            for item in evidence_records
        ]
        payload["findings"] = [
            {
                "collection_id": item.collection_id,
                "objective_id": item.objective_id,
                "analysis_version": item.analysis_version,
                "finding_id": item.finding_id,
                "statement": item.statement,
                "factors": list(item.factors),
                "outcome": item.outcome,
                "direction": item.direction,
                "assertion_strength": item.assertion_strength,
                "attribution_scope": item.attribution_scope,
                "synthesis_status": item.synthesis_status,
                "certainty": item.certainty,
                "display_rank": item.display_rank,
                "mechanisms": [
                    {
                        "source_term": mechanism.source_term,
                        "relation_type": mechanism.relation_type,
                        "target_term": mechanism.target_term,
                        "direction": mechanism.direction,
                        "assertion_strength": mechanism.assertion_strength,
                        "supporting_evidence_ids": list(
                            mechanism.supporting_evidence_ids
                        ),
                    }
                    for mechanism in item.mechanisms
                ],
                "scientific_context": {
                    "material": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in item.scientific_context.material
                    ],
                    "sample": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in item.scientific_context.sample
                    ],
                    "process": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in item.scientific_context.process
                    ],
                    "test": [
                        {
                            "name": attribute.name,
                            "value": attribute.value,
                            "unit": attribute.unit,
                            **(
                                {"context_scope": attribute.context_scope}
                                if attribute.context_scope != "unknown"
                                else {}
                            ),
                            **(
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
                                if attribute.applies_to_outcomes
                                else {}
                            ),
                        }
                        for attribute in item.scientific_context.test
                    ],
                },
                "limitations": list(item.limitations),
                "paper_contributions": [
                    {
                        "document_id": contribution.document_id,
                        "analysis_status": contribution.analysis_status,
                        "supporting_evidence_ids": list(
                            contribution.supporting_evidence_ids
                        ),
                        "contradicting_evidence_ids": list(
                            contribution.contradicting_evidence_ids
                        ),
                        "context_evidence_ids": list(contribution.context_evidence_ids),
                        "condition_boundary_evidence_ids": list(
                            contribution.condition_boundary_evidence_ids
                        ),
                    }
                    for contribution in item.paper_contributions
                ],
                "origin": item.origin,
                "source_analysis_version": item.source_analysis_version,
                "parent_finding_id": item.parent_finding_id,
                "created_by_user_id": item.created_by_user_id,
                "created_by_tool_call_id": item.created_by_tool_call_id,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                **(
                    {"selection_ids": list(item.selection_ids)}
                    if item.selection_ids
                    else {}
                ),
                **(
                    {"comparison_group_ids": list(item.comparison_group_ids)}
                    if item.comparison_group_ids
                    else {}
                ),
                **({"warnings": list(item.warnings)} if item.warnings else {}),
            }
            for item in findings
        ]
        row.payload = payload

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


def _finding_creation_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = (str(value).strip() or None) if value is not None else None
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid Finding creation time") from exc
