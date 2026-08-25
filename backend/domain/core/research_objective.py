from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from hashlib import sha1
import json
import math
import re
from typing import Any, Final, Mapping

from domain.pipeline import ExecutionStats


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
PAPER_EVIDENCE_DISPOSITIONS: Final[frozenset[str]] = frozenset(
    {
        "excluded",
        "no_routable_evidence",
        "extraction_failed",
        "no_comparable_evidence",
        "comparable_evidence",
    }
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
EVIDENCE_ATTRIBUTION_SCOPES: Final[frozenset[str]] = frozenset(
    {
        "isolated_effect",
        "joint_effect",
        "association_only",
        "descriptive_only",
        "not_attributable",
    }
)
EVIDENCE_RESULT_DIRECTIONS: Final[frozenset[str]] = frozenset(
    {
        "increase",
        "decrease",
        "improve",
        "worsen",
        "changed",
        "no_change",
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
OBJECTIVE_ORIGINS: Final[frozenset[str]] = frozenset(
    {"system_discovered", "chat_assisted"}
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
_PAPER_STUDY_SOURCE_KINDS = frozenset(
    {"document", "block", "table", "table_row", "figure"}
)


@dataclass(frozen=True)
class PaperStudySourceRef:
    """Stable Source locator supporting a paper-level study fact."""

    source_kind: str
    source_ref: str

    def __post_init__(self) -> None:
        if not self.source_kind.strip() or not self.source_ref.strip():
            raise ValueError("paper study source reference cannot be empty")
        if self.source_kind not in _PAPER_STUDY_SOURCE_KINDS:
            raise ValueError(
                f"unsupported paper study source kind: {self.source_kind}"
            )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperStudySourceRef":
        return cls(
            source_kind=_text(payload.get("source_kind")) or "",
            source_ref=_text(payload.get("source_ref")) or "",
        )

    def to_record(self) -> dict[str, str]:
        return {
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
        }


def _paper_study_source_refs(value: Any) -> tuple[PaperStudySourceRef, ...]:
    refs: list[PaperStudySourceRef] = []
    seen: set[tuple[str, str]] = set()
    for item in value or ():
        if not isinstance(item, Mapping):
            continue
        source_ref = PaperStudySourceRef.from_mapping(item)
        key = (source_ref.source_kind, source_ref.source_ref)
        if key in seen:
            continue
        seen.add(key)
        refs.append(source_ref)
    return tuple(refs)


@dataclass(frozen=True)
class PaperStudyRelationship:
    """One Source-supported joint-factor-to-outcome candidate-scope link."""

    relationship_id: str
    varied_factors: tuple[str, ...]
    outcome: str
    source_refs: tuple[PaperStudySourceRef, ...]
    confidence: float

    def __post_init__(self) -> None:
        if not self.relationship_id.strip():
            raise ValueError("paper study relationship requires relationship_id")
        if not self.varied_factors:
            raise ValueError("paper study relationship requires varied factors")
        if not self.outcome.strip():
            raise ValueError("paper study relationship requires an outcome")
        if not self.source_refs:
            raise ValueError("paper study relationship requires a source reference")

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        parent_study_boundary: str | None = None,
    ) -> "PaperStudyRelationship":
        varied_factors = normalize_objective_terms(payload.get("varied_factors"))
        outcome = _text(payload.get("outcome")) or ""
        source_refs = _paper_study_source_refs(payload.get("source_refs"))
        relationship_id = _text(payload.get("relationship_id"))
        if relationship_id is None:
            identity = json.dumps(
                {
                    "document_id": (_text(payload.get("document_id")) or "").casefold(),
                    "parent_study_boundary": parent_study_boundary,
                    "varied_factors": sorted(
                        value.casefold() for value in varied_factors
                    ),
                    "outcome": outcome.casefold(),
                    "source_refs": sorted(
                        (item.source_kind, item.source_ref) for item in source_refs
                    ),
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            relationship_id = (
                f"relationship_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
            )
        return cls(
            relationship_id=relationship_id,
            varied_factors=varied_factors,
            outcome=outcome,
            source_refs=source_refs,
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "relationship_id": self.relationship_id,
            "varied_factors": list(self.varied_factors),
            "outcome": self.outcome,
            "source_refs": [item.to_record() for item in self.source_refs],
            "confidence": self.confidence,
        }


_PAPER_STUDY_DESIGN_TYPES = frozenset(
    {"experimental", "observational", "modeling", "mixed", "uncertain"}
)
_PAPER_STUDY_CLAIM_SCOPES = frozenset(
    {"current_work", "synthesis", "background", "uncertain"}
)


@dataclass(frozen=True)
class PaperStudy:
    """One paper-owned research-scope group used for Objective screening."""

    study_id: str
    document_id: str
    design_type: str
    claim_scope: str
    experiment_label: str | None
    material_scope: tuple[str, ...]
    process_context: tuple[str, ...]
    sample_context: tuple[str, ...]
    test_context: tuple[str, ...]
    comparator: str | None
    fixed_conditions: tuple[str, ...]
    relationships: tuple[PaperStudyRelationship, ...]
    confidence: float

    def __post_init__(self) -> None:
        if not self.study_id.strip() or not self.document_id.strip():
            raise ValueError("paper study requires study and document ids")
        if self.design_type not in _PAPER_STUDY_DESIGN_TYPES:
            raise ValueError(f"unsupported paper study design type: {self.design_type}")
        if self.claim_scope not in _PAPER_STUDY_CLAIM_SCOPES:
            raise ValueError(f"unsupported paper study claim scope: {self.claim_scope}")
        object.__setattr__(self, "relationships", tuple(self.relationships))
        if not self.relationships:
            raise ValueError("paper study requires at least one relationship")
        relationship_ids = [item.relationship_id for item in self.relationships]
        if len(relationship_ids) != len(set(relationship_ids)):
            raise ValueError("paper study relationship ids must be unique")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperStudy":
        document_id = _text(payload.get("document_id")) or ""
        design_type = _text(payload.get("design_type")) or "uncertain"
        claim_scope = _text(payload.get("claim_scope")) or "uncertain"
        experiment_label = _text(payload.get("experiment_label"))
        material_scope = normalize_objective_terms(payload.get("material_scope"))
        process_context = normalize_objective_terms(payload.get("process_context"))
        sample_context = normalize_objective_terms(payload.get("sample_context"))
        test_context = normalize_objective_terms(payload.get("test_context"))
        comparator = _text(payload.get("comparator"))
        fixed_conditions = normalize_objective_terms(payload.get("fixed_conditions"))
        parent_study_boundary = json.dumps(
            {
                "document_id": document_id.casefold(),
                "design_type": design_type,
                "claim_scope": claim_scope,
                "experiment_label": (
                    experiment_label.casefold() if experiment_label else None
                ),
                "material_scope": sorted(value.casefold() for value in material_scope),
                "process_context": sorted(
                    value.casefold() for value in process_context
                ),
                "sample_context": sorted(value.casefold() for value in sample_context),
                "test_context": sorted(value.casefold() for value in test_context),
                "comparator": comparator.casefold() if comparator else None,
                "fixed_conditions": sorted(
                    value.casefold() for value in fixed_conditions
                ),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        relationships = tuple(
            PaperStudyRelationship.from_mapping(
                {**dict(item), "document_id": document_id},
                parent_study_boundary=parent_study_boundary,
            )
            for item in payload.get("relationships") or ()
            if isinstance(item, Mapping)
        )
        study_id = _text(payload.get("study_id"))
        if study_id is None:
            identity = json.dumps(
                {
                    "document_id": document_id.casefold(),
                    "design_type": design_type,
                    "claim_scope": claim_scope,
                    "experiment_label": (
                        experiment_label.casefold() if experiment_label else None
                    ),
                    "material_scope": sorted(
                        value.casefold() for value in material_scope
                    ),
                    "process_context": sorted(
                        value.casefold() for value in process_context
                    ),
                    "sample_context": sorted(
                        value.casefold() for value in sample_context
                    ),
                    "test_context": sorted(
                        value.casefold() for value in test_context
                    ),
                    "comparator": comparator.casefold() if comparator else None,
                    "fixed_conditions": sorted(
                        value.casefold() for value in fixed_conditions
                    ),
                    "relationship_ids": sorted(
                        item.relationship_id for item in relationships
                    ),
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            study_id = f"study_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
        return cls(
            study_id=study_id,
            document_id=document_id,
            design_type=design_type,
            claim_scope=claim_scope,
            experiment_label=experiment_label,
            material_scope=material_scope,
            process_context=process_context,
            sample_context=sample_context,
            test_context=test_context,
            comparator=comparator,
            fixed_conditions=fixed_conditions,
            relationships=relationships,
            confidence=normalize_objective_confidence(payload.get("confidence")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "study_id": self.study_id,
            "document_id": self.document_id,
            "design_type": self.design_type,
            "claim_scope": self.claim_scope,
            "experiment_label": self.experiment_label,
            "material_scope": list(self.material_scope),
            "process_context": list(self.process_context),
            "sample_context": list(self.sample_context),
            "test_context": list(self.test_context),
            "comparator": self.comparator,
            "fixed_conditions": list(self.fixed_conditions),
            "relationships": [item.to_record() for item in self.relationships],
            "confidence": self.confidence,
        }


class PaperStudyDispositionStatus(StrEnum):
    PENDING = "pending"
    PROMOTED = "promoted"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PaperStudyDisposition:
    """Collection-level accounting result for one paper-study relationship."""

    document_id: str
    study_id: str
    relationship_id: str
    status: PaperStudyDispositionStatus
    objective_id: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.document_id, self.study_id, self.relationship_id)
        ):
            raise ValueError(
                "paper study disposition requires document, study, and relationship ids"
            )
        object.__setattr__(self, "status", self._status(self.status))
        if self.status is PaperStudyDispositionStatus.PROMOTED:
            if not _text(self.objective_id):
                raise ValueError("promoted paper study disposition requires objective_id")
            if _text(self.reason):
                raise ValueError("promoted paper study disposition cannot have a reason")
        elif self.status is PaperStudyDispositionStatus.REJECTED:
            if _text(self.objective_id):
                raise ValueError("rejected paper study disposition cannot link an objective")
            if not _text(self.reason):
                raise ValueError("rejected paper study disposition requires a reason")
        elif _text(self.objective_id) or _text(self.reason):
            raise ValueError("pending paper study disposition cannot have a result")

    @staticmethod
    def _status(value: Any) -> PaperStudyDispositionStatus:
        if isinstance(value, PaperStudyDispositionStatus):
            return value
        try:
            return PaperStudyDispositionStatus(str(value))
        except ValueError as exc:
            raise ValueError(f"unsupported paper study disposition status: {value}") from exc

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "PaperStudyDisposition":
        return cls(
            document_id=_text(payload.get("document_id")) or "",
            study_id=_text(payload.get("study_id")) or "",
            relationship_id=_text(payload.get("relationship_id")) or "",
            status=cls._status(payload.get("status") or "pending"),
            objective_id=_text(payload.get("objective_id")),
            reason=_text(payload.get("reason")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "study_id": self.study_id,
            "relationship_id": self.relationship_id,
            "status": self.status.value,
            "objective_id": self.objective_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PaperStudySignal:
    """One source-linked factor or outcome awaiting a paper-study link."""

    signal_id: str
    signal_type: str
    label: str
    design_type: str
    claim_scope: str
    experiment_label: str | None
    material_scope: tuple[str, ...]
    process_context: tuple[str, ...]
    sample_context: tuple[str, ...]
    test_context: tuple[str, ...]
    comparator: str | None
    fixed_conditions: tuple[str, ...]
    source_refs: tuple[PaperStudySourceRef, ...]
    confidence: float
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.signal_type not in {"variable", "outcome"}:
            raise ValueError("paper study signal type must be variable or outcome")
        if self.design_type not in _PAPER_STUDY_DESIGN_TYPES:
            raise ValueError(
                f"unsupported paper study signal design type: {self.design_type}"
            )
        if self.claim_scope not in _PAPER_STUDY_CLAIM_SCOPES:
            raise ValueError(
                f"unsupported paper study signal claim scope: {self.claim_scope}"
            )
        if not self.label.strip():
            raise ValueError("paper study signal label cannot be empty")
        if not self.source_refs:
            raise ValueError("paper study signal requires at least one source")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperStudySignal":
        signal_type = _text(payload.get("signal_type")) or ""
        label = _text(payload.get("label")) or ""
        design_type = _text(payload.get("design_type")) or "uncertain"
        claim_scope = _text(payload.get("claim_scope")) or "uncertain"
        experiment_label = _text(payload.get("experiment_label"))
        material_scope = normalize_objective_terms(payload.get("material_scope"))
        process_context = normalize_objective_terms(payload.get("process_context"))
        sample_context = normalize_objective_terms(payload.get("sample_context"))
        test_context = normalize_objective_terms(payload.get("test_context"))
        comparator = _text(payload.get("comparator"))
        fixed_conditions = normalize_objective_terms(payload.get("fixed_conditions"))
        source_refs = _paper_study_source_refs(payload.get("source_refs"))
        signal_id = _text(payload.get("signal_id"))
        if signal_id is None:
            identity = json.dumps(
                {
                    "document_id": (
                        _text(payload.get("document_id")) or ""
                    ).casefold(),
                    "signal_type": signal_type,
                    "label": label.casefold(),
                    "design_type": design_type,
                    "claim_scope": claim_scope,
                    "experiment_label": (
                        experiment_label.casefold() if experiment_label else None
                    ),
                    "material_scope": sorted(
                        value.casefold() for value in material_scope
                    ),
                    "process_context": sorted(
                        value.casefold() for value in process_context
                    ),
                    "sample_context": sorted(
                        value.casefold() for value in sample_context
                    ),
                    "test_context": sorted(
                        value.casefold() for value in test_context
                    ),
                    "comparator": comparator.casefold() if comparator else None,
                    "fixed_conditions": sorted(
                        value.casefold() for value in fixed_conditions
                    ),
                    "source_refs": sorted(
                        (item.source_kind, item.source_ref) for item in source_refs
                    ),
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            signal_id = f"signal_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
        return cls(
            signal_id=signal_id,
            signal_type=signal_type,
            label=label,
            design_type=design_type,
            claim_scope=claim_scope,
            experiment_label=experiment_label,
            material_scope=material_scope,
            process_context=process_context,
            sample_context=sample_context,
            test_context=test_context,
            comparator=comparator,
            fixed_conditions=fixed_conditions,
            source_refs=source_refs,
            confidence=normalize_objective_confidence(payload.get("confidence")),
            reason=_text(payload.get("reason")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "label": self.label,
            "design_type": self.design_type,
            "claim_scope": self.claim_scope,
            "experiment_label": self.experiment_label,
            "material_scope": list(self.material_scope),
            "process_context": list(self.process_context),
            "sample_context": list(self.sample_context),
            "test_context": list(self.test_context),
            "comparator": self.comparator,
            "fixed_conditions": list(self.fixed_conditions),
            "source_refs": [item.to_record() for item in self.source_refs],
            "confidence": self.confidence,
            "reason": self.reason,
        }


class PaperSourceUnitCoverageStatus(StrEnum):
    RELATIONSHIP_EMITTED = "relationship_emitted"
    UNRESOLVED_SIGNAL_EMITTED = "unresolved_signal_emitted"
    NO_STUDY_SIGNAL = "no_study_signal"
    EXTRACTION_FAILED = "extraction_failed"


@dataclass(frozen=True)
class PaperSourceUnitCoverage:
    """First-stage extraction outcome for one Source unit."""

    source_unit_id: str
    window_id: str
    source_kind: str
    source_ref: str
    status: PaperSourceUnitCoverageStatus
    reason: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.source_unit_id,
                self.window_id,
                self.source_kind,
                self.source_ref,
            )
        ):
            raise ValueError("paper Source-unit coverage fields cannot be empty")
        if self.source_kind not in _PAPER_STUDY_SOURCE_KINDS:
            raise ValueError(
                f"unsupported paper Source-unit kind: {self.source_kind}"
            )
        object.__setattr__(self, "status", self._status(self.status))
        if self.status in {
            PaperSourceUnitCoverageStatus.NO_STUDY_SIGNAL,
            PaperSourceUnitCoverageStatus.EXTRACTION_FAILED,
        }:
            if not _text(self.reason):
                raise ValueError(
                    f"{self.status.value} Source-unit coverage requires a reason"
                )
        elif _text(self.reason):
            raise ValueError(
                f"{self.status.value} Source-unit coverage cannot have a reason"
            )

    @staticmethod
    def _status(value: Any) -> PaperSourceUnitCoverageStatus:
        if isinstance(value, PaperSourceUnitCoverageStatus):
            return value
        try:
            return PaperSourceUnitCoverageStatus(str(value))
        except ValueError as exc:
            raise ValueError(
                f"unsupported paper Source-unit coverage status: {value}"
            ) from exc

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperSourceUnitCoverage":
        return cls(
            source_unit_id=_text(payload.get("source_unit_id")) or "",
            window_id=_text(payload.get("window_id")) or "",
            source_kind=_text(payload.get("source_kind")) or "",
            source_ref=_text(payload.get("source_ref")) or "",
            status=cls._status(payload.get("status")),
            reason=_text(payload.get("reason")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "source_unit_id": self.source_unit_id,
            "window_id": self.window_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "status": self.status.value,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PaperSkim:
    """Bounded Source-linked research-scope map for one paper."""

    document_id: str
    doc_role: str
    studies: tuple[PaperStudy, ...]
    evidence_density: str
    confidence: float
    warnings: tuple[str, ...]
    unresolved_signals: tuple[PaperStudySignal, ...] = ()
    source_unit_coverage: tuple[PaperSourceUnitCoverage, ...] = ()
    map_status: str = "unknown"
    map_limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            raise ValueError("paper skim requires document_id")
        object.__setattr__(self, "studies", tuple(self.studies))
        object.__setattr__(self, "unresolved_signals", tuple(self.unresolved_signals))
        object.__setattr__(
            self,
            "source_unit_coverage",
            tuple(self.source_unit_coverage),
        )
        if self.map_status not in {"unknown", "sufficient", "insufficient_map"}:
            raise ValueError(f"unsupported paper map status: {self.map_status}")
        object.__setattr__(
            self,
            "map_limitations",
            normalize_objective_terms(self.map_limitations),
        )
        if any(study.document_id != self.document_id for study in self.studies):
            raise ValueError("paper skim contains a study owned by another document")
        study_ids = [study.study_id for study in self.studies]
        if len(study_ids) != len(set(study_ids)):
            raise ValueError("paper skim study ids must be unique")
        coverage_ids = [item.source_unit_id for item in self.source_unit_coverage]
        if len(coverage_ids) != len(set(coverage_ids)):
            raise ValueError("paper skim Source-unit coverage ids must be unique")

    @property
    def coverage_complete(self) -> bool:
        return not any(
            item.status is PaperSourceUnitCoverageStatus.EXTRACTION_FAILED
            for item in self.source_unit_coverage
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PaperSkim":
        document_id = _text(payload.get("document_id") or payload.get("paper_id")) or ""
        return cls(
            document_id=document_id,
            doc_role=_text(payload.get("doc_role")) or "uncertain",
            studies=tuple(
                PaperStudy.from_mapping(
                    {**dict(item), "document_id": item.get("document_id", document_id)}
                )
                for item in payload.get("studies") or ()
                if isinstance(item, Mapping)
            ),
            evidence_density=_text(payload.get("evidence_density")) or "unknown",
            confidence=normalize_objective_confidence(payload.get("confidence")),
            warnings=normalize_objective_terms(payload.get("warnings")),
            unresolved_signals=tuple(
                PaperStudySignal.from_mapping(
                    {**dict(item), "document_id": document_id}
                )
                for item in payload.get("unresolved_signals") or ()
                if isinstance(item, Mapping)
            ),
            source_unit_coverage=tuple(
                PaperSourceUnitCoverage.from_mapping(item)
                for item in payload.get("source_unit_coverage") or ()
                if isinstance(item, Mapping)
            ),
            map_status=_text(payload.get("map_status")) or "unknown",
            map_limitations=normalize_objective_terms(
                payload.get("map_limitations")
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "doc_role": self.doc_role,
            "studies": [study.to_record() for study in self.studies],
            "evidence_density": self.evidence_density,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "unresolved_signals": [
                signal.to_record() for signal in self.unresolved_signals
            ],
            "source_unit_coverage": [
                item.to_record() for item in self.source_unit_coverage
            ],
            "map_status": self.map_status,
            "map_limitations": list(self.map_limitations),
        }


@dataclass(frozen=True)
class ResearchObjective:
    collection_id: str
    objective_id: str
    question: str
    material_scope: tuple[str, ...]
    variables: tuple[str, ...]
    outcomes: tuple[str, ...]
    mechanisms: tuple[str, ...]
    constraints: tuple[str, ...]
    requested_comparator: str | None
    seed_document_ids: tuple[str, ...]
    excluded_document_ids: tuple[str, ...]
    confidence: float
    reason: str | None
    source_relationship_ids: tuple[str, ...] = ()
    rank: int | None = None
    confirmation_status: str = "candidate"
    active_analysis_version: int | None = None
    published_analysis_version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    origin: str = "system_discovered"
    source_build_id: str | None = None
    created_by_user_id: str | None = None
    created_by_tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if not _text(self.collection_id):
            raise ValueError("research objective requires collection_id")
        if not _text(self.objective_id):
            raise ValueError("research objective requires objective_id")
        if not _text(self.question):
            raise ValueError("research objective requires question")
        if not self.variables:
            raise ValueError("research objective requires at least one variable")
        if not self.outcomes:
            raise ValueError("research objective requires at least one outcome")
        if self.rank is not None and self.rank < 1:
            raise ValueError("research objective rank must be a positive integer")
        primary_terms = {
            value.casefold() for value in (*self.variables, *self.outcomes)
        }
        duplicate_mechanisms = primary_terms & {
            value.casefold() for value in self.mechanisms
        }
        if duplicate_mechanisms:
            raise ValueError(
                "objective mechanisms duplicate variables or outcomes: "
                + ", ".join(sorted(duplicate_mechanisms))
            )
        duplicate_constraints = primary_terms & {
            value.casefold() for value in self.constraints
        }
        if duplicate_constraints:
            raise ValueError(
                "objective constraints duplicate variables or outcomes: "
                + ", ".join(sorted(duplicate_constraints))
            )
        if self.confirmation_status not in OBJECTIVE_CONFIRMATION_STATUSES:
            raise ValueError(
                f"unsupported objective confirmation status: {self.confirmation_status}"
            )
        if self.origin not in OBJECTIVE_ORIGINS:
            raise ValueError(f"unsupported objective origin: {self.origin}")
        creator_values = (
            _text(self.created_by_user_id),
            _text(self.created_by_tool_call_id),
        )
        if self.origin == "chat_assisted" and not all(creator_values):
            raise ValueError(
                "chat-assisted objective requires user and tool-call provenance"
            )
        if self.origin == "system_discovered" and any(creator_values):
            raise ValueError(
                "system-discovered objective cannot have Chat creator provenance"
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
        material_scope = normalize_objective_terms(payload.get("material_scope"))
        variables = normalize_objective_terms(payload.get("variables"))
        outcomes = normalize_objective_terms(payload.get("outcomes"))
        mechanisms = normalize_objective_terms(payload.get("mechanisms"))
        constraints = normalize_objective_terms(payload.get("constraints"))
        requested_comparator = _text(payload.get("requested_comparator"))
        return cls(
            collection_id=_text(payload.get("collection_id")) or "",
            objective_id=_text(payload.get("objective_id"))
            or build_research_objective_id(
                question=question,
                material_scope=material_scope,
                variables=variables,
                outcomes=outcomes,
                mechanisms=mechanisms,
                constraints=constraints,
                requested_comparator=requested_comparator,
            ),
            question=question,
            material_scope=material_scope,
            variables=variables,
            outcomes=outcomes,
            mechanisms=mechanisms,
            constraints=constraints,
            requested_comparator=requested_comparator,
            seed_document_ids=normalize_objective_terms(
                payload.get("seed_document_ids")
            ),
            excluded_document_ids=normalize_objective_terms(
                payload.get("excluded_document_ids")
            ),
            confidence=normalize_objective_confidence(payload.get("confidence")),
            reason=_text(payload.get("reason")),
            source_relationship_ids=normalize_objective_terms(
                payload.get("source_relationship_ids")
            ),
            rank=_positive_int_or_none(payload.get("rank")),
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
            origin=_choice(
                payload.get("origin"),
                OBJECTIVE_ORIGINS,
                "system_discovered",
            ),
            source_build_id=_text(payload.get("source_build_id")),
            created_by_user_id=_text(payload.get("created_by_user_id")),
            created_by_tool_call_id=_text(payload.get("created_by_tool_call_id")),
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
            "variables": list(self.variables),
            "outcomes": list(self.outcomes),
            "mechanisms": list(self.mechanisms),
            "constraints": list(self.constraints),
            "requested_comparator": self.requested_comparator,
            "seed_document_ids": list(self.seed_document_ids),
            "excluded_document_ids": list(self.excluded_document_ids),
            "confidence": self.confidence,
            "reason": self.reason,
            "source_relationship_ids": list(self.source_relationship_ids),
            "rank": self.rank,
            "confirmation_status": self.confirmation_status,
            "active_analysis_version": self.active_analysis_version,
            "published_analysis_version": self.published_analysis_version,
            "created_at": _datetime_record(self.created_at),
            "updated_at": _datetime_record(self.updated_at),
            "origin": self.origin,
            "source_build_id": self.source_build_id,
            "created_by_user_id": self.created_by_user_id,
            "created_by_tool_call_id": self.created_by_tool_call_id,
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
        object.__setattr__(
            self,
            "diagnostics",
            tuple(deepcopy(dict(item)) for item in self.diagnostics),
        )

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

    def succeed(self, *, completed_at: datetime | None = None) -> "ObjectiveAnalysis":
        return self._transition(
            "succeeded",
            phase="completed",
            processed_document_count=self.total_document_count,
            current_document_id=None,
            progress_message="Objective analysis completed.",
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
    evidence_disposition: str | None = None
    routed_source_count: int | None = None
    extracted_source_count: int | None = None
    comparable_evidence_count: int | None = None
    failed_source_count: int | None = None
    evidence_disposition_reason: str | None = None

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
            self.exclusion_reason
            or self.warnings
            or self.evidence_disposition_reason
        ):
            raise ValueError(
                "excluded or failed paper contribution requires a reason or warning"
            )
        self._validate_evidence_accounting()

    def _validate_evidence_accounting(self) -> None:
        values = (
            self.evidence_disposition,
            self.routed_source_count,
            self.extracted_source_count,
            self.comparable_evidence_count,
            self.failed_source_count,
        )
        if not any(value is not None for value in values):
            return
        if not all(value is not None for value in values):
            raise ValueError(
                "paper evidence disposition and counts must be all present or all absent"
            )
        if self.evidence_disposition not in PAPER_EVIDENCE_DISPOSITIONS:
            raise ValueError(
                "unsupported paper evidence disposition: "
                f"{self.evidence_disposition}"
            )
        counts = (
            self.routed_source_count,
            self.extracted_source_count,
            self.comparable_evidence_count,
            self.failed_source_count,
        )
        if any(count is None or count < 0 for count in counts):
            raise ValueError("paper evidence counts cannot be negative")
        routed = self.routed_source_count or 0
        extracted = self.extracted_source_count or 0
        comparable = self.comparable_evidence_count or 0
        failed = self.failed_source_count or 0
        if extracted > routed or failed > routed:
            raise ValueError(
                "extracted and failed source counts cannot exceed routed sources"
            )
        disposition = self.evidence_disposition
        if disposition == "excluded":
            if self.analysis_status != "excluded" or any(counts):
                raise ValueError("excluded evidence disposition requires zero counts")
            return
        if disposition == "extraction_failed":
            if (
                self.analysis_status != "failed"
                or routed == 0
                or extracted != 0
                or comparable != 0
                or failed == 0
            ):
                raise ValueError(
                    "extraction_failed disposition requires failed routed sources"
                )
        elif self.analysis_status != "analyzed":
            raise ValueError(
                "non-excluded evidence disposition requires analyzed paper status"
            )
        if disposition == "no_routable_evidence" and any(counts):
            raise ValueError("no_routable_evidence disposition requires zero counts")
        if disposition == "no_comparable_evidence" and (
            routed == 0 or comparable != 0
        ):
            raise ValueError(
                "no_comparable_evidence disposition requires routed sources"
            )
        if disposition == "comparable_evidence" and (
            extracted == 0 or comparable == 0
        ):
            raise ValueError(
                "comparable_evidence disposition requires comparable Evidence"
            )
        if disposition in {
            "no_routable_evidence",
            "extraction_failed",
            "no_comparable_evidence",
        } and not self.evidence_disposition_reason:
            raise ValueError(
                f"{disposition} disposition requires an evidence reason"
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
            evidence_disposition=_text(payload.get("evidence_disposition")),
            routed_source_count=_non_negative_int_or_none(
                payload.get("routed_source_count")
            ),
            extracted_source_count=_non_negative_int_or_none(
                payload.get("extracted_source_count")
            ),
            comparable_evidence_count=_non_negative_int_or_none(
                payload.get("comparable_evidence_count")
            ),
            failed_source_count=_non_negative_int_or_none(
                payload.get("failed_source_count")
            ),
            evidence_disposition_reason=_text(
                payload.get("evidence_disposition_reason")
            ),
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
            "evidence_disposition": self.evidence_disposition,
            "routed_source_count": self.routed_source_count,
            "extracted_source_count": self.extracted_source_count,
            "comparable_evidence_count": self.comparable_evidence_count,
            "failed_source_count": self.failed_source_count,
            "evidence_disposition_reason": self.evidence_disposition_reason,
        }


EvidenceScalar = str | int | float | bool


@dataclass(frozen=True)
class ObjectiveEvidenceAttribute:
    name: str
    value: EvidenceScalar
    unit: str | None = None

    def __post_init__(self) -> None:
        if not _text(self.name) or _scientific_scalar(self.value) is None:
            raise ValueError("objective evidence attribute requires name and value")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObjectiveEvidenceAttribute":
        value = _scientific_scalar(payload.get("value"))
        return cls(
            name=_text(payload.get("name")) or "",
            value=value if value is not None else "",
            unit=_text(payload.get("unit")),
        )

    def to_record(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value, "unit": self.unit}


@dataclass(frozen=True)
class ObjectiveEvidenceVariable:
    name: str
    baseline_value: EvidenceScalar | None
    target_value: EvidenceScalar | None
    unit: str | None = None

    def __post_init__(self) -> None:
        if not _text(self.name):
            raise ValueError("objective evidence variable requires name")
        if self.baseline_value is None and self.target_value is None:
            raise ValueError("objective evidence variable requires a reported value")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObjectiveEvidenceVariable":
        return cls(
            name=_text(payload.get("name")) or "",
            baseline_value=_scientific_scalar(payload.get("baseline_value")),
            target_value=_scientific_scalar(payload.get("target_value")),
            unit=_text(payload.get("unit")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "baseline_value": self.baseline_value,
            "target_value": self.target_value,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class ObjectiveEvidenceComparison:
    baseline_label: str
    target_label: str
    axis_names: tuple[str, ...]
    comparable: bool
    incomparability_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _text(self.baseline_label) or not _text(self.target_label):
            raise ValueError("objective evidence comparison requires both groups")
        if not self.axis_names:
            raise ValueError("objective evidence comparison requires axes")
        if not self.comparable and not self.incomparability_reasons:
            raise ValueError("incomparable evidence requires reasons")
        if self.comparable and self.incomparability_reasons:
            raise ValueError("comparable evidence cannot have incomparability reasons")

    @classmethod
    def from_mapping(
        cls, payload: Mapping[str, Any]
    ) -> "ObjectiveEvidenceComparison":
        return cls(
            baseline_label=_text(payload.get("baseline_label")) or "",
            target_label=_text(payload.get("target_label")) or "",
            axis_names=normalize_objective_terms(payload.get("axis_names")),
            comparable=payload.get("comparable") is True,
            incomparability_reasons=normalize_objective_terms(
                payload.get("incomparability_reasons")
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "baseline_label": self.baseline_label,
            "target_label": self.target_label,
            "axis_names": list(self.axis_names),
            "comparable": self.comparable,
            "incomparability_reasons": list(self.incomparability_reasons),
        }


@dataclass(frozen=True)
class ObjectiveEvidenceResult:
    outcome: str
    value: EvidenceScalar | None
    unit: str | None
    direction: str
    result_text: str
    baseline_value: EvidenceScalar | None = None
    target_value: EvidenceScalar | None = None

    def __post_init__(self) -> None:
        if not _text(self.outcome) or not _text(self.result_text):
            raise ValueError("objective evidence result requires outcome and result text")
        if self.direction not in EVIDENCE_RESULT_DIRECTIONS:
            raise ValueError(f"unsupported evidence result direction: {self.direction}")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObjectiveEvidenceResult":
        return cls(
            outcome=_text(payload.get("outcome")) or "",
            value=_scientific_scalar(payload.get("value")),
            unit=_text(payload.get("unit")),
            direction=_choice(
                payload.get("direction"), EVIDENCE_RESULT_DIRECTIONS, "unknown"
            ),
            result_text=_text(payload.get("result_text")) or "",
            baseline_value=_scientific_scalar(payload.get("baseline_value")),
            target_value=_scientific_scalar(payload.get("target_value")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "value": self.value,
            "baseline_value": self.baseline_value,
            "target_value": self.target_value,
            "unit": self.unit,
            "direction": self.direction,
            "result_text": self.result_text,
        }


@dataclass(frozen=True)
class ObjectiveEvidenceContext:
    material: tuple[ObjectiveEvidenceAttribute, ...] = ()
    sample: tuple[ObjectiveEvidenceAttribute, ...] = ()
    process: tuple[ObjectiveEvidenceAttribute, ...] = ()
    test: tuple[ObjectiveEvidenceAttribute, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObjectiveEvidenceContext":
        return cls(
            material=_evidence_attributes(payload.get("material")),
            sample=_evidence_attributes(payload.get("sample")),
            process=_evidence_attributes(payload.get("process")),
            test=_evidence_attributes(payload.get("test")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "material": [item.to_record() for item in self.material],
            "sample": [item.to_record() for item in self.sample],
            "process": [item.to_record() for item in self.process],
            "test": [item.to_record() for item in self.test],
        }

    @property
    def has_content(self) -> bool:
        return bool(self.material or self.sample or self.process or self.test)


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
    changed_variables: tuple[ObjectiveEvidenceVariable, ...]
    comparison: ObjectiveEvidenceComparison | None
    reported_result: ObjectiveEvidenceResult | None
    attribution_scope: str
    scientific_context: ObjectiveEvidenceContext
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
        if self.attribution_scope not in EVIDENCE_ATTRIBUTION_SCOPES:
            raise ValueError(
                f"unsupported objective evidence attribution: {self.attribution_scope}"
            )
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
        self._validate_attribution()

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
        reported_result_payload = payload.get("reported_result")
        reported_result = (
            ObjectiveEvidenceResult.from_mapping(reported_result_payload)
            if isinstance(reported_result_payload, Mapping)
            else None
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
            payload.get("semantic_slot")
            or (reported_result.outcome if reported_result is not None else None),
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
            changed_variables=_evidence_variables(payload.get("changed_variables")),
            comparison=(
                ObjectiveEvidenceComparison.from_mapping(payload["comparison"])
                if isinstance(payload.get("comparison"), Mapping)
                else None
            ),
            reported_result=reported_result,
            attribution_scope=_choice(
                payload.get("attribution_scope"),
                EVIDENCE_ATTRIBUTION_SCOPES,
                "not_attributable",
            ),
            scientific_context=(
                ObjectiveEvidenceContext.from_mapping(payload["scientific_context"])
                if isinstance(payload.get("scientific_context"), Mapping)
                else ObjectiveEvidenceContext()
            ),
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
        if "extracted" not in OBJECTIVE_EVIDENCE_STATE_TRANSITIONS[
            self.selection_status
        ]:
            raise ValueError(
                "invalid objective evidence transition: "
                f"{self.selection_status} -> extracted"
            )
        record = self.to_record()
        record.update(scientific_content)
        record.update(
            {
                "selection_status": "extracted",
                "resolution_status": scientific_content.get(
                    "resolution_status", "resolved"
                ),
                "failure_reason": None,
            }
        )
        return ObjectiveEvidence.from_mapping(record)

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
            self.changed_variables
            or self.comparison
            or self.reported_result
            or self.scientific_context.has_content
        )

    def _validate_attribution(self) -> None:
        result_role = self.evidence_role in {"direct_result", "contradictory_result"}
        if self.selection_status == "extracted" and result_role:
            if self.reported_result is None:
                raise ValueError("result evidence requires one reported result")
        if not result_role and self.reported_result is not None:
            raise ValueError("context evidence cannot report an experimental result")
        if not result_role and self.attribution_scope in {
            "isolated_effect",
            "joint_effect",
        }:
            raise ValueError("context evidence cannot claim experimental attribution")
        if self.comparison is not None and not self.comparison.comparable:
            if self.attribution_scope != "not_attributable":
                raise ValueError("incomparable evidence cannot be attributed")
        if self.attribution_scope not in {"isolated_effect", "joint_effect"}:
            return
        if self.comparison is None or not self.comparison.comparable:
            raise ValueError("experimental attribution requires a comparable comparison")
        variable_names = {item.name.casefold() for item in self.changed_variables}
        axis_names = {item.casefold() for item in self.comparison.axis_names}
        if variable_names != axis_names:
            raise ValueError("comparison axes must match all changed variables")
        if any(
            item.baseline_value is None or item.target_value is None
            for item in self.changed_variables
        ):
            raise ValueError("experimental attribution requires baseline and target values")
        if any(
            item.baseline_value == item.target_value for item in self.changed_variables
        ):
            raise ValueError("experimental attribution requires changed variable values")
        if self.attribution_scope == "isolated_effect" and len(variable_names) != 1:
            raise ValueError("isolated effect requires exactly one changed variable")
        if self.attribution_scope == "joint_effect" and len(variable_names) < 2:
            raise ValueError("joint effect requires at least two changed variables")

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
            "changed_variables": [item.to_record() for item in self.changed_variables],
            "comparison": self.comparison.to_record() if self.comparison else None,
            "reported_result": (
                self.reported_result.to_record() if self.reported_result else None
            ),
            "attribution_scope": self.attribution_scope,
            "scientific_context": self.scientific_context.to_record(),
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
    study_dispositions: tuple[PaperStudyDisposition, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "paper_skims", tuple(self.paper_skims))
        object.__setattr__(
            self,
            "research_objectives",
            tuple(self.research_objectives),
        )
        object.__setattr__(
            self,
            "study_dispositions",
            tuple(self.study_dispositions),
        )
        relationships_by_key = {
            (skim.document_id, study.study_id, relationship.relationship_id): relationship
            for skim in self.paper_skims
            for study in skim.studies
            for relationship in study.relationships
        }
        relationship_keys = set(relationships_by_key)
        if len(relationships_by_key) != sum(
            len(study.relationships)
            for skim in self.paper_skims
            for study in skim.studies
        ):
            raise ValueError("paper study relationship identities must be unique")
        relationship_ids = {
            relationship_id
            for _document_id, _study_id, relationship_id in relationship_keys
        }
        if len(relationship_ids) != len(relationship_keys):
            raise ValueError("paper study relationship ids must be collection-unique")
        disposition_keys = [
            (item.document_id, item.study_id, item.relationship_id)
            for item in self.study_dispositions
        ]
        if len(disposition_keys) != len(set(disposition_keys)):
            raise ValueError("paper study relationship was accounted for more than once")
        unknown = set(disposition_keys) - relationship_keys
        if unknown:
            raise ValueError("study disposition references an unknown relationship")
        if not self.research_objectives_ready:
            if any(
                item.status is not PaperStudyDispositionStatus.PENDING
                for item in self.study_dispositions
            ):
                raise ValueError("an unready objective fact set can only be pending")
            return
        if set(disposition_keys) != relationship_keys:
            raise ValueError("ready objective facts must account for every relationship")
        if any(
            item.status is PaperStudyDispositionStatus.PENDING
            for item in self.study_dispositions
        ):
            raise ValueError("ready objective facts cannot contain pending relationships")
        objectives_by_id = {
            objective.objective_id: objective for objective in self.research_objectives
        }
        if len(objectives_by_id) != len(self.research_objectives):
            raise ValueError("research objective ids must be unique")
        ranked = [objective.rank for objective in self.research_objectives]
        if ranked != list(range(1, len(self.research_objectives) + 1)):
            raise ValueError("ready research objectives require contiguous rank order")
        linked_dispositions: dict[str, list[PaperStudyDisposition]] = {}
        for disposition in self.study_dispositions:
            if disposition.objective_id is None:
                continue
            objective = objectives_by_id.get(disposition.objective_id)
            if objective is None:
                raise ValueError("study disposition references an unknown objective")
            if disposition.relationship_id not in objective.source_relationship_ids:
                raise ValueError("study disposition is missing from objective lineage")
            linked_dispositions.setdefault(disposition.objective_id, []).append(
                disposition
            )
        for objective in self.research_objectives:
            linked = linked_dispositions.get(objective.objective_id, [])
            if {item.relationship_id for item in linked} != set(
                objective.source_relationship_ids
            ):
                raise ValueError("objective lineage has a dangling relationship id")
            if not linked or any(
                item.status is not PaperStudyDispositionStatus.PROMOTED
                for item in linked
            ):
                raise ValueError("objective lineage requires promoted study relationships")
            if {item.document_id for item in linked} != set(
                objective.seed_document_ids
            ):
                raise ValueError(
                    "objective seed documents do not match study relationship lineage"
                )


def build_research_objective_id(
    *,
    question: str,
    material_scope: tuple[str, ...],
    variables: tuple[str, ...],
    outcomes: tuple[str, ...],
    mechanisms: tuple[str, ...],
    constraints: tuple[str, ...],
    requested_comparator: str | None,
) -> str:
    normalized_question = (_text(question) or "unspecified").lower()
    slug = _SLUG_NON_WORD_PATTERN.sub("-", normalized_question).strip("-")
    if not slug:
        slug = "unspecified"
    identity = json.dumps(
        {
            "question": normalized_question,
            "material_scope": sorted(value.casefold() for value in material_scope),
            "variables": sorted(value.casefold() for value in variables),
            "outcomes": sorted(value.casefold() for value in outcomes),
            "mechanisms": sorted(value.casefold() for value in mechanisms),
            "constraints": sorted(value.casefold() for value in constraints),
            "requested_comparator": (
                requested_comparator.casefold() if requested_comparator else None
            ),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = sha1(identity.encode("utf-8")).hexdigest()[:8]
    return f"obj_{slug[:72].strip('-')}_{digest}"


def _is_question_shaped(value: Any) -> bool:
    question = (_text(value) or "").lower()
    return bool(
        question.endswith("?")
        or any(term in question for term in _QUESTION_SIGNAL_TERMS)
    )


def is_question_shaped_objective(objective: ResearchObjective) -> bool:
    return _is_question_shaped(objective.question)


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


def _scientific_scalar(value: Any) -> EvidenceScalar | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return _text(value)


def _evidence_attributes(value: Any) -> tuple[ObjectiveEvidenceAttribute, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        ObjectiveEvidenceAttribute.from_mapping(item)
        for item in value
        if isinstance(item, Mapping)
    )


def _evidence_variables(value: Any) -> tuple[ObjectiveEvidenceVariable, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    variables = tuple(
        ObjectiveEvidenceVariable.from_mapping(item)
        for item in value
        if isinstance(item, Mapping)
    )
    names = [item.name.casefold() for item in variables]
    if len(names) != len(set(names)):
        raise ValueError("objective evidence changed variables must be unique")
    return variables


def _positive_int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def _non_negative_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("paper evidence count must be an integer")
    try:
        numeric = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("paper evidence count must be an integer") from exc
    if numeric < 0:
        raise ValueError("paper evidence count cannot be negative")
    return numeric


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
