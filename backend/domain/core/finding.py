from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import math
from typing import Any, Final, Mapping

from domain.core.research_objective import ObjectiveEvidence


FINDING_LEVELS: Final[frozenset[str]] = frozenset({"paper", "cross_paper"})
FINDING_EVIDENCE_STRENGTHS: Final[frozenset[str]] = frozenset(
    {"strong", "moderate", "weak", "insufficient"}
)
FINDING_GENERALIZATION_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "paper_level_only",
        "cross_paper_agreement",
        "condition_dependent",
        "conflict",
        "insufficient_confirmation",
    }
)
FINDING_ASSERTION_STRENGTHS: Final[frozenset[str]] = frozenset(
    {"causal", "associative", "descriptive", "uncertain"}
)
FINDING_COMPARISON_STATUSES: Final[frozenset[str]] = frozenset(
    {"agreement", "conflict", "condition_dependent", "insufficient_confirmation"}
)


@dataclass(frozen=True)
class FindingRelation:
    source_term: str
    relation_type: str
    target_term: str
    direction: str | None
    assertion_strength: str
    supporting_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _text(self.source_term) or not _text(self.relation_type):
            raise ValueError("finding relation requires source and relation type")
        if not _text(self.target_term):
            raise ValueError("finding relation requires target")
        if self.assertion_strength not in FINDING_ASSERTION_STRENGTHS:
            raise ValueError(
                f"unsupported finding assertion strength: {self.assertion_strength}"
            )
        if not self.supporting_evidence_ids:
            raise ValueError("finding relation requires supporting evidence")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FindingRelation":
        return cls(
            source_term=_text(payload.get("source_term")) or "",
            relation_type=_text(payload.get("relation_type")) or "",
            target_term=_text(payload.get("target_term")) or "",
            direction=_text(payload.get("direction")),
            assertion_strength=_choice(
                payload.get("assertion_strength"),
                FINDING_ASSERTION_STRENGTHS,
                "uncertain",
            ),
            supporting_evidence_ids=_strings(
                payload.get("supporting_evidence_ids")
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "source_term": self.source_term,
            "relation_type": self.relation_type,
            "target_term": self.target_term,
            "direction": self.direction,
            "assertion_strength": self.assertion_strength,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
        }


@dataclass(frozen=True)
class FindingContext:
    material_system: dict[str, Any]
    process_conditions: tuple[dict[str, Any], ...]
    sample_state: dict[str, Any]
    test_conditions: tuple[dict[str, Any], ...]
    comparison_baseline: dict[str, Any]
    limitations: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FindingContext":
        return cls(
            material_system=_mapping(payload.get("material_system")),
            process_conditions=_mapping_list(payload.get("process_conditions")),
            sample_state=_mapping(payload.get("sample_state")),
            test_conditions=_mapping_list(payload.get("test_conditions")),
            comparison_baseline=_mapping(payload.get("comparison_baseline")),
            limitations=_strings(payload.get("limitations")),
            supporting_evidence_ids=_strings(
                payload.get("supporting_evidence_ids")
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "material_system": dict(self.material_system),
            "process_conditions": [dict(value) for value in self.process_conditions],
            "sample_state": dict(self.sample_state),
            "test_conditions": [dict(value) for value in self.test_conditions],
            "comparison_baseline": dict(self.comparison_baseline),
            "limitations": list(self.limitations),
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
        }


@dataclass(frozen=True)
class FindingDerivation:
    synthesis_mode: str
    comparison_status: str
    contributing_document_ids: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        if self.synthesis_mode not in FINDING_LEVELS:
            raise ValueError(f"unsupported finding synthesis mode: {self.synthesis_mode}")
        if self.comparison_status not in FINDING_COMPARISON_STATUSES:
            raise ValueError(
                f"unsupported finding comparison status: {self.comparison_status}"
            )
        if not self.contributing_document_ids:
            raise ValueError("finding derivation requires contributing documents")
        if not self.supporting_evidence_ids:
            raise ValueError("finding derivation requires supporting evidence")
        if set(self.supporting_evidence_ids) & set(self.contradicting_evidence_ids):
            raise ValueError("supporting and contradicting evidence must be disjoint")
        if not _text(self.rationale):
            raise ValueError("finding derivation requires rationale")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FindingDerivation":
        return cls(
            synthesis_mode=_choice(
                payload.get("synthesis_mode"), FINDING_LEVELS, "paper"
            ),
            comparison_status=_choice(
                payload.get("comparison_status"),
                FINDING_COMPARISON_STATUSES,
                "insufficient_confirmation",
            ),
            contributing_document_ids=_strings(
                payload.get("contributing_document_ids")
            ),
            supporting_evidence_ids=_strings(
                payload.get("supporting_evidence_ids")
            ),
            contradicting_evidence_ids=_strings(
                payload.get("contradicting_evidence_ids")
            ),
            rationale=_text(payload.get("rationale")) or "",
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "synthesis_mode": self.synthesis_mode,
            "comparison_status": self.comparison_status,
            "contributing_document_ids": list(self.contributing_document_ids),
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "contradicting_evidence_ids": list(self.contradicting_evidence_ids),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class Finding:
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    finding_level: str
    statement: str
    variables: tuple[str, ...]
    mediators: tuple[str, ...]
    outcomes: tuple[str, ...]
    direction: str | None
    scope_summary: str
    evidence_strength: str
    generalization_status: str
    paper_count: int
    confidence: float
    display_rank: int
    relations: tuple[FindingRelation, ...]
    context: FindingContext
    derivation: FindingDerivation

    def __post_init__(self) -> None:
        if not all(
            _text(value)
            for value in (
                self.collection_id,
                self.objective_id,
                self.finding_id,
                self.statement,
                self.scope_summary,
            )
        ):
            raise ValueError("finding requires scoped identity and statement")
        if len(self.finding_id) > 128:
            raise ValueError("finding ID exceeds 128 characters")
        if self.analysis_version < 1:
            raise ValueError("finding requires positive analysis_version")
        if self.finding_level not in FINDING_LEVELS:
            raise ValueError(f"unsupported finding level: {self.finding_level}")
        if not self.variables or not self.outcomes:
            raise ValueError("finding requires variables and outcomes")
        if self.evidence_strength not in FINDING_EVIDENCE_STRENGTHS:
            raise ValueError(
                f"unsupported finding evidence strength: {self.evidence_strength}"
            )
        if self.generalization_status not in FINDING_GENERALIZATION_STATUSES:
            raise ValueError(
                "unsupported finding generalization status: "
                f"{self.generalization_status}"
            )
        if self.paper_count < 1:
            raise ValueError("finding paper_count must be positive")
        if self.display_rank < 0:
            raise ValueError("finding display_rank cannot be negative")
        if self.finding_level != self.derivation.synthesis_mode:
            raise ValueError("finding level and derivation mode differ")
        if self.paper_count != len(set(self.derivation.contributing_document_ids)):
            raise ValueError("finding paper_count differs from derivation documents")
        if self.finding_level == "paper":
            if self.paper_count != 1:
                raise ValueError("paper finding must have exactly one paper")
            if self.generalization_status != "paper_level_only":
                raise ValueError("paper finding must remain paper_level_only")
        elif self.paper_count < 2:
            raise ValueError("cross-paper finding requires at least two papers")

    @property
    def key(self) -> tuple[str, str, int, str]:
        return (
            self.collection_id,
            self.objective_id,
            self.analysis_version,
            self.finding_id,
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "Finding":
        return cls(
            collection_id=_text(payload.get("collection_id")) or "",
            objective_id=_text(payload.get("objective_id")) or "",
            analysis_version=_positive_int(payload.get("analysis_version")),
            finding_id=_text(payload.get("finding_id")) or _stable_id(
                "finding",
                payload.get("objective_id"),
                payload.get("analysis_version"),
                payload.get("statement"),
                payload.get("variables"),
                payload.get("outcomes"),
            ),
            finding_level=_choice(
                payload.get("finding_level"), FINDING_LEVELS, "paper"
            ),
            statement=_text(payload.get("statement")) or "",
            variables=_strings(payload.get("variables")),
            mediators=_strings(payload.get("mediators")),
            outcomes=_strings(payload.get("outcomes")),
            direction=_text(payload.get("direction")),
            scope_summary=_text(payload.get("scope_summary")) or "",
            evidence_strength=_choice(
                payload.get("evidence_strength"),
                FINDING_EVIDENCE_STRENGTHS,
                "insufficient",
            ),
            generalization_status=_choice(
                payload.get("generalization_status"),
                FINDING_GENERALIZATION_STATUSES,
                "paper_level_only",
            ),
            paper_count=_positive_int(payload.get("paper_count")),
            confidence=_confidence_or_none(payload.get("confidence")) or 0.0,
            display_rank=_non_negative_int(payload.get("display_rank")),
            relations=tuple(
                FindingRelation.from_mapping(item)
                for item in _mapping_list(payload.get("relations"))
            ),
            context=FindingContext.from_mapping(_mapping(payload.get("context"))),
            derivation=FindingDerivation.from_mapping(
                _mapping(payload.get("derivation"))
            ),
        )

    def validate_evidence(
        self,
        evidence_records: tuple[ObjectiveEvidence, ...],
    ) -> None:
        evidence_by_id = {item.evidence_id: item for item in evidence_records}
        referenced = set(self.derivation.supporting_evidence_ids) | set(
            self.derivation.contradicting_evidence_ids
        )
        referenced.update(self.context.supporting_evidence_ids)
        for relation in self.relations:
            referenced.update(relation.supporting_evidence_ids)
        missing = referenced - set(evidence_by_id)
        if missing:
            raise ValueError(
                "finding references missing evidence: " + ", ".join(sorted(missing))
            )
        for evidence in (evidence_by_id[evidence_id] for evidence_id in referenced):
            if (
                evidence.collection_id,
                evidence.objective_id,
                evidence.analysis_version,
            ) != (self.collection_id, self.objective_id, self.analysis_version):
                raise ValueError("finding references cross-version evidence")
        supporting = [
            evidence_by_id[evidence_id]
            for evidence_id in self.derivation.supporting_evidence_ids
        ]
        if any(not evidence.supports_finding for evidence in supporting):
            raise ValueError("finding references ineligible supporting evidence")
        direct_results = [
            evidence
            for evidence in supporting
            if evidence.evidence_role == "direct_result"
        ]
        if not direct_results:
            raise ValueError("finding requires direct result evidence")
        direct_documents = {evidence.document_id for evidence in direct_results}
        if direct_documents != set(self.derivation.contributing_document_ids):
            raise ValueError("derivation documents differ from direct result evidence")
        if self.finding_level == "cross_paper" and len(direct_documents) < 2:
            raise ValueError("cross-paper finding lacks independent direct results")
        for relation in self.relations:
            if relation.assertion_strength != "causal":
                continue
            relation_evidence = [
                evidence_by_id[evidence_id]
                for evidence_id in relation.supporting_evidence_ids
            ]
            if not any(
                evidence.evidence_role == "direct_result"
                and bool(evidence.join_keys.get("isolated_variable"))
                for evidence in relation_evidence
            ):
                raise ValueError("causal relation lacks isolated-variable evidence")

    def to_record(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "objective_id": self.objective_id,
            "analysis_version": self.analysis_version,
            "finding_id": self.finding_id,
            "finding_level": self.finding_level,
            "statement": self.statement,
            "variables": list(self.variables),
            "mediators": list(self.mediators),
            "outcomes": list(self.outcomes),
            "direction": self.direction,
            "scope_summary": self.scope_summary,
            "evidence_strength": self.evidence_strength,
            "generalization_status": self.generalization_status,
            "paper_count": self.paper_count,
            "confidence": self.confidence,
            "display_rank": self.display_rank,
            "relations": [
                {"relation_order": order, **relation.to_record()}
                for order, relation in enumerate(self.relations)
            ],
            "context": self.context.to_record(),
            "derivation": self.derivation.to_record(),
        }


def _stable_id(prefix: str, *parts: Any) -> str:
    text = "|".join(_stable_text(part) for part in parts if part is not None)
    digest = sha1((text or prefix).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _stable_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return "|".join(
            f"{key}:{_stable_text(value[key])}" for key in sorted(value, key=str)
        )
    if isinstance(value, (list, tuple, set)):
        return ",".join(_stable_text(item) for item in value)
    return str(value or "")


def _choice(value: Any, allowed: frozenset[str], default: str) -> str:
    normalized = (_text(value) or "").lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in allowed else default


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _confidence_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        numeric = float(value)
        if math.isnan(numeric):
            return None
        return round(min(1.0, max(0.0, numeric)), 2)
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return 0
    return numeric if numeric > 0 else 0


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, numeric)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def _strings(value: Any) -> tuple[str, ...]:
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
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return tuple(normalized)
