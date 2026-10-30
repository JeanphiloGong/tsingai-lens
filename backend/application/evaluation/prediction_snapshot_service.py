from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from application.core.objectives.analysis.analysis_record_source import (
    should_read_experiment_projection,
)
from domain.evaluation import (
    EvaluationPredictionItem,
    EvaluationPredictionSnapshot,
)


class CoreArtifactsNotReadyForEvaluationError(RuntimeError):
    """Raised when Core artifacts cannot produce an evaluation snapshot."""

    def __init__(self, collection_id: str, fact_source: str) -> None:
        self.collection_id = collection_id
        self.fact_source = fact_source
        super().__init__(
            f"core artifacts not ready for evaluation: {collection_id}/{fact_source}"
        )


from repositories.evaluation_repository import EvaluationRepo
from repositories.objective_repository import ObjectiveRepo
from application.source import collection_service
from application.core.objectives.analysis import experiment_compatibility_projection as experiment_projection


async def create_core_snapshot(
    *,
    collection_id: str,
    fact_source: str = "objective_first",
    snapshot_id: str | None = None,
    system_context: dict[str, Any] | None = None,
) -> EvaluationPredictionSnapshot:
    await collection_service.get_collection(collection_id)
    if fact_source != "objective_first":
        raise ValueError(f"unsupported fact_source: {fact_source}")
    items, objective_counts = await _objective_first_items(collection_id)
    if not items:
        raise CoreArtifactsNotReadyForEvaluationError(collection_id, fact_source)
    snapshot = EvaluationPredictionSnapshot(
        snapshot_id=snapshot_id
        or f"pred_{collection_id}_{fact_source}_{_timestamp_id()}",
        collection_id=collection_id,
        target_layer="core",
        fact_source=fact_source,
        system_context=system_context or {},
        artifact_counts=objective_counts,
        items=tuple(items),
    )
    await EvaluationRepo.upsert_prediction_snapshot(snapshot)
    return snapshot


async def _objective_first_items(
    collection_id: str,
) -> tuple[list[EvaluationPredictionItem], dict[str, int]]:
    items: list[EvaluationPredictionItem] = []
    published_analysis_count = 0
    exported_evidence_keys: set[tuple[str, int, str]] = set()
    for objective in await ObjectiveRepo.list_objectives(collection_id):
        analysis_version = objective.published_analysis_version
        if analysis_version is None:
            continue
        published_analysis_count += 1
        finding_offset = 0
        while True:
            findings, finding_total = await _list_findings(
                collection_id,
                objective.objective_id,
                analysis_version,
                offset=finding_offset,
                limit=200,
            )
            if not findings:
                break
            for finding in findings:
                finding_id = str(_field(finding, "finding_id") or "")
                evidence_records: list[Any] = []
                evidence_offset = 0
                while True:
                    evidence_page, evidence_total = await _list_evidence(
                        collection_id,
                        objective.objective_id,
                        analysis_version,
                        finding_id=finding_id,
                        offset=evidence_offset,
                        limit=500,
                    )
                    if not evidence_page:
                        break
                    evidence_records.extend(evidence_page)
                    evidence_offset += len(evidence_page)
                    if evidence_offset >= evidence_total:
                        break
                for evidence in evidence_records:
                    exported_evidence_keys.add(
                        (
                            objective.objective_id,
                            analysis_version,
                            str(_field(evidence, "evidence_id") or ""),
                        )
                    )
                contributing_documents = tuple(
                    _field(item, "document_id")
                    for item in (_field(finding, "paper_contributions") or ())
                    if _field(item, "document_id")
                )
                item_key = (
                    f"{objective.objective_id}:v{analysis_version}:" f"{finding_id}"
                )
                payload = (
                    dict(finding)
                    if isinstance(finding, Mapping)
                    else {
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
                                "supporting_evidence_ids": list(
                                    mechanism.supporting_evidence_ids
                                ),
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
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
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
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
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
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
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
                                        {
                                            "applies_to_outcomes": list(
                                                attribute.applies_to_outcomes
                                            )
                                        }
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
                                "context_evidence_ids": list(
                                    contribution.context_evidence_ids
                                ),
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
                            finding.created_at.isoformat()
                            if finding.created_at
                            else None
                        ),
                        **(
                            {"selection_ids": list(finding.selection_ids)}
                            if finding.selection_ids
                            else {}
                        ),
                        **(
                            {
                                "comparison_group_ids": list(
                                    finding.comparison_group_ids
                                )
                            }
                            if finding.comparison_group_ids
                            else {}
                        ),
                        **(
                            {"warnings": list(finding.warnings)}
                            if finding.warnings
                            else {}
                        ),
                    }
                )
                payload["evidence"] = [
                    (
                        dict(evidence)
                        if isinstance(evidence, Mapping)
                        else {
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
                                    "axis_names": list(
                                        evidence.comparison.axis_names
                                    ),
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
                                            {
                                                "context_scope": attribute.context_scope
                                            }
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
                                    for attribute in evidence.scientific_context.material
                                ],
                                "sample": [
                                    {
                                        "name": attribute.name,
                                        "value": attribute.value,
                                        "unit": attribute.unit,
                                        **(
                                            {
                                                "context_scope": attribute.context_scope
                                            }
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
                                    for attribute in evidence.scientific_context.sample
                                ],
                                "process": [
                                    {
                                        "name": attribute.name,
                                        "value": attribute.value,
                                        "unit": attribute.unit,
                                        **(
                                            {
                                                "context_scope": attribute.context_scope
                                            }
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
                                    for attribute in evidence.scientific_context.process
                                ],
                                "test": [
                                    {
                                        "name": attribute.name,
                                        "value": attribute.value,
                                        "unit": attribute.unit,
                                        **(
                                            {
                                                "context_scope": attribute.context_scope
                                            }
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
                                evidence.created_at.isoformat()
                                if evidence.created_at is not None
                                else None
                            ),
                            "authoring_note": evidence.authoring_note,
                            **(
                                {"warnings": list(evidence.warnings)}
                                if evidence.warnings
                                else {}
                            ),
                            **(
                                {
                                    "related_source_refs": [
                                        dict(item)
                                        for item in evidence.related_source_refs
                                    ]
                                }
                                if evidence.related_source_refs
                                or evidence.related_source_refs_explicit
                                else {}
                            ),
                        }
                    )
                    for evidence in evidence_records
                ]
                source_refs = tuple(
                    {
                        "evidence_id": _field(evidence, "evidence_id"),
                        "document_id": _field(evidence, "document_id"),
                        "source_kind": _field(evidence, "source_kind"),
                        "source_ref": _field(evidence, "source_ref"),
                        "source_excerpt": _field(evidence, "source_excerpt"),
                        "page_numbers": list(
                            _field(evidence, "page_numbers") or ()
                        ),
                        "related_source_refs": [
                            dict(locator)
                            for locator in (
                                _field(evidence, "related_source_refs") or ()
                            )
                        ],
                    }
                    for evidence in evidence_records
                )
                items.append(
                    EvaluationPredictionItem(
                        item_id=item_key,
                        document_id=(
                            contributing_documents[0]
                            if len(contributing_documents) == 1
                            else ""
                        ),
                        family="objective_findings",
                        item_key=item_key,
                        payload=payload,
                        source_refs=source_refs,
                        confidence=float(_field(finding, "certainty") or 0),
                    )
                )
            finding_offset += len(findings)
            if finding_offset >= finding_total:
                break
    return items, {
        "published_objective_analyses": published_analysis_count,
        "objective_findings": len(items),
        "objective_evidence": len(exported_evidence_keys),
    }


async def _list_findings(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    *,
    offset: int,
    limit: int,
) -> tuple[tuple[Any, ...], int]:
    if await should_read_experiment_projection(
        objective_repository=ObjectiveRepo,
        experiment_projection=experiment_projection,
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
    ):
        return await experiment_projection.list_findings(
            collection_id,
            objective_id,
            analysis_version,
            offset=offset,
            limit=limit,
        )
    return await ObjectiveRepo.list_findings(
        collection_id,
        objective_id,
        analysis_version,
        offset=offset,
        limit=limit,
    )


async def _list_evidence(
    collection_id: str,
    objective_id: str,
    analysis_version: int,
    *,
    finding_id: str,
    offset: int,
    limit: int,
) -> tuple[tuple[Any, ...], int]:
    if await should_read_experiment_projection(
        objective_repository=ObjectiveRepo,
        experiment_projection=experiment_projection,
        collection_id=collection_id,
        objective_id=objective_id,
        analysis_version=analysis_version,
    ):
        return await experiment_projection.list_evidence(
            collection_id,
            objective_id,
            analysis_version,
            finding_id=finding_id,
            offset=offset,
            limit=limit,
        )
    return await ObjectiveRepo.list_evidence(
        collection_id,
        objective_id,
        analysis_version,
        finding_id=finding_id,
        offset=offset,
        limit=limit,
    )


def _field(record: Any, name: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(name)
    return getattr(record, name, None)


def _timestamp_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
