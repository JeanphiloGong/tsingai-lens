from __future__ import annotations

from dataclasses import dataclass, replace
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
SOURCE_KIND_VALUES: Final[frozenset[str]] = frozenset(
    {"text_window", "table", "figure"}
)
EVIDENCE_ROUTE_ROLE_VALUES: Final[frozenset[str]] = frozenset(
    {
        "current_experimental_evidence",
        "process_or_treatment",
        "test_condition",
        "composition_or_background",
        "characterization",
        "literature_comparison",
        "modeling_or_prediction",
        "low_value_or_irrelevant",
    }
)
EVIDENCE_UNIT_KIND_VALUES: Final[frozenset[str]] = frozenset(
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
OBJECTIVE_EVIDENCE_STATES: Final[frozenset[str]] = frozenset(
    {"candidate", "selected", "extracted", "rejected", "failed"}
)
OBJECTIVE_EVIDENCE_STATE_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "candidate": frozenset({"selected", "extracted", "rejected", "failed"}),
    "selected": frozenset({"extracted", "rejected", "failed"}),
    "extracted": frozenset(),
    "rejected": frozenset(),
    "failed": frozenset(),
}
LOGIC_CHAIN_SCOPE_VALUES: Final[frozenset[str]] = frozenset(
    {"objective", "paper", "cross_paper"}
)
OBJECTIVE_STATUSES: Final[frozenset[str]] = frozenset(
    {"candidate", "confirmed", "queued", "running", "ready", "failed"}
)
OBJECTIVE_STATUS_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "candidate": frozenset({"confirmed"}),
    "confirmed": frozenset({"queued"}),
    "queued": frozenset({"running", "failed"}),
    "running": frozenset({"ready", "failed"}),
    "ready": frozenset({"queued"}),
    "failed": frozenset({"queued"}),
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
            document_id=_normalize_text(payload.get("document_id") or payload.get("paper_id"))
            or "",
            title=_normalize_text(payload.get("title")),
            source_filename=_normalize_text(payload.get("source_filename")),
            doc_role=_normalize_text(payload.get("doc_role")) or "uncertain",
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
            evidence_density=_normalize_text(payload.get("evidence_density"))
            or "unknown",
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
    source_build_id: str | None = None
    status: str = "candidate"
    analysis_error: str | None = None
    analysis_progress: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchObjective":
        question = _normalize_text(payload.get("question")) or ""
        objective_id = _normalize_text(payload.get("objective_id")) or build_research_objective_id(
            question
        )
        return cls(
            objective_id=objective_id,
            question=question,
            material_scope=normalize_objective_terms(payload.get("material_scope")),
            process_axes=normalize_objective_terms(payload.get("process_axes")),
            property_axes=normalize_objective_terms(payload.get("property_axes")),
            comparison_intent=_normalize_text(payload.get("comparison_intent")),
            seed_document_ids=normalize_objective_terms(payload.get("seed_document_ids")),
            excluded_document_ids=normalize_objective_terms(
                payload.get("excluded_document_ids")
            ),
            confidence=normalize_objective_confidence(payload.get("confidence")),
            reason=_normalize_text(payload.get("reason")),
            source_build_id=_normalize_text(payload.get("source_build_id")),
            status=_normalize_choice(
                payload.get("status"),
                allowed=OBJECTIVE_STATUSES,
                default="candidate",
            ),
            analysis_error=_normalize_text(payload.get("analysis_error")),
            analysis_progress=_normalize_optional_mapping(
                payload.get("analysis_progress")
            ),
            created_at=_normalize_text(payload.get("created_at")),
            updated_at=_normalize_text(payload.get("updated_at")),
        )

    def confirm(self) -> "ResearchObjective":
        return self._transition("confirmed")

    def queue(self) -> "ResearchObjective":
        return self._transition(
            "queued",
            analysis_error=None,
            analysis_progress={
                "phase": "queued",
                "unit": "steps",
                "message": "Objective analysis is queued.",
            },
        )

    def start(self) -> "ResearchObjective":
        return self._transition(
            "running",
            analysis_error=None,
            analysis_progress={
                "phase": "objective_analysis_started",
                "unit": "steps",
                "message": "Objective analysis has started.",
            },
        )

    def update_progress(
        self,
        analysis_progress: Mapping[str, Any],
    ) -> "ResearchObjective":
        if self.status != "running":
            raise ValueError(
                f"cannot update objective progress while status is {self.status}"
            )
        if not analysis_progress:
            raise ValueError("objective analysis progress must not be empty")
        return replace(self, analysis_progress=dict(analysis_progress))

    def complete(self) -> "ResearchObjective":
        return self._transition(
            "ready",
            analysis_error=None,
            analysis_progress={
                "phase": "objective_analysis_completed",
                "unit": "steps",
                "message": "Objective analysis has completed.",
            },
        )

    def fail(self, error: str) -> "ResearchObjective":
        normalized_error = str(error or "").strip()
        if not normalized_error:
            raise ValueError("objective analysis error must not be empty")
        return self._transition(
            "failed",
            analysis_error=normalized_error,
            analysis_progress={
                "phase": "objective_analysis_failed",
                "unit": "steps",
                "message": "Objective analysis has failed.",
            },
        )

    def _transition(
        self,
        target: str,
        *,
        analysis_error: str | None = None,
        analysis_progress: Mapping[str, Any] | None = None,
    ) -> "ResearchObjective":
        require_objective_status_transition(self.status, target)
        return replace(
            self,
            status=target,
            analysis_error=analysis_error,
            analysis_progress=(
                dict(analysis_progress) if analysis_progress is not None else None
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
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
        }

    def to_workspace_record(self) -> dict[str, Any]:
        return {
            **self.to_record(),
            "source_build_id": self.source_build_id,
            "status": self.status,
            "analysis_error": self.analysis_error,
            "analysis_progress": (
                dict(self.analysis_progress)
                if self.analysis_progress is not None
                else None
            ),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ObjectiveContext:
    objective_id: str
    question: str
    material_scope: tuple[str, ...]
    variable_process_axes: tuple[str, ...]
    process_context_axes: tuple[str, ...]
    target_property_axes: tuple[str, ...]
    excluded_property_axes: tuple[str, ...]
    objective_evidence_lens: dict[str, Any]
    routing_hints: tuple[dict[str, Any], ...]
    extraction_guidance: dict[str, Any]
    confidence: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObjectiveContext":
        return cls(
            objective_id=_normalize_text(payload.get("objective_id")) or "",
            question=_normalize_text(payload.get("question")) or "",
            material_scope=normalize_objective_terms(payload.get("material_scope")),
            variable_process_axes=normalize_objective_terms(
                payload.get("variable_process_axes")
            ),
            process_context_axes=normalize_objective_terms(
                payload.get("process_context_axes")
            ),
            target_property_axes=normalize_objective_terms(
                payload.get("target_property_axes")
            ),
            excluded_property_axes=normalize_objective_terms(
                payload.get("excluded_property_axes")
            ),
            objective_evidence_lens=_normalize_objective_evidence_lens(payload),
            routing_hints=_normalize_mapping_tuple(payload.get("routing_hints")),
            extraction_guidance=_normalize_mapping(payload.get("extraction_guidance")),
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "question": self.question,
            "material_scope": list(self.material_scope),
            "variable_process_axes": list(self.variable_process_axes),
            "process_context_axes": list(self.process_context_axes),
            "target_property_axes": list(self.target_property_axes),
            "excluded_property_axes": list(self.excluded_property_axes),
            "objective_evidence_lens": dict(self.objective_evidence_lens),
            "routing_hints": [dict(item) for item in self.routing_hints],
            "extraction_guidance": dict(self.extraction_guidance),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ObjectivePaperFrame:
    frame_id: str
    objective_id: str
    document_id: str
    relevance: str
    paper_role: str
    background: str | None
    material_match: tuple[str, ...]
    changed_variables: tuple[str, ...]
    measured_property_scope: tuple[str, ...]
    test_environment_scope: tuple[str, ...]
    relevant_sections: tuple[str, ...]
    relevant_tables: tuple[str, ...]
    excluded_tables: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObjectivePaperFrame":
        objective_id = _normalize_text(payload.get("objective_id")) or ""
        document_id = (
            _normalize_text(payload.get("document_id") or payload.get("paper_id")) or ""
        )
        return cls(
            frame_id=_normalize_text(payload.get("frame_id"))
            or _build_scoped_id("opf", objective_id, document_id),
            objective_id=objective_id,
            document_id=document_id,
            relevance=_normalize_choice(
                payload.get("relevance"),
                allowed=PAPER_RELEVANCE_VALUES,
                default="uncertain",
            ),
            paper_role=_normalize_choice(
                payload.get("paper_role"),
                allowed=PAPER_ROLE_VALUES,
                default="uncertain",
            ),
            background=_normalize_text(payload.get("background")),
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
            relevant_sections=normalize_objective_terms(
                payload.get("relevant_sections")
            ),
            relevant_tables=normalize_objective_terms(payload.get("relevant_tables")),
            excluded_tables=normalize_objective_terms(payload.get("excluded_tables")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "relevance": self.relevance,
            "paper_role": self.paper_role,
            "background": self.background,
            "material_match": list(self.material_match),
            "changed_variables": list(self.changed_variables),
            "measured_property_scope": list(self.measured_property_scope),
            "test_environment_scope": list(self.test_environment_scope),
            "relevant_sections": list(self.relevant_sections),
            "relevant_tables": list(self.relevant_tables),
            "excluded_tables": list(self.excluded_tables),
        }


@dataclass(frozen=True)
class ObjectiveEvidenceRoute:
    route_id: str
    objective_id: str
    document_id: str
    source_kind: str
    source_ref: str
    role: str
    extractable: bool
    reason: str | None
    table_schema: dict[str, Any]
    column_roles: dict[str, Any]
    join_keys: dict[str, Any]
    join_plan: dict[str, Any]
    confidence: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObjectiveEvidenceRoute":
        objective_id = _normalize_text(payload.get("objective_id")) or ""
        document_id = (
            _normalize_text(payload.get("document_id") or payload.get("paper_id")) or ""
        )
        source_kind = _normalize_choice(
            payload.get("source_kind"),
            allowed=SOURCE_KIND_VALUES,
            default="text_window",
        )
        source_ref = _normalize_text(payload.get("source_ref")) or ""
        role = _normalize_choice(
            payload.get("role"),
            allowed=EVIDENCE_ROUTE_ROLE_VALUES,
            default="low_value_or_irrelevant",
        )
        return cls(
            route_id=_normalize_text(payload.get("route_id"))
            or _build_scoped_id(
                "oer",
                objective_id,
                document_id,
                source_kind,
                source_ref,
                role,
            ),
            objective_id=objective_id,
            document_id=document_id,
            source_kind=source_kind,
            source_ref=source_ref,
            role=role,
            extractable=_normalize_bool(payload.get("extractable")),
            reason=_normalize_text(payload.get("reason")),
            table_schema=_normalize_mapping(payload.get("table_schema")),
            column_roles=_normalize_mapping(payload.get("column_roles")),
            join_keys=_normalize_mapping(payload.get("join_keys")),
            join_plan=_normalize_mapping(payload.get("join_plan")),
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "role": self.role,
            "extractable": self.extractable,
            "reason": self.reason,
            "table_schema": dict(self.table_schema),
            "column_roles": dict(self.column_roles),
            "join_keys": dict(self.join_keys),
            "join_plan": dict(self.join_plan),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ObjectiveEvidenceUnit:
    evidence_unit_id: str
    objective_id: str
    document_id: str
    source_kind: str | None
    source_ref: str | None
    evidence_role: str | None
    selection_reason: str | None
    selection_status: str
    unit_kind: str
    property_normalized: str | None
    material_system: dict[str, Any]
    sample_context: dict[str, Any]
    process_context: dict[str, Any]
    resolved_condition: dict[str, Any]
    test_condition: dict[str, Any]
    value_payload: dict[str, Any]
    unit: str | None
    baseline_context: dict[str, Any]
    interpretation: str | None
    source_refs: tuple[dict[str, Any], ...]
    evidence_anchor_ids: tuple[str, ...]
    join_keys: dict[str, Any]
    resolution_status: str
    confidence: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObjectiveEvidenceUnit":
        objective_id = _normalize_text(payload.get("objective_id")) or ""
        document_id = (
            _normalize_text(payload.get("document_id") or payload.get("paper_id")) or ""
        )
        unit_kind = _normalize_choice(
            payload.get("unit_kind"),
            allowed=EVIDENCE_UNIT_KIND_VALUES,
            default="unknown",
        )
        property_normalized = _normalize_text(payload.get("property_normalized"))
        source_refs = _normalize_mapping_sequence(payload.get("source_refs"))
        first_source_ref = source_refs[0] if source_refs else {}
        return cls(
            evidence_unit_id=_normalize_text(payload.get("evidence_unit_id"))
            or _build_scoped_id(
                "oeu",
                objective_id,
                document_id,
                unit_kind,
                property_normalized,
                _stable_payload(source_refs),
                _stable_payload(payload.get("value_payload")),
            ),
            objective_id=objective_id,
            document_id=document_id,
            source_kind=(
                _normalize_text(payload.get("source_kind"))
                or _normalize_text(first_source_ref.get("source_kind"))
            ),
            source_ref=(
                _normalize_text(payload.get("source_ref"))
                or _normalize_text(first_source_ref.get("source_ref"))
            ),
            evidence_role=(
                _normalize_text(payload.get("evidence_role"))
                or _normalize_text(first_source_ref.get("evidence_role"))
            ),
            selection_reason=(
                _normalize_text(payload.get("selection_reason"))
                or _normalize_text(first_source_ref.get("selection_reason"))
            ),
            selection_status=_normalize_choice(
                payload.get("selection_status"),
                allowed=OBJECTIVE_EVIDENCE_STATES,
                default="extracted",
            ),
            unit_kind=unit_kind,
            property_normalized=property_normalized,
            material_system=_normalize_mapping(payload.get("material_system")),
            sample_context=_normalize_mapping(payload.get("sample_context")),
            process_context=_normalize_mapping(payload.get("process_context")),
            resolved_condition=_normalize_mapping(payload.get("resolved_condition")),
            test_condition=_normalize_mapping(payload.get("test_condition")),
            value_payload=_normalize_mapping(payload.get("value_payload")),
            unit=_normalize_text(payload.get("unit")),
            baseline_context=_normalize_mapping(payload.get("baseline_context")),
            interpretation=_normalize_text(payload.get("interpretation")),
            source_refs=source_refs,
            evidence_anchor_ids=normalize_objective_terms(
                payload.get("evidence_anchor_ids")
            ),
            join_keys=_normalize_mapping(payload.get("join_keys")),
            resolution_status=_normalize_choice(
                payload.get("resolution_status"),
                allowed=EVIDENCE_RESOLUTION_STATUS_VALUES,
                default="unknown",
            ),
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def select(
        self,
        *,
        evidence_role: str,
        reason: str | None = None,
    ) -> "ObjectiveEvidenceUnit":
        return self._evidence_transition(
            "selected",
            evidence_role=evidence_role,
            selection_reason=reason,
        )

    def mark_extracted(self) -> "ObjectiveEvidenceUnit":
        return self._evidence_transition("extracted")

    def reject(self, reason: str | None = None) -> "ObjectiveEvidenceUnit":
        return self._evidence_transition(
            "rejected",
            selection_reason=reason or self.selection_reason,
        )

    def fail(self, reason: str) -> "ObjectiveEvidenceUnit":
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise ValueError("objective evidence failure reason must not be empty")
        return self._evidence_transition(
            "failed",
            selection_reason=normalized_reason,
        )

    def _evidence_transition(
        self,
        target: str,
        *,
        evidence_role: str | None = None,
        selection_reason: str | None = None,
    ) -> "ObjectiveEvidenceUnit":
        allowed_targets = OBJECTIVE_EVIDENCE_STATE_TRANSITIONS.get(
            self.selection_status,
            frozenset(),
        )
        if target not in allowed_targets:
            raise ValueError(
                "invalid objective evidence transition: "
                f"{self.selection_status} -> {target}"
            )
        return replace(
            self,
            selection_status=target,
            evidence_role=evidence_role or self.evidence_role,
            selection_reason=selection_reason,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "evidence_unit_id": self.evidence_unit_id,
            "objective_id": self.objective_id,
            "document_id": self.document_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "evidence_role": self.evidence_role,
            "selection_reason": self.selection_reason,
            "selection_status": self.selection_status,
            "unit_kind": self.unit_kind,
            "property_normalized": self.property_normalized,
            "material_system": dict(self.material_system),
            "sample_context": dict(self.sample_context),
            "process_context": dict(self.process_context),
            "resolved_condition": dict(self.resolved_condition),
            "test_condition": dict(self.test_condition),
            "value_payload": dict(self.value_payload),
            "unit": self.unit,
            "baseline_context": dict(self.baseline_context),
            "interpretation": self.interpretation,
            "source_refs": [dict(item) for item in self.source_refs],
            "evidence_anchor_ids": list(self.evidence_anchor_ids),
            "join_keys": dict(self.join_keys),
            "resolution_status": self.resolution_status,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ObjectiveLogicChain:
    logic_chain_id: str
    objective_id: str
    chain_scope: str
    document_id: str | None
    question: str | None
    evidence_unit_ids: tuple[str, ...]
    chain_payload: dict[str, Any]
    summary: str | None
    confidence: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObjectiveLogicChain":
        objective_id = _normalize_text(payload.get("objective_id")) or ""
        chain_scope = _normalize_choice(
            payload.get("chain_scope"),
            allowed=LOGIC_CHAIN_SCOPE_VALUES,
            default="objective",
        )
        document_id = _normalize_text(payload.get("document_id") or payload.get("paper_id"))
        evidence_unit_ids = normalize_objective_terms(payload.get("evidence_unit_ids"))
        return cls(
            logic_chain_id=_normalize_text(payload.get("logic_chain_id"))
            or _build_scoped_id(
                "olc",
                objective_id,
                chain_scope,
                document_id,
                _stable_payload(evidence_unit_ids),
            ),
            objective_id=objective_id,
            chain_scope=chain_scope,
            document_id=document_id,
            question=_normalize_text(payload.get("question")),
            evidence_unit_ids=evidence_unit_ids,
            chain_payload=_normalize_mapping(payload.get("chain_payload")),
            summary=_normalize_text(payload.get("summary")),
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "logic_chain_id": self.logic_chain_id,
            "objective_id": self.objective_id,
            "chain_scope": self.chain_scope,
            "document_id": self.document_id,
            "question": self.question,
            "evidence_unit_ids": list(self.evidence_unit_ids),
            "chain_payload": dict(self.chain_payload),
            "summary": self.summary,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ObjectiveFactSet:
    research_objectives_ready: bool = False
    paper_skims: tuple[PaperSkim, ...] = ()
    research_objectives: tuple[ResearchObjective, ...] = ()
    objective_contexts: tuple[ObjectiveContext, ...] = ()
    objective_paper_frames: tuple[ObjectivePaperFrame, ...] = ()
    objective_evidence_routes: tuple[ObjectiveEvidenceRoute, ...] = ()
    objective_evidence_units: tuple[ObjectiveEvidenceUnit, ...] = ()
    objective_logic_chains: tuple[ObjectiveLogicChain, ...] = ()


@dataclass(frozen=True)
class ObjectiveAnalysisWorkspace:
    """Bounded analysis state for one objective run."""

    collection_id: str
    objective: ResearchObjective
    objective_context: ObjectiveContext | None
    paper_frames: tuple[ObjectivePaperFrame, ...]
    evidence_units: tuple[ObjectiveEvidenceUnit, ...]
    logic_chain: ObjectiveLogicChain | None

    def __post_init__(self) -> None:
        objective_id = self.objective.objective_id
        if not _normalize_text(self.collection_id):
            raise ValueError("objective analysis workspace requires collection_id")
        if self.objective_context is not None and (
            self.objective_context.objective_id != objective_id
        ):
            raise ValueError("objective context does not belong to objective")
        members = (*self.paper_frames, *self.evidence_units)
        if any(member.objective_id != objective_id for member in members):
            raise ValueError("objective analysis workspace member has wrong objective")
        if self.logic_chain is not None:
            if self.logic_chain.objective_id != objective_id:
                raise ValueError("objective logic chain does not belong to objective")
            evidence_ids = {unit.evidence_unit_id for unit in self.evidence_units}
            missing_ids = set(self.logic_chain.evidence_unit_ids) - evidence_ids
            if missing_ids:
                raise ValueError(
                    "objective logic chain references missing evidence units: "
                    + ", ".join(sorted(missing_ids))
                )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObjectiveAnalysisWorkspace":
        objective_payload = payload.get("objective")
        objective = (
            objective_payload
            if isinstance(objective_payload, ResearchObjective)
            else ResearchObjective.from_mapping(
                _normalize_mapping(objective_payload)
            )
        )
        context_payload = payload.get("objective_context")
        objective_context = (
            context_payload
            if isinstance(context_payload, ObjectiveContext)
            else (
                ObjectiveContext.from_mapping(_normalize_mapping(context_payload))
                if isinstance(context_payload, Mapping)
                else None
            )
        )
        paper_frames = tuple(
            frame
            if isinstance(frame, ObjectivePaperFrame)
            else ObjectivePaperFrame.from_mapping(_normalize_mapping(frame))
            for frame in payload.get("paper_frames") or ()
            if isinstance(frame, (ObjectivePaperFrame, Mapping))
        )
        evidence_units = tuple(
            unit
            if isinstance(unit, ObjectiveEvidenceUnit)
            else ObjectiveEvidenceUnit.from_mapping(_normalize_mapping(unit))
            for unit in payload.get("evidence_units") or ()
            if isinstance(unit, (ObjectiveEvidenceUnit, Mapping))
        )
        logic_chain_payload = payload.get("logic_chain")
        logic_chain = (
            logic_chain_payload
            if isinstance(logic_chain_payload, ObjectiveLogicChain)
            else (
                ObjectiveLogicChain.from_mapping(
                    _normalize_mapping(logic_chain_payload)
                )
                if isinstance(logic_chain_payload, Mapping)
                else None
            )
        )
        return cls(
            collection_id=_normalize_text(payload.get("collection_id")) or "",
            objective=objective,
            objective_context=objective_context,
            paper_frames=paper_frames,
            evidence_units=evidence_units,
            logic_chain=logic_chain,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "objective": self.objective.to_workspace_record(),
            "objective_context": (
                self.objective_context.to_record()
                if self.objective_context is not None
                else None
            ),
            "paper_frames": [frame.to_record() for frame in self.paper_frames],
            "evidence_units": [unit.to_record() for unit in self.evidence_units],
            "logic_chain": (
                self.logic_chain.to_record()
                if self.logic_chain is not None
                else None
            ),
        }


def build_research_objective_id(question: str) -> str:
    normalized_question = (_normalize_text(question) or "unspecified").lower()
    slug = _SLUG_NON_WORD_PATTERN.sub("-", normalized_question).strip("-")
    if not slug:
        slug = "unspecified"
    digest = sha1(normalized_question.encode("utf-8")).hexdigest()[:8]
    return f"obj_{slug[:72].strip('-')}_{digest}"


def require_objective_status_transition(current: str, target: str) -> None:
    if target not in OBJECTIVE_STATUS_TRANSITIONS.get(current, frozenset()):
        raise ValueError(f"invalid objective status transition: {current} -> {target}")


def normalize_objective_terms(value: Any) -> tuple[str, ...]:
    if _is_missing(value):
        return ()
    if hasattr(value, "tolist") and not isinstance(
        value,
        (str, bytes, bytearray, dict),
    ):
        value = value.tolist()
    if isinstance(value, dict):
        values = value.values()
    elif isinstance(value, set):
        values = sorted(value, key=lambda item: str(item))
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        text = _normalize_text(value)
        return (text,) if text else ()

    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _normalize_text(item)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return tuple(normalized)


def normalize_objective_confidence(value: Any) -> float:
    try:
        if _is_missing(value):
            return 0.0
        return round(min(1.0, max(0.0, float(value))), 2)
    except (TypeError, ValueError):
        return 0.0


def is_question_shaped_objective(objective: ResearchObjective) -> bool:
    question = (_normalize_text(objective.question) or "").lower()
    if len(question) < 12:
        return False
    if question in {term.lower() for term in objective.material_scope}:
        return False
    return any(term in question for term in _QUESTION_SIGNAL_TERMS)


def _normalize_objective_evidence_lens(payload: Mapping[str, Any]) -> dict[str, Any]:
    lens = _normalize_mapping(payload.get("objective_evidence_lens"))
    if lens:
        return lens
    target_axes = normalize_objective_terms(payload.get("target_property_axes"))
    variable_axes = normalize_objective_terms(payload.get("variable_process_axes"))
    material_scope = normalize_objective_terms(payload.get("material_scope"))
    context_axes = normalize_objective_terms(payload.get("process_context_axes"))
    excluded_axes = normalize_objective_terms(payload.get("excluded_property_axes"))
    return {
        "target_outcome_axes": list(target_axes),
        "mediator_axes": [],
        "variable_process_axes": list(variable_axes),
        "context_axes": [*material_scope, *context_axes],
        "excluded_axes": list(excluded_axes),
        "direct_support_rules": [
            "Direct support must explicitly report, compare, or explain at least one target_outcome_axis.",
            "Variable, material, and test context alone can bind evidence but cannot by themselves support a claim.",
        ],
    }


def _normalize_text(value: Any) -> str | None:
    if _is_missing(value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            value = value.item()
        except Exception:
            pass
    text = str(value).strip()
    return text or None


def _normalize_choice(
    value: Any,
    *,
    allowed: frozenset[str],
    default: str,
) -> str:
    text = (_normalize_text(value) or "").lower().replace("-", "_").replace(" ", "_")
    return text if text in allowed else default


def _normalize_bool(value: Any) -> bool:
    if _is_missing(value):
        return False
    if isinstance(value, bool):
        return value
    text = (_normalize_text(value) or "").lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return bool(value)


def _normalize_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _normalize_optional_mapping(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return _normalize_mapping(value)


def _normalize_mapping_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(_normalize_mapping(item) for item in value if isinstance(item, Mapping))


def _normalize_mapping_sequence(value: Any) -> tuple[dict[str, Any], ...]:
    if isinstance(value, Mapping):
        return (_normalize_mapping(value),)
    return _normalize_mapping_tuple(value)


def _build_scoped_id(prefix: str, *parts: Any) -> str:
    seed = "|".join(_normalize_text(part) or "" for part in parts) or "unspecified"
    digest = sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _stable_payload(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


__all__ = [
    "EVIDENCE_RESOLUTION_STATUS_VALUES",
    "EVIDENCE_ROUTE_ROLE_VALUES",
    "EVIDENCE_UNIT_KIND_VALUES",
    "LOGIC_CHAIN_SCOPE_VALUES",
    "OBJECTIVE_STATUSES",
    "OBJECTIVE_STATUS_TRANSITIONS",
    "ObjectiveContext",
    "ObjectiveAnalysisWorkspace",
    "ObjectiveEvidenceRoute",
    "ObjectiveEvidenceUnit",
    "ObjectiveFactSet",
    "ObjectiveLogicChain",
    "ObjectivePaperFrame",
    "PAPER_RELEVANCE_VALUES",
    "PAPER_ROLE_VALUES",
    "PaperSkim",
    "ResearchObjective",
    "SOURCE_KIND_VALUES",
    "build_research_objective_id",
    "is_question_shaped_objective",
    "normalize_objective_confidence",
    "normalize_objective_terms",
    "require_objective_status_transition",
]
