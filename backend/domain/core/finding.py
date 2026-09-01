from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
import math
import re
from typing import Any, Final, Mapping

from domain.core.research_objective import (
    EVIDENCE_ATTRIBUTION_SCOPES,
    EVIDENCE_RESULT_DIRECTIONS,
    PAPER_CONTRIBUTION_STATUSES,
    ObjectiveEvidence,
    ObjectiveEvidenceAttribute,
    ObjectiveEvidenceContext,
    PaperContribution,
)


FINDING_ASSERTION_STRENGTHS: Final[frozenset[str]] = frozenset(
    {"causal", "associative", "descriptive"}
)
FINDING_SYNTHESIS_STATUSES: Final[frozenset[str]] = frozenset(
    {"agreement", "conflict", "condition_dependent", "insufficient_confirmation"}
)
FINDING_ORIGINS: Final[frozenset[str]] = frozenset(
    {"system_generated", "human_authored", "hybrid"}
)
_FINDING_CONTEXT_ROLES: Final[frozenset[str]] = frozenset(
    {
        "condition_context",
        "mechanism_context",
        "baseline_context",
        "comparison_context",
    }
)
_CONTRADICTING_DIRECTIONS: Final[dict[str, frozenset[str]]] = {
    "increase": frozenset({"decrease", "no_change"}),
    "decrease": frozenset({"increase", "no_change"}),
    "improve": frozenset({"worsen", "no_change"}),
    "worsen": frozenset({"improve", "no_change"}),
    "changed": frozenset({"no_change"}),
    "no_change": frozenset(
        {"increase", "decrease", "improve", "worsen", "changed"}
    ),
}
_J_PER_CUBIC_MM_RE = re.compile(
    r"\bj\s*/\s*mm\s*(?:\^\s*)?(?:3|\u00b3)\b",
    re.IGNORECASE,
)


def directions_contradict(direction: str, observed_direction: str) -> bool:
    """Return whether two reported-result directions explicitly oppose."""

    return observed_direction in _CONTRADICTING_DIRECTIONS.get(direction, ())


@dataclass(frozen=True)
class FindingMechanismRelation:
    source_term: str
    relation_type: str
    target_term: str
    direction: str | None
    assertion_strength: str
    supporting_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all(
            _text(value)
            for value in (self.source_term, self.relation_type, self.target_term)
        ):
            raise ValueError("finding mechanism requires source, relation, and target")
        if self.assertion_strength not in FINDING_ASSERTION_STRENGTHS:
            raise ValueError(
                "unsupported finding mechanism assertion strength: "
                f"{self.assertion_strength}"
            )
        if not self.supporting_evidence_ids:
            raise ValueError("finding mechanism requires supporting evidence")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FindingMechanismRelation":
        return cls(
            source_term=_text(payload.get("source_term")) or "",
            relation_type=_text(payload.get("relation_type")) or "",
            target_term=_text(payload.get("target_term")) or "",
            direction=_text(payload.get("direction")),
            assertion_strength=_choice(
                payload.get("assertion_strength"),
                FINDING_ASSERTION_STRENGTHS,
                "descriptive",
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
class FindingPaperContribution:
    document_id: str
    analysis_status: str
    supporting_evidence_ids: tuple[str, ...] = ()
    contradicting_evidence_ids: tuple[str, ...] = ()
    context_evidence_ids: tuple[str, ...] = ()
    condition_boundary_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _text(self.document_id):
            raise ValueError("finding paper contribution requires document_id")
        if self.analysis_status not in PAPER_CONTRIBUTION_STATUSES:
            raise ValueError(
                "unsupported finding paper contribution status: "
                f"{self.analysis_status}"
            )
        if self.analysis_status == "pending":
            raise ValueError("completed Finding cannot contain pending paper analysis")
        supporting = set(self.supporting_evidence_ids)
        contradicting = set(self.contradicting_evidence_ids)
        context = set(self.context_evidence_ids)
        if supporting & contradicting:
            raise ValueError("supporting and contradicting evidence must be disjoint")
        if self.analysis_status != "analyzed" and (
            supporting or contradicting or context
        ):
            raise ValueError("excluded or failed paper cannot bind Finding evidence")
        linked = supporting | contradicting | context
        if not set(self.condition_boundary_evidence_ids) <= linked:
            raise ValueError("condition-boundary evidence must already bind the paper")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FindingPaperContribution":
        return cls(
            document_id=_text(payload.get("document_id")) or "",
            analysis_status=_choice(
                payload.get("analysis_status"),
                PAPER_CONTRIBUTION_STATUSES,
                "pending",
            ),
            supporting_evidence_ids=_strings(
                payload.get("supporting_evidence_ids")
            ),
            contradicting_evidence_ids=_strings(
                payload.get("contradicting_evidence_ids")
            ),
            context_evidence_ids=_strings(payload.get("context_evidence_ids")),
            condition_boundary_evidence_ids=_strings(
                payload.get("condition_boundary_evidence_ids")
            ),
        )

    @property
    def has_direct_evidence(self) -> bool:
        return bool(self.supporting_evidence_ids or self.contradicting_evidence_ids)

    def to_record(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "analysis_status": self.analysis_status,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "contradicting_evidence_ids": list(self.contradicting_evidence_ids),
            "context_evidence_ids": list(self.context_evidence_ids),
            "condition_boundary_evidence_ids": list(
                self.condition_boundary_evidence_ids
            ),
        }


@dataclass(frozen=True)
class Finding:
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    statement: str
    factors: tuple[str, ...]
    outcome: str
    direction: str
    assertion_strength: str
    attribution_scope: str
    synthesis_status: str
    certainty: float
    display_rank: int
    mechanisms: tuple[FindingMechanismRelation, ...]
    scientific_context: ObjectiveEvidenceContext
    limitations: tuple[str, ...]
    paper_contributions: tuple[FindingPaperContribution, ...]
    origin: str = "system_generated"
    source_analysis_version: int | None = None
    parent_finding_id: str | None = None
    created_by_user_id: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not all(
            _text(value)
            for value in (
                self.collection_id,
                self.objective_id,
                self.finding_id,
                self.statement,
                self.outcome,
            )
        ):
            raise ValueError("finding requires scoped identity and one outcome")
        if len(self.finding_id) > 128:
            raise ValueError("finding ID exceeds 128 characters")
        if self.analysis_version < 1:
            raise ValueError("finding requires positive analysis_version")
        if not self.factors:
            raise ValueError("finding requires factors")
        factor_keys = [_normalize_term(value) for value in self.factors]
        if any(not value for value in factor_keys) or len(factor_keys) != len(
            set(factor_keys)
        ):
            raise ValueError("finding factors must be non-empty and unique")
        if self.direction not in EVIDENCE_RESULT_DIRECTIONS:
            raise ValueError(f"unsupported finding direction: {self.direction}")
        if self.assertion_strength not in FINDING_ASSERTION_STRENGTHS:
            raise ValueError(
                f"unsupported finding assertion strength: {self.assertion_strength}"
            )
        if self.attribution_scope not in EVIDENCE_ATTRIBUTION_SCOPES - {
            "not_attributable"
        }:
            raise ValueError(
                f"unsupported finding attribution scope: {self.attribution_scope}"
            )
        if self.synthesis_status not in FINDING_SYNTHESIS_STATUSES:
            raise ValueError(
                f"unsupported finding synthesis status: {self.synthesis_status}"
            )
        if not math.isfinite(self.certainty) or not 0 <= self.certainty <= 1:
            raise ValueError("finding certainty must be between 0 and 1")
        if self.display_rank < 0:
            raise ValueError("finding display_rank cannot be negative")
        if not self.paper_contributions:
            raise ValueError("finding requires paper contribution coverage")
        document_ids = [item.document_id for item in self.paper_contributions]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("finding paper contributions must be unique")
        if not self.supporting_evidence_ids:
            raise ValueError("finding requires supporting direct evidence")
        if set(self.supporting_evidence_ids) & set(self.contradicting_evidence_ids):
            raise ValueError("supporting and contradicting evidence must be disjoint")
        mechanism_ids = set(
            _ordered_union(item.supporting_evidence_ids for item in self.mechanisms)
        )
        if not mechanism_ids <= set(self.context_evidence_ids):
            raise ValueError("finding mechanism evidence must bind as paper context")
        if self.synthesis_status != self.synthesis_status_for(
            self.paper_contributions
        ):
            raise ValueError("finding synthesis status differs from paper evidence")
        if self.attribution_scope == "isolated_effect" and len(self.factors) != 1:
            raise ValueError("isolated-effect Finding requires one factor")
        if self.attribution_scope == "joint_effect" and len(self.factors) < 2:
            raise ValueError("joint-effect Finding requires multiple factors")
        if self.assertion_strength == "causal" and self.attribution_scope != (
            "isolated_effect"
        ):
            raise ValueError("causal Finding requires isolated-effect attribution")
        if self.attribution_scope == "descriptive_only" and (
            self.assertion_strength != "descriptive"
        ):
            raise ValueError("descriptive Finding requires descriptive assertion")
        if self.origin not in FINDING_ORIGINS:
            raise ValueError(f"unsupported finding origin: {self.origin}")
        if self.origin == "system_generated":
            if self.created_by_user_id or self.parent_finding_id:
                raise ValueError(
                    "system-generated Finding cannot have human author provenance"
                )
        else:
            if self.source_analysis_version is None:
                raise ValueError("authored Finding requires source_analysis_version")
            if self.source_analysis_version >= self.analysis_version:
                raise ValueError("authored Finding source must be an older version")
            if not _text(self.created_by_user_id) or self.created_at is None:
                raise ValueError("authored Finding requires creator and creation time")
        if self.origin == "hybrid" and not _text(self.parent_finding_id):
            raise ValueError("hybrid Finding requires parent_finding_id")
        if self.origin == "human_authored" and self.parent_finding_id is not None:
            raise ValueError("human-authored Finding cannot have a parent Finding")
        if self.parent_finding_id == self.finding_id:
            raise ValueError("Finding cannot derive from itself")

    @property
    def key(self) -> tuple[str, str, int, str]:
        return (
            self.collection_id,
            self.objective_id,
            self.analysis_version,
            self.finding_id,
        )

    @property
    def supporting_evidence_ids(self) -> tuple[str, ...]:
        return _ordered_union(
            item.supporting_evidence_ids for item in self.paper_contributions
        )

    @property
    def contradicting_evidence_ids(self) -> tuple[str, ...]:
        return _ordered_union(
            item.contradicting_evidence_ids for item in self.paper_contributions
        )

    @property
    def context_evidence_ids(self) -> tuple[str, ...]:
        return _ordered_union(
            item.context_evidence_ids for item in self.paper_contributions
        )

    @property
    def condition_boundary_evidence_ids(self) -> tuple[str, ...]:
        return _ordered_union(
            item.condition_boundary_evidence_ids
            for item in self.paper_contributions
        )

    @property
    def supporting_document_ids(self) -> tuple[str, ...]:
        return tuple(
            item.document_id
            for item in self.paper_contributions
            if item.supporting_evidence_ids
        )

    @property
    def contributing_document_ids(self) -> tuple[str, ...]:
        return tuple(
            item.document_id
            for item in self.paper_contributions
            if item.has_direct_evidence
        )

    @property
    def direct_document_count(self) -> int:
        return len(self.contributing_document_ids)

    @property
    def support_scope(self) -> str:
        return "cross_paper" if self.direct_document_count >= 2 else "paper"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "Finding":
        factors = _strings(payload.get("factors"))
        outcome = _text(payload.get("outcome")) or ""
        return cls(
            collection_id=_text(payload.get("collection_id")) or "",
            objective_id=_text(payload.get("objective_id")) or "",
            analysis_version=_positive_int(payload.get("analysis_version")),
            finding_id=_text(payload.get("finding_id"))
            or _stable_id(
                "finding",
                payload.get("objective_id"),
                payload.get("analysis_version"),
                factors,
                outcome,
                payload.get("supporting_evidence_ids"),
            ),
            statement=_text(payload.get("statement")) or "",
            factors=factors,
            outcome=outcome,
            direction=_choice(
                payload.get("direction"), EVIDENCE_RESULT_DIRECTIONS, "unknown"
            ),
            assertion_strength=_choice(
                payload.get("assertion_strength"),
                FINDING_ASSERTION_STRENGTHS,
                "descriptive",
            ),
            attribution_scope=_choice(
                payload.get("attribution_scope"),
                EVIDENCE_ATTRIBUTION_SCOPES - {"not_attributable"},
                "descriptive_only",
            ),
            synthesis_status=_choice(
                payload.get("synthesis_status"),
                FINDING_SYNTHESIS_STATUSES,
                "insufficient_confirmation",
            ),
            certainty=_certainty(payload.get("certainty")),
            display_rank=_non_negative_int(payload.get("display_rank")),
            mechanisms=tuple(
                FindingMechanismRelation.from_mapping(item)
                for item in _mapping_list(payload.get("mechanisms"))
            ),
            scientific_context=(
                ObjectiveEvidenceContext.from_mapping(
                    _mapping(payload.get("scientific_context"))
                )
            ),
            limitations=_strings(payload.get("limitations")),
            paper_contributions=tuple(
                FindingPaperContribution.from_mapping(item)
                for item in _mapping_list(payload.get("paper_contributions"))
            ),
            origin=_choice(
                payload.get("origin"), FINDING_ORIGINS, "system_generated"
            ),
            source_analysis_version=(
                _positive_int(payload.get("source_analysis_version")) or None
            ),
            parent_finding_id=_text(payload.get("parent_finding_id")),
            created_by_user_id=_text(payload.get("created_by_user_id")),
            created_at=_datetime_or_none(payload.get("created_at")),
        )

    @staticmethod
    def synthesis_status_for(
        paper_contributions: tuple[FindingPaperContribution, ...],
    ) -> str:
        direct = tuple(item for item in paper_contributions if item.has_direct_evidence)
        if len(direct) < 2:
            return "insufficient_confirmation"
        if any(item.condition_boundary_evidence_ids for item in direct):
            return "condition_dependent"
        if any(item.contradicting_evidence_ids for item in direct):
            return "conflict"
        if sum(bool(item.supporting_evidence_ids) for item in direct) >= 2:
            return "agreement"
        return "insufficient_confirmation"

    @staticmethod
    def attribution_scope_for(
        factors: tuple[str, ...],
        supporting_evidence: tuple[ObjectiveEvidence, ...],
    ) -> str:
        if not supporting_evidence:
            raise ValueError("Finding attribution requires supporting evidence")
        scopes = {item.attribution_scope for item in supporting_evidence}
        if "descriptive_only" in scopes:
            return "descriptive_only"
        if "association_only" in scopes:
            return "association_only"
        if len(factors) == 1 and scopes == {"isolated_effect"}:
            return "isolated_effect"
        if len(factors) >= 2 and scopes == {"joint_effect"}:
            return "joint_effect"
        return "association_only"

    @staticmethod
    def certainty_for(
        synthesis_status: str,
        direct_evidence: tuple[ObjectiveEvidence, ...],
    ) -> float:
        if not direct_evidence:
            raise ValueError("Finding certainty requires direct evidence")
        certainty = round(min(item.confidence for item in direct_evidence), 2)
        document_count = len({item.document_id for item in direct_evidence})
        document_cap = 0.5 if document_count == 1 else 0.75 if document_count == 2 else 0.85
        status_cap = {
            "conflict": 0.6,
            "condition_dependent": 0.7,
            "insufficient_confirmation": 0.5,
        }.get(synthesis_status, 1.0)
        return min(certainty, document_cap, status_cap)

    @staticmethod
    def common_scientific_context_for(
        supporting_evidence: tuple[ObjectiveEvidence, ...],
    ) -> ObjectiveEvidenceContext:
        if not supporting_evidence:
            return ObjectiveEvidenceContext()
        return ObjectiveEvidenceContext(
            material=_common_attributes(supporting_evidence, "material"),
            sample=_common_attributes(supporting_evidence, "sample"),
            process=_common_attributes(supporting_evidence, "process"),
            test=_common_attributes(supporting_evidence, "test"),
        )

    def validate_sources(
        self,
        evidence_records: tuple[ObjectiveEvidence, ...],
        contributions: tuple[PaperContribution, ...],
    ) -> None:
        evidence_by_id = {item.evidence_id: item for item in evidence_records}
        contribution_by_document = {
            item.document_id: item for item in contributions
        }
        binding_by_document = {
            item.document_id: item for item in self.paper_contributions
        }
        if set(binding_by_document) != set(contribution_by_document):
            raise ValueError("finding paper coverage differs from Objective analysis")
        for document_id, binding in binding_by_document.items():
            contribution = contribution_by_document[document_id]
            if binding.analysis_status != contribution.analysis_status:
                raise ValueError("finding paper status differs from paper contribution")

        mechanism_ids = _ordered_union(
            item.supporting_evidence_ids for item in self.mechanisms
        )
        referenced_ids = set(
            (
                *self.supporting_evidence_ids,
                *self.contradicting_evidence_ids,
                *self.context_evidence_ids,
                *mechanism_ids,
            )
        )
        missing = referenced_ids - set(evidence_by_id)
        if missing:
            raise ValueError(
                "finding references missing evidence: " + ", ".join(sorted(missing))
            )

        for binding in self.paper_contributions:
            for evidence_id in (
                *binding.supporting_evidence_ids,
                *binding.contradicting_evidence_ids,
                *binding.context_evidence_ids,
            ):
                evidence = evidence_by_id[evidence_id]
                if evidence.document_id != binding.document_id:
                    raise ValueError("finding paper binding crosses documents")

        for evidence_id in referenced_ids:
            evidence = evidence_by_id[evidence_id]
            if (
                evidence.collection_id,
                evidence.objective_id,
                evidence.analysis_version,
            ) != (self.collection_id, self.objective_id, self.analysis_version):
                raise ValueError("finding references cross-version evidence")
            if not evidence.supports_finding:
                raise ValueError("finding references ineligible evidence")

        supporting = tuple(
            evidence_by_id[evidence_id]
            for evidence_id in self.supporting_evidence_ids
        )
        contradicting = tuple(
            evidence_by_id[evidence_id]
            for evidence_id in self.contradicting_evidence_ids
        )
        for evidence in supporting:
            self._validate_direct_evidence(evidence)
            if evidence.reported_result.direction != self.direction:
                raise ValueError("finding support direction differs from Finding")
        for evidence in contradicting:
            self._validate_direct_evidence(evidence)
            if not directions_contradict(
                self.direction,
                evidence.reported_result.direction,
            ):
                raise ValueError("finding contradiction does not oppose its direction")
        for evidence_id in self.context_evidence_ids:
            if evidence_by_id[evidence_id].evidence_role not in _FINDING_CONTEXT_ROLES:
                raise ValueError("finding context references non-context evidence")
        for evidence_id in mechanism_ids:
            if evidence_by_id[evidence_id].evidence_role != "mechanism_context":
                raise ValueError("finding mechanism lacks mechanism evidence")

        expected_scope = self.attribution_scope_for(self.factors, supporting)
        if self.attribution_scope != expected_scope:
            raise ValueError("finding attribution differs from supporting evidence")
        expected_certainty = self.certainty_for(
            self.synthesis_status, supporting + contradicting
        )
        if self.certainty != expected_certainty:
            raise ValueError("finding certainty differs from direct evidence")
        expected_context = self.common_scientific_context_for(supporting)
        if self.scientific_context != expected_context:
            raise ValueError("finding context differs from common supporting evidence")

    def _validate_direct_evidence(
        self,
        evidence: ObjectiveEvidence,
    ) -> None:
        if evidence.evidence_role not in {"direct_result", "contradictory_result"}:
            raise ValueError("finding direct evidence must have a result role")
        if evidence.attribution_scope == "not_attributable":
            raise ValueError("finding cannot use non-attributable direct evidence")
        if evidence.reported_result is None:
            raise ValueError("finding direct evidence requires reported result")

        evidence_factors = tuple(
            sorted(
                (_normalize_term(item.name) for item in evidence.changed_variables),
            )
        )
        finding_factors = tuple(sorted(_normalize_term(item) for item in self.factors))
        if evidence_factors != finding_factors:
            raise ValueError("finding factors differ from direct evidence")
        if _normalize_term(evidence.reported_result.outcome) != _normalize_term(
            self.outcome
        ):
            raise ValueError("finding outcome differs from direct evidence")

    def to_record(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "objective_id": self.objective_id,
            "analysis_version": self.analysis_version,
            "finding_id": self.finding_id,
            "statement": self.statement,
            "factors": list(self.factors),
            "outcome": self.outcome,
            "direction": self.direction,
            "assertion_strength": self.assertion_strength,
            "attribution_scope": self.attribution_scope,
            "synthesis_status": self.synthesis_status,
            "certainty": self.certainty,
            "display_rank": self.display_rank,
            "mechanisms": [item.to_record() for item in self.mechanisms],
            "scientific_context": self.scientific_context.to_record(),
            "limitations": list(self.limitations),
            "paper_contributions": [
                item.to_record() for item in self.paper_contributions
            ],
            "origin": self.origin,
            "source_analysis_version": self.source_analysis_version,
            "parent_finding_id": self.parent_finding_id,
            "created_by_user_id": self.created_by_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def _common_attributes(
    evidence_records: tuple[ObjectiveEvidence, ...],
    category: str,
) -> tuple[ObjectiveEvidenceAttribute, ...]:
    first = tuple(getattr(evidence_records[0].scientific_context, category))
    common_keys = {_attribute_key(item) for item in first}
    for evidence in evidence_records[1:]:
        common_keys &= {
            _attribute_key(item)
            for item in getattr(evidence.scientific_context, category)
        }
    return tuple(item for item in first if _attribute_key(item) in common_keys)


def _attribute_key(attribute: ObjectiveEvidenceAttribute) -> tuple[str, str, str]:
    return (
        _normalize_term(attribute.name),
        _stable_text(attribute.value),
        _normalize_term(attribute.unit),
    )


def _ordered_union(values: Any) -> tuple[str, ...]:
    return _strings(item for group in values for item in group)


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


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = _text(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid Finding creation time") from exc


def _certainty(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(numeric):
        return 0.0
    return round(min(1.0, max(0.0, numeric)), 2)


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
    elif isinstance(value, str):
        items = (value,)
    else:
        try:
            items = tuple(value)
        except TypeError:
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


def _normalize_term(value: Any) -> str:
    text = _J_PER_CUBIC_MM_RE.sub("J/mm3", _text(value) or "")
    return " ".join(
        part
        for part in "".join(
            character.lower() if character.isalnum() else " "
            for character in text
        ).split()
    )
