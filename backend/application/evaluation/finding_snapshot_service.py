"""Read canonical Finding review snapshots and check plan source validity."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha1, sha256
from typing import (
    Any,
    Mapping,
)

from application.core.objectives.analysis import experiment_projection
from application.core.objectives.analysis.analysis_record_source import (
    should_read_experiment_projection,
)
from application.core.objectives.objective_analysis_service import (
    ResearchObjectiveNotFoundError,
)
from domain.core.finding import Finding
from domain.core.research_objective import ObjectiveEvidence, PaperContribution
from domain.evaluation import FindingCuration, FindingFeedback
from exceptions import ResourceConflictException, ResourceNotFoundException

_FINDING_PAGE_SIZE = 200
_EVIDENCE_PAGE_SIZE = 500


from repositories.finding_review_repository import FindingReviewRepo
from repositories.objective_repository import ObjectiveRepo


from dataclasses import dataclass


@dataclass(frozen=True)
class FindingReviewSnapshot:
    target_finding: Finding
    evidence: tuple[ObjectiveEvidence, ...]
    label_status: str
    dataset_use_status: str
    system_prediction: dict[str, Any]
    expert_target: dict[str, Any] | None
    training_target: dict[str, Any]
    evidence_records: list[dict[str, Any]]
    finding_fingerprint: str
    evidence_fingerprint: str


async def read_finding_snapshot(finding: Finding) -> FindingReviewSnapshot:
    evidence = await _finding_evidence(finding)
    feedback = await FindingReviewRepo.list_feedback(
        finding.collection_id,
        finding.objective_id,
        finding.analysis_version,
        finding.finding_id,
    )
    curations = await FindingReviewRepo.list_curations(
        finding.collection_id,
        finding.objective_id,
        finding.analysis_version,
        finding.finding_id,
    )
    sample_label, use_status, current_curation = _dataset_status(
        feedback,
        curations,
    )
    system_prediction = {
        "collection_id": finding.collection_id,
        "objective_id": finding.objective_id,
        "analysis_version": finding.analysis_version,
        "finding_id": finding.finding_id,
        "statement": finding.statement,
        "factors": list(finding.factors),
        "outcome": finding.outcome,
        "direction": finding.direction,
        "assertion_strength": finding.assertion_strength,
        "attribution_scope": finding.attribution_scope,
        "synthesis_status": finding.synthesis_status,
        "certainty": finding.certainty,
        "display_rank": finding.display_rank,
        "mechanisms": [
            {
                "source_term": mechanism.source_term,
                "relation_type": mechanism.relation_type,
                "target_term": mechanism.target_term,
                "direction": mechanism.direction,
                "assertion_strength": mechanism.assertion_strength,
                "supporting_evidence_ids": list(mechanism.supporting_evidence_ids),
            }
            for mechanism in finding.mechanisms
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
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in finding.scientific_context.material
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
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in finding.scientific_context.sample
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
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in finding.scientific_context.process
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
                        {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                        if attribute.applies_to_outcomes
                        else {}
                    ),
                }
                for attribute in finding.scientific_context.test
            ],
        },
        "limitations": list(finding.limitations),
        "paper_contributions": [
            {
                "document_id": contribution.document_id,
                "analysis_status": contribution.analysis_status,
                "supporting_evidence_ids": list(contribution.supporting_evidence_ids),
                "contradicting_evidence_ids": list(
                    contribution.contradicting_evidence_ids
                ),
                "context_evidence_ids": list(contribution.context_evidence_ids),
                "condition_boundary_evidence_ids": list(
                    contribution.condition_boundary_evidence_ids
                ),
            }
            for contribution in finding.paper_contributions
        ],
        "origin": finding.origin,
        "source_analysis_version": finding.source_analysis_version,
        "parent_finding_id": finding.parent_finding_id,
        "created_by_user_id": finding.created_by_user_id,
        "created_by_tool_call_id": finding.created_by_tool_call_id,
        "created_at": (finding.created_at.isoformat() if finding.created_at else None),
        **(
            {"selection_ids": list(finding.selection_ids)}
            if finding.selection_ids
            else {}
        ),
        **(
            {"comparison_group_ids": list(finding.comparison_group_ids)}
            if finding.comparison_group_ids
            else {}
        ),
        **({"warnings": list(finding.warnings)} if finding.warnings else {}),
    }
    expert_target = (
        {
            "collection_id": current_curation.curated_finding.collection_id,
            "objective_id": current_curation.curated_finding.objective_id,
            "analysis_version": current_curation.curated_finding.analysis_version,
            "finding_id": current_curation.curated_finding.finding_id,
            "statement": current_curation.curated_finding.statement,
            "factors": list(current_curation.curated_finding.factors),
            "outcome": current_curation.curated_finding.outcome,
            "direction": current_curation.curated_finding.direction,
            "assertion_strength": current_curation.curated_finding.assertion_strength,
            "attribution_scope": current_curation.curated_finding.attribution_scope,
            "synthesis_status": current_curation.curated_finding.synthesis_status,
            "certainty": current_curation.curated_finding.certainty,
            "display_rank": current_curation.curated_finding.display_rank,
            "mechanisms": [
                {
                    "source_term": mechanism.source_term,
                    "relation_type": mechanism.relation_type,
                    "target_term": mechanism.target_term,
                    "direction": mechanism.direction,
                    "assertion_strength": mechanism.assertion_strength,
                    "supporting_evidence_ids": list(mechanism.supporting_evidence_ids),
                }
                for mechanism in current_curation.curated_finding.mechanisms
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
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in current_curation.curated_finding.scientific_context.material
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
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in current_curation.curated_finding.scientific_context.sample
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
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in current_curation.curated_finding.scientific_context.process
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
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
                            if attribute.applies_to_outcomes
                            else {}
                        ),
                    }
                    for attribute in current_curation.curated_finding.scientific_context.test
                ],
            },
            "limitations": list(current_curation.curated_finding.limitations),
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
                for contribution in current_curation.curated_finding.paper_contributions
            ],
            "origin": current_curation.curated_finding.origin,
            "source_analysis_version": current_curation.curated_finding.source_analysis_version,
            "parent_finding_id": current_curation.curated_finding.parent_finding_id,
            "created_by_user_id": current_curation.curated_finding.created_by_user_id,
            "created_by_tool_call_id": current_curation.curated_finding.created_by_tool_call_id,
            "created_at": (
                current_curation.curated_finding.created_at.isoformat()
                if current_curation.curated_finding.created_at
                else None
            ),
            **(
                {"selection_ids": list(current_curation.curated_finding.selection_ids)}
                if current_curation.curated_finding.selection_ids
                else {}
            ),
            **(
                {
                    "comparison_group_ids": list(
                        current_curation.curated_finding.comparison_group_ids
                    )
                }
                if current_curation.curated_finding.comparison_group_ids
                else {}
            ),
            **(
                {"warnings": list(current_curation.curated_finding.warnings)}
                if current_curation.curated_finding.warnings
                else {}
            ),
        }
        if current_curation is not None
        else None
    )
    training_target = expert_target or system_prediction
    target_finding = (
        current_curation.curated_finding if current_curation is not None else finding
    )
    evidence_records = [
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
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
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
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
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
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
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
                            {"applies_to_outcomes": list(attribute.applies_to_outcomes)}
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
        for item in evidence
    ]
    finding_fingerprint = _fingerprint("finding.v2", training_target)
    evidence_fingerprint = _fingerprint("evidence.v2", evidence_records)
    return FindingReviewSnapshot(
        target_finding=target_finding,
        evidence=evidence,
        label_status=sample_label,
        dataset_use_status=use_status,
        system_prediction=system_prediction,
        expert_target=expert_target,
        training_target=training_target,
        evidence_records=evidence_records,
        finding_fingerprint=finding_fingerprint,
        evidence_fingerprint=evidence_fingerprint,
    )


async def _all_findings(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
) -> tuple[Finding, ...]:
    if await should_read_experiment_projection(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
    ):
        findings, _, _ = await experiment_projection.read_analysis_records(
            collection_id, objective_id, analysis_version
        )
        return findings
    result: list[Finding] = []
    offset = 0
    while True:
        page, total = await ObjectiveRepo.list_findings(
            collection_id,
            objective_id,
            analysis_version,
            offset=offset,
            limit=_FINDING_PAGE_SIZE,
        )
        result.extend(page)
        offset += len(page)
        if offset >= total:
            return tuple(result)
        if not page:
            raise RuntimeError("Finding pagination ended before the reported total")


async def _finding_evidence(finding: Finding) -> tuple[ObjectiveEvidence, ...]:
    if await should_read_experiment_projection(
        collection_id=finding.collection_id,
        objective_id=finding.objective_id,
        analysis_version=finding.analysis_version,
    ):
        _, evidence, _ = await experiment_projection.read_analysis_records(
            finding.collection_id, finding.objective_id, finding.analysis_version
        )
        linked = {
            *finding.supporting_evidence_ids,
            *finding.contradicting_evidence_ids,
            *finding.context_evidence_ids,
        }
        return tuple(item for item in evidence if item.evidence_id in linked)
    result: list[ObjectiveEvidence] = []
    offset = 0
    while True:
        page, total = await ObjectiveRepo.list_evidence(
            finding.collection_id,
            finding.objective_id,
            finding.analysis_version,
            finding_id=finding.finding_id,
            offset=offset,
            limit=_EVIDENCE_PAGE_SIZE,
        )
        result.extend(page)
        offset += len(page)
        if offset >= total:
            return tuple(result)
        if not page:
            raise RuntimeError("Evidence pagination ended before the reported total")


async def _require_published_finding(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    finding_id: str,
) -> Finding:
    objective = await ObjectiveRepo.read_objective(collection_id, objective_id)
    if objective is None:
        raise ResearchObjectiveNotFoundError(collection_id, objective_id)
    if objective.published_analysis_version != analysis_version:
        raise ResourceConflictException(
            "Review must reference the published analysis version.",
            data={
                "code": "analysis_version_not_published",
                "published_analysis_version": objective.published_analysis_version,
            },
        )
    if await should_read_experiment_projection(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
    ):
        findings, _, _ = await experiment_projection.read_analysis_records(
            collection_id, objective_id, analysis_version
        )
        finding = next(
            (item for item in findings if item.finding_id == finding_id), None
        )
    else:
        finding = await ObjectiveRepo.read_finding(
            collection_id,
            objective_id,
            analysis_version,
            finding_id,
        )
    if finding is None:
        raise ResourceNotFoundException(
            "Finding is not present in the published analysis.",
            data={"code": "finding_not_found", "finding_id": finding_id},
        )
    return finding


async def _list_contributions(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
) -> tuple[PaperContribution, ...]:
    if await should_read_experiment_projection(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
    ):
        _, _, contributions = await experiment_projection.read_analysis_records(
            collection_id, objective_id, analysis_version
        )
        return contributions
    return await ObjectiveRepo.list_contributions(
        collection_id,
        objective_id,
        analysis_version,
    )


def _dataset_status(
    feedback: tuple[FindingFeedback, ...],
    curations: tuple[FindingCuration, ...],
) -> tuple[str, str, FindingCuration | None]:
    events: list[tuple[datetime, int, FindingFeedback | FindingCuration]] = [
        (_datetime(item.created_at), 0, item) for item in feedback
    ]
    events.extend((_datetime(item.updated_at), 1, item) for item in curations)
    if not events:
        return "candidate", "review_candidate", None
    latest = max(events, key=lambda item: (item[0], item[1]))[2]
    if isinstance(latest, FindingCuration):
        if latest.curated_status == "unsupported":
            return "rejected", "rejected", latest
        return "gold", "training_ready", latest
    if latest.review_status == "correct":
        return "gold", "training_ready", None
    if latest.review_status == "incorrect":
        return "rejected", "rejected", None
    return "silver", "review_candidate", None


def _source_snapshot_validity(
    source_findings: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    dataset_items: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    if not source_findings:
        return "stale", ["source_finding_snapshot_missing"]
    current_by_finding_id = {item["finding_id"]: item for item in dataset_items}
    reasons: list[str] = []
    for source_finding in source_findings:
        finding_id = source_finding["finding_id"]
        current = current_by_finding_id.get(finding_id)
        if current is None:
            reasons.append("source_finding_missing")
            continue
        if current.get("dataset_use_status") != "training_ready":
            reasons.append("source_finding_no_longer_reviewed")
            continue
        if current["analysis_version"] != source_finding["analysis_version"]:
            reasons.append("source_analysis_version_changed")
        if current["finding_fingerprint"] != source_finding["finding_fingerprint"]:
            reasons.append("source_finding_changed")
        if current["evidence_fingerprint"] != source_finding["evidence_fingerprint"]:
            reasons.append("source_evidence_changed")
        if _dataset_evidence_ids(current) != tuple(source_finding["evidence_ids"]):
            reasons.append("source_evidence_ids_changed")
    if reasons:
        return "stale", list(dict.fromkeys(reasons))
    return "current", []


def _dataset_evidence_ids(item: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(evidence["evidence_id"] for evidence in item["evidence"])


def _fingerprint(prefix: str, value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{prefix}:{sha256(payload.encode('utf-8')).hexdigest()}"


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


async def source_snapshot_validity(
    *,
    collection_id: str,
    objective_id: str,
    source_findings: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
) -> tuple[str, list[str]]:
    objective = await ObjectiveRepo.read_objective(collection_id, objective_id)
    if objective is None or objective.published_analysis_version is None:
        return "stale", ["source_dataset_unavailable"]
    items = []
    for finding_id in dict.fromkeys(item["finding_id"] for item in source_findings):
        try:
            finding = await _require_published_finding(
                collection_id,
                objective_id,
                objective.published_analysis_version,
                finding_id,
            )
        except ResourceNotFoundException:
            continue
        snapshot = await read_finding_snapshot(finding)
        items.append(
            {
                "finding_id": finding_id,
                "analysis_version": finding.analysis_version,
                "dataset_use_status": snapshot.dataset_use_status,
                "finding_fingerprint": snapshot.finding_fingerprint,
                "evidence_fingerprint": snapshot.evidence_fingerprint,
                "evidence": snapshot.evidence_records,
            }
        )
    return _source_snapshot_validity(source_findings, items)
