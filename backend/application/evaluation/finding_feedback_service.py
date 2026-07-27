from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any

from domain.core import Finding, ObjectiveEvidence
from domain.evaluation import FindingCuration, FindingFeedback
from domain.ports import FindingReviewRepository, ObjectiveRepository


DATASET_SCHEMA_VERSION = "objective_finding_dataset.v1"
TRAINING_SCHEMA_VERSION = "objective_finding_training.v1"
TRAINING_PROMPT_VERSION = "objective_finding_training_prompt.v1"


class FindingFeedbackService:
    """Review and export published, versioned Objective Findings."""

    def __init__(
        self,
        *,
        review_repository: FindingReviewRepository,
        objective_repository: ObjectiveRepository,
    ) -> None:
        self.review_repository = review_repository
        self.objective_repository = objective_repository

    def record_feedback(
        self,
        *,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
        review_status: str,
        issue_type: str,
        note: str | None = None,
        reviewer: str | None = None,
    ) -> FindingFeedback:
        self._require_published_finding(
            collection_id,
            objective_id,
            analysis_version,
            finding_id,
        )
        created_at = _now_iso()
        feedback = FindingFeedback.from_mapping(
            {
                "feedback_id": _stable_id(
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
                "collection_id": collection_id,
                "objective_id": objective_id,
                "analysis_version": analysis_version,
                "finding_id": finding_id,
                "review_status": review_status,
                "issue_type": issue_type,
                "note": note,
                "reviewer": reviewer,
                "created_at": created_at,
            }
        )
        return self.review_repository.upsert_feedback(feedback)

    def list_feedback(
        self,
        *,
        collection_id: str,
        objective_id: str | None = None,
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ) -> tuple[FindingFeedback, ...]:
        return self.review_repository.list_feedback(
            collection_id,
            objective_id,
            analysis_version,
            finding_id,
        )

    def record_curation(
        self,
        *,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
        curated_status: str,
        curated_statement: str,
        curated_evidence_ids: list[str],
        curated_support_grade: str | None = None,
        curated_review_status: str | None = None,
        curated_variables: list[str] | None = None,
        curated_mediators: list[str] | None = None,
        curated_outcomes: list[str] | None = None,
        curated_direction: str | None = None,
        curated_scope_summary: str | None = None,
        note: str | None = None,
        reviewer: str | None = None,
    ) -> FindingCuration:
        finding = self._require_published_finding(
            collection_id,
            objective_id,
            analysis_version,
            finding_id,
        )
        available_evidence, _ = self.objective_repository.list_evidence(
            collection_id,
            objective_id,
            analysis_version,
            finding_id=finding_id,
            offset=0,
            limit=500,
        )
        available_ids = {item.evidence_id for item in available_evidence}
        if set(curated_evidence_ids) - available_ids:
            raise ValueError("curation references evidence outside the Finding")
        updated_at = _now_iso()
        curation = FindingCuration.from_mapping(
            {
                "curation_id": _stable_id(
                    "curation",
                    collection_id,
                    objective_id,
                    str(analysis_version),
                    finding_id,
                ),
                "collection_id": collection_id,
                "objective_id": objective_id,
                "analysis_version": analysis_version,
                "finding_id": finding_id,
                "curated_status": curated_status,
                "curated_statement": curated_statement,
                "curated_support_grade": curated_support_grade,
                "curated_review_status": curated_review_status,
                "curated_variables": curated_variables or list(finding.variables),
                "curated_mediators": curated_mediators or list(finding.mediators),
                "curated_outcomes": curated_outcomes or list(finding.outcomes),
                "curated_direction": curated_direction or finding.direction,
                "curated_scope_summary": (
                    curated_scope_summary or finding.scope_summary
                ),
                "curated_evidence_ids": curated_evidence_ids,
                "note": note,
                "reviewer": reviewer,
                "updated_at": updated_at,
            }
        )
        return self.review_repository.upsert_curation(curation)

    def list_curations(
        self,
        *,
        collection_id: str,
        objective_id: str | None = None,
        analysis_version: int | None = None,
        finding_id: str | None = None,
    ) -> tuple[FindingCuration, ...]:
        return self.review_repository.list_curations(
            collection_id,
            objective_id,
            analysis_version,
            finding_id,
        )

    def export_dataset(
        self,
        *,
        collection_id: str,
        objective_id: str,
        label_status: str | None = None,
        dataset_use_status: str | None = None,
    ) -> dict[str, Any]:
        objective = self.objective_repository.read_objective(
            collection_id, objective_id
        )
        if objective is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        version = objective.published_analysis_version
        if version is None:
            raise ValueError("objective has no published analysis")
        items = self._dataset_items(
            collection_id,
            objective_id,
            version,
            label_status=label_status,
            dataset_use_status=dataset_use_status,
        )
        return {
            "schema_version": DATASET_SCHEMA_VERSION,
            "collection_id": collection_id,
            "objective_id": objective_id,
            "items": items,
            "warnings": [],
        }

    def export_collection_dataset(
        self,
        *,
        collection_id: str,
        label_status: str | None = None,
        dataset_use_status: str | None = None,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for objective in self.objective_repository.list_objectives(collection_id):
            version = objective.published_analysis_version
            if version is None:
                continue
            items.extend(
                self._dataset_items(
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

    def export_gold_draft(self, *, collection_id: str) -> dict[str, Any]:
        dataset = self.export_collection_dataset(
            collection_id=collection_id,
            label_status="gold",
        )
        return {
            "gold_id": _stable_id("gold", collection_id),
            "collection_id": collection_id,
            "version": DATASET_SCHEMA_VERSION,
            "target_layer": "core",
            "metric_profile": "objective_findings_v1",
            "items": dataset["items"],
        }

    def _dataset_items(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        label_status: str | None,
        dataset_use_status: str | None,
    ) -> list[dict[str, Any]]:
        objective = self.objective_repository.read_objective(
            collection_id, objective_id
        )
        assert objective is not None
        findings, _ = self.objective_repository.list_findings(
            collection_id,
            objective_id,
            analysis_version,
            offset=0,
            limit=200,
        )
        result: list[dict[str, Any]] = []
        for finding in findings:
            evidence, _ = self.objective_repository.list_evidence(
                collection_id,
                objective_id,
                analysis_version,
                finding_id=finding.finding_id,
                offset=0,
                limit=500,
            )
            feedback = self.list_feedback(
                collection_id=collection_id,
                objective_id=objective_id,
                analysis_version=analysis_version,
                finding_id=finding.finding_id,
            )
            curations = self.list_curations(
                collection_id=collection_id,
                objective_id=objective_id,
                analysis_version=analysis_version,
                finding_id=finding.finding_id,
            )
            sample_label, use_status = _dataset_status(feedback)
            if label_status is not None and sample_label != label_status:
                continue
            if dataset_use_status is not None and use_status != dataset_use_status:
                continue
            curation = curations[-1] if curations else None
            output = _curated_finding_record(finding, curation)
            evidence_records = [item.to_record() for item in evidence]
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
                    "finding_level": finding.finding_level,
                    "document_ids": list(
                        finding.derivation.contributing_document_ids
                    ),
                    "label_status": sample_label,
                    "dataset_use_status": use_status,
                    "system_prediction": finding.to_record(),
                    "expert_target": output if curation is not None else None,
                    "evidence": evidence_records,
                    "training_schema_version": TRAINING_SCHEMA_VERSION,
                    "training_prompt_version": TRAINING_PROMPT_VERSION,
                    "training_messages": _training_messages(
                        objective.question,
                        finding,
                        evidence,
                        output,
                    ),
                    "metadata": {
                        "schema_version": TRAINING_SCHEMA_VERSION,
                        "collection_id": collection_id,
                        "objective_id": objective_id,
                        "analysis_version": analysis_version,
                        "finding_id": finding.finding_id,
                        "label_status": sample_label,
                        "dataset_use_status": use_status,
                        "evidence_ids": [item.evidence_id for item in evidence],
                    },
                }
            )
        return result

    def _require_published_finding(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
    ) -> Finding:
        objective = self.objective_repository.read_objective(
            collection_id, objective_id
        )
        if objective is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        if objective.published_analysis_version != analysis_version:
            raise ValueError("feedback must reference the published analysis version")
        finding = self.objective_repository.read_finding(
            collection_id,
            objective_id,
            analysis_version,
            finding_id,
        )
        if finding is None:
            raise ValueError("finding is not present in the published analysis")
        return finding


def _dataset_status(
    feedback: tuple[FindingFeedback, ...],
) -> tuple[str, str]:
    if not feedback:
        return "candidate", "review_candidate"
    latest = feedback[-1]
    if latest.review_status == "correct":
        return "gold", "training_ready"
    if latest.review_status == "incorrect":
        return "rejected", "rejected"
    return "silver", "review_candidate"


def _curated_finding_record(
    finding: Finding,
    curation: FindingCuration | None,
) -> dict[str, Any]:
    if curation is None:
        return finding.to_record()
    record = finding.to_record()
    record.update(
        {
            "statement": curation.curated_statement,
            "variables": list(curation.curated_variables),
            "mediators": list(curation.curated_mediators),
            "outcomes": list(curation.curated_outcomes),
            "direction": curation.curated_direction,
            "scope_summary": curation.curated_scope_summary,
            "evidence_strength": (
                curation.curated_support_grade or finding.evidence_strength
            ),
        }
    )
    return record


def _training_messages(
    question: str,
    finding: Finding,
    evidence: tuple[ObjectiveEvidence, ...],
    output: dict[str, Any],
) -> list[dict[str, str]]:
    evidence_text = "\n".join(
        (
            f"[{item.evidence_id} | {item.document_id} | "
            f"{item.source_kind}:{item.source_ref} | pages "
            f"{','.join(str(page) for page in item.page_numbers) or 'unknown'} | "
            f"{item.evidence_role}] {item.source_excerpt}"
        )
        for item in evidence
    )
    user_content = (
        f"Research objective: {question}\n"
        f"Finding level: {finding.finding_level}\n"
        f"Evidence:\n{evidence_text}\n"
        "Return one structured Finding using only the evidence above."
    )
    return [
        {"role": "user", "content": user_content},
        {
            "role": "assistant",
            "content": json.dumps(output, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "DATASET_SCHEMA_VERSION",
    "FindingFeedbackService",
    "TRAINING_PROMPT_VERSION",
    "TRAINING_SCHEMA_VERSION",
]
