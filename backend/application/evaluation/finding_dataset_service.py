"""Export reviewed Finding datasets, training messages and gold drafts."""

from __future__ import annotations

import json
from typing import (
    Any,
    Mapping,
)

from application.core.objectives.objective_analysis_service import (
    ResearchObjectiveNotFoundError,
)
from application.source import collection_service
from domain.core.research_objective import ObjectiveEvidence
from exceptions import ResourceConflictException

DATASET_SCHEMA_VERSION = "objective_finding_dataset.v2"
TRAINING_SCHEMA_VERSION = "objective_finding_training.v2"
TRAINING_PROMPT_VERSION = "objective_finding_training_prompt.v2"


from repositories.objective_repository import ObjectiveRepo


from application.evaluation.finding_snapshot_service import (
    _all_findings,
    _stable_id,
    read_finding_snapshot,
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
        snapshot = await read_finding_snapshot(finding)
        if label_status is not None and snapshot.label_status != label_status:
            continue
        if (
            dataset_use_status is not None
            and snapshot.dataset_use_status != dataset_use_status
        ):
            continue
        training_messages = (
            _training_messages(
                objective.question,
                snapshot.evidence,
                snapshot.training_target,
            )
            if snapshot.dataset_use_status == "training_ready"
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
                "document_ids": list(snapshot.target_finding.contributing_document_ids),
                "label_status": snapshot.label_status,
                "dataset_use_status": snapshot.dataset_use_status,
                "finding_fingerprint": snapshot.finding_fingerprint,
                "evidence_fingerprint": snapshot.evidence_fingerprint,
                "system_prediction": snapshot.system_prediction,
                "expert_target": snapshot.expert_target,
                "training_target": snapshot.training_target,
                "evidence": snapshot.evidence_records,
                "training_schema_version": TRAINING_SCHEMA_VERSION,
                "training_prompt_version": TRAINING_PROMPT_VERSION,
                "training_messages": training_messages,
                "metadata": {
                    "schema_version": TRAINING_SCHEMA_VERSION,
                    "collection_id": collection_id,
                    "objective_id": objective_id,
                    "analysis_version": analysis_version,
                    "finding_id": finding.finding_id,
                    "label_status": snapshot.label_status,
                    "dataset_use_status": snapshot.dataset_use_status,
                    "finding_fingerprint": snapshot.finding_fingerprint,
                    "evidence_fingerprint": snapshot.evidence_fingerprint,
                    "document_ids": list(
                        snapshot.target_finding.contributing_document_ids
                    ),
                    "evidence_ids": [item.evidence_id for item in snapshot.evidence],
                },
            }
        )
    return result


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
