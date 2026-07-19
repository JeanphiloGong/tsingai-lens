from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Mapping


EVALUATION_TARGET_LAYERS: Final[frozenset[str]] = frozenset({"core", "goal"})
EVALUATION_LAYERS: Final[frozenset[str]] = frozenset(
    {"source", "core_extraction", "core_normalization", "goal", "unknown"}
)
EVALUATION_FAILURE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "missing_gold_item",
        "extra_prediction",
        "numeric_value_mismatch",
        "unit_mismatch",
        "evidence_trace_missing",
        "comparison_value_mismatch",
        "comparison_direction_mismatch",
        "missing_required_claim",
        "forbidden_overclaim",
        "evidence_not_grounded",
    }
)
RESEARCH_UNDERSTANDING_REVIEW_STATUSES: Final[frozenset[str]] = frozenset(
    {"correct", "incorrect", "partial", "unclear"}
)
RESEARCH_UNDERSTANDING_ISSUE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "none",
        "evidence_not_grounded",
        "missing_evidence",
        "insufficient_evidence",
        "wrong_variable",
        "wrong_outcome",
        "wrong_direction",
        "wrong_context",
        "wrong_relation",
        "overclaim",
        "unclear_statement",
        "other",
    }
)
RESEARCH_UNDERSTANDING_CLAIM_TYPES: Final[frozenset[str]] = frozenset(
    {"finding", "measurement", "comparison", "mechanism", "limitation", "context"}
)
RESEARCH_UNDERSTANDING_CLAIM_STATUSES: Final[frozenset[str]] = frozenset(
    {"supported", "limited", "conflicted", "unsupported"}
)


@dataclass(frozen=True)
class EvaluationGoldSet:
    gold_id: str
    collection_id: str
    version: str
    target_layer: str
    metric_profile: str
    description: str | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EvaluationGoldSet":
        return cls(
            gold_id=_normalize_text(payload.get("gold_id")) or "",
            collection_id=_normalize_text(payload.get("collection_id")) or "",
            version=_normalize_text(payload.get("version")) or "v1",
            target_layer=_normalize_choice(
                payload.get("target_layer"),
                allowed=EVALUATION_TARGET_LAYERS,
                default="core",
            ),
            metric_profile=_normalize_text(payload.get("metric_profile"))
            or "materials_core_v1",
            description=_normalize_text(payload.get("description")),
            metadata=_normalize_mapping(payload.get("metadata")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "gold_id": self.gold_id,
            "collection_id": self.collection_id,
            "version": self.version,
            "target_layer": self.target_layer,
            "metric_profile": self.metric_profile,
            "description": self.description,
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class EvaluationGoldItem:
    gold_item_id: str
    gold_id: str
    document_id: str
    family: str
    item_key: str
    payload: dict[str, Any]
    evidence_refs: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EvaluationGoldItem":
        return cls(
            gold_item_id=_normalize_text(payload.get("gold_item_id")) or "",
            gold_id=_normalize_text(payload.get("gold_id")) or "",
            document_id=_normalize_text(payload.get("document_id")) or "",
            family=_normalize_text(payload.get("family")) or "",
            item_key=_normalize_text(payload.get("item_key")) or "",
            payload=_normalize_mapping(payload.get("payload")),
            evidence_refs=_normalize_mapping_tuple(payload.get("evidence_refs")),
            metadata=_normalize_mapping(payload.get("metadata")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "gold_item_id": self.gold_item_id,
            "gold_id": self.gold_id,
            "document_id": self.document_id,
            "family": self.family,
            "item_key": self.item_key,
            "payload": dict(self.payload),
            "evidence_refs": [dict(item) for item in self.evidence_refs],
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class EvaluationPredictionItem:
    item_id: str
    document_id: str
    family: str
    item_key: str
    payload: dict[str, Any]
    source_refs: tuple[dict[str, Any], ...] = ()
    confidence: float | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EvaluationPredictionItem":
        return cls(
            item_id=_normalize_text(payload.get("item_id")) or "",
            document_id=_normalize_text(payload.get("document_id")) or "",
            family=_normalize_text(payload.get("family")) or "",
            item_key=_normalize_text(payload.get("item_key")) or "",
            payload=_normalize_mapping(payload.get("payload")),
            source_refs=_normalize_mapping_tuple(payload.get("source_refs")),
            confidence=_normalize_optional_float(payload.get("confidence")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "document_id": self.document_id,
            "family": self.family,
            "item_key": self.item_key,
            "payload": dict(self.payload),
            "source_refs": [dict(item) for item in self.source_refs],
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class EvaluationPredictionSnapshot:
    snapshot_id: str
    collection_id: str
    target_layer: str
    fact_source: str
    system_context: dict[str, Any]
    artifact_counts: dict[str, int]
    items: tuple[EvaluationPredictionItem, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EvaluationPredictionSnapshot":
        return cls(
            snapshot_id=_normalize_text(payload.get("snapshot_id")) or "",
            collection_id=_normalize_text(payload.get("collection_id")) or "",
            target_layer=_normalize_choice(
                payload.get("target_layer"),
                allowed=EVALUATION_TARGET_LAYERS,
                default="core",
            ),
            fact_source=_normalize_text(payload.get("fact_source")) or "paper_facts",
            system_context=_normalize_mapping(payload.get("system_context")),
            artifact_counts=_normalize_int_mapping(payload.get("artifact_counts")),
            items=tuple(
                EvaluationPredictionItem.from_mapping(item)
                for item in _normalize_mapping_sequence(payload.get("items"))
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "collection_id": self.collection_id,
            "target_layer": self.target_layer,
            "fact_source": self.fact_source,
            "system_context": dict(self.system_context),
            "artifact_counts": dict(self.artifact_counts),
            "items": [item.to_record() for item in self.items],
        }


@dataclass(frozen=True)
class EvaluationScore:
    score_id: str
    evaluation_run_id: str
    family: str
    metric: str
    value: float
    numerator: float | None = None
    denominator: float | None = None
    document_id: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EvaluationScore":
        return cls(
            score_id=_normalize_text(payload.get("score_id")) or "",
            evaluation_run_id=_normalize_text(payload.get("evaluation_run_id")) or "",
            family=_normalize_text(payload.get("family")) or "overall",
            metric=_normalize_text(payload.get("metric")) or "",
            value=_normalize_optional_float(payload.get("value")) or 0.0,
            numerator=_normalize_optional_float(payload.get("numerator")),
            denominator=_normalize_optional_float(payload.get("denominator")),
            document_id=_normalize_text(payload.get("document_id")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "score_id": self.score_id,
            "evaluation_run_id": self.evaluation_run_id,
            "family": self.family,
            "metric": self.metric,
            "value": self.value,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "document_id": self.document_id,
        }


@dataclass(frozen=True)
class EvaluationFailure:
    failure_id: str
    evaluation_run_id: str
    document_id: str
    family: str
    failure_type: str
    likely_layer: str
    severity: str
    gold_item_id: str | None
    prediction_item_id: str | None
    gold: dict[str, Any] | None
    prediction: dict[str, Any] | None
    reason: str | None = None
    source_refs: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EvaluationFailure":
        return cls(
            failure_id=_normalize_text(payload.get("failure_id")) or "",
            evaluation_run_id=_normalize_text(payload.get("evaluation_run_id")) or "",
            document_id=_normalize_text(payload.get("document_id")) or "",
            family=_normalize_text(payload.get("family")) or "",
            failure_type=_normalize_choice(
                payload.get("failure_type"),
                allowed=EVALUATION_FAILURE_TYPES,
                default="missing_gold_item",
            ),
            likely_layer=_normalize_choice(
                payload.get("likely_layer"),
                allowed=EVALUATION_LAYERS,
                default="unknown",
            ),
            severity=_normalize_text(payload.get("severity")) or "medium",
            gold_item_id=_normalize_text(payload.get("gold_item_id")),
            prediction_item_id=_normalize_text(payload.get("prediction_item_id")),
            gold=_normalize_optional_mapping(payload.get("gold")),
            prediction=_normalize_optional_mapping(payload.get("prediction")),
            reason=_normalize_text(payload.get("reason")),
            source_refs=_normalize_mapping_tuple(payload.get("source_refs")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "evaluation_run_id": self.evaluation_run_id,
            "document_id": self.document_id,
            "family": self.family,
            "failure_type": self.failure_type,
            "likely_layer": self.likely_layer,
            "severity": self.severity,
            "gold_item_id": self.gold_item_id,
            "prediction_item_id": self.prediction_item_id,
            "gold": dict(self.gold) if self.gold is not None else None,
            "prediction": (
                dict(self.prediction) if self.prediction is not None else None
            ),
            "reason": self.reason,
            "source_refs": [dict(item) for item in self.source_refs],
        }


@dataclass(frozen=True)
class EvaluationRun:
    evaluation_run_id: str
    collection_id: str
    gold_id: str
    prediction_snapshot_id: str
    target_layer: str
    fact_source: str
    metric_profile: str
    status: str
    summary: dict[str, Any]
    scores: tuple[EvaluationScore, ...] = ()
    failures: tuple[EvaluationFailure, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EvaluationRun":
        return cls(
            evaluation_run_id=_normalize_text(payload.get("evaluation_run_id")) or "",
            collection_id=_normalize_text(payload.get("collection_id")) or "",
            gold_id=_normalize_text(payload.get("gold_id")) or "",
            prediction_snapshot_id=_normalize_text(
                payload.get("prediction_snapshot_id")
            )
            or "",
            target_layer=_normalize_choice(
                payload.get("target_layer"),
                allowed=EVALUATION_TARGET_LAYERS,
                default="core",
            ),
            fact_source=_normalize_text(payload.get("fact_source")) or "paper_facts",
            metric_profile=_normalize_text(payload.get("metric_profile"))
            or "materials_core_v1",
            status=_normalize_text(payload.get("status")) or "ready",
            summary=_normalize_mapping(payload.get("summary")),
            scores=tuple(
                EvaluationScore.from_mapping(score)
                for score in _normalize_mapping_sequence(payload.get("scores"))
            ),
            failures=tuple(
                EvaluationFailure.from_mapping(failure)
                for failure in _normalize_mapping_sequence(payload.get("failures"))
            ),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "evaluation_run_id": self.evaluation_run_id,
            "collection_id": self.collection_id,
            "gold_id": self.gold_id,
            "prediction_snapshot_id": self.prediction_snapshot_id,
            "target_layer": self.target_layer,
            "fact_source": self.fact_source,
            "metric_profile": self.metric_profile,
            "status": self.status,
            "summary": dict(self.summary),
            "scores": [score.to_record() for score in self.scores],
            "failures": [failure.to_record() for failure in self.failures],
        }


@dataclass(frozen=True)
class ResearchUnderstandingFeedback:
    feedback_id: str
    collection_id: str
    scope_type: str
    scope_id: str
    finding_id: str
    claim_id: str | None
    finding_fingerprint: str | None
    review_status: str
    issue_type: str
    note: str | None
    reviewer: str | None
    created_at: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchUnderstandingFeedback":
        return cls(
            feedback_id=_normalize_text(payload.get("feedback_id")) or "",
            collection_id=_normalize_text(payload.get("collection_id")) or "",
            scope_type=_normalize_text(payload.get("scope_type")) or "",
            scope_id=_normalize_text(payload.get("scope_id")) or "",
            finding_id=_normalize_text(payload.get("finding_id")) or "",
            claim_id=_normalize_text(payload.get("claim_id")),
            finding_fingerprint=_normalize_text(payload.get("finding_fingerprint")),
            review_status=_normalize_choice(
                payload.get("review_status"),
                allowed=RESEARCH_UNDERSTANDING_REVIEW_STATUSES,
                default="unclear",
            ),
            issue_type=_normalize_choice(
                payload.get("issue_type"),
                allowed=RESEARCH_UNDERSTANDING_ISSUE_TYPES,
                default="other",
            ),
            note=_normalize_text(payload.get("note")),
            reviewer=_normalize_text(payload.get("reviewer")),
            created_at=_normalize_text(payload.get("created_at")) or "",
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "collection_id": self.collection_id,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "finding_id": self.finding_id,
            "claim_id": self.claim_id,
            "finding_fingerprint": self.finding_fingerprint,
            "review_status": self.review_status,
            "issue_type": self.issue_type,
            "note": self.note,
            "reviewer": self.reviewer,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ResearchUnderstandingCuration:
    curation_id: str
    collection_id: str
    scope_type: str
    scope_id: str
    finding_id: str
    claim_id: str | None
    finding_fingerprint: str | None
    curated_claim_type: str
    curated_status: str
    curated_statement: str
    curated_support_grade: str | None
    curated_review_status: str | None
    curated_variables: tuple[str, ...]
    curated_mediators: tuple[str, ...]
    curated_outcomes: tuple[str, ...]
    curated_direction: str | None
    curated_scope_summary: str | None
    curated_evidence_ref_ids: tuple[str, ...]
    curated_context_ids: tuple[str, ...]
    note: str | None
    reviewer: str | None
    updated_at: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ResearchUnderstandingCuration":
        return cls(
            curation_id=_normalize_text(payload.get("curation_id")) or "",
            collection_id=_normalize_text(payload.get("collection_id")) or "",
            scope_type=_normalize_text(payload.get("scope_type")) or "",
            scope_id=_normalize_text(payload.get("scope_id")) or "",
            finding_id=_normalize_text(payload.get("finding_id")) or "",
            claim_id=_normalize_text(payload.get("claim_id")),
            finding_fingerprint=_normalize_text(payload.get("finding_fingerprint")),
            curated_claim_type=_normalize_choice(
                payload.get("curated_claim_type"),
                allowed=RESEARCH_UNDERSTANDING_CLAIM_TYPES,
                default="finding",
            ),
            curated_status=_normalize_choice(
                payload.get("curated_status"),
                allowed=RESEARCH_UNDERSTANDING_CLAIM_STATUSES,
                default="limited",
            ),
            curated_statement=_normalize_text(payload.get("curated_statement")) or "",
            curated_support_grade=_normalize_text(payload.get("curated_support_grade")),
            curated_review_status=_normalize_text(payload.get("curated_review_status")),
            curated_variables=_normalize_text_tuple(payload.get("curated_variables")),
            curated_mediators=_normalize_text_tuple(payload.get("curated_mediators")),
            curated_outcomes=_normalize_text_tuple(payload.get("curated_outcomes")),
            curated_direction=_normalize_text(payload.get("curated_direction")),
            curated_scope_summary=_normalize_text(payload.get("curated_scope_summary")),
            curated_evidence_ref_ids=_normalize_text_tuple(
                payload.get("curated_evidence_ref_ids")
            ),
            curated_context_ids=_normalize_text_tuple(payload.get("curated_context_ids")),
            note=_normalize_text(payload.get("note")),
            reviewer=_normalize_text(payload.get("reviewer")),
            updated_at=_normalize_text(payload.get("updated_at")) or "",
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "curation_id": self.curation_id,
            "collection_id": self.collection_id,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "finding_id": self.finding_id,
            "claim_id": self.claim_id,
            "finding_fingerprint": self.finding_fingerprint,
            "curated_claim_type": self.curated_claim_type,
            "curated_status": self.curated_status,
            "curated_statement": self.curated_statement,
            "curated_support_grade": self.curated_support_grade,
            "curated_review_status": self.curated_review_status,
            "curated_variables": list(self.curated_variables),
            "curated_mediators": list(self.curated_mediators),
            "curated_outcomes": list(self.curated_outcomes),
            "curated_direction": self.curated_direction,
            "curated_scope_summary": self.curated_scope_summary,
            "curated_evidence_ref_ids": list(self.curated_evidence_ref_ids),
            "curated_context_ids": list(self.curated_context_ids),
            "note": self.note,
            "reviewer": self.reviewer,
            "updated_at": self.updated_at,
        }


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_choice(value: Any, *, allowed: frozenset[str], default: str) -> str:
    text = (_normalize_text(value) or default).lower()
    return text if text in allowed else default


def _normalize_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _normalize_optional_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return _normalize_mapping(value)


def _normalize_mapping_sequence(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return (_normalize_mapping(value),)
    if isinstance(value, (str, bytes)):
        return ()
    try:
        return tuple(_normalize_mapping(item) for item in value if isinstance(item, Mapping))
    except TypeError:
        return ()


def _normalize_mapping_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    return _normalize_mapping_sequence(value)


def _normalize_text_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        normalized = _normalize_text(value)
        return (normalized,) if normalized else ()
    try:
        return tuple(
            normalized
            for item in value
            if (normalized := _normalize_text(item)) is not None
        )
    except TypeError:
        return ()


def _normalize_int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, int] = {}
    for key, item in value.items():
        try:
            normalized[str(key)] = int(item)
        except (TypeError, ValueError):
            normalized[str(key)] = 0
    return normalized


def _normalize_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
