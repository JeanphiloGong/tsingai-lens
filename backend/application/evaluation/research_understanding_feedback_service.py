from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Mapping

from application.core.research_understanding_service import ResearchUnderstandingService
from domain.evaluation import (
    ResearchUnderstandingCuration,
    ResearchUnderstandingFeedback,
)
from domain.ports import (
    ResearchUnderstandingRepository,
    ResearchUnderstandingReviewRepository,
)


DATASET_SCHEMA_VERSION = "research_understanding_dataset.v1"
DATASET_TASK_TYPE = "research_understanding_finding"
TRAINING_SCHEMA_VERSION = "research_understanding_finding_training.v1"
TRAINING_PROMPT_VERSION = "research_understanding_finding_training_prompt.v1"
DATASET_LABEL_STATUSES = ("candidate", "silver", "gold", "rejected")
DATASET_USE_STATUSES = ("training_ready", "review_candidate", "rejected")
_ACCEPTANCE_REVIEW_CHECKS = {
    "accept_as_paper_level": "Confirm the finding is only paper-level unless cross-paper evidence is present.",
    "needs_cross_paper_confirmation": "Confirm the finding is only paper-level unless cross-paper evidence is present.",
    "single_paper_evidence": "Confirm the finding is only paper-level unless cross-paper evidence is present.",
    "review_table_rows": "Verify the selected table rows, variable columns, and outcome values.",
    "table_row_needs_expert_review": "Verify the selected table rows, variable columns, and outcome values.",
    "verify_table_rows": "Verify parsed table-row alignment against the source table.",
    "table_row_alignment_uncertain": "Verify parsed table-row alignment against the source table.",
    "review_table_variables": "Check whether multiple table variables changed before assigning a single-variable effect.",
    "non_single_variable_table_comparison": "Check whether multiple table variables changed before assigning a single-variable effect.",
    "check_mechanism_requirement": "Decide whether mechanism evidence is required for this reviewed finding.",
    "missing_mechanism_evidence": "Decide whether mechanism evidence is required for this reviewed finding.",
    "resolve_conflict": "Resolve conflicting evidence direction before downstream use.",
    "conflicting_direction": "Resolve conflicting evidence direction before downstream use.",
    "repair_evidence_binding": "Repair or reject the evidence binding before accepting.",
    "missing_direct_result_evidence": "Repair or reject the evidence binding before accepting.",
    "validate_model_evidence": "Validate the model-prediction or validation evidence before accepting.",
    "model_validation_finding": "Validate the model-prediction or validation evidence before accepting.",
}
_ACCEPT_BLOCKING_REVIEW_CODES = frozenset(
    {
        "table_row_alignment_uncertain",
        "verify_table_rows",
    }
)
_REJECTING_ISSUE_TYPES = frozenset(
    {
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
    }
)
_ISSUE_ERROR_CATEGORIES = {
    "none": "none",
    "unreviewed": "unreviewed",
    "wrong_variable": "variable_error",
    "wrong_outcome": "outcome_error",
    "wrong_direction": "direction_error",
    "wrong_context": "context_error",
    "wrong_relation": "relation_error",
    "evidence_not_grounded": "evidence_error",
    "missing_evidence": "evidence_error",
    "insufficient_evidence": "evidence_error",
    "overclaim": "claim_scope_error",
    "unclear_statement": "statement_error",
    "other": "other_error",
}


class ResearchUnderstandingFeedbackService:
    """Persist expert review feedback for research-understanding findings."""

    def __init__(
        self,
        review_repository: ResearchUnderstandingReviewRepository,
        research_understanding_repository: ResearchUnderstandingRepository,
        research_understanding_service: ResearchUnderstandingService,
    ) -> None:
        self.review_repository = review_repository
        self.research_understanding_repository = research_understanding_repository
        self.research_understanding_service = research_understanding_service

    def record_feedback(
        self,
        *,
        collection_id: str,
        objective_id: str,
        finding_id: str,
        review_status: str,
        issue_type: str,
        claim_id: str | None = None,
        note: str | None = None,
        reviewer: str | None = None,
    ) -> ResearchUnderstandingFeedback:
        finding = self._current_finding(
            collection_id=collection_id,
            objective_id=objective_id,
            finding_id=finding_id,
            claim_id=claim_id,
        )
        created_at = _now_iso()
        feedback = ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": _feedback_id(
                    collection_id,
                    objective_id,
                    finding_id,
                    review_status,
                    issue_type,
                    note,
                    reviewer,
                    created_at,
                ),
                "collection_id": collection_id,
                "objective_id": objective_id,
                "finding_id": finding_id,
                "claim_id": claim_id,
                "finding_fingerprint": _finding_fingerprint(finding),
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
        finding_id: str | None = None,
        claim_id: str | None = None,
    ) -> tuple[ResearchUnderstandingFeedback, ...]:
        return self.review_repository.list_feedback(
            collection_id=collection_id,
            objective_id=objective_id,
            finding_id=finding_id,
            claim_id=claim_id,
        )

    def record_curation(
        self,
        *,
        collection_id: str,
        objective_id: str,
        finding_id: str,
        curated_claim_type: str,
        curated_status: str,
        curated_statement: str,
        curated_evidence_ref_ids: list[str],
        curated_context_ids: list[str],
        claim_id: str | None = None,
        curated_support_grade: str | None = None,
        curated_review_status: str | None = None,
        curated_variables: list[str] | None = None,
        curated_mediators: list[str] | None = None,
        curated_outcomes: list[str] | None = None,
        curated_direction: str | None = None,
        curated_scope_summary: str | None = None,
        note: str | None = None,
        reviewer: str | None = None,
    ) -> ResearchUnderstandingCuration:
        finding = self._current_finding(
            collection_id=collection_id,
            objective_id=objective_id,
            finding_id=finding_id,
            claim_id=claim_id,
        )
        updated_at = _now_iso()
        curation = ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": _curation_id(
                    collection_id,
                    objective_id,
                    finding_id,
                ),
                "collection_id": collection_id,
                "objective_id": objective_id,
                "finding_id": finding_id,
                "claim_id": claim_id,
                "finding_fingerprint": _finding_fingerprint(finding),
                "curated_claim_type": curated_claim_type,
                "curated_status": curated_status,
                "curated_statement": curated_statement,
                "curated_support_grade": curated_support_grade,
                "curated_review_status": curated_review_status,
                "curated_variables": curated_variables or [],
                "curated_mediators": curated_mediators or [],
                "curated_outcomes": curated_outcomes or [],
                "curated_direction": curated_direction,
                "curated_scope_summary": curated_scope_summary,
                "curated_evidence_ref_ids": curated_evidence_ref_ids,
                "curated_context_ids": curated_context_ids,
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
        finding_id: str | None = None,
        claim_id: str | None = None,
    ) -> tuple[ResearchUnderstandingCuration, ...]:
        return self.review_repository.list_curations(
            collection_id=collection_id,
            objective_id=objective_id,
            finding_id=finding_id,
            claim_id=claim_id,
        )

    def export_gold_draft(
        self,
        *,
        collection_id: str,
        objective_id: str,
    ) -> dict[str, object]:
        raw_curations = self.list_curations(
            collection_id=collection_id,
            objective_id=objective_id,
        )
        current_fingerprints = self._current_finding_fingerprints(
            collection_id=collection_id,
            objective_id=objective_id,
        )
        curations = tuple(
            curation
            for curation in raw_curations
            if curation.finding_fingerprint
            and curation.finding_fingerprint
            == current_fingerprints.get(curation.finding_id)
        )
        items = [
            {
                "gold_item_id": "gold_" + curation.curation_id.removeprefix("ruc_"),
                "document_id": "",
                "family": "research_understanding_findings",
                "item_key": ":".join(
                    [curation.objective_id, curation.finding_id]
                ),
                "payload": {
                    "finding_id": curation.finding_id,
                    "claim_id": curation.claim_id,
                    "finding_fingerprint": curation.finding_fingerprint,
                    "claim_type": curation.curated_claim_type,
                    "status": curation.curated_status,
                    "statement": curation.curated_statement,
                    "support_grade": curation.curated_support_grade,
                    "review_status": curation.curated_review_status,
                    "variables": list(curation.curated_variables),
                    "mediators": list(curation.curated_mediators),
                    "outcomes": list(curation.curated_outcomes),
                    "direction": curation.curated_direction,
                    "scope_summary": curation.curated_scope_summary,
                    "evidence_ref_ids": list(curation.curated_evidence_ref_ids),
                    "context_ids": list(curation.curated_context_ids),
                },
                "evidence_refs": [
                    {"evidence_ref_id": evidence_ref_id}
                    for evidence_ref_id in curation.curated_evidence_ref_ids
                ],
                "metadata": {
                    "curation_id": curation.curation_id,
                    "reviewer": curation.reviewer,
                    "note": curation.note,
                    "updated_at": curation.updated_at,
                    "finding_fingerprint": curation.finding_fingerprint,
                },
            }
            for curation in curations
        ]
        return {
            "collection_id": collection_id,
            "objective_id": objective_id,
            "gold_id": _gold_draft_id(collection_id, objective_id),
            "target_layer": "core",
            "metric_profile": "research_understanding_v1",
            "item_count": len(items),
            "items": items,
        }

    def export_dataset(
        self,
        *,
        collection_id: str,
        objective_id: str,
        label_status: str | None = None,
        dataset_use_status: str | None = None,
        task_type: str | None = None,
    ) -> dict[str, object]:
        if label_status and label_status not in DATASET_LABEL_STATUSES:
            raise ValueError(f"unsupported label_status: {label_status}")
        if dataset_use_status and dataset_use_status not in DATASET_USE_STATUSES:
            raise ValueError(f"unsupported dataset_use_status: {dataset_use_status}")

        understanding = (
            self.research_understanding_repository.read_objective_understanding(
                collection_id,
                objective_id,
            )
        )
        if understanding is None:
            return self._dataset_payload(
                collection_id=collection_id,
                objective_id=objective_id,
                label_status_filter=label_status,
                dataset_use_status_filter=dataset_use_status,
                task_type_filter=task_type,
                items=[],
                warnings=["research understanding artifact is not available"],
            )

        items: list[dict[str, object]] = []
        for sample in self._dataset_items_for_understanding(
            collection_id=collection_id,
            objective_id=objective_id,
            understanding=understanding,
        ):
            if label_status and sample["label_status"] != label_status:
                continue
            if (
                dataset_use_status
                and sample["dataset_use_status"] != dataset_use_status
            ):
                continue
            if task_type and sample["task_type"] != task_type:
                continue
            items.append(sample)

        return self._dataset_payload(
            collection_id=collection_id,
            objective_id=objective_id,
            label_status_filter=label_status,
            dataset_use_status_filter=dataset_use_status,
            task_type_filter=task_type,
            items=items,
            warnings=[],
        )

    def export_collection_dataset(
        self,
        *,
        collection_id: str,
        label_status: str | None = None,
        dataset_use_status: str | None = None,
        task_type: str | None = None,
    ) -> dict[str, object]:
        if label_status and label_status not in DATASET_LABEL_STATUSES:
            raise ValueError(f"unsupported label_status: {label_status}")
        if dataset_use_status and dataset_use_status not in DATASET_USE_STATUSES:
            raise ValueError(f"unsupported dataset_use_status: {dataset_use_status}")

        understandings = (
            self.research_understanding_repository.list_objective_understandings(
                collection_id
            )
        )
        items: list[dict[str, object]] = []
        warnings: list[str] = []
        for understanding in understandings:
            objective_id = understanding.scope.objective_id
            if not objective_id:
                continue
            scope_items = self._dataset_items_for_understanding(
                collection_id=collection_id,
                objective_id=objective_id,
                understanding=understanding,
            )
            for sample in scope_items:
                if label_status and sample["label_status"] != label_status:
                    continue
                if (
                    dataset_use_status
                    and sample["dataset_use_status"] != dataset_use_status
                ):
                    continue
                if task_type and sample["task_type"] != task_type:
                    continue
                items.append(sample)
        if not understandings:
            warnings.append("research understanding artifacts are not available")

        return self._dataset_payload(
            collection_id=collection_id,
            objective_id=None,
            label_status_filter=label_status,
            dataset_use_status_filter=dataset_use_status,
            task_type_filter=task_type,
            items=items,
            warnings=warnings,
        )

    def _dataset_payload(
        self,
        *,
        collection_id: str,
        objective_id: str | None,
        label_status_filter: str | None,
        dataset_use_status_filter: str | None,
        task_type_filter: str | None,
        items: list[dict[str, object]],
        warnings: list[str],
    ) -> dict[str, object]:
        label_counts = {status: 0 for status in DATASET_LABEL_STATUSES}
        for item in items:
            status = _text(item.get("label_status")) or "candidate"
            if status in label_counts:
                label_counts[status] += 1
        return {
            "schema_version": DATASET_SCHEMA_VERSION,
            "dataset_id": _dataset_id(collection_id, objective_id),
            "collection_id": collection_id,
            "objective_id": objective_id,
            "task_type": DATASET_TASK_TYPE,
            "metric_profile": "research_understanding_v1",
            "label_status_filter": label_status_filter,
            "dataset_use_status_filter": dataset_use_status_filter,
            "task_type_filter": task_type_filter,
            "item_count": len(items),
            "label_counts": label_counts,
            "quality_summary": _dataset_quality_summary(items),
            "items": items,
            "warnings": warnings,
        }

    def _finding_records(
        self,
        understanding: Mapping[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        presentation = _mapping(understanding.get("presentation"))
        findings = _mapping_list(presentation.get("findings"))
        findings_by_id = _by_id(findings, "finding_id")
        visible_findings = [
            *_mapping_list(presentation.get("primary_findings")),
            *_mapping_list(presentation.get("review_queue_findings")),
        ]
        if visible_findings:
            records: list[dict[str, Any]] = []
            seen: set[str] = set()
            for visible_finding in visible_findings:
                finding_id = _text(visible_finding.get("finding_id"))
                full_finding = (
                    findings_by_id.get(finding_id, {}) if finding_id else {}
                )
                if finding_id and finding_id in seen:
                    continue
                if finding_id:
                    seen.add(finding_id)
                records.append({**visible_finding, **full_finding})
            return tuple(records)
        if findings:
            return findings
        records: list[dict[str, Any]] = []
        for claim in _mapping_list(understanding.get("claims")):
            claim_id = _text(claim.get("claim_id")) or _sample_id("claim", claim)
            records.append(
                {
                    "finding_id": f"finding_{claim_id}",
                    "claim_id": claim_id,
                    "title": _text(claim.get("statement")) or claim_id,
                    "statement": _text(claim.get("statement")) or "",
                    "variables": [],
                    "mediators": [],
                    "outcomes": [],
                    "direction": "",
                    "scope_summary": "",
                    "support_grade": _text(claim.get("strength")) or "weak",
                    "review_status": "pending_review",
                    "confidence": claim.get("confidence"),
                    "paper_count": 0,
                    "evidence_count": len(_strings(claim.get("evidence_ref_ids"))),
                    "evidence_ref_ids": list(_strings(claim.get("evidence_ref_ids"))),
                    "context_ids": list(_strings(claim.get("context_ids"))),
                    "relation_ids": [],
                    "warnings": list(_strings(claim.get("warnings"))),
                }
            )
        return tuple(records)

    def _dataset_items_for_understanding(
        self,
        *,
        collection_id: str,
        objective_id: str,
        understanding: Any,
    ) -> list[dict[str, object]]:
        understanding_record = (
            self.research_understanding_service.with_presentation(
                understanding,
                recover_source_findings=False,
            )
            or understanding.to_record()
        )
        feedback = self.list_feedback(
            collection_id=collection_id,
            objective_id=objective_id,
        )
        curations = self.list_curations(
            collection_id=collection_id,
            objective_id=objective_id,
        )
        feedback_index = _feedback_index(feedback)
        curation_index = _curation_index(curations)
        presentation = _mapping(understanding_record.get("presentation"))
        evidence_items = _by_id(
            _mapping_list(presentation.get("evidence_items")),
            "evidence_ref_id",
        )
        context_summaries = _by_id(
            _mapping_list(presentation.get("context_summaries")),
            "context_id",
        )
        evidence_refs = {
            ref.evidence_ref_id: ref.to_record()
            for ref in understanding.evidence_refs
        }
        contexts = {
            context.context_id: context.to_record()
            for context in understanding.contexts
        }
        relations = {
            relation.relation_id: relation.to_record()
            for relation in understanding.relations
        }
        model_traces = tuple(dict(trace) for trace in understanding.model_traces)
        finding_buckets = _finding_bucket_index(presentation)

        return [
            self._dataset_sample(
                collection_id=collection_id,
                objective_id=objective_id,
                research_objective=_text(understanding.scope.title),
                finding=finding,
                evidence_refs=evidence_refs,
                evidence_items=evidence_items,
                contexts=contexts,
                context_summaries=context_summaries,
                relations=relations,
                model_traces=model_traces,
                feedback_index=feedback_index,
                curation_index=curation_index,
                presentation_bucket=_presentation_bucket_for_finding(
                    finding,
                    finding_buckets,
                ),
            )
            for finding in self._finding_records(understanding_record)
        ]

    def _current_finding(
        self,
        *,
        collection_id: str,
        objective_id: str,
        finding_id: str,
        claim_id: str | None,
    ) -> Mapping[str, Any]:
        findings = self._current_findings(
            collection_id=collection_id,
            objective_id=objective_id,
        )
        for finding in findings:
            if _text(finding.get("finding_id")) != finding_id:
                continue
            current_claim_id = _text(finding.get("claim_id"))
            if claim_id and current_claim_id and claim_id != current_claim_id:
                raise ValueError("claim_id does not match the current finding")
            return finding
        raise ValueError("finding_id is not present in the current research understanding")

    def _current_findings(
        self,
        *,
        collection_id: str,
        objective_id: str,
    ) -> tuple[Mapping[str, Any], ...]:
        understanding = (
            self.research_understanding_repository.read_objective_understanding(
                collection_id,
                objective_id,
            )
        )
        if understanding is None:
            return ()
        understanding_record = (
            self.research_understanding_service.with_presentation(
                understanding,
                recover_source_findings=False,
            )
            or understanding.to_record()
        )
        return self._finding_records(understanding_record)

    def _current_finding_fingerprints(
        self,
        *,
        collection_id: str,
        objective_id: str,
    ) -> dict[str, str]:
        return {
            finding_id: _finding_fingerprint(finding)
            for finding in self._current_findings(
                collection_id=collection_id,
                objective_id=objective_id,
            )
            if (finding_id := _text(finding.get("finding_id")))
        }

    def _dataset_sample(
        self,
        *,
        collection_id: str,
        objective_id: str,
        research_objective: str,
        finding: Mapping[str, Any],
        evidence_refs: Mapping[str, Mapping[str, Any]],
        evidence_items: Mapping[str, Mapping[str, Any]],
        contexts: Mapping[str, Mapping[str, Any]],
        context_summaries: Mapping[str, Mapping[str, Any]],
        relations: Mapping[str, Mapping[str, Any]],
        model_traces: tuple[dict[str, Any], ...],
        feedback_index: Mapping[tuple[str, str], tuple[ResearchUnderstandingFeedback, ...]],
        curation_index: Mapping[tuple[str, str], tuple[ResearchUnderstandingCuration, ...]],
        presentation_bucket: str,
    ) -> dict[str, object]:
        finding_id = _text(finding.get("finding_id")) or _sample_id("finding", finding)
        claim_id = _text(finding.get("claim_id"))
        finding_fingerprint = _finding_fingerprint(finding)
        raw_feedback = _feedback_for(feedback_index, finding_id, claim_id)
        raw_curations = _curations_for(curation_index, finding_id, claim_id)
        feedback = _aligned_feedback_for_current_finding(
            raw_feedback,
            finding_fingerprint=finding_fingerprint,
        )
        curations = _aligned_curations_for_current_finding(
            raw_curations,
            finding_fingerprint=finding_fingerprint,
        )
        curation = curations[0] if curations else None
        label_status = _label_status(feedback, curation)
        dataset_use_status = _dataset_use_status(
            label_status=label_status,
            presentation_bucket=presentation_bucket,
        )
        system_prediction = _system_prediction(finding)
        system_prediction["presentation_bucket"] = presentation_bucket
        finding_level = _training_finding_level(finding)
        base_evidence_ref_ids = _strings(finding.get("evidence_ref_ids"))
        evidence_ref_ids_list: list[str] = []
        bundle = _mapping(finding.get("evidence_bundle"))
        for role in (
            "direct_result",
            "mechanism",
            "condition_context",
            "conflict",
            "background",
            "noise",
            "uncategorized",
        ):
            for ref_id in _strings(bundle.get(role)):
                if ref_id in evidence_refs and ref_id not in evidence_ref_ids_list:
                    evidence_ref_ids_list.append(ref_id)
        evidence_ref_ids_list.extend(
            ref_id for ref_id in base_evidence_ref_ids if ref_id not in evidence_ref_ids_list
        )
        expert_target = (
            _expert_target_from_curation(curation)
            if curation is not None
            else _expert_target_from_feedback(system_prediction, feedback)
        )
        if curation is not None:
            curated_ref_ids = [
                ref_id
                for ref_id in curation.curated_evidence_ref_ids
                if ref_id in evidence_refs
            ]
            curation_first_ref_ids = list(
                _strings(curated_ref_ids + evidence_ref_ids_list)
            )
            curation_matches_current = _curation_matches_system_prediction(
                {
                    "evidence_refs": [
                        _evidence_record(ref_id, evidence_refs, evidence_items)
                        for ref_id in curation_first_ref_ids
                    ]
                },
                system_prediction=system_prediction,
                target=_mapping(expert_target),
            )
            if curation_matches_current:
                evidence_ref_ids_list = list(
                    _strings(evidence_ref_ids_list + curated_ref_ids)
                )
            else:
                evidence_ref_ids_list = curation_first_ref_ids
        evidence_ref_ids = tuple(evidence_ref_ids_list)
        evidence_records = [
            _evidence_record(evidence_ref_id, evidence_refs, evidence_items)
            for evidence_ref_id in evidence_ref_ids
        ]
        training_evidence_ref_ids = _training_evidence_ref_ids(
            finding,
            evidence_ref_ids=evidence_ref_ids,
            expert_target=_mapping(expert_target),
        )
        training_evidence_records = [
            record
            for record in evidence_records
            if record["evidence_ref_id"] in training_evidence_ref_ids
        ] or evidence_records
        context_ids = _strings(finding.get("context_ids"))
        context_records = [
            _context_record(context_id, contexts, context_summaries)
            for context_id in context_ids
        ]
        training_messages = (
            _training_messages(
                research_objective=research_objective,
                finding_level=finding_level,
                system_prediction=system_prediction,
                expert_target=_mapping(expert_target),
                evidence_records=training_evidence_records,
                context_records=context_records,
            )
            if dataset_use_status == "training_ready"
            else []
        )
        training_message_diagnostic = _training_message_diagnostic(
            _mapping(expert_target),
            system_prediction,
            training_messages,
            evidence_records=training_evidence_records,
        )
        matched_trace = _matched_trace_for_finding(
            finding,
            evidence_ref_ids=evidence_ref_ids,
            evidence_refs=evidence_refs,
            relations=relations,
            model_traces=model_traces,
        )
        trace_status = _trace_status(
            matched_trace,
            evidence_records=evidence_records,
        )
        input_blocks = _trace_input_blocks(
            matched_trace,
            evidence_records=evidence_records,
        )
        review_action = _review_action_for_sample(
            system_prediction=system_prediction,
            evidence_records=evidence_records,
        )
        protocol_readiness = _protocol_readiness_for_sample(
            dataset_use_status=dataset_use_status,
            system_prediction=system_prediction,
            expert_target=_mapping(expert_target),
            training_evidence_records=training_evidence_records,
            training_messages=training_messages,
        )
        protocol_source_fingerprint = _protocol_source_fingerprint(
            finding_fingerprint=finding_fingerprint,
            dataset_use_status=dataset_use_status,
            expert_target=_mapping(expert_target),
            training_evidence_records=training_evidence_records,
            protocol_readiness=protocol_readiness,
        )
        acceptance_gate = _acceptance_gate_for_sample(
            dataset_use_status=dataset_use_status,
            system_prediction=system_prediction,
            review_action=review_action,
            protocol_readiness=protocol_readiness,
        )
        return {
            "sample_id": _sample_id(
                "rus",
                collection_id,
                objective_id,
                finding_id,
                label_status,
            ),
            "task_type": DATASET_TASK_TYPE,
            "training_schema_version": TRAINING_SCHEMA_VERSION,
            "training_prompt_version": TRAINING_PROMPT_VERSION,
            "research_objective": research_objective,
            "finding_level": finding_level,
            "document_ids": list(
                _strings(
                    [record.get("document_id") for record in training_evidence_records]
                )
            ),
            "collection_id": collection_id,
            "objective_id": objective_id,
            "finding_id": finding_id,
            "claim_id": claim_id,
            "finding_fingerprint": finding_fingerprint,
            "protocol_source_fingerprint": protocol_source_fingerprint,
            "label_status": label_status,
            "dataset_use_status": dataset_use_status,
            "presentation_bucket": presentation_bucket,
            "trace_status": trace_status,
            "input_blocks": input_blocks,
            "prompt_version": (
                _text(matched_trace.get("prompt_version")) if matched_trace else None
            ),
            "model_output": _trace_model_output(matched_trace),
            "system_prediction": system_prediction,
            "review_action": review_action,
            "expert_target": expert_target,
            "evidence_refs": evidence_records,
            "training_evidence_refs": training_evidence_records,
            "training_messages": training_messages,
            "protocol_readiness": protocol_readiness,
            "acceptance_gate": acceptance_gate,
            "review_decision_hint": _review_decision_hint_for_sample(
                acceptance_gate=acceptance_gate,
                protocol_readiness=protocol_readiness,
                review_action=review_action,
            ),
            "context_refs": context_records,
            "feedback_refs": [item.to_record() for item in feedback],
            "metadata": {
                "curation_id": curation.curation_id if curation else None,
                "feedback_count": len(feedback),
                "ignored_feedback_refs": [
                    item.to_record()
                    for item in raw_feedback
                    if item not in feedback
                ],
                "ignored_curation_refs": [
                    item.to_record()
                    for item in raw_curations
                    if item not in curations
                ],
                "trace_id": _text(matched_trace.get("trace_id")) if matched_trace else None,
                "trace_note": _trace_note(matched_trace, trace_status),
                "presentation_bucket": presentation_bucket,
                "training_message_diagnostic": training_message_diagnostic,
            },
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _feedback_id(*parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return "ruf_" + sha1(payload.encode("utf-8")).hexdigest()[:16]


def _curation_id(*parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return "ruc_" + sha1(payload.encode("utf-8")).hexdigest()[:16]


def _gold_draft_id(collection_id: str, objective_id: str) -> str:
    payload = "_".join(
        part.strip().replace(" ", "_")
        for part in (collection_id, objective_id)
        if part.strip()
    )
    return f"gold_{payload}_research_understanding"


def _dataset_id(collection_id: str, objective_id: str | None) -> str:
    payload = "_".join(
        part.strip().replace(" ", "_")
        for part in (collection_id, objective_id or "all_objectives")
        if part.strip()
    )
    return f"dataset_{payload}_research_understanding"


def _feedback_index(
    records: tuple[ResearchUnderstandingFeedback, ...],
) -> dict[tuple[str, str], tuple[ResearchUnderstandingFeedback, ...]]:
    indexed: dict[tuple[str, str], list[ResearchUnderstandingFeedback]] = {}
    for record in records:
        for key in _record_keys(record.finding_id, record.claim_id):
            indexed.setdefault(key, []).append(record)
    return {key: tuple(value) for key, value in indexed.items()}


def _curation_index(
    records: tuple[ResearchUnderstandingCuration, ...],
) -> dict[tuple[str, str], tuple[ResearchUnderstandingCuration, ...]]:
    indexed: dict[tuple[str, str], list[ResearchUnderstandingCuration]] = {}
    for record in records:
        for key in _record_keys(record.finding_id, record.claim_id):
            indexed.setdefault(key, []).append(record)
    return {key: tuple(value) for key, value in indexed.items()}


def _record_keys(
    finding_id: str | None,
    claim_id: str | None,
) -> tuple[tuple[str, str], ...]:
    keys: list[tuple[str, str]] = []
    if finding_id:
        keys.append(("finding", finding_id))
    if claim_id:
        keys.append(("claim", claim_id))
    return tuple(keys)


def _feedback_for(
    index: Mapping[tuple[str, str], tuple[ResearchUnderstandingFeedback, ...]],
    finding_id: str,
    claim_id: str | None,
) -> tuple[ResearchUnderstandingFeedback, ...]:
    records: list[ResearchUnderstandingFeedback] = []
    seen: set[str] = set()
    for key in _record_keys(finding_id, claim_id):
        for record in index.get(key, ()):
            if record.feedback_id in seen:
                continue
            seen.add(record.feedback_id)
            records.append(record)
    return tuple(records)


def _curations_for(
    index: Mapping[tuple[str, str], tuple[ResearchUnderstandingCuration, ...]],
    finding_id: str,
    claim_id: str | None,
) -> tuple[ResearchUnderstandingCuration, ...]:
    records: list[ResearchUnderstandingCuration] = []
    seen: set[str] = set()
    for key in _record_keys(finding_id, claim_id):
        for record in index.get(key, ()):
            if record.curation_id in seen:
                continue
            seen.add(record.curation_id)
            records.append(record)
    return tuple(records)


def _label_status(
    feedback: tuple[ResearchUnderstandingFeedback, ...],
    curation: ResearchUnderstandingCuration | None,
) -> str:
    if curation is not None:
        return "gold" if _is_human_reviewer(curation.reviewer) else "silver"
    if any(
        item.review_status == "incorrect" or item.issue_type in _REJECTING_ISSUE_TYPES
        for item in feedback
    ):
        return "rejected"
    if any(
        item.review_status == "correct" and _is_human_reviewer(item.reviewer)
        for item in feedback
    ):
        return "gold"
    if any(item.review_status in {"correct", "partial"} for item in feedback):
        return "silver"
    return "candidate"


def _dataset_use_status(*, label_status: str, presentation_bucket: str) -> str:
    if label_status == "rejected":
        return "rejected"
    if label_status == "gold":
        return "training_ready"
    return "review_candidate"


def _training_evidence_ref_ids(
    finding: Mapping[str, Any],
    *,
    evidence_ref_ids: tuple[str, ...],
    expert_target: Mapping[str, Any] | None = None,
) -> set[str]:
    expert_ref_ids = {
        ref_id
        for ref_id in _strings(_mapping(expert_target).get("evidence_ref_ids"))
        if ref_id in evidence_ref_ids
    }
    if expert_ref_ids:
        return expert_ref_ids
    bundle = _mapping(finding.get("evidence_bundle"))
    training_ids = {
        ref_id
        for role in ("direct_result", "mechanism", "condition_context")
        for ref_id in _strings(bundle.get(role))
        if ref_id in evidence_ref_ids
    }
    if training_ids:
        return training_ids
    return set(evidence_ref_ids)


def _finding_bucket_index(presentation: Mapping[str, Any]) -> dict[str, str]:
    buckets: dict[str, str] = {}
    for bucket_name, field_name in (
        ("primary", "primary_findings"),
        ("review_queue", "review_queue_findings"),
    ):
        for finding in _mapping_list(presentation.get(field_name)):
            finding_id = _text(finding.get("finding_id"))
            if finding_id and finding_id not in buckets:
                buckets[finding_id] = bucket_name
    return buckets


def _presentation_bucket_for_finding(
    finding: Mapping[str, Any],
    buckets: Mapping[str, str],
) -> str:
    finding_id = _text(finding.get("finding_id"))
    if finding_id:
        return buckets.get(finding_id, "unbucketed")
    return "unbucketed"


def _aligned_feedback_for_current_finding(
    records: tuple[ResearchUnderstandingFeedback, ...],
    *,
    finding_fingerprint: str,
) -> tuple[ResearchUnderstandingFeedback, ...]:
    return tuple(
        record
        for record in records
        if record.finding_fingerprint == finding_fingerprint
    )


def _aligned_curations_for_current_finding(
    records: tuple[ResearchUnderstandingCuration, ...],
    *,
    finding_fingerprint: str,
) -> tuple[ResearchUnderstandingCuration, ...]:
    return tuple(
        record
        for record in records
        if record.finding_fingerprint == finding_fingerprint
    )


def _finding_fingerprint(finding: Mapping[str, Any]) -> str:
    semantic_fields = {
        key: finding.get(key)
        for key in (
            "finding_id",
            "claim_id",
            "title",
            "statement",
            "variables",
            "mediators",
            "outcomes",
            "direction",
            "scope_summary",
            "support_grade",
            "review_status",
            "paper_count",
            "evidence_ref_ids",
            "context_ids",
            "relation_ids",
            "evidence_bundle",
            "comparison_summary",
            "generalization_status",
            "generalization_note",
            "review_reasons",
            "warnings",
        )
    }
    payload = json.dumps(
        _canonical_fingerprint_value(semantic_fields),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "finding.v1:" + sha1(payload.encode("utf-8")).hexdigest()


def _protocol_source_fingerprint(
    *,
    finding_fingerprint: str,
    dataset_use_status: str,
    expert_target: Mapping[str, Any],
    training_evidence_records: list[dict[str, Any]],
    protocol_readiness: Mapping[str, Any],
) -> str:
    payload = json.dumps(
        _canonical_fingerprint_value(
            {
                "finding_fingerprint": finding_fingerprint,
                "dataset_use_status": dataset_use_status,
                "expert_target": expert_target,
                "training_evidence_refs": training_evidence_records,
                "protocol_readiness": protocol_readiness,
            }
        ),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "protocol-source.v1:" + sha1(payload.encode("utf-8")).hexdigest()


def _canonical_fingerprint_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_fingerprint_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list | tuple | set | frozenset):
        items = [_canonical_fingerprint_value(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    return value


_LABEL_TERM_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "claim",
        "finding",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
    }
)


def _dataset_quality_summary(items: list[dict[str, object]]) -> dict[str, object]:
    by_label_status = {status: 0 for status in DATASET_LABEL_STATUSES}
    by_review_status: dict[str, int] = {}
    by_issue_type: dict[str, int] = {}
    by_error_category: dict[str, int] = {}
    by_support_grade: dict[str, int] = {}
    by_trace_status: dict[str, int] = {}
    by_evidence_role: dict[str, int] = {}
    by_evidence_traceability_status: dict[str, int] = {}
    by_quality_decision: dict[str, int] = {}
    by_presentation_bucket: dict[str, int] = {}
    by_bucket_quality_decision: dict[str, dict[str, int]] = {}
    by_review_reason: dict[str, int] = {}
    by_system_warning: dict[str, int] = {}
    by_review_candidate_reason: dict[str, int] = {}
    by_review_candidate_warning: dict[str, int] = {}
    optimization_breakdown: dict[str, dict[str, dict[str, dict[str, int]]]] = {
        "by_variable": {},
        "by_outcome": {},
        "by_direction": {},
        "by_evidence_role": {},
    }
    warning_counts = {
        "missing_evidence": 0,
        "missing_source_text": 0,
        "missing_context": 0,
        "unavailable_trace": 0,
        "failed_trace": 0,
        "rejected_feedback": 0,
        "resolved_feedback": 0,
    }
    by_dataset_use_status = {status: 0 for status in DATASET_USE_STATUSES}
    usable_sample_count = 0
    training_ready_sample_count = 0
    training_message_sample_count = 0
    protocol_ready_sample_count = 0
    review_candidate_sample_count = 0
    needs_review_count = 0
    rejected_count = 0
    labeled_sample_count = 0
    accepted_system_sample_count = 0
    accepted_after_curation_match_count = 0
    curated_correction_count = 0
    system_error_count = 0
    resolved_feedback_count = 0
    next_review_finding_id = ""

    for item in items:
        label_status = _text(item.get("label_status")) or "candidate"
        dataset_use_status = (
            _text(item.get("dataset_use_status"))
            or _dataset_use_status(
                label_status=label_status,
                presentation_bucket=_text(item.get("presentation_bucket")) or "unbucketed",
            )
        )
        presentation_bucket = _text(item.get("presentation_bucket")) or "unbucketed"
        _increment_count(by_label_status, label_status)
        _increment_count(by_dataset_use_status, dataset_use_status)
        _increment_count(by_presentation_bucket, presentation_bucket)
        if label_status in {"gold", "silver"}:
            usable_sample_count += 1
        if dataset_use_status == "training_ready":
            training_ready_sample_count += 1
            if _has_training_messages_for_expert_target(item):
                training_message_sample_count += 1
                if _has_protocol_design_inputs_for_expert_target(item):
                    protocol_ready_sample_count += 1
        elif dataset_use_status == "review_candidate":
            review_candidate_sample_count += 1
            if not next_review_finding_id:
                next_review_finding_id = _text(item.get("finding_id"))
        if label_status != "candidate":
            labeled_sample_count += 1
        if label_status == "rejected":
            rejected_count += 1

        target = _mapping(item.get("expert_target"))
        feedback_records = _mapping_list(item.get("feedback_refs"))
        system_prediction = _mapping(item.get("system_prediction"))
        for reason in _strings(system_prediction.get("review_reasons")):
            _increment_count(by_review_reason, reason)
            if dataset_use_status == "review_candidate":
                _increment_count(by_review_candidate_reason, reason)
        for warning in _strings(system_prediction.get("warnings")):
            _increment_count(by_system_warning, warning)
            if dataset_use_status == "review_candidate":
                _increment_count(by_review_candidate_warning, warning)

        review_status = _text(target.get("review_status"))
        if not review_status:
            for feedback in feedback_records:
                review_status = _text(feedback.get("review_status"))
                if review_status:
                    break
        review_status = review_status or _text(system_prediction.get("review_status")) or "unreviewed"
        _increment_count(by_review_status, review_status)
        if label_status in {"candidate", "silver"} or review_status in {
            "needs_review",
            "pending_review",
            "partial",
            "unclear",
        }:
            needs_review_count += 1

        issue_type = ""
        has_rejecting_feedback = False
        for feedback in feedback_records:
            current_issue_type = _text(feedback.get("issue_type"))
            current_review_status = _text(feedback.get("review_status"))
            if (
                current_review_status == "incorrect"
                or current_issue_type in _REJECTING_ISSUE_TYPES
            ):
                has_rejecting_feedback = True
            if current_issue_type and current_issue_type != "none" and not issue_type:
                issue_type = current_issue_type
        if not issue_type:
            issue_type = (
                "none"
                if feedback_records or _text(target.get("source")) == "curation"
                else "unreviewed"
            )
        error_category = _issue_error_category(issue_type)
        _increment_count(by_issue_type, issue_type)
        _increment_count(by_error_category, error_category)
        _increment_count(
            by_support_grade,
            _text(target.get("support_grade"))
            or _text(system_prediction.get("support_grade"))
            or "unknown",
        )

        target_source = _text(target.get("source"))
        if target_source == "ai_curation":
            quality_decision = "ai_curated_suggestion"
        elif target_source == "unverified_curation":
            quality_decision = "unverified_curation"
        elif target_source == "curation" and _curation_matches_system_prediction(
            item,
            system_prediction=system_prediction,
            target=target,
        ):
            quality_decision = "accepted_after_curation_match"
        elif target_source == "curation":
            quality_decision = "curated_correction"
        elif has_rejecting_feedback:
            quality_decision = "rejected_system"
        elif label_status == "gold":
            quality_decision = "accepted_system"
        elif label_status == "silver":
            quality_decision = "partial_review"
        else:
            quality_decision = "candidate"
        _increment_count(by_quality_decision, quality_decision)
        bucket_decisions = by_bucket_quality_decision.setdefault(
            presentation_bucket,
            {},
        )
        _increment_count(bucket_decisions, quality_decision)
        if quality_decision == "accepted_system":
            accepted_system_sample_count += 1
        elif quality_decision == "accepted_after_curation_match":
            accepted_after_curation_match_count += 1
        elif quality_decision == "curated_correction":
            curated_correction_count += 1
        if has_rejecting_feedback and quality_decision == "accepted_after_curation_match":
            resolved_feedback_count += 1
            warning_counts["resolved_feedback"] += 1
        elif has_rejecting_feedback:
            system_error_count += 1
            warning_counts["rejected_feedback"] += 1

        trace_status = _text(item.get("trace_status")) or "unavailable"
        _increment_count(by_trace_status, trace_status)
        if trace_status == "unavailable":
            warning_counts["unavailable_trace"] += 1
        elif trace_status == "failed":
            warning_counts["failed_trace"] += 1

        evidence_records = _mapping_list(item.get("evidence_refs"))
        if not evidence_records:
            warning_counts["missing_evidence"] += 1
            warning_counts["missing_source_text"] += 1
        elif not any(
            _text(record.get("quote")) or _text(record.get("source_text"))
            for record in evidence_records
        ):
            warning_counts["missing_source_text"] += 1
        variable_values = _dimension_list(
            system_prediction,
            target,
            "variables",
            missing_label="unknown_variable",
        )
        outcome_values = _dimension_list(
            system_prediction,
            target,
            "outcomes",
            missing_label="unknown_outcome",
        )
        direction_values = _dimension_text(
            system_prediction,
            target,
            "direction",
            missing_label="unknown_direction",
        )
        review_reasons = list(_strings(system_prediction.get("review_reasons")))
        system_warnings = list(_strings(system_prediction.get("warnings")))
        _increment_quality_dimension(
            optimization_breakdown["by_variable"],
            values=variable_values,
            issue_type=issue_type,
            error_category=error_category,
            dataset_use_status=dataset_use_status,
            review_reasons=review_reasons,
            system_warnings=system_warnings,
        )
        _increment_quality_dimension(
            optimization_breakdown["by_outcome"],
            values=outcome_values,
            issue_type=issue_type,
            error_category=error_category,
            dataset_use_status=dataset_use_status,
            review_reasons=review_reasons,
            system_warnings=system_warnings,
        )
        _increment_quality_dimension(
            optimization_breakdown["by_direction"],
            values=direction_values,
            issue_type=issue_type,
            error_category=error_category,
            dataset_use_status=dataset_use_status,
            review_reasons=review_reasons,
            system_warnings=system_warnings,
        )
        for record in evidence_records:
            evidence_role = _text(record.get("evidence_role")) or "uncategorized"
            _increment_count(
                by_evidence_role,
                evidence_role,
            )
            _increment_quality_dimension(
                optimization_breakdown["by_evidence_role"],
                values=[evidence_role],
                issue_type=issue_type,
                error_category=error_category,
                dataset_use_status=dataset_use_status,
                review_reasons=review_reasons,
                system_warnings=system_warnings,
            )
            _increment_count(
                by_evidence_traceability_status,
                _text(record.get("traceability_status")) or "unknown",
            )

        if not _mapping_list(item.get("context_refs")):
            warning_counts["missing_context"] += 1

    return {
        "total_samples": len(items),
        "usable_sample_count": usable_sample_count,
        "training_ready_sample_count": training_ready_sample_count,
        "training_message_sample_count": training_message_sample_count,
        "protocol_ready_sample_count": protocol_ready_sample_count,
        "review_candidate_sample_count": review_candidate_sample_count,
        "next_review_finding_id": next_review_finding_id,
        "needs_review_count": needs_review_count,
        "rejected_count": rejected_count,
        "labeled_sample_count": labeled_sample_count,
        "accepted_system_sample_count": accepted_system_sample_count,
        "accepted_after_curation_match_count": accepted_after_curation_match_count,
        "curated_correction_count": curated_correction_count,
        "system_error_count": system_error_count,
        "resolved_feedback_count": resolved_feedback_count,
        "by_label_status": by_label_status,
        "by_dataset_use_status": by_dataset_use_status,
        "by_review_status": by_review_status,
        "by_issue_type": by_issue_type,
        "by_error_category": by_error_category,
        "by_support_grade": by_support_grade,
        "by_trace_status": by_trace_status,
        "by_evidence_role": by_evidence_role,
        "by_evidence_traceability_status": by_evidence_traceability_status,
        "by_quality_decision": by_quality_decision,
        "by_presentation_bucket": by_presentation_bucket,
        "by_bucket_quality_decision": by_bucket_quality_decision,
        "by_review_reason": by_review_reason,
        "by_system_warning": by_system_warning,
        "by_review_candidate_reason": by_review_candidate_reason,
        "by_review_candidate_warning": by_review_candidate_warning,
        "optimization_breakdown": optimization_breakdown,
        "top_error_categories": _top_counts(by_error_category),
        "top_issue_types": _top_counts(by_issue_type),
        "top_review_reasons": _top_counts(by_review_reason),
        "top_system_warnings": _top_counts(by_system_warning),
        "top_variable_issue_types": _top_dimension_counts(
            optimization_breakdown["by_variable"],
            "issue_type",
            skip={"none", "unreviewed"},
        ),
        "top_outcome_issue_types": _top_dimension_counts(
            optimization_breakdown["by_outcome"],
            "issue_type",
            skip={"none", "unreviewed"},
        ),
        "top_direction_issue_types": _top_dimension_counts(
            optimization_breakdown["by_direction"],
            "issue_type",
            skip={"none", "unreviewed"},
        ),
        "top_evidence_role_issue_types": _top_dimension_counts(
            optimization_breakdown["by_evidence_role"],
            "issue_type",
            skip={"none", "unreviewed"},
        ),
        "top_variable_review_reasons": _top_dimension_counts(
            optimization_breakdown["by_variable"],
            "review_candidate_reason",
        ),
        "top_outcome_review_reasons": _top_dimension_counts(
            optimization_breakdown["by_outcome"],
            "review_candidate_reason",
        ),
        "top_direction_review_reasons": _top_dimension_counts(
            optimization_breakdown["by_direction"],
            "review_candidate_reason",
        ),
        "top_evidence_role_review_reasons": _top_dimension_counts(
            optimization_breakdown["by_evidence_role"],
            "review_candidate_reason",
        ),
        "warning_counts": warning_counts,
    }


def _increment_count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _increment_quality_dimension(
    breakdown: dict[str, dict[str, dict[str, int]]],
    *,
    values: list[str],
    issue_type: str,
    error_category: str,
    dataset_use_status: str,
    review_reasons: list[str],
    system_warnings: list[str],
) -> None:
    for value in values:
        bucket = breakdown.setdefault(
            value,
            {
                "issue_type": {},
                "error_category": {},
                "review_candidate_reason": {},
                "system_warning": {},
            },
        )
        _increment_count(bucket["issue_type"], issue_type)
        _increment_count(bucket["error_category"], error_category)
        if dataset_use_status == "review_candidate":
            for reason in review_reasons:
                _increment_count(bucket["review_candidate_reason"], reason)
            for warning in system_warnings:
                _increment_count(bucket["system_warning"], warning)


def _dimension_list(
    system_prediction: Mapping[str, Any],
    target: Mapping[str, Any],
    key: str,
    *,
    missing_label: str,
) -> list[str]:
    values = list(_strings(system_prediction.get(key))) or list(
        _strings(target.get(key))
    )
    return values or [missing_label]


def _dimension_text(
    system_prediction: Mapping[str, Any],
    target: Mapping[str, Any],
    key: str,
    *,
    missing_label: str,
) -> list[str]:
    value = _text(system_prediction.get(key)) or _text(target.get(key))
    return [value or missing_label]


def _top_counts(counts: dict[str, int], *, limit: int = 5) -> list[dict[str, object]]:
    return [
        {"name": key, "count": value}
        for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if value
    ][:limit]


def _top_dimension_counts(
    breakdown: Mapping[str, Mapping[str, Mapping[str, int]]],
    metric: str,
    *,
    limit: int = 5,
    skip: set[str] | None = None,
) -> list[dict[str, object]]:
    rows = []
    skipped = skip or set()
    for name, metrics in breakdown.items():
        for key, count in _mapping(metrics.get(metric)).items():
            if not count or key in skipped:
                continue
            rows.append({"name": name, "metric": key, "count": count})
    return sorted(
        rows,
        key=lambda item: (-int(item["count"]), str(item["name"]), str(item["metric"])),
    )[:limit]


def _issue_error_category(issue_type: str) -> str:
    return _ISSUE_ERROR_CATEGORIES.get(issue_type, "other_error")


def _curation_matches_system_prediction(
    item: Mapping[str, object],
    *,
    system_prediction: Mapping[str, Any],
    target: Mapping[str, Any],
) -> bool:
    system_statement = _text(system_prediction.get("statement")) or ""
    target_statement = _text(target.get("statement")) or ""
    if not system_statement or not target_statement:
        return False
    target_refs = set(_strings(target.get("evidence_ref_ids")))
    sample_refs = {
        ref_id
        for ref in _mapping_list(item.get("evidence_refs"))
        if (ref_id := _text(ref.get("evidence_ref_id")))
    }
    if target_refs and not (target_refs & sample_refs):
        return False
    system_terms = set(
        _quality_decision_terms(
            " ".join(
                [
                    system_statement,
                    *list(_strings(system_prediction.get("variables"))),
                    *list(_strings(system_prediction.get("mediators"))),
                    *list(_strings(system_prediction.get("outcomes"))),
                ]
            )
        )
    )
    target_terms = set(_quality_decision_terms(target_statement))
    if not system_terms or not target_terms:
        return False
    overlap = system_terms & target_terms
    if len(overlap) >= 3:
        return True
    outcome_terms = set(
        _quality_decision_terms(" ".join(_strings(system_prediction.get("outcomes"))))
    )
    return bool(outcome_terms and outcome_terms <= overlap)


def _quality_decision_terms(value: str | None) -> tuple[str, ...]:
    text = _text(value)
    if not text:
        return ()
    terms: list[str] = []
    seen: set[str] = set()
    for raw_term in re.split(r"[^a-z0-9]+", text.lower()):
        if len(raw_term) < 4 or raw_term in _LABEL_TERM_STOPWORDS:
            continue
        if raw_term in {
            "about",
            "better",
            "claim",
            "finding",
            "formed",
            "higher",
            "improved",
            "increased",
            "lower",
            "more",
            "sample",
            "samples",
            "statement",
            "system",
            "while",
        }:
            continue
        if raw_term in seen:
            continue
        seen.add(raw_term)
        terms.append(raw_term)
    return tuple(terms)


def _system_prediction(finding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "finding_id": _text(finding.get("finding_id")) or "",
        "claim_id": _text(finding.get("claim_id")),
        "title": _text(finding.get("title")) or "",
        "statement": _text(finding.get("statement")) or "",
        "variables": list(_strings(finding.get("variables"))),
        "mediators": list(_strings(finding.get("mediators"))),
        "outcomes": list(_strings(finding.get("outcomes"))),
        "direction": _text(finding.get("direction")),
        "scope_summary": _text(finding.get("scope_summary")),
        "support_grade": _text(finding.get("support_grade")),
        "review_status": _text(finding.get("review_status")),
        "generalization_status": _text(finding.get("generalization_status")),
        "generalization_note": _text(finding.get("generalization_note")),
        "confidence": finding.get("confidence"),
        "paper_count": _int(finding.get("paper_count")),
        "evidence_count": _int(finding.get("evidence_count")),
        "evidence_ref_ids": list(_strings(finding.get("evidence_ref_ids"))),
        "context_ids": list(_strings(finding.get("context_ids"))),
        "relation_ids": list(_strings(finding.get("relation_ids"))),
        "evidence_bundle": _mapping(finding.get("evidence_bundle")),
        "review_reasons": list(_strings(finding.get("review_reasons"))),
        "warnings": list(_strings(finding.get("warnings"))),
    }


def _review_action_for_sample(
    *,
    system_prediction: Mapping[str, Any],
    evidence_records: list[dict[str, Any]],
) -> dict[str, str]:
    risk_codes = {
        *list(_strings(system_prediction.get("review_reasons"))),
        *list(_strings(system_prediction.get("warnings"))),
    }
    if "table_row_alignment_uncertain" in risk_codes:
        code = "verify_table_rows"
        label = "verify parsed table rows before accepting or correcting"
    elif "non_single_variable_table_comparison" in risk_codes:
        code = "review_table_variables"
        label = "check whether multiple table variables changed before accepting"
    elif "table_row_needs_expert_review" in risk_codes:
        code = "review_table_rows"
        label = "review selected table rows before accepting or correcting"
    elif "conflicting_direction" in risk_codes:
        code = "resolve_conflict"
        label = "resolve conflicting evidence before downstream use"
    elif "missing_direct_result_evidence" in risk_codes or not evidence_records:
        code = "repair_evidence_binding"
        label = "repair or reject the evidence binding"
    elif "missing_mechanism_evidence" in risk_codes:
        code = "check_mechanism_requirement"
        label = "check whether mechanism evidence is required for the final label"
    elif "model_validation_finding" in risk_codes:
        code = "validate_model_evidence"
        label = "validate the model-prediction or validation evidence"
    elif (
        "needs_cross_paper_confirmation" in risk_codes
        or "single_paper_evidence" in risk_codes
    ):
        code = "accept_as_paper_level"
        label = "accept only as paper-level evidence unless another paper confirms it"
    else:
        code = "review_evidence"
        label = "accept, reject, or correct after checking the evidence"
    return {"code": code, "label": label}


def _expert_target_from_curation(
    curation: ResearchUnderstandingCuration,
) -> dict[str, Any]:
    source = (
        "curation"
        if _is_human_reviewer(curation.reviewer)
        else "ai_curation"
        if _is_ai_reviewer(curation.reviewer)
        else "unverified_curation"
    )
    return {
        "source": source,
        "curation_id": curation.curation_id,
        "claim_id": curation.claim_id,
        "claim_type": curation.curated_claim_type,
        "status": curation.curated_status,
        "statement": curation.curated_statement,
        "support_grade": curation.curated_support_grade,
        "review_status": curation.curated_review_status,
        "variables": list(curation.curated_variables),
        "mediators": list(curation.curated_mediators),
        "outcomes": list(curation.curated_outcomes),
        "direction": curation.curated_direction,
        "scope_summary": curation.curated_scope_summary,
        "evidence_ref_ids": list(curation.curated_evidence_ref_ids),
        "context_ids": list(curation.curated_context_ids),
        "note": curation.note,
        "reviewer": curation.reviewer,
        "updated_at": curation.updated_at,
    }


def _expert_target_from_feedback(
    system_prediction: Mapping[str, Any],
    feedback: tuple[ResearchUnderstandingFeedback, ...],
) -> dict[str, Any] | None:
    accepted = next(
        (item for item in feedback if item.review_status == "correct"),
        None,
    )
    partial = next(
        (item for item in feedback if item.review_status == "partial"),
        None,
    )
    item = accepted or partial
    if item is None:
        return None
    source = (
        "accepted_system_prediction"
        if item.review_status == "correct" and _is_human_reviewer(item.reviewer)
        else "ai_review_feedback"
        if item.review_status == "correct" and _is_ai_reviewer(item.reviewer)
        else "reviewer_feedback"
    )
    return {
        "source": source,
        "statement": system_prediction.get("statement"),
        "review_status": item.review_status,
        "issue_type": item.issue_type,
        "feedback_id": item.feedback_id,
        "note": item.note,
        "reviewer": item.reviewer,
        "created_at": item.created_at,
        "system_prediction": dict(system_prediction),
    }


def _training_finding_level(finding: Mapping[str, Any]) -> str:
    return "cross_paper" if _int(finding.get("paper_count")) > 1 else "paper_level"


def _training_messages(
    *,
    research_objective: str,
    finding_level: str,
    system_prediction: Mapping[str, Any],
    expert_target: Mapping[str, Any],
    evidence_records: list[dict[str, Any]],
    context_records: list[dict[str, Any]],
) -> list[dict[str, str]]:
    research_objective = _text(research_objective)
    if not expert_target or not research_objective:
        return []
    statement = _text(expert_target.get("statement")) or _text(
        system_prediction.get("statement")
    )
    if not statement:
        return []
    evidence_lines: list[str] = []
    condition_lines: list[str] = []
    result_records = [
        record
        for record in evidence_records
        if _text(record.get("evidence_role")) != "condition_context"
    ]
    condition_records = [
        record
        for record in evidence_records
        if _text(record.get("evidence_role")) == "condition_context"
    ]
    for index, record in enumerate(result_records[:8], start=1):
        text = _text(record.get("training_source_text")) or _text(record.get("quote"))
        if not text:
            text = _text(record.get("source_text"))
        if not text:
            continue
        source_label = (
            _text(record.get("source_label"))
            or _text(record.get("label"))
            or _text(record.get("evidence_ref_id"))
            or f"evidence {index}"
        )
        page = _text(record.get("page"))
        header = " | ".join(
            item
            for item in (
                f"E{index}",
                f"evidence_ref_id={_text(record.get('evidence_ref_id'))}",
                f"role={_text(record.get('evidence_role')) or 'direct_result'}",
                f"document_id={_text(record.get('document_id'))}",
                f"source={source_label}",
                f"page={page}" if page else "",
            )
            if item and not item.endswith("=")
        )
        evidence_lines.append(f"[{header}]: {text}")
    for index, record in enumerate(condition_records[:8], start=1):
        text = _text(record.get("training_source_text")) or _text(record.get("quote"))
        if not text:
            text = _text(record.get("source_text"))
        if not text:
            continue
        source_label = (
            _text(record.get("source_label"))
            or _text(record.get("label"))
            or _text(record.get("document_id"))
            or f"condition {index}"
        )
        page = _text(record.get("page"))
        header = " | ".join(
            item
            for item in (
                f"CE{index}",
                f"evidence_ref_id={_text(record.get('evidence_ref_id'))}",
                f"role={_text(record.get('evidence_role')) or 'condition_context'}",
                f"document_id={_text(record.get('document_id'))}",
                f"source={source_label}",
                f"page={page}" if page else "",
            )
            if item and not item.endswith("=")
        )
        condition_lines.append(f"[{header}]: {text}")
    context_lines = []
    for index, record in enumerate(context_records[:4], start=1):
        parts = [
            *_strings(record.get("material_scope")),
            *_strings(record.get("property_scope")),
            _text(record.get("process_summary")),
            _text(record.get("test_summary")),
        ]
        context = "; ".join(item for item in parts if item)
        if context:
            context_lines.append(f"[C{index}] {context}")
    target_payload = {
        "statement": statement,
        "variables": list(
            _strings(expert_target.get("variables") or system_prediction.get("variables"))
        ),
        "mediators": list(
            _strings(expert_target.get("mediators") or system_prediction.get("mediators"))
        ),
        "outcomes": list(
            _strings(expert_target.get("outcomes") or system_prediction.get("outcomes"))
        ),
        "direction": _text(
            expert_target.get("direction") or system_prediction.get("direction")
        ),
        "scope_summary": _text(
            expert_target.get("scope_summary")
            or system_prediction.get("scope_summary")
        ),
        "support_grade": _text(
            expert_target.get("support_grade")
            or system_prediction.get("support_grade")
        ),
        "generalization_status": _text(
            expert_target.get("generalization_status")
            or system_prediction.get("generalization_status")
        ),
        "generalization_note": _text(
            expert_target.get("generalization_note")
            or system_prediction.get("generalization_note")
        ),
        "evidence_ref_ids": list(
            _strings(
                expert_target.get("evidence_ref_ids")
                or [record.get("evidence_ref_id") for record in evidence_records]
            )
        ),
    }
    task_instruction = (
        "Synthesize one evidence-grounded cross-paper materials research finding. "
        "Preserve agreement, conflict, and condition dependence across papers."
        if finding_level == "cross_paper"
        else "Extract one evidence-grounded materials research finding from the source paper. "
        "Do not generalize it beyond that paper."
    )
    user_lines = [
        task_instruction,
        "",
        "Research objective:",
        research_objective,
        f"Finding level: {finding_level}",
        "Return only a JSON object with statement, variables, mediators, outcomes, direction, scope_summary, support_grade, generalization_status, generalization_note, and evidence_ref_ids.",
        "Use only evidence_ref_id values shown in the evidence headers.",
        "",
        "Evidence:",
        *(evidence_lines or ["No source evidence text available."]),
    ]
    if condition_lines:
        user_lines.extend(["", "Condition evidence:", *condition_lines])
    user_lines.extend(
        [
            "",
            "Context:",
            *(context_lines or ["No structured context available."]),
        ]
    )
    user_content = "\n".join(user_lines)
    return [
        {"role": "user", "content": user_content},
        {
            "role": "assistant",
            "content": json.dumps(target_payload, ensure_ascii=False, sort_keys=True),
        },
    ]


def _has_training_messages_for_expert_target(item: Mapping[str, Any]) -> bool:
    return not _training_message_diagnostic(
        _mapping(item.get("expert_target")),
        _mapping(item.get("system_prediction")),
        _mapping_list(item.get("training_messages")),
        evidence_records=_mapping_list(item.get("training_evidence_refs")),
    )


def _has_protocol_design_inputs_for_expert_target(item: Mapping[str, Any]) -> bool:
    readiness = _mapping(item.get("protocol_readiness"))
    if readiness:
        return _text(readiness.get("status")) == "protocol_ready"
    if not _has_training_messages_for_expert_target(item):
        return False
    target = _mapping(item.get("expert_target"))
    prediction = _mapping(item.get("system_prediction"))
    status = (
        _text(target.get("status") or prediction.get("status")) or ""
    ).lower()
    support_grade = (
        _text(target.get("support_grade") or prediction.get("support_grade")) or ""
    ).lower()
    if status in {"unsupported", "conflicted"}:
        return False
    if support_grade in {"insufficient", "conflict", "conflicted", "weak"}:
        return False
    statement = _text(target.get("statement") or prediction.get("statement"))
    variables = _strings(target.get("variables") or prediction.get("variables"))
    outcomes = _strings(target.get("outcomes") or prediction.get("outcomes"))
    direction = _text(target.get("direction") or prediction.get("direction"))
    scope = _text(target.get("scope_summary") or prediction.get("scope_summary"))
    evidence = _mapping_list(item.get("training_evidence_refs"))
    return bool(
        statement
        and variables
        and outcomes
        and (direction or scope)
        and any(_text(ref.get("evidence_ref_id")) and _text(ref.get("quote")) for ref in evidence)
    )


def _protocol_readiness_for_sample(
    *,
    dataset_use_status: str,
    system_prediction: Mapping[str, Any],
    expert_target: Mapping[str, Any],
    training_evidence_records: list[dict[str, Any]],
    training_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    status = (
        _text(expert_target.get("status") or system_prediction.get("status")) or ""
    ).lower()
    support_grade = (
        _text(
            expert_target.get("support_grade")
            or system_prediction.get("support_grade")
        )
        or ""
    ).lower()
    checks = {
        "expert_review_decision": dataset_use_status == "training_ready",
        "training_messages": (
            _training_messages_match_target(
                expert_target,
                system_prediction,
                training_messages,
                evidence_records=training_evidence_records,
            )
            if dataset_use_status == "training_ready"
            else True
        ),
        "statement": bool(
            _text(expert_target.get("statement") or system_prediction.get("statement"))
        ),
        "variables": bool(
            _strings(expert_target.get("variables") or system_prediction.get("variables"))
        ),
        "outcomes": bool(
            _strings(expert_target.get("outcomes") or system_prediction.get("outcomes"))
        ),
        "direction_or_scope": bool(
            _text(expert_target.get("direction") or system_prediction.get("direction"))
            or _text(
                expert_target.get("scope_summary")
                or system_prediction.get("scope_summary")
            )
        ),
        "support_status": status not in {"unsupported", "conflicted"},
        "support_grade": support_grade
        not in {"insufficient", "conflict", "conflicted", "weak"},
        "traceable_training_evidence": any(
            _text(ref.get("evidence_ref_id")) and _text(ref.get("quote"))
            for ref in training_evidence_records
        ),
    }
    blocking_keys = (
        (
            "training_messages",
        )
        if dataset_use_status == "training_ready"
        else ()
    ) + (
        "statement",
        "variables",
        "outcomes",
        "direction_or_scope",
        "support_status",
        "support_grade",
        "traceable_training_evidence",
    )
    blocking_missing = [key for key in blocking_keys if not checks[key]]
    missing_keys = ("expert_review_decision", "training_messages", *blocking_keys)
    missing = [
        key
        for index, key in enumerate(missing_keys)
        if key not in missing_keys[:index]
        if not checks[key]
    ]
    if not missing:
        status_label = "protocol_ready"
        guidance = "Ready for traceable protocol drafting."
    elif blocking_missing:
        status_label = "needs_correction"
        guidance = "Correct the missing fields or evidence before importing this row."
    else:
        status_label = "ready_after_review"
        guidance = "Accept only after expert review confirms the finding and evidence."
    return {
        "status": status_label,
        "ready_after_review": not blocking_missing,
        "missing": missing,
        "blocking_missing": blocking_missing,
        "checks": checks,
        "guidance": guidance,
    }


def _acceptance_gate_for_sample(
    *,
    dataset_use_status: str,
    system_prediction: Mapping[str, Any],
    review_action: Mapping[str, str],
    protocol_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    blocking_missing = list(_strings(protocol_readiness.get("blocking_missing")))
    accept_blockers = _accept_blockers(
        system_prediction=system_prediction,
        review_action=review_action,
    )
    review_checks = _acceptance_review_checks(
        system_prediction=system_prediction,
        review_action=review_action,
    )
    if dataset_use_status == "training_ready":
        status = "accepted"
        accept_allowed = False
        requires_correction = False
        guidance = "Already accepted for training use."
    elif accept_blockers:
        status = "correction_required"
        accept_allowed = False
        requires_correction = True
        guidance = "Do not accept directly; correct or reject the table alignment risk first."
    elif blocking_missing:
        status = "correction_required"
        accept_allowed = False
        requires_correction = True
        guidance = "Do not accept directly; correct or reject the blocking gaps first."
    else:
        status = "review_required"
        accept_allowed = True
        requires_correction = False
        guidance = "Accept only after the listed checks and source evidence match."
    return {
        "status": status,
        "accept_allowed": accept_allowed,
        "requires_correction": requires_correction,
        "blocking_missing": blocking_missing,
        "accept_blockers": accept_blockers,
        "review_checks": review_checks,
        "recommended_action_code": _text(review_action.get("code")),
        "guidance": guidance,
    }


def _review_decision_hint_for_sample(
    *,
    acceptance_gate: Mapping[str, Any],
    protocol_readiness: Mapping[str, Any],
    review_action: Mapping[str, str],
) -> dict[str, Any]:
    accept_allowed = bool(acceptance_gate.get("accept_allowed"))
    review_checks = list(_strings(acceptance_gate.get("review_checks")))
    accept_blockers = list(_strings(acceptance_gate.get("accept_blockers")))
    blocking_missing = list(_strings(acceptance_gate.get("blocking_missing"))) or list(
        _strings(protocol_readiness.get("blocking_missing"))
    )
    if not accept_allowed:
        blocked_reasons: list[str] = []
        if accept_blockers:
            blocked_reasons.append(f"accept_blockers={', '.join(accept_blockers)}")
        if blocking_missing:
            blocked_reasons.append(f"blocking_missing={', '.join(blocking_missing)}")
        if not blocked_reasons:
            blocked_reasons.append("acceptance_gate blocks direct accept")
        return {
            "summary": (
                "Do not accept directly; correct the row or reject it after "
                "source review."
            ),
            "preferred_next_action": "correct_or_reject",
            "allowed_actions": ["reject", "correct", "skip"],
            "blocked_actions": ["accept"],
            "why_accept_blocked": blocked_reasons,
            "required_checks": review_checks,
            "import_note": "accept is rejected while acceptance_gate.accept_allowed=false",
        }
    action_summaries = {
        "accept_as_paper_level": (
            "Accept only as paper-level evidence after checking the quote; "
            "correct if the scope should be narrower."
        ),
        "review_table_rows": (
            "Verify the selected table rows and then accept or correct the finding."
        ),
        "review_table_variables": (
            "Check whether other table variables changed; correct if this is not "
            "a single-variable effect."
        ),
        "check_mechanism_requirement": (
            "Decide whether mechanism evidence is required; accept only if the "
            "final scope matches that decision."
        ),
        "resolve_conflict": "Resolve the conflicting evidence direction before accepting.",
    }
    action_code = _text(review_action.get("code"))
    preferred_next_action = (
        "verify_then_accept_or_correct"
        if action_code
        in {"review_table_rows", "review_table_variables", "check_mechanism_requirement"}
        else "accept_after_checks"
    )
    return {
        "summary": action_summaries.get(
            action_code,
            "Accept, reject, or correct after checking the cited evidence.",
        ),
        "preferred_next_action": preferred_next_action,
        "allowed_actions": ["accept", "reject", "correct", "skip"],
        "blocked_actions": [],
        "why_accept_blocked": [],
        "required_checks": review_checks,
        "import_note": "accept imports only after the reviewer changes action from skip",
    }


def _accept_blockers(
    *,
    system_prediction: Mapping[str, Any],
    review_action: Mapping[str, str],
) -> list[str]:
    blockers: list[str] = []
    for value in [
        _text(review_action.get("code")),
        *_strings(system_prediction.get("review_reasons")),
        *_strings(system_prediction.get("warnings")),
    ]:
        if value in _ACCEPT_BLOCKING_REVIEW_CODES and value not in blockers:
            blockers.append(value)
    return blockers


def _acceptance_review_checks(
    *,
    system_prediction: Mapping[str, Any],
    review_action: Mapping[str, str],
) -> list[str]:
    checks: list[str] = []
    action_code = _text(review_action.get("code"))
    if action_code in _ACCEPTANCE_REVIEW_CHECKS:
        checks.append(_ACCEPTANCE_REVIEW_CHECKS[action_code])
    for value in [
        *_strings(system_prediction.get("review_reasons")),
        *_strings(system_prediction.get("warnings")),
    ]:
        if value in _ACCEPTANCE_REVIEW_CHECKS:
            check = _ACCEPTANCE_REVIEW_CHECKS[value]
            if check not in checks:
                checks.append(check)
    return checks


def _training_messages_match_target(
    expert_target: Mapping[str, Any],
    system_prediction: Mapping[str, Any],
    messages: list[dict[str, Any]],
    *,
    evidence_records: list[dict[str, Any]],
) -> bool:
    return not _training_message_diagnostic(
        expert_target,
        system_prediction,
        messages,
        evidence_records=evidence_records,
    )


def _training_message_diagnostic(
    expert_target: Mapping[str, Any],
    system_prediction: Mapping[str, Any],
    messages: list[dict[str, Any]],
    *,
    evidence_records: list[dict[str, Any]],
) -> list[str]:
    expected = _training_message_expected_payload(
        expert_target,
        system_prediction,
        evidence_records=evidence_records,
    )
    missing_expected = _training_message_missing_expected_fields(expected)
    if missing_expected:
        return [f"missing_expected_{field}" for field in missing_expected]
    if len(messages) < 2:
        return ["missing_message_pair"]
    if _text(messages[0].get("role")) != "user" or not _text(
        messages[0].get("content")
    ):
        return ["invalid_user_message"]
    if _text(messages[-1].get("role")) != "assistant":
        return ["missing_assistant_message"]
    try:
        assistant_payload = json.loads(_text(messages[-1].get("content")))
    except json.JSONDecodeError:
        return ["invalid_assistant_json"]
    if not isinstance(assistant_payload, Mapping):
        return ["invalid_assistant_json_object"]
    return [
        f"mismatched_assistant_{field}"
        for field in _training_message_payload_mismatch_fields(
            assistant_payload,
            expected,
        )
    ]


def _training_message_expected_payload(
    expert_target: Mapping[str, Any],
    system_prediction: Mapping[str, Any],
    *,
    evidence_records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "statement": _text(
            expert_target.get("statement") or system_prediction.get("statement")
        ),
        "variables": list(
            _strings(expert_target.get("variables") or system_prediction.get("variables"))
        ),
        "mediators": list(
            _strings(expert_target.get("mediators") or system_prediction.get("mediators"))
        ),
        "outcomes": list(
            _strings(expert_target.get("outcomes") or system_prediction.get("outcomes"))
        ),
        "direction": _text(
            expert_target.get("direction") or system_prediction.get("direction")
        ),
        "scope_summary": _text(
            expert_target.get("scope_summary")
            or system_prediction.get("scope_summary")
        ),
        "support_grade": _text(
            expert_target.get("support_grade")
            or system_prediction.get("support_grade")
        ),
        "generalization_status": _text(
            expert_target.get("generalization_status")
            or system_prediction.get("generalization_status")
        ),
        "generalization_note": _text(
            expert_target.get("generalization_note")
            or system_prediction.get("generalization_note")
        ),
        "evidence_ref_ids": list(
            _strings(
                expert_target.get("evidence_ref_ids")
                or [record.get("evidence_ref_id") for record in evidence_records]
            )
        ),
    }


def _training_message_expected_payload_is_complete(
    expected: Mapping[str, Any],
) -> bool:
    return not _training_message_missing_expected_fields(expected)


def _training_message_missing_expected_fields(
    expected: Mapping[str, Any],
) -> list[str]:
    missing = []
    if not _text(expected.get("statement")):
        missing.append("statement")
    if not _strings(expected.get("variables")):
        missing.append("variables")
    if not _strings(expected.get("outcomes")):
        missing.append("outcomes")
    if not (
        _text(expected.get("direction")) or _text(expected.get("scope_summary"))
    ):
        missing.append("direction_or_scope")
    if not _text(expected.get("support_grade")):
        missing.append("support_grade")
    if not _text(expected.get("generalization_status")):
        missing.append("generalization_status")
    if not _strings(expected.get("evidence_ref_ids")):
        missing.append("evidence_ref_ids")
    return missing


def _training_message_payload_matches_expected(
    assistant_payload: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> bool:
    return not _training_message_payload_mismatch_fields(assistant_payload, expected)


def _training_message_payload_mismatch_fields(
    assistant_payload: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> list[str]:
    mismatches = []
    if _normalized_text(assistant_payload.get("statement")) != _normalized_text(
        expected.get("statement")
    ):
        mismatches.append("statement")
    if _normalized_strings(assistant_payload.get("variables")) != _normalized_strings(
        expected.get("variables")
    ):
        mismatches.append("variables")
    if _normalized_strings(assistant_payload.get("outcomes")) != _normalized_strings(
        expected.get("outcomes")
    ):
        mismatches.append("outcomes")
    if _text(expected.get("direction")) and _normalized_text(
        assistant_payload.get("direction")
    ) != _normalized_text(expected.get("direction")):
        mismatches.append("direction")
    if _text(expected.get("scope_summary")) and _normalized_text(
        assistant_payload.get("scope_summary")
    ) != _normalized_text(expected.get("scope_summary")):
        mismatches.append("scope_summary")
    if _normalized_text(assistant_payload.get("support_grade")) != _normalized_text(
        expected.get("support_grade")
    ):
        mismatches.append("support_grade")
    if _normalized_text(
        assistant_payload.get("generalization_status")
    ) != _normalized_text(expected.get("generalization_status")):
        mismatches.append("generalization_status")
    if _normalized_strings(
        assistant_payload.get("evidence_ref_ids")
    ) != _normalized_strings(expected.get("evidence_ref_ids")):
        mismatches.append("evidence_ref_ids")
    return mismatches


def _normalized_text(value: Any) -> str:
    return " ".join((_text(value) or "").casefold().split())


def _normalized_strings(values: Any) -> tuple[str, ...]:
    return tuple(_normalized_text(value) for value in _strings(values))


def _is_ai_reviewer(reviewer: str | None) -> bool:
    normalized = (_text(reviewer) or "").lower()
    return normalized.startswith("ai-reviewer") or normalized.startswith("agent-")


def _is_human_reviewer(reviewer: str | None) -> bool:
    normalized = _text(reviewer)
    return bool(normalized) and not _is_ai_reviewer(normalized)


def _matched_trace_for_finding(
    finding: Mapping[str, Any],
    *,
    evidence_ref_ids: tuple[str, ...],
    evidence_refs: Mapping[str, Mapping[str, Any]],
    relations: Mapping[str, Mapping[str, Any]],
    model_traces: tuple[dict[str, Any], ...],
) -> dict[str, Any] | None:
    source_ids = set(_strings(finding.get("source_object_ids")))
    for evidence_ref_id in evidence_ref_ids:
        source_ids.update(_strings(evidence_refs.get(evidence_ref_id, {}).get("fact_ids")))
    for relation_id in _strings(finding.get("relation_ids")):
        relation = relations.get(relation_id, {})
        source_ids.update(_strings(relation.get("source_object_ids")))
    if not source_ids:
        return None
    for trace in model_traces:
        trace_source_ids = set(_strings(trace.get("source_object_ids")))
        if source_ids & trace_source_ids:
            return trace
    return None


def _trace_status(
    trace: Mapping[str, Any] | None,
    *,
    evidence_records: list[dict[str, Any]] | None = None,
) -> str:
    if not _trace_has_text_input_blocks(trace):
        if any(
            _text(record.get("source_ref"))
            and (_text(record.get("quote")) or _text(record.get("source_text")))
            for record in evidence_records or []
        ):
            return "evidence_derived"
        return "unavailable"
    return _text(trace.get("trace_status")) or "available"


def _trace_input_blocks(
    trace: Mapping[str, Any] | None,
    *,
    evidence_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not _trace_has_text_input_blocks(trace):
        return _evidence_input_blocks(evidence_records or [])
    return list(_mapping_list(trace.get("input_blocks")))


def _trace_has_text_input_blocks(trace: Mapping[str, Any] | None) -> bool:
    if not trace:
        return False
    return any(_text(block.get("text")) for block in _mapping_list(trace.get("input_blocks")))


def _evidence_input_blocks(
    evidence_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for record in evidence_records:
        source_ref = _text(record.get("source_ref"))
        text = _text(record.get("quote")) or _text(record.get("source_text"))
        if not source_ref or not text:
            continue
        evidence_ref_id = _text(record.get("evidence_ref_id"))
        key = (evidence_ref_id, source_ref)
        if key in seen:
            continue
        seen.add(key)
        blocks.append(
            {
                "source_object_id": evidence_ref_id,
                "source_kind": _text(record.get("source_kind")) or "unknown",
                "document_id": _text(record.get("document_id")),
                "source_ref": source_ref,
                "page": _text(record.get("page")),
                "role": _text(record.get("evidence_role")) or "uncategorized",
                "text": text,
                "href": _text(record.get("href")),
            }
        )
    return blocks


def _trace_note(trace: Mapping[str, Any] | None, trace_status: str) -> str:
    if trace_status == "evidence_derived":
        return "dataset input reconstructed from resolved evidence source text"
    if trace:
        return "matched research-understanding model trace"
    return "prompt/model trace is not captured for historical samples"


def _trace_model_output(trace: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not trace:
        return None
    return {
        "trace_id": _text(trace.get("trace_id")),
        "task_type": _text(trace.get("task_type")),
        "model": _text(trace.get("model")),
        "extraction_mode": _text(trace.get("extraction_mode")),
        "response_model": _text(trace.get("response_model")),
        "raw_output": _text(trace.get("raw_output")),
        "parsed_output": trace.get("parsed_output"),
        "error": _text(trace.get("error")),
    }


def _evidence_record(
    evidence_ref_id: str,
    evidence_refs: Mapping[str, Mapping[str, Any]],
    evidence_items: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    ref = _mapping(evidence_refs.get(evidence_ref_id))
    item = _mapping(evidence_items.get(evidence_ref_id))
    locator = _mapping(ref.get("locator"))
    quote = _text(item.get("quote")) or _text(ref.get("quote"))
    source_text = _text(item.get("source_text"))
    return {
        "evidence_ref_id": evidence_ref_id,
        "document_id": _text(item.get("document_id")) or _text(ref.get("document_id")),
        "source_kind": (
            _text(item.get("source_kind"))
            or _text(ref.get("source_kind"))
            or "unknown"
        ),
        "label": _text(item.get("title")) or _text(ref.get("label")) or evidence_ref_id,
        "source_label": _text(item.get("source_label")),
        "source_ref": _text(item.get("source_ref")) or _text(locator.get("source_ref")),
        "block_type": _text(item.get("block_type")),
        "heading_path": _text(item.get("heading_path")),
        "page": _text(item.get("page")),
        "quote": quote,
        "source_text": source_text,
        "training_source_text": quote or source_text,
        "value_summary": _text(item.get("value_summary")),
        "table_audit": _mapping(item.get("table_audit")) or None,
        "locator": locator,
        "fact_ids": list(_strings(ref.get("fact_ids"))),
        "anchor_ids": list(_strings(ref.get("anchor_ids"))),
        "traceability_status": (
            _text(item.get("traceability_status"))
            or _text(ref.get("traceability_status"))
            or "unknown"
        ),
        "evidence_role": (
            _text(item.get("evidence_role")) or _text(ref.get("evidence_role"))
        ),
        "confidence": (
            item.get("confidence")
            if item.get("confidence") is not None
            else ref.get("confidence")
        ),
        "href": _text(item.get("href")) or _text(ref.get("href")),
    }


def _context_record(
    context_id: str,
    contexts: Mapping[str, Mapping[str, Any]],
    context_summaries: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    context = _mapping(contexts.get(context_id))
    summary = _mapping(context_summaries.get(context_id))
    return {
        "context_id": context_id,
        "label": _text(summary.get("label")) or _text(context.get("label")) or context_id,
        "material_scope": list(
            _strings(summary.get("material_scope") or context.get("material_scope"))
        ),
        "property_scope": list(
            _strings(summary.get("property_scope") or context.get("property_scope"))
        ),
        "process_summary": _text(summary.get("process_summary")),
        "test_summary": _text(summary.get("test_summary")),
        "limitations": list(_strings(summary.get("limitations") or context.get("limitations"))),
        "process_context": _mapping(context.get("process_context")),
        "test_condition": _mapping(context.get("test_condition")),
    }


def _by_id(
    records: tuple[dict[str, Any], ...],
    key: str,
) -> dict[str, dict[str, Any]]:
    return {
        identifier: record
        for record in records
        if (identifier := _text(record.get(key)))
    }


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


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _sample_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return prefix + "_" + sha1(payload.encode("utf-8")).hexdigest()[:16]
