from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from hashlib import sha1, sha256
from typing import (
    Any,
    Mapping,
)

from application.core.objectives.analysis import experiment_compatibility_projection
from application.core.objectives.analysis.analysis_record_source import (
    should_read_experiment_projection,
)
from application.core.objectives.objective_analysis_service import (
    ResearchObjectiveNotFoundError,
)
from application.source import collection_service
from domain.core.finding import (
    EVIDENCE_ATTRIBUTION_SCOPES,
    FINDING_ASSERTION_STRENGTHS,
    FINDING_ORIGINS,
    FINDING_SYNTHESIS_STATUSES,
    PAPER_CONTRIBUTION_STATUSES,
    Finding,
    FindingMechanismRelation,
    FindingPaperContribution,
)
from domain.core.research_objective import ObjectiveEvidence, PaperContribution
from domain.core.scientific_fact import (
    SCIENTIFIC_CONTEXT_SCOPES,
    SCIENTIFIC_RESULT_DIRECTIONS,
    ScientificAttribute,
    ScientificContext,
)
from domain.evaluation import FindingCuration, FindingFeedback
from domain.evaluation.records import FindingFeedbackDecisionError
from exceptions import (
    RequestInvalidException,
    ResourceConflictException,
    ResourceNotFoundException,
)

DATASET_SCHEMA_VERSION = "objective_finding_dataset.v2"
TRAINING_SCHEMA_VERSION = "objective_finding_training.v2"
TRAINING_PROMPT_VERSION = "objective_finding_training_prompt.v2"
_FINDING_PAGE_SIZE = 200
_EVIDENCE_PAGE_SIZE = 500


from repositories.finding_review_repository import FindingReviewRepo
from repositories.objective_repository import ObjectiveRepo


async def record_feedback(
    *,
    user_id: str,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    finding_id: str,
    review_status: str,
    issue_type: str,
    note: str | None = None,
    reviewer: str | None = None,
) -> FindingFeedback:
    await collection_service.get_collection_for_user(collection_id, user_id)
    created_at = _now_iso()
    try:
        feedback = FindingFeedback(
            feedback_id=_stable_id(
                "feedback",
                collection_id,
                objective_id,
                str(analysis_version),
                finding_id,
                review_status,
                issue_type,
                note or "",
                reviewer or "",
                created_at,
            ),
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=analysis_version,
            finding_id=finding_id,
            review_status=review_status,
            issue_type=issue_type,
            note=note,
            reviewer=reviewer,
            created_at=created_at,
        )
    except FindingFeedbackDecisionError as exc:
        raise RequestInvalidException(
            str(exc), data={"code": "finding_feedback_invalid"}
        ) from exc

    await _require_published_finding(
        collection_id,
        objective_id,
        analysis_version,
        finding_id,
    )
    return await FindingReviewRepo.upsert_feedback(feedback)


async def list_feedback(
    *,
    user_id: str,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    finding_id: str,
) -> tuple[FindingFeedback, ...]:
    await collection_service.get_collection_for_user(collection_id, user_id)
    await _require_published_finding(
        collection_id,
        objective_id,
        analysis_version,
        finding_id,
    )
    return await FindingReviewRepo.list_feedback(
        collection_id,
        objective_id,
        analysis_version,
        finding_id,
    )


async def record_curation(
    *,
    user_id: str,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    finding_id: str,
    curated_status: str,
    curated_finding: Finding,
    note: str | None = None,
    reviewer: str | None = None,
) -> FindingCuration:
    candidate = await validate_curation(
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
        finding_id=finding_id,
        curated_finding=curated_finding,
        user_id=user_id,
    )
    updated_at = _now_iso()
    curation = FindingCuration(
        curation_id=_stable_id(
            "curation",
            collection_id,
            objective_id,
            str(analysis_version),
            finding_id,
        ),
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
        finding_id=finding_id,
        curated_status=curated_status,
        curated_finding=candidate,
        note=note,
        reviewer=reviewer,
        updated_at=updated_at,
    )
    return await FindingReviewRepo.upsert_curation(curation)


async def validate_curation(
    *,
    user_id: str,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    finding_id: str,
    curated_finding: Finding,
) -> Finding:
    await collection_service.get_collection_for_user(collection_id, user_id)
    published = await _require_published_finding(
        collection_id,
        objective_id,
        analysis_version,
        finding_id,
    )
    candidate = curated_finding
    if candidate.key != published.key:
        raise RequestInvalidException(
            "Curation cannot change the published Finding identity.",
            data={"code": "curation_identity_changed"},
        )
    if tuple(
        (item.document_id, item.analysis_status)
        for item in candidate.paper_contributions
    ) != tuple(
        (item.document_id, item.analysis_status)
        for item in published.paper_contributions
    ):
        raise RequestInvalidException(
            "Curation cannot change Objective paper coverage.",
            data={"code": "curation_coverage_changed"},
        )

    evidence = await _finding_evidence(published)
    contributions = await _list_contributions(
        collection_id, objective_id, analysis_version
    )
    try:
        candidate.validate_sources(evidence, contributions)
    except ValueError as exc:
        raise RequestInvalidException(
            str(exc), data={"code": "curation_sources_invalid"}
        ) from exc
    return candidate


async def list_curations(
    *,
    user_id: str,
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    finding_id: str,
) -> tuple[FindingCuration, ...]:
    await collection_service.get_collection_for_user(collection_id, user_id)
    await _require_published_finding(
        collection_id,
        objective_id,
        analysis_version,
        finding_id,
    )
    return await FindingReviewRepo.list_curations(
        collection_id,
        objective_id,
        analysis_version,
        finding_id,
    )


async def export_dataset(
    *,
    user_id: str,
    collection_id: str,
    objective_id: str,
    label_status: str | None = None,
    dataset_use_status: str | None = None,
) -> dict[str, Any]:
    await collection_service.get_collection_for_user(collection_id, user_id)
    objective = await ObjectiveRepo.read_objective(collection_id, objective_id)
    if objective is None:
        raise ResearchObjectiveNotFoundError(collection_id, objective_id)
    version = objective.published_analysis_version
    if version is None:
        raise ResourceConflictException(
            "Objective has no published analysis.",
            data={"code": "objective_analysis_not_published"},
        )
    return {
        "schema_version": DATASET_SCHEMA_VERSION,
        "collection_id": collection_id,
        "objective_id": objective_id,
        "items": await _dataset_items(
            collection_id,
            objective_id,
            version,
            label_status=label_status,
            dataset_use_status=dataset_use_status,
        ),
        "warnings": [],
    }


async def export_collection_dataset(
    *,
    user_id: str,
    collection_id: str,
    label_status: str | None = None,
    dataset_use_status: str | None = None,
) -> dict[str, Any]:
    await collection_service.get_collection_for_user(collection_id, user_id)
    items: list[dict[str, Any]] = []
    for objective in await ObjectiveRepo.list_objectives(collection_id):
        version = objective.published_analysis_version
        if version is None:
            continue
        items.extend(
            await _dataset_items(
                collection_id,
                objective.objective_id,
                version,
                label_status=label_status,
                dataset_use_status=dataset_use_status,
            )
        )
    return {
        "schema_version": DATASET_SCHEMA_VERSION,
        "collection_id": collection_id,
        "objective_id": None,
        "items": items,
        "warnings": [],
    }


async def export_gold_draft(*, collection_id: str, user_id: str) -> dict[str, Any]:
    dataset = await export_collection_dataset(
        collection_id=collection_id,
        label_status="gold",
        user_id=user_id,
    )
    return {
        "gold_id": _stable_id("gold", collection_id),
        "collection_id": collection_id,
        "version": DATASET_SCHEMA_VERSION,
        "target_layer": "core",
        "metric_profile": "objective_findings_v2",
        "items": dataset["items"],
    }


async def source_snapshot_validity(
    *,
    collection_id: str,
    objective_id: str,
    source_findings: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
) -> tuple[str, list[str]]:
    objective = await ObjectiveRepo.read_objective(collection_id, objective_id)
    if objective is None or objective.published_analysis_version is None:
        return "stale", ["source_dataset_unavailable"]
    items = await _dataset_items(
        collection_id,
        objective_id,
        objective.published_analysis_version,
        label_status=None,
        dataset_use_status=None,
    )
    return _source_snapshot_validity(source_findings, items)


async def _dataset_items(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    *,
    label_status: str | None,
    dataset_use_status: str | None,
) -> list[dict[str, Any]]:
    objective = await ObjectiveRepo.read_objective(collection_id, objective_id)
    assert objective is not None
    findings = await _all_findings(collection_id, objective_id, analysis_version)
    result: list[dict[str, Any]] = []
    for finding in findings:
        evidence = await _finding_evidence(finding)
        feedback = await FindingReviewRepo.list_feedback(
            collection_id,
            objective_id,
            analysis_version,
            finding.finding_id,
        )
        curations = await FindingReviewRepo.list_curations(
            collection_id,
            objective_id,
            analysis_version,
            finding.finding_id,
        )
        sample_label, use_status, current_curation = _dataset_status(
            feedback,
            curations,
        )
        if label_status is not None and sample_label != label_status:
            continue
        if dataset_use_status is not None and use_status != dataset_use_status:
            continue

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
                for contribution in finding.paper_contributions
            ],
            "origin": finding.origin,
            "source_analysis_version": finding.source_analysis_version,
            "parent_finding_id": finding.parent_finding_id,
            "created_by_user_id": finding.created_by_user_id,
            "created_by_tool_call_id": finding.created_by_tool_call_id,
            "created_at": (
                finding.created_at.isoformat() if finding.created_at else None
            ),
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
                        "supporting_evidence_ids": list(
                            mechanism.supporting_evidence_ids
                        ),
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
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
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
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
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
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
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
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
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
                    {
                        "selection_ids": list(
                            current_curation.curated_finding.selection_ids
                        )
                    }
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
            current_curation.curated_finding
            if current_curation is not None
            else finding
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
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
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
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
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
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
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
                                {
                                    "applies_to_outcomes": list(
                                        attribute.applies_to_outcomes
                                    )
                                }
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
        training_messages = (
            _training_messages(
                objective.question,
                evidence,
                training_target,
            )
            if use_status == "training_ready"
            else []
        )
        result.append(
            {
                "sample_id": _stable_id(
                    "sample",
                    collection_id,
                    objective_id,
                    str(analysis_version),
                    finding.finding_id,
                ),
                "objective_id": objective_id,
                "analysis_version": analysis_version,
                "finding_id": finding.finding_id,
                "research_objective": objective.question,
                "document_ids": list(target_finding.contributing_document_ids),
                "label_status": sample_label,
                "dataset_use_status": use_status,
                "finding_fingerprint": finding_fingerprint,
                "evidence_fingerprint": evidence_fingerprint,
                "system_prediction": system_prediction,
                "expert_target": expert_target,
                "training_target": training_target,
                "evidence": evidence_records,
                "training_schema_version": TRAINING_SCHEMA_VERSION,
                "training_prompt_version": TRAINING_PROMPT_VERSION,
                "training_messages": training_messages,
                "metadata": {
                    "schema_version": TRAINING_SCHEMA_VERSION,
                    "collection_id": collection_id,
                    "objective_id": objective_id,
                    "analysis_version": analysis_version,
                    "finding_id": finding.finding_id,
                    "label_status": sample_label,
                    "dataset_use_status": use_status,
                    "finding_fingerprint": finding_fingerprint,
                    "evidence_fingerprint": evidence_fingerprint,
                    "document_ids": list(target_finding.contributing_document_ids),
                    "evidence_ids": [item.evidence_id for item in evidence],
                },
            }
        )
    return result


async def _all_findings(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
) -> tuple[Finding, ...]:
    if await should_read_experiment_projection(
        objective_repository=ObjectiveRepo,
        experiment_projection=experiment_compatibility_projection,
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
    ):
        findings, _, _ = (
            await experiment_compatibility_projection.read_analysis_records(
                collection_id, objective_id, analysis_version
            )
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
        objective_repository=ObjectiveRepo,
        experiment_projection=experiment_compatibility_projection,
        collection_id=finding.collection_id,
        objective_id=finding.objective_id,
        analysis_version=finding.analysis_version,
    ):
        _, evidence, _ = (
            await experiment_compatibility_projection.read_analysis_records(
                finding.collection_id, finding.objective_id, finding.analysis_version
            )
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
        objective_repository=ObjectiveRepo,
        experiment_projection=experiment_compatibility_projection,
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
    ):
        findings, _, _ = (
            await experiment_compatibility_projection.read_analysis_records(
                collection_id, objective_id, analysis_version
            )
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
        objective_repository=ObjectiveRepo,
        experiment_projection=experiment_compatibility_projection,
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
    ):
        _, _, contributions = (
            await experiment_compatibility_projection.read_analysis_records(
                collection_id, objective_id, analysis_version
            )
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


def _training_messages(
    question: str,
    evidence: tuple[ObjectiveEvidence, ...],
    output: Mapping[str, Any],
) -> list[dict[str, str]]:
    evidence_text = "\n\n".join(
        _training_evidence_text(index, item)
        for index, item in enumerate(evidence, start=1)
    )
    user_content = (
        f"Research objective: {question}\n"
        "Task: Return one atomic Finding with one complete factor set and one "
        "outcome. Preserve attribution scope, synthesis status, mechanisms, "
        "scientific context, limitations, paper contributions, and Evidence "
        "roles. Use only the Evidence below.\n\n"
        f"Evidence:\n{evidence_text}"
    )
    return [
        {"role": "user", "content": user_content},
        {
            "role": "assistant",
            "content": json.dumps(output, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def _training_evidence_text(index: int, evidence: ObjectiveEvidence) -> str:
    record = {
        "collection_id": evidence.collection_id,
        "objective_id": evidence.objective_id,
        "analysis_version": evidence.analysis_version,
        "evidence_id": evidence.evidence_id,
        "document_id": evidence.document_id,
        "source_kind": evidence.source_kind,
        "source_ref": evidence.source_ref,
        "source_excerpt": evidence.source_excerpt,
        "page_numbers": list(evidence.page_numbers),
        "evidence_role": evidence.evidence_role,
        "selection_status": evidence.selection_status,
        "selection_reason": evidence.selection_reason,
        "evidence_status": evidence.evidence_status,
        "evidence_status_reason": evidence.evidence_status_reason,
        "changed_variables": [
            {
                "name": variable.name,
                "baseline_value": variable.baseline_value,
                "target_value": variable.target_value,
                "unit": variable.unit,
            }
            for variable in evidence.changed_variables
        ],
        "comparison": (
            {
                "baseline_label": evidence.comparison.baseline_label,
                "target_label": evidence.comparison.target_label,
                "axis_names": list(evidence.comparison.axis_names),
                "comparable": evidence.comparison.comparable,
                "incomparability_reasons": list(
                    evidence.comparison.incomparability_reasons
                ),
            }
            if evidence.comparison
            else None
        ),
        "reported_result": (
            {
                "outcome": evidence.reported_result.outcome,
                "value": evidence.reported_result.value,
                "baseline_value": evidence.reported_result.baseline_value,
                "target_value": evidence.reported_result.target_value,
                "unit": evidence.reported_result.unit,
                "direction": evidence.reported_result.direction,
                "result_text": evidence.reported_result.result_text,
                "result_kind": evidence.reported_result.result_kind,
            }
            if evidence.reported_result
            else None
        ),
        "attribution_scope": evidence.attribution_scope,
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
                for attribute in evidence.scientific_context.material
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
                for attribute in evidence.scientific_context.sample
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
                for attribute in evidence.scientific_context.process
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
                for attribute in evidence.scientific_context.test
            ],
        },
        "resolution_status": evidence.resolution_status,
        "failure_reason": evidence.failure_reason,
        "confidence": evidence.confidence,
        "origin": evidence.origin,
        "source_analysis_version": evidence.source_analysis_version,
        "supersedes_evidence_id": evidence.supersedes_evidence_id,
        "superseded_by_evidence_id": evidence.superseded_by_evidence_id,
        "created_by_user_id": evidence.created_by_user_id,
        "created_by_tool_call_id": evidence.created_by_tool_call_id,
        "created_at": (
            evidence.created_at.isoformat() if evidence.created_at is not None else None
        ),
        "authoring_note": evidence.authoring_note,
        **({"warnings": list(evidence.warnings)} if evidence.warnings else {}),
        **(
            {
                "related_source_refs": [
                    dict(item) for item in evidence.related_source_refs
                ]
            }
            if evidence.related_source_refs or evidence.related_source_refs_explicit
            else {}
        ),
    }
    locator = (
        f"{evidence.source_kind}:{evidence.source_ref}; pages="
        f"{','.join(str(page) for page in evidence.page_numbers) or 'unknown'}"
    )
    scientific_payload = {
        "changed_variables": record["changed_variables"],
        "comparison": record["comparison"],
        "reported_result": record["reported_result"],
        "attribution_scope": record["attribution_scope"],
        "scientific_context": record["scientific_context"],
    }
    return (
        f"[E{index} | evidence_id={evidence.evidence_id} | "
        f"document_id={evidence.document_id} | role={evidence.evidence_role} | "
        f"{locator}]\n"
        f"Scientific record: {json.dumps(scientific_payload, ensure_ascii=False, separators=(',', ':'))}\n"
        f"Source excerpt: {evidence.source_excerpt}"
    )


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "DATASET_SCHEMA_VERSION",
    "TRAINING_PROMPT_VERSION",
    "TRAINING_SCHEMA_VERSION",
    "record_feedback",
    "list_feedback",
    "record_curation",
    "validate_curation",
    "list_curations",
    "export_dataset",
    "export_collection_dataset",
    "export_gold_draft",
    "source_snapshot_validity",
]


def parse_curated_finding(payload: Mapping[str, Any]) -> Finding:
    """Reject malformed external review JSON, then construct the Finding once."""
    required = {
        "collection_id",
        "objective_id",
        "analysis_version",
        "finding_id",
        "statement",
        "factors",
        "outcome",
        "direction",
        "assertion_strength",
        "attribution_scope",
        "synthesis_status",
        "certainty",
        "display_rank",
        "mechanisms",
        "scientific_context",
        "limitations",
        "paper_contributions",
        "origin",
        "source_analysis_version",
        "parent_finding_id",
        "created_by_user_id",
        "created_by_tool_call_id",
        "created_at",
    }
    optional = {"selection_ids", "comparison_group_ids", "warnings"}
    error = "curated_finding must use the complete canonical Finding contract"
    if (
        not isinstance(payload, Mapping)
        or not required <= payload.keys()
        or payload.keys() - required - optional
    ):
        raise ValueError(error)
    for name in ("collection_id", "objective_id", "finding_id", "statement", "outcome"):
        if (
            not isinstance(payload[name], str)
            or not payload[name]
            or payload[name] != payload[name].strip()
        ):
            raise ValueError(f"{error}: invalid {name}")
    for name in ("parent_finding_id", "created_by_user_id", "created_by_tool_call_id"):
        value = payload[name]
        if value is not None and (
            not isinstance(value, str) or not value or value != value.strip()
        ):
            raise ValueError(f"{error}: invalid {name}")
    for name, allowed in (
        ("direction", SCIENTIFIC_RESULT_DIRECTIONS),
        ("assertion_strength", FINDING_ASSERTION_STRENGTHS),
        ("attribution_scope", EVIDENCE_ATTRIBUTION_SCOPES - {"not_attributable"}),
        ("synthesis_status", FINDING_SYNTHESIS_STATUSES),
        ("origin", FINDING_ORIGINS),
    ):
        if not isinstance(payload[name], str) or payload[name] not in allowed:
            raise ValueError(f"{error}: invalid {name}")
    for name, minimum in (
        ("analysis_version", 1),
        ("display_rank", 0),
        ("source_analysis_version", 1),
    ):
        value = payload[name]
        if name == "source_analysis_version" and value is None:
            continue
        if type(value) is not int or value < minimum:
            raise ValueError(f"{error}: invalid {name}")
    if (
        type(payload["certainty"]) not in (int, float)
        or not 0 <= payload["certainty"] <= 1
    ):
        raise ValueError(f"{error}: invalid certainty")
    for name in (
        "factors",
        "limitations",
        "selection_ids",
        "comparison_group_ids",
        "warnings",
    ):
        values = payload.get(name, [])
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value or value != value.strip()
            for value in values
        ):
            raise ValueError(f"{error}: invalid {name}")
    if not isinstance(payload["mechanisms"], list) or not isinstance(
        payload["paper_contributions"], list
    ):
        raise ValueError(f"{error}: mechanisms and paper_contributions must be lists")
    mechanisms = []
    for item in payload["mechanisms"]:
        if not isinstance(item, Mapping) or item.keys() != {
            "source_term",
            "relation_type",
            "target_term",
            "direction",
            "assertion_strength",
            "supporting_evidence_ids",
        }:
            raise ValueError(f"{error}: invalid mechanism fields")
        for name in ("source_term", "relation_type", "target_term"):
            if (
                not isinstance(item[name], str)
                or not item[name]
                or item[name] != item[name].strip()
            ):
                raise ValueError(f"{error}: invalid mechanism {name}")
        if item["direction"] is not None and (
            not isinstance(item["direction"], str)
            or item["direction"] not in SCIENTIFIC_RESULT_DIRECTIONS
        ):
            raise ValueError(f"{error}: invalid mechanism direction")
        if (
            not isinstance(item["assertion_strength"], str)
            or item["assertion_strength"] not in FINDING_ASSERTION_STRENGTHS
        ):
            raise ValueError(f"{error}: invalid mechanism assertion_strength")
        refs = item["supporting_evidence_ids"]
        if not isinstance(refs, list) or any(
            not isinstance(ref, str) or not ref or ref != ref.strip() for ref in refs
        ):
            raise ValueError(f"{error}: invalid mechanism evidence")
        mechanisms.append(
            FindingMechanismRelation(
                source_term=item["source_term"],
                relation_type=item["relation_type"],
                target_term=item["target_term"],
                direction=item["direction"],
                assertion_strength=item["assertion_strength"],
                supporting_evidence_ids=tuple(refs),
            )
        )
    contributions = []
    evidence_fields = (
        "supporting_evidence_ids",
        "contradicting_evidence_ids",
        "context_evidence_ids",
        "condition_boundary_evidence_ids",
    )
    for item in payload["paper_contributions"]:
        if not isinstance(item, Mapping) or item.keys() != {
            "document_id",
            "analysis_status",
            *evidence_fields,
        }:
            raise ValueError(f"{error}: invalid paper contribution fields")
        if (
            not isinstance(item["document_id"], str)
            or not item["document_id"]
            or item["document_id"] != item["document_id"].strip()
        ):
            raise ValueError(f"{error}: invalid contribution document_id")
        if (
            not isinstance(item["analysis_status"], str)
            or item["analysis_status"] not in PAPER_CONTRIBUTION_STATUSES
        ):
            raise ValueError(f"{error}: invalid contribution analysis_status")
        for name in evidence_fields:
            refs = item[name]
            if not isinstance(refs, list) or any(
                not isinstance(ref, str) or not ref or ref != ref.strip()
                for ref in refs
            ):
                raise ValueError(f"{error}: invalid {name}")
        contributions.append(
            FindingPaperContribution(
                document_id=item["document_id"],
                analysis_status=item["analysis_status"],
                supporting_evidence_ids=tuple(item["supporting_evidence_ids"]),
                contradicting_evidence_ids=tuple(item["contradicting_evidence_ids"]),
                context_evidence_ids=tuple(item["context_evidence_ids"]),
                condition_boundary_evidence_ids=tuple(
                    item["condition_boundary_evidence_ids"]
                ),
            )
        )
    context = payload["scientific_context"]
    if not isinstance(context, Mapping) or context.keys() != {
        "material",
        "sample",
        "process",
        "test",
    }:
        raise ValueError(f"{error}: invalid scientific_context")
    context_values = {}
    for name in ("material", "sample", "process", "test"):
        if not isinstance(context[name], list):
            raise ValueError(f"{error}: {name} must be a list")
        attributes = []
        for item in context[name]:
            if (
                not isinstance(item, Mapping)
                or not {"name", "value", "unit"} <= item.keys()
                or item.keys()
                - {"name", "value", "unit", "context_scope", "applies_to_outcomes"}
            ):
                raise ValueError(f"{error}: invalid scientific attribute fields")
            if (
                not isinstance(item["name"], str)
                or not item["name"].strip()
                or type(item["value"]) not in (str, int, float, bool)
            ):
                raise ValueError(f"{error}: invalid scientific attribute")
            if isinstance(item["value"], float) and not math.isfinite(item["value"]):
                raise ValueError(f"{error}: invalid scientific value")
            if item["unit"] is not None and not isinstance(item["unit"], str):
                raise ValueError(f"{error}: invalid scientific unit")
            if (
                not isinstance(item.get("context_scope", "unknown"), str)
                or item.get("context_scope", "unknown") not in SCIENTIFIC_CONTEXT_SCOPES
            ):
                raise ValueError(f"{error}: invalid scientific context_scope")
            outcomes = item.get("applies_to_outcomes", [])
            if not isinstance(outcomes, list) or any(
                not isinstance(value, str) for value in outcomes
            ):
                raise ValueError(f"{error}: invalid applies_to_outcomes")
            attributes.append(
                ScientificAttribute(
                    name=item["name"],
                    value=item["value"],
                    unit=item["unit"],
                    context_scope=item.get("context_scope", "unknown"),
                    applies_to_outcomes=tuple(outcomes),
                )
            )
        context_values[name] = tuple(attributes)
    created_at = payload["created_at"]
    if created_at is not None:
        if not isinstance(created_at, str):
            raise ValueError(f"{error}: invalid created_at")
        created_at = datetime.fromisoformat(created_at)
    return Finding(
        collection_id=payload["collection_id"],
        objective_id=payload["objective_id"],
        analysis_version=payload["analysis_version"],
        finding_id=payload["finding_id"],
        statement=payload["statement"],
        factors=tuple(payload["factors"]),
        outcome=payload["outcome"],
        direction=payload["direction"],
        assertion_strength=payload["assertion_strength"],
        attribution_scope=payload["attribution_scope"],
        synthesis_status=payload["synthesis_status"],
        certainty=payload["certainty"],
        display_rank=payload["display_rank"],
        mechanisms=tuple(mechanisms),
        scientific_context=ScientificContext(**context_values),
        limitations=tuple(payload["limitations"]),
        paper_contributions=tuple(contributions),
        origin=payload["origin"],
        source_analysis_version=payload["source_analysis_version"],
        parent_finding_id=payload["parent_finding_id"],
        created_by_user_id=payload["created_by_user_id"],
        created_by_tool_call_id=payload["created_by_tool_call_id"],
        created_at=created_at,
        warnings=tuple(payload.get("warnings", [])),
        selection_ids=tuple(payload.get("selection_ids", [])),
        comparison_group_ids=tuple(payload.get("comparison_group_ids", [])),
    )


def finding_training_rows(payload: dict, format: str):
    """Select approved training items and project the requested training format."""
    for item in payload["items"]:
        if (
            item["dataset_use_status"] != "training_ready"
            or not item["training_messages"]
        ):
            continue
        messages = item["training_messages"]
        if format == "training_jsonl":
            yield {"messages": messages, "metadata": item["metadata"]}
            continue
        instruction = next(
            (
                message["content"]
                for message in messages
                if message.get("role") == "user" and message.get("content")
            ),
            None,
        )
        output = next(
            (
                message["content"]
                for message in messages
                if message.get("role") == "assistant" and message.get("content")
            ),
            None,
        )
        if instruction and output:
            yield {
                "instruction": instruction,
                "input": "",
                "output": output,
                "metadata": item["metadata"],
            }
