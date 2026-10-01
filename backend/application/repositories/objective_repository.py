from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Final, Mapping, Protocol

from application.repositories.pipeline_run_repository import ExecutionStats
from application.repositories.transaction import RepositoryTransaction
from domain.core.finding import Finding
from domain.core.research_objective import (
    ObjectiveEvidence,
    ObjectiveFactSet,
    PaperContribution,
    PreparedDocumentInput,
    ResearchObjective,
    _choice,
    _datetime_or_none,
    _datetime_record,
    _positive_int_or_none,
    _required_text,
    _text,
)

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
            stats=ExecutionStats.from_mapping(payload.get("stats")),
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
            "stats": self.stats.to_record(),
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


class ObjectiveRepository(Protocol):
    backend_name: str

    async def replace(
        self,
        collection_id: str,
        facts: ObjectiveFactSet,
    ) -> None: ...

    async def read(
        self,
        collection_id: str,
    ) -> ObjectiveFactSet: ...

    async def list_objectives(
        self,
        collection_id: str,
    ) -> tuple[ResearchObjective, ...]: ...

    async def list_objective_records(
        self,
        collection_id: str,
    ) -> tuple[StoredObjective, ...]: ...

    async def create_authored_candidate(
        self,
        objective: ResearchObjective,
        *,
        created_by_user_id: str,
        created_by_tool_call_id: str,
    ) -> ResearchObjective: ...

    async def read_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective | None: ...

    async def read_objective_record(
        self,
        collection_id: str,
        objective_id: str,
    ) -> StoredObjective | None: ...

    async def confirm_objective(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ResearchObjective: ...

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
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]: ...

    async def claim_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> ObjectiveAnalysis | None: ...

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
    ) -> ObjectiveAnalysis: ...

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
    ) -> ObjectiveAnalysis: ...

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
    ) -> ObjectiveAnalysis: ...

    async def interrupt_active_analyses(self) -> int: ...

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
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]: ...

    async def publish_experiment_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        contributions: tuple[PaperContribution, ...] = (),
        abstention_reason: str | None = None,
        abstention_note: str | None = None,
        transaction: RepositoryTransaction | None = None,
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]: ...

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
    ) -> tuple[ResearchObjective, ObjectiveAnalysis]: ...

    async def read_analysis(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int | None = None,
    ) -> ObjectiveAnalysis | None: ...

    async def read_published_analysis(
        self,
        collection_id: str,
        objective_id: str,
    ) -> ObjectiveAnalysis | None: ...

    async def list_contributions(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[PaperContribution, ...]: ...

    async def list_findings(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[tuple[Finding, ...], int]: ...

    async def read_finding(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
    ) -> Finding | None: ...

    async def list_evidence(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        finding_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[tuple[ObjectiveEvidence, ...], int]: ...
