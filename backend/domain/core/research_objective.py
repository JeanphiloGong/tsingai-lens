from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha1
import json
import math
import re
from typing import Any, Final, Mapping


PAPER_RELEVANCE_VALUES: Final[frozenset[str]] = frozenset(
    {"high", "medium", "low", "irrelevant", "uncertain"}
)
PAPER_ROLE_VALUES: Final[frozenset[str]] = frozenset(
    {
        "primary_experiment",
        "supporting_method",
        "supporting_background",
        "review",
        "modeling_only",
        "irrelevant",
        "mixed",
        "uncertain",
    }
)
PAPER_CONTRIBUTION_STATUSES: Final[frozenset[str]] = frozenset(
    {"pending", "analyzed", "excluded", "failed"}
)
SOURCE_KIND_VALUES: Final[frozenset[str]] = frozenset(
    {"text_window", "table", "figure"}
)
EVIDENCE_ROLE_VALUES: Final[frozenset[str]] = frozenset(
    {
        "direct_result",
        "condition_context",
        "mechanism_context",
        "baseline_context",
        "comparison_context",
        "background_context",
        "contradictory_result",
        "irrelevant",
    }
)
EVIDENCE_KIND_VALUES: Final[frozenset[str]] = frozenset(
    {
        "measurement",
        "test_condition",
        "sample_context",
        "process_context",
        "characterization",
        "baseline_reference",
        "comparison",
        "interpretation",
        "mixed",
        "unknown",
    }
)
EVIDENCE_RESOLUTION_STATUS_VALUES: Final[frozenset[str]] = frozenset(
    {"resolved", "partial", "unresolved", "skipped", "unknown"}
)
OBJECTIVE_CONFIRMATION_STATUSES: Final[frozenset[str]] = frozenset(
    {"candidate", "confirmed"}
)
OBJECTIVE_ANALYSIS_STATUSES: Final[frozenset[str]] = frozenset(
    {"queued", "running", "succeeded", "failed"}
)
OBJECTIVE_ANALYSIS_STATUS_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "queued": frozenset({"running", "failed"}),
    "running": frozenset({"succeeded", "failed"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
}
OBJECTIVE_EVIDENCE_STATES: Final[frozenset[str]] = frozenset(
    {"candidate", "selected", "extracted", "rejected", "failed"}
)
OBJECTIVE_EVIDENCE_STATE_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "candidate": frozenset({"selected", "rejected", "failed"}),
    "selected": frozenset({"extracted", "rejected", "failed"}),
    "extracted": frozenset(),
    "rejected": frozenset(),
    "failed": frozenset(),
}
_QUESTION_SIGNAL_TERMS: Final[tuple[str, ...]] = (
    "how ",
    "what ",
    "which ",
    "why ",
    "whether ",
    "does ",
    "do ",
    "is ",
    "are ",
    "can ",
    "affect",
    "effect",
    "impact",
    "influence",
    "compare",
    "comparison",
    "relationship",
    "versus",
    " vs ",
    "optimize",
    "improve",
)
_SLUG_NON_WORD_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class PaperSkim:
    document_id: str
    title: str | None
    source_filename: str | None
    doc_role: str
    candidate_materials: tuple[str, ...]
    candidate_processes: tuple[str, ...]
    candidate_properties: tuple[str, ...]
    changed_variables: tuple[str, ...]
    possible_objectives: tuple[str, ...]
    evidence_density: str
    confidence: float
    warnings: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperSkim":
        return cls(
            document_id=_text(payload.get("document_id") or payload.get("paper_id"))
            or "",
            title=_text(payload.get("title")),
            source_filename=_text(payload.get("source_filename")),
            doc_role=_text(payload.get("doc_role")) or "uncertain",
            candidate_materials=normalize_objective_terms(
                payload.get("candidate_materials")
            ),
            candidate_processes=normalize_objective_terms(
                payload.get("candidate_processes")
            ),
            candidate_properties=normalize_objective_terms(
                payload.get("candidate_properties")
            ),
            changed_variables=normalize_objective_terms(
                payload.get("changed_variables")
            ),
            possible_objectives=normalize_objective_terms(
                payload.get("possible_objectives")
            ),
            evidence_density=_text(payload.get("evidence_density")) or "unknown",
            confidence=normalize_objective_confidence(payload.get("confidence")),
            warnings=normalize_objective_terms(payload.get("warnings")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "source_filename": self.source_filename,
            "doc_role": self.doc_role,
            "candidate_materials": list(self.candidate_materials),
            "candidate_processes": list(self.candidate_processes),
            "candidate_properties": list(self.candidate_properties),
            "changed_variables": list(self.changed_variables),
            "possible_objectives": list(self.possible_objectives),
            "evidence_density": self.evidence_density,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ResearchObjective:
    collection_id: str
    objective_id: str
    question: str
    material_scope: tuple[str, ...]
    process_axes: tuple[str, ...]
    property_axes: tuple[str, ...]
    comparison_intent: str | None
    seed_document_ids: tuple[str, ...]
    excluded_document_ids: tuple[str, ...]
    confidence: float
    reason: str | None
    confirmation_status: str = "candidate"
    active_analysis_version: int | None = None
    published_analysis_version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not _text(self.collection_id):
            raise ValueError("research objective requires collection_id")
        if not _text(self.objective_id):
            raise ValueError("research objective requires objective_id")
        if not _text(self.question):
            raise ValueError("research objective requires question")
        if self.confirmation_status not in OBJECTIVE_CONFIRMATION_STATUSES:
            raise ValueError(
                f"unsupported objective confirmation status: {self.confirmation_status}"
            )
        overlap = set(self.seed_document_ids) & set(self.excluded_document_ids)
        if overlap:
            raise ValueError(
                "objective seed and excluded documents overlap: "
                + ", ".join(sorted(overlap))
            )
        for field_name, version in (
            ("active_analysis_version", self.active_analysis_version),
            ("published_analysis_version", self.published_analysis_version),
        ):
            if version is not None and version < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if (
            self.published_analysis_version is not None
            and self.active_analysis_version is None
        ):
            raise ValueError("published analysis requires an active analysis version")
        if (
            self.published_analysis_version is not None
            and self.active_analysis_version is not None
            and self.published_analysis_version > self.active_analysis_version
        ):
            raise ValueError("published analysis cannot be newer than active analysis")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchObjective":
        question = _text(payload.get("question")) or ""
        return cls(
            collection_id=_text(payload.get("collection_id")) or "",
            objective_id=_text(payload.get("objective_id"))
            or build_research_objective_id(question),
            question=question,
            material_scope=normalize_objective_terms(payload.get("material_scope")),
            process_axes=normalize_objective_terms(payload.get("process_axes")),
            property_axes=normalize_objective_terms(payload.get("property_axes")),
            comparison_intent=_text(payload.get("comparison_intent")),
            seed_document_ids=normalize_objective_terms(
                payload.get("seed_document_ids")
            ),
            excluded_document_ids=normalize_objective_terms(
                payload.get("excluded_document_ids")
            ),
            confidence=normalize_objective_confidence(payload.get("confidence")),
            reason=_text(payload.get("reason")),
            confirmation_status=_choice(
                payload.get("confirmation_status"),
                OBJECTIVE_CONFIRMATION_STATUSES,
                "candidate",
            ),
            active_analysis_version=_positive_int_or_none(
                payload.get("active_analysis_version")
            ),
            published_analysis_version=_positive_int_or_none(
                payload.get("published_analysis_version")
            ),
            created_at=_datetime_or_none(payload.get("created_at")),
            updated_at=_datetime_or_none(payload.get("updated_at")),
        )

    def confirm(self) -> "ResearchObjective":
        if self.confirmation_status != "candidate":
            raise ValueError(
                "invalid objective confirmation transition: "
                f"{self.confirmation_status} -> confirmed"
            )
        return replace(self, confirmation_status="confirmed")

    def queue_analysis(self, analysis_version: int) -> "ResearchObjective":
        if self.confirmation_status != "confirmed":
            raise ValueError("objective must be confirmed before analysis")
        if analysis_version < 1:
            raise ValueError("analysis_version must be a positive integer")
        if (
            self.active_analysis_version is not None
            and analysis_version <= self.active_analysis_version
        ):
            raise ValueError("analysis_version must be newer than active version")
        return replace(self, active_analysis_version=analysis_version)

    def publish_analysis(self, analysis: "ObjectiveAnalysis") -> "ResearchObjective":
        if analysis.collection_id != self.collection_id:
            raise ValueError("analysis belongs to another collection")
        if analysis.objective_id != self.objective_id:
            raise ValueError("analysis belongs to another objective")
        if analysis.analysis_version != self.active_analysis_version:
            raise ValueError("analysis is not the active objective version")
        if analysis.status != "succeeded":
            raise ValueError("only succeeded analysis can be published")
        return replace(self, published_analysis_version=analysis.analysis_version)

    def to_record(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "objective_id": self.objective_id,
            "question": self.question,
            "material_scope": list(self.material_scope),
            "process_axes": list(self.process_axes),
            "property_axes": list(self.property_axes),
            "comparison_intent": self.comparison_intent,
            "seed_document_ids": list(self.seed_document_ids),
            "excluded_document_ids": list(self.excluded_document_ids),
            "confidence": self.confidence,
            "reason": self.reason,
            "confirmation_status": self.confirmation_status,
            "active_analysis_version": self.active_analysis_version,
            "published_analysis_version": self.published_analysis_version,
            "created_at": _datetime_record(self.created_at),
            "updated_at": _datetime_record(self.updated_at),
        }


@dataclass(frozen=True)
class ObjectiveAnalysis:
    collection_id: str
    objective_id: str
    analysis_version: int
    source_build_id: str
    pipeline_version: str
    model_name: str | None
    prompt_versions: dict[str, str]
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

    def __post_init__(self) -> None:
        if not _text(self.collection_id) or not _text(self.objective_id):
            raise ValueError("objective analysis requires collection and objective IDs")
        if self.analysis_version < 1:
            raise ValueError("analysis_version must be a positive integer")
        if not _text(self.source_build_id):
            raise ValueError("objective analysis requires source_build_id")
        if not _text(self.pipeline_version):
            raise ValueError("objective analysis requires pipeline_version")
        if self.status not in OBJECTIVE_ANALYSIS_STATUSES:
            raise ValueError(f"unsupported objective analysis status: {self.status}")
        if self.processed_document_count < 0 or self.total_document_count < 0:
            raise ValueError("analysis document counts cannot be negative")
        if self.processed_document_count > self.total_document_count:
            raise ValueError("processed document count exceeds total")
        if self.status == "failed" and not _text(self.error_message):
            raise ValueError("failed objective analysis requires error_message")
        if self.status == "succeeded" and self.error_message is not None:
            raise ValueError("succeeded objective analysis cannot have an error")

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.collection_id, self.objective_id, self.analysis_version)

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
        return replace(
            self,
            phase=_required_text(phase, "analysis progress requires phase"),
            processed_document_count=processed_document_count,
            total_document_count=total_document_count,
            current_document_id=_text(current_document_id),
            progress_message=_text(progress_message),
        )

    def succeed(self, *, completed_at: datetime | None = None) -> "ObjectiveAnalysis":
        return self._transition(
            "succeeded",
            phase="completed",
            processed_document_count=self.total_document_count,
            current_document_id=None,
            error_code=None,
            error_message=None,
            completed_at=completed_at or self.completed_at,
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
            error_code=_required_text(error_code, "analysis failure requires error_code"),
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
            "source_build_id": self.source_build_id,
            "pipeline_version": self.pipeline_version,
            "model_name": self.model_name,
            "prompt_versions": dict(self.prompt_versions),
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
        }


@dataclass(frozen=True)
class PaperContribution:
    collection_id: str
    objective_id: str
    analysis_version: int
    document_id: str
    analysis_status: str
    relevance: str
    paper_role: str
    contribution_summary: str | None
    material_match: tuple[str, ...]
    changed_variables: tuple[str, ...]
    measured_property_scope: tuple[str, ...]
    test_environment_scope: tuple[str, ...]
    exclusion_reason: str | None
    warnings: tuple[str, ...]
    confidence: float

    def __post_init__(self) -> None:
        if not all(
            _text(value)
            for value in (self.collection_id, self.objective_id, self.document_id)
        ):
            raise ValueError("paper contribution requires scoped identity")
        if self.analysis_version < 1:
            raise ValueError("paper contribution requires positive analysis_version")
        if self.analysis_status not in PAPER_CONTRIBUTION_STATUSES:
            raise ValueError(
                f"unsupported paper contribution status: {self.analysis_status}"
            )
        if self.relevance not in PAPER_RELEVANCE_VALUES:
            raise ValueError(f"unsupported paper relevance: {self.relevance}")
        if self.paper_role not in PAPER_ROLE_VALUES:
            raise ValueError(f"unsupported paper role: {self.paper_role}")
        if self.analysis_status in {"excluded", "failed"} and not (
            self.exclusion_reason or self.warnings
        ):
            raise ValueError(
                "excluded or failed paper contribution requires a reason or warning"
            )

    @property
    def key(self) -> tuple[str, str, int, str]:
        return (
            self.collection_id,
            self.objective_id,
            self.analysis_version,
            self.document_id,
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperContribution":
        return cls(
            collection_id=_text(payload.get("collection_id")) or "",
            objective_id=_text(payload.get("objective_id")) or "",
            analysis_version=_positive_int_or_none(payload.get("analysis_version"))
            or 0,
            document_id=_text(payload.get("document_id")) or "",
            analysis_status=_choice(
                payload.get("analysis_status"),
                PAPER_CONTRIBUTION_STATUSES,
                "pending",
            ),
            relevance=_choice(
                payload.get("relevance"), PAPER_RELEVANCE_VALUES, "uncertain"
            ),
            paper_role=_choice(
                payload.get("paper_role"), PAPER_ROLE_VALUES, "uncertain"
            ),
            contribution_summary=_text(payload.get("contribution_summary")),
            material_match=normalize_objective_terms(payload.get("material_match")),
            changed_variables=normalize_objective_terms(
                payload.get("changed_variables")
            ),
            measured_property_scope=normalize_objective_terms(
                payload.get("measured_property_scope")
            ),
            test_environment_scope=normalize_objective_terms(
                payload.get("test_environment_scope")
            ),
            exclusion_reason=_text(payload.get("exclusion_reason")),
            warnings=normalize_objective_terms(payload.get("warnings")),
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "objective_id": self.objective_id,
            "analysis_version": self.analysis_version,
            "document_id": self.document_id,
            "analysis_status": self.analysis_status,
            "relevance": self.relevance,
            "paper_role": self.paper_role,
            "contribution_summary": self.contribution_summary,
            "material_match": list(self.material_match),
            "changed_variables": list(self.changed_variables),
            "measured_property_scope": list(self.measured_property_scope),
            "test_environment_scope": list(self.test_environment_scope),
            "exclusion_reason": self.exclusion_reason,
            "warnings": list(self.warnings),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ObjectiveEvidence:
    collection_id: str
    objective_id: str
    analysis_version: int
    evidence_id: str
    document_id: str
    source_kind: str
    source_ref: str
    source_excerpt: str
    page_numbers: tuple[int, ...]
    related_source_refs: tuple[dict[str, Any], ...]
    evidence_role: str
    selection_status: str
    selection_reason: str | None
    evidence_kind: str
    property_normalized: str | None
    material_system: dict[str, Any]
    sample_context: dict[str, Any]
    process_context: dict[str, Any]
    test_condition: dict[str, Any]
    resolved_condition: dict[str, Any]
    value_payload: dict[str, Any]
    unit: str | None
    baseline_context: dict[str, Any]
    interpretation: str | None
    join_keys: dict[str, Any]
    anchor_ids: tuple[str, ...]
    resolution_status: str
    failure_reason: str | None
    confidence: float

    def __post_init__(self) -> None:
        if not all(
            _text(value)
            for value in (
                self.collection_id,
                self.objective_id,
                self.evidence_id,
                self.document_id,
                self.source_ref,
                self.source_excerpt,
            )
        ):
            raise ValueError("objective evidence requires scoped identity and source")
        if len(self.evidence_id) > 128:
            raise ValueError("objective evidence ID exceeds 128 characters")
        if self.analysis_version < 1:
            raise ValueError("objective evidence requires positive analysis_version")
        if self.source_kind not in SOURCE_KIND_VALUES:
            raise ValueError(f"unsupported objective evidence source: {self.source_kind}")
        if self.evidence_role not in EVIDENCE_ROLE_VALUES:
            raise ValueError(f"unsupported objective evidence role: {self.evidence_role}")
        if self.selection_status not in OBJECTIVE_EVIDENCE_STATES:
            raise ValueError(
                f"unsupported objective evidence state: {self.selection_status}"
            )
        if self.evidence_kind not in EVIDENCE_KIND_VALUES:
            raise ValueError(f"unsupported objective evidence kind: {self.evidence_kind}")
        if self.resolution_status not in EVIDENCE_RESOLUTION_STATUS_VALUES:
            raise ValueError(
                f"unsupported evidence resolution status: {self.resolution_status}"
            )
        if self.selection_status == "failed" and not _text(self.failure_reason):
            raise ValueError("failed objective evidence requires failure_reason")
        if self.selection_status == "extracted":
            if self.resolution_status not in {"resolved", "partial"}:
                raise ValueError("extracted evidence must be resolved or partial")
            if not self._has_scientific_content():
                raise ValueError("extracted evidence requires scientific content")
        if self.evidence_role in {"direct_result", "contradictory_result"}:
            if self.selection_status == "extracted" and not (
                self.value_payload or self.interpretation
            ):
                raise ValueError("result evidence requires an explicit outcome")

    @property
    def key(self) -> tuple[str, str, int, str]:
        return (
            self.collection_id,
            self.objective_id,
            self.analysis_version,
            self.evidence_id,
        )

    @property
    def supports_finding(self) -> bool:
        return (
            self.selection_status == "extracted"
            and self.resolution_status in {"resolved", "partial"}
            and self.evidence_role
            not in {"background_context", "irrelevant"}
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObjectiveEvidence":
        collection_id = _text(payload.get("collection_id")) or ""
        objective_id = _text(payload.get("objective_id")) or ""
        analysis_version = _positive_int_or_none(payload.get("analysis_version")) or 0
        document_id = _text(payload.get("document_id")) or ""
        source_kind = _choice(
            payload.get("source_kind"), SOURCE_KIND_VALUES, "text_window"
        )
        source_ref = _text(payload.get("source_ref")) or ""
        evidence_role = _choice(
            payload.get("evidence_role"), EVIDENCE_ROLE_VALUES, "irrelevant"
        )
        evidence_kind = _choice(
            payload.get("evidence_kind"), EVIDENCE_KIND_VALUES, "unknown"
        )
        evidence_id = _text(payload.get("evidence_id")) or _scoped_id(
            "oev",
            collection_id,
            objective_id,
            analysis_version,
            document_id,
            source_kind,
            source_ref,
            evidence_role,
            payload.get("semantic_slot") or evidence_kind,
        )
        return cls(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=analysis_version,
            evidence_id=evidence_id,
            document_id=document_id,
            source_kind=source_kind,
            source_ref=source_ref,
            source_excerpt=_text(payload.get("source_excerpt")) or "",
            page_numbers=_positive_ints(payload.get("page_numbers")),
            related_source_refs=_mapping_tuple(payload.get("related_source_refs")),
            evidence_role=evidence_role,
            selection_status=_choice(
                payload.get("selection_status"),
                OBJECTIVE_EVIDENCE_STATES,
                "candidate",
            ),
            selection_reason=_text(payload.get("selection_reason")),
            evidence_kind=evidence_kind,
            property_normalized=_text(payload.get("property_normalized")),
            material_system=_mapping(payload.get("material_system")),
            sample_context=_mapping(payload.get("sample_context")),
            process_context=_mapping(payload.get("process_context")),
            test_condition=_mapping(payload.get("test_condition")),
            resolved_condition=_mapping(payload.get("resolved_condition")),
            value_payload=_mapping(payload.get("value_payload")),
            unit=_text(payload.get("unit")),
            baseline_context=_mapping(payload.get("baseline_context")),
            interpretation=_text(payload.get("interpretation")),
            join_keys=_mapping(payload.get("join_keys")),
            anchor_ids=normalize_objective_terms(payload.get("anchor_ids")),
            resolution_status=_choice(
                payload.get("resolution_status"),
                EVIDENCE_RESOLUTION_STATUS_VALUES,
                "unknown",
            ),
            failure_reason=_text(payload.get("failure_reason")),
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def select(
        self,
        *,
        evidence_role: str,
        reason: str | None = None,
    ) -> "ObjectiveEvidence":
        if evidence_role not in EVIDENCE_ROLE_VALUES:
            raise ValueError(f"unsupported objective evidence role: {evidence_role}")
        return self._transition(
            "selected",
            evidence_role=evidence_role,
            selection_reason=_text(reason),
        )

    def mark_extracted(self, **scientific_content: Any) -> "ObjectiveEvidence":
        return self._transition(
            "extracted",
            resolution_status=scientific_content.pop("resolution_status", "resolved"),
            failure_reason=None,
            **scientific_content,
        )

    def reject(self, reason: str) -> "ObjectiveEvidence":
        return self._transition(
            "rejected",
            selection_reason=_required_text(reason, "rejected evidence requires reason"),
        )

    def fail(self, reason: str) -> "ObjectiveEvidence":
        return self._transition(
            "failed",
            failure_reason=_required_text(reason, "failed evidence requires reason"),
        )

    def _transition(self, target: str, **changes: Any) -> "ObjectiveEvidence":
        if target not in OBJECTIVE_EVIDENCE_STATE_TRANSITIONS[self.selection_status]:
            raise ValueError(
                "invalid objective evidence transition: "
                f"{self.selection_status} -> {target}"
            )
        return replace(self, selection_status=target, **changes)

    def _has_scientific_content(self) -> bool:
        return bool(
            self.property_normalized
            or self.material_system
            or self.sample_context
            or self.process_context
            or self.test_condition
            or self.resolved_condition
            or self.value_payload
            or self.baseline_context
            or self.interpretation
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "objective_id": self.objective_id,
            "analysis_version": self.analysis_version,
            "evidence_id": self.evidence_id,
            "document_id": self.document_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "source_excerpt": self.source_excerpt,
            "page_numbers": list(self.page_numbers),
            "related_source_refs": [dict(item) for item in self.related_source_refs],
            "evidence_role": self.evidence_role,
            "selection_status": self.selection_status,
            "selection_reason": self.selection_reason,
            "evidence_kind": self.evidence_kind,
            "property_normalized": self.property_normalized,
            "material_system": dict(self.material_system),
            "sample_context": dict(self.sample_context),
            "process_context": dict(self.process_context),
            "test_condition": dict(self.test_condition),
            "resolved_condition": dict(self.resolved_condition),
            "value_payload": dict(self.value_payload),
            "unit": self.unit,
            "baseline_context": dict(self.baseline_context),
            "interpretation": self.interpretation,
            "join_keys": dict(self.join_keys),
            "anchor_ids": list(self.anchor_ids),
            "resolution_status": self.resolution_status,
            "failure_reason": self.failure_reason,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ObjectiveFactSet:
    """Collection-build output containing candidate Objective definitions only."""

    research_objectives_ready: bool = False
    paper_skims: tuple[PaperSkim, ...] = ()
    research_objectives: tuple[ResearchObjective, ...] = ()


def build_research_objective_id(question: str) -> str:
    normalized_question = (_text(question) or "unspecified").lower()
    slug = _SLUG_NON_WORD_PATTERN.sub("-", normalized_question).strip("-")
    if not slug:
        slug = "unspecified"
    digest = sha1(normalized_question.encode("utf-8")).hexdigest()[:8]
    return f"obj_{slug[:72].strip('-')}_{digest}"


def is_question_shaped_objective(objective: ResearchObjective) -> bool:
    question = (_text(objective.question) or "").lower()
    return bool(
        question.endswith("?")
        or any(term in question for term in _QUESTION_SIGNAL_TERMS)
    )


def normalize_objective_terms(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        items = value.values()
    elif isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = (value,)
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _text(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return tuple(normalized)


def normalize_objective_confidence(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(numeric):
        return 0.0
    return round(min(1.0, max(0.0, numeric)), 4)


def _choice(value: Any, allowed: frozenset[str], default: str) -> str:
    normalized = (_text(value) or "").lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in allowed else default


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


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def _positive_int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def _positive_ints(value: Any) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple, set)):
        value = () if value is None else (value,)
    result: list[int] = []
    for item in value:
        numeric = _positive_int_or_none(item)
        if numeric is not None and numeric not in result:
            result.append(numeric)
    return tuple(result)


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


def _stable_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    if isinstance(value, (list, tuple, set)):
        return json.dumps(list(value), ensure_ascii=True, sort_keys=True, default=str)
    return str(value or "")


def _scoped_id(prefix: str, *parts: Any) -> str:
    payload = "|".join(_stable_text(part) for part in parts if part is not None)
    digest = sha1((payload or prefix).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"
