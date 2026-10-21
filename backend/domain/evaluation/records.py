from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Mapping

from domain.core.finding import Finding


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
        "missing_required_finding",
        "forbidden_overclaim",
        "evidence_not_grounded",
    }
)
FINDING_REVIEW_STATUSES: Final[frozenset[str]] = frozenset(
    {"correct", "incorrect", "partial", "unclear"}
)
FINDING_ISSUE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "none",
        "evidence_not_grounded",
        "missing_evidence",
        "insufficient_evidence",
        "wrong_factor",
        "wrong_outcome",
        "wrong_direction",
        "wrong_context",
        "wrong_mechanism",
        "wrong_attribution",
        "wrong_synthesis",
        "overclaim",
        "unclear_statement",
        "other",
    }
)
FINDING_CURATION_STATUSES: Final[frozenset[str]] = frozenset(
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

@dataclass(frozen=True)
class EvaluationPredictionItem:
    item_id: str
    document_id: str
    family: str
    item_key: str
    payload: dict[str, Any]
    source_refs: tuple[dict[str, Any], ...] = ()
    confidence: float | None = None

@dataclass(frozen=True)
class EvaluationPredictionSnapshot:
    snapshot_id: str
    collection_id: str
    target_layer: str
    fact_source: str
    system_context: dict[str, Any]
    artifact_counts: dict[str, int]
    items: tuple[EvaluationPredictionItem, ...]

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

@dataclass(frozen=True)
class FindingFeedback:
    feedback_id: str
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    review_status: str
    issue_type: str
    note: str | None
    reviewer: str | None
    created_at: str

    def __post_init__(self) -> None:
        if not self.collection_id or not self.objective_id or not self.finding_id:
            raise ValueError("finding feedback requires objective and finding identity")
        if self.analysis_version < 1:
            raise ValueError("finding feedback requires a positive analysis_version")
        if self.review_status not in FINDING_REVIEW_STATUSES:
            raise ValueError(f"unsupported finding review status: {self.review_status}")
        if self.issue_type not in FINDING_ISSUE_TYPES:
            raise ValueError(f"unsupported finding issue type: {self.issue_type}")
        if self.review_status == "correct" and self.issue_type != "none":
            raise ValueError("correct finding feedback cannot report an issue")
        if self.review_status in {"incorrect", "partial"} and self.issue_type == "none":
            raise ValueError(
                f"{self.review_status} finding feedback requires an issue"
            )

@dataclass(frozen=True)
class FindingCuration:
    curation_id: str
    collection_id: str
    objective_id: str
    analysis_version: int
    finding_id: str
    curated_status: str
    curated_finding: Finding
    note: str | None
    reviewer: str | None
    updated_at: str

    def __post_init__(self) -> None:
        if not self.collection_id or not self.objective_id or not self.finding_id:
            raise ValueError("finding curation requires objective and finding identity")
        if self.analysis_version < 1:
            raise ValueError("finding curation requires a positive analysis_version")
        if self.curated_status not in FINDING_CURATION_STATUSES:
            raise ValueError(
                f"unsupported finding curation status: {self.curated_status}"
            )
        if self.curated_finding.key != (
            self.collection_id,
            self.objective_id,
            self.analysis_version,
            self.finding_id,
        ):
            raise ValueError("curated Finding identity differs from curation identity")

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
        return tuple(
            _normalize_mapping(item) for item in value if isinstance(item, Mapping)
        )
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
