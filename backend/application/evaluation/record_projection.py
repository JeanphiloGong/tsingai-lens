"""Boundary projections for evaluation records.

Evaluation domain objects stay focused on validated values.  JSON decoding and
the persisted record shape live here so storage and API callers can preserve
the existing contract without putting mapping methods on the domain classes.
"""

from __future__ import annotations

from typing import Any, Mapping

from domain.evaluation.records import (
    EvaluationFailure,
    EvaluationGoldItem,
    EvaluationGoldSet,
    EvaluationPredictionItem,
    EvaluationPredictionSnapshot,
    EvaluationRun,
    EvaluationScore,
    FindingFeedback,
    FindingCuration,
    _normalize_choice,
    _normalize_int_mapping,
    _normalize_mapping,
    _normalize_mapping_sequence,
    _normalize_mapping_tuple,
    _normalize_optional_float,
    _normalize_optional_mapping,
    _normalize_text,
    EVALUATION_FAILURE_TYPES,
    EVALUATION_LAYERS,
    EVALUATION_TARGET_LAYERS,
)
from domain.core.finding import Finding

def evaluation_gold_set_from_record(payload: Mapping[str, Any]) -> EvaluationGoldSet:
    return EvaluationGoldSet(
        gold_id=_normalize_text(payload.get("gold_id")) or "",
        collection_id=_normalize_text(payload.get("collection_id")) or "",
        version=_normalize_text(payload.get("version")) or "v1",
        target_layer=_normalize_choice(payload.get("target_layer"), allowed=EVALUATION_TARGET_LAYERS, default="core"),
        metric_profile=_normalize_text(payload.get("metric_profile")) or "materials_core_v1",
        description=_normalize_text(payload.get("description")),
        metadata=_normalize_mapping(payload.get("metadata")),
    )


def evaluation_gold_set_record(value: EvaluationGoldSet) -> dict[str, Any]:
    return {"gold_id": value.gold_id, "collection_id": value.collection_id, "version": value.version,
            "target_layer": value.target_layer, "metric_profile": value.metric_profile,
            "description": value.description, "metadata": dict(value.metadata or {})}


def evaluation_gold_item_from_record(payload: Mapping[str, Any]) -> EvaluationGoldItem:
    return EvaluationGoldItem(
        gold_item_id=_normalize_text(payload.get("gold_item_id")) or "",
        gold_id=_normalize_text(payload.get("gold_id")) or "",
        document_id=_normalize_text(payload.get("document_id")) or "",
        family=_normalize_text(payload.get("family")) or "",
        item_key=_normalize_text(payload.get("item_key")) or "",
        payload=_normalize_mapping(payload.get("payload")),
        evidence_refs=_normalize_mapping_tuple(payload.get("evidence_refs")),
        metadata=_normalize_mapping(payload.get("metadata")),
    )


def evaluation_gold_item_record(value: EvaluationGoldItem) -> dict[str, Any]:
    return {"gold_item_id": value.gold_item_id, "gold_id": value.gold_id,
            "document_id": value.document_id, "family": value.family, "item_key": value.item_key,
            "payload": dict(value.payload), "evidence_refs": [dict(item) for item in value.evidence_refs],
            "metadata": dict(value.metadata or {})}


def evaluation_prediction_item_from_record(payload: Mapping[str, Any]) -> EvaluationPredictionItem:
    return EvaluationPredictionItem(
        item_id=_normalize_text(payload.get("item_id")) or "",
        document_id=_normalize_text(payload.get("document_id")) or "",
        family=_normalize_text(payload.get("family")) or "",
        item_key=_normalize_text(payload.get("item_key")) or "",
        payload=_normalize_mapping(payload.get("payload")),
        source_refs=_normalize_mapping_tuple(payload.get("source_refs")),
        confidence=_normalize_optional_float(payload.get("confidence")),
    )


def evaluation_prediction_item_record(value: EvaluationPredictionItem) -> dict[str, Any]:
    return {"item_id": value.item_id, "document_id": value.document_id, "family": value.family,
            "item_key": value.item_key, "payload": dict(value.payload),
            "source_refs": [dict(item) for item in value.source_refs], "confidence": value.confidence}


def evaluation_prediction_snapshot_from_record(payload: Mapping[str, Any]) -> EvaluationPredictionSnapshot:
    return EvaluationPredictionSnapshot(
        snapshot_id=_normalize_text(payload.get("snapshot_id")) or "",
        collection_id=_normalize_text(payload.get("collection_id")) or "",
        target_layer=_normalize_choice(payload.get("target_layer"), allowed=EVALUATION_TARGET_LAYERS, default="core"),
        fact_source=_normalize_text(payload.get("fact_source")) or "paper_facts",
        system_context=_normalize_mapping(payload.get("system_context")),
        artifact_counts=_normalize_int_mapping(payload.get("artifact_counts")),
        items=tuple(evaluation_prediction_item_from_record(item) for item in _normalize_mapping_sequence(payload.get("items"))),
    )


def evaluation_prediction_snapshot_record(value: EvaluationPredictionSnapshot) -> dict[str, Any]:
    return {"snapshot_id": value.snapshot_id, "collection_id": value.collection_id,
            "target_layer": value.target_layer, "fact_source": value.fact_source,
            "system_context": dict(value.system_context), "artifact_counts": dict(value.artifact_counts),
            "items": [evaluation_prediction_item_record(item) for item in value.items]}


def evaluation_score_from_record(payload: Mapping[str, Any]) -> EvaluationScore:
    return EvaluationScore(
        score_id=_normalize_text(payload.get("score_id")) or "",
        evaluation_run_id=_normalize_text(payload.get("evaluation_run_id")) or "",
        family=_normalize_text(payload.get("family")) or "overall",
        metric=_normalize_text(payload.get("metric")) or "",
        value=_normalize_optional_float(payload.get("value")) or 0.0,
        numerator=_normalize_optional_float(payload.get("numerator")),
        denominator=_normalize_optional_float(payload.get("denominator")),
        document_id=_normalize_text(payload.get("document_id")),
    )


def evaluation_score_record(value: EvaluationScore) -> dict[str, Any]:
    return {"score_id": value.score_id, "evaluation_run_id": value.evaluation_run_id,
            "family": value.family, "metric": value.metric, "value": value.value,
            "numerator": value.numerator, "denominator": value.denominator, "document_id": value.document_id}


def evaluation_failure_from_record(payload: Mapping[str, Any]) -> EvaluationFailure:
    return EvaluationFailure(
        failure_id=_normalize_text(payload.get("failure_id")) or "",
        evaluation_run_id=_normalize_text(payload.get("evaluation_run_id")) or "",
        document_id=_normalize_text(payload.get("document_id")) or "",
        family=_normalize_text(payload.get("family")) or "",
        failure_type=_normalize_choice(payload.get("failure_type"), allowed=EVALUATION_FAILURE_TYPES, default="missing_gold_item"),
        likely_layer=_normalize_choice(payload.get("likely_layer"), allowed=EVALUATION_LAYERS, default="unknown"),
        severity=_normalize_text(payload.get("severity")) or "medium",
        gold_item_id=_normalize_text(payload.get("gold_item_id")),
        prediction_item_id=_normalize_text(payload.get("prediction_item_id")),
        gold=_normalize_optional_mapping(payload.get("gold")),
        prediction=_normalize_optional_mapping(payload.get("prediction")),
        reason=_normalize_text(payload.get("reason")),
        source_refs=_normalize_mapping_tuple(payload.get("source_refs")),
    )


def evaluation_failure_record(value: EvaluationFailure) -> dict[str, Any]:
    return {"failure_id": value.failure_id, "evaluation_run_id": value.evaluation_run_id,
            "document_id": value.document_id, "family": value.family, "failure_type": value.failure_type,
            "likely_layer": value.likely_layer, "severity": value.severity,
            "gold_item_id": value.gold_item_id, "prediction_item_id": value.prediction_item_id,
            "gold": dict(value.gold) if value.gold is not None else None,
            "prediction": dict(value.prediction) if value.prediction is not None else None,
            "reason": value.reason, "source_refs": [dict(item) for item in value.source_refs]}


def evaluation_run_from_record(payload: Mapping[str, Any]) -> EvaluationRun:
    return EvaluationRun(
        evaluation_run_id=_normalize_text(payload.get("evaluation_run_id")) or "",
        collection_id=_normalize_text(payload.get("collection_id")) or "",
        gold_id=_normalize_text(payload.get("gold_id")) or "",
        prediction_snapshot_id=_normalize_text(payload.get("prediction_snapshot_id")) or "",
        target_layer=_normalize_choice(payload.get("target_layer"), allowed=EVALUATION_TARGET_LAYERS, default="core"),
        fact_source=_normalize_text(payload.get("fact_source")) or "paper_facts",
        metric_profile=_normalize_text(payload.get("metric_profile")) or "materials_core_v1",
        status=_normalize_text(payload.get("status")) or "ready",
        summary=_normalize_mapping(payload.get("summary")),
        scores=tuple(evaluation_score_from_record(item) for item in _normalize_mapping_sequence(payload.get("scores"))),
        failures=tuple(evaluation_failure_from_record(item) for item in _normalize_mapping_sequence(payload.get("failures"))),
    )


def evaluation_run_record(value: EvaluationRun) -> dict[str, Any]:
    return {"evaluation_run_id": value.evaluation_run_id, "collection_id": value.collection_id,
            "gold_id": value.gold_id, "prediction_snapshot_id": value.prediction_snapshot_id,
            "target_layer": value.target_layer, "fact_source": value.fact_source,
            "metric_profile": value.metric_profile, "status": value.status, "summary": dict(value.summary),
            "scores": [evaluation_score_record(item) for item in value.scores],
            "failures": [evaluation_failure_record(item) for item in value.failures]}


def finding_feedback_from_record(payload: Mapping[str, Any]) -> FindingFeedback:
    return FindingFeedback(
        feedback_id=_normalize_text(payload.get("feedback_id")) or "",
        collection_id=_normalize_text(payload.get("collection_id")) or "",
        objective_id=_normalize_text(payload.get("objective_id")) or "",
        analysis_version=int(payload.get("analysis_version") or 0),
        finding_id=_normalize_text(payload.get("finding_id")) or "",
        review_status=(_normalize_text(payload.get("review_status")) or "").lower(),
        issue_type=(_normalize_text(payload.get("issue_type")) or "").lower(),
        note=_normalize_text(payload.get("note")), reviewer=_normalize_text(payload.get("reviewer")),
        created_at=_normalize_text(payload.get("created_at")) or "",
    )


def finding_feedback_record(value: FindingFeedback) -> dict[str, Any]:
    return {"feedback_id": value.feedback_id, "collection_id": value.collection_id,
            "objective_id": value.objective_id, "analysis_version": value.analysis_version,
            "finding_id": value.finding_id, "review_status": value.review_status,
            "issue_type": value.issue_type, "note": value.note, "reviewer": value.reviewer,
            "created_at": value.created_at}


def finding_curation_from_record(payload: Mapping[str, Any]) -> FindingCuration:
    return FindingCuration(
        curation_id=_normalize_text(payload.get("curation_id")) or "",
        collection_id=_normalize_text(payload.get("collection_id")) or "",
        objective_id=_normalize_text(payload.get("objective_id")) or "",
        analysis_version=int(payload.get("analysis_version") or 0),
        finding_id=_normalize_text(payload.get("finding_id")) or "",
        curated_status=(_normalize_text(payload.get("curated_status")) or "").lower(),
        curated_finding=Finding.from_mapping(_normalize_mapping(payload.get("curated_finding"))),
        note=_normalize_text(payload.get("note")), reviewer=_normalize_text(payload.get("reviewer")),
        updated_at=_normalize_text(payload.get("updated_at")) or "",
    )


def finding_curation_record(value: FindingCuration) -> dict[str, Any]:
    return {"curation_id": value.curation_id, "collection_id": value.collection_id,
            "objective_id": value.objective_id, "analysis_version": value.analysis_version,
            "finding_id": value.finding_id, "curated_status": value.curated_status,
            "curated_finding": value.curated_finding.to_record(), "note": value.note,
            "reviewer": value.reviewer, "updated_at": value.updated_at}
