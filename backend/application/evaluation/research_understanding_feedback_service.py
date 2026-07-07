from __future__ import annotations

import re
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Mapping

from application.core.research_understanding_service import ResearchUnderstandingService
from domain.evaluation import (
    ResearchUnderstandingCuration,
    ResearchUnderstandingFeedback,
)
from domain.ports import CoreFactRepository, EvaluationRepository
from infra.persistence.factory import (
    build_core_fact_repository,
    build_evaluation_repository,
)


DATASET_SCHEMA_VERSION = "research_understanding_dataset.v1"
DATASET_TASK_TYPE = "research_understanding_finding"
DATASET_LABEL_STATUSES = ("candidate", "silver", "gold", "rejected")
_REJECTING_ISSUE_TYPES = frozenset(
    {
        "evidence_not_grounded",
        "missing_evidence",
        "wrong_context",
        "wrong_relation",
        "overclaim",
        "unclear_statement",
    }
)


class ResearchUnderstandingFeedbackService:
    """Persist expert review feedback for research-understanding findings."""

    def __init__(
        self,
        evaluation_repository: EvaluationRepository | None = None,
        core_fact_repository: CoreFactRepository | None = None,
        research_understanding_service: ResearchUnderstandingService | None = None,
    ) -> None:
        self.evaluation_repository = (
            evaluation_repository or build_evaluation_repository()
        )
        self.core_fact_repository = core_fact_repository or build_core_fact_repository()
        self.research_understanding_service = (
            research_understanding_service or ResearchUnderstandingService()
        )

    def record_feedback(
        self,
        *,
        collection_id: str,
        scope_type: str,
        scope_id: str,
        finding_id: str,
        review_status: str,
        issue_type: str,
        claim_id: str | None = None,
        note: str | None = None,
        reviewer: str | None = None,
    ) -> ResearchUnderstandingFeedback:
        created_at = _now_iso()
        feedback = ResearchUnderstandingFeedback.from_mapping(
            {
                "feedback_id": _feedback_id(
                    collection_id,
                    scope_type,
                    scope_id,
                    finding_id,
                    review_status,
                    issue_type,
                    note,
                    reviewer,
                    created_at,
                ),
                "collection_id": collection_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "finding_id": finding_id,
                "claim_id": claim_id,
                "review_status": review_status,
                "issue_type": issue_type,
                "note": note,
                "reviewer": reviewer,
                "created_at": created_at,
            }
        )
        return self.evaluation_repository.upsert_research_understanding_feedback(
            feedback
        )

    def list_feedback(
        self,
        *,
        collection_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        finding_id: str | None = None,
        claim_id: str | None = None,
    ) -> tuple[ResearchUnderstandingFeedback, ...]:
        return self.evaluation_repository.list_research_understanding_feedback(
            collection_id=collection_id,
            scope_type=scope_type,
            scope_id=scope_id,
            finding_id=finding_id,
            claim_id=claim_id,
        )

    def record_curation(
        self,
        *,
        collection_id: str,
        scope_type: str,
        scope_id: str,
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
        updated_at = _now_iso()
        curation = ResearchUnderstandingCuration.from_mapping(
            {
                "curation_id": _curation_id(
                    collection_id,
                    scope_type,
                    scope_id,
                    finding_id,
                ),
                "collection_id": collection_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "finding_id": finding_id,
                "claim_id": claim_id,
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
        return self.evaluation_repository.upsert_research_understanding_curation(
            curation
        )

    def list_curations(
        self,
        *,
        collection_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        finding_id: str | None = None,
        claim_id: str | None = None,
    ) -> tuple[ResearchUnderstandingCuration, ...]:
        return self.evaluation_repository.list_research_understanding_curations(
            collection_id=collection_id,
            scope_type=scope_type,
            scope_id=scope_id,
            finding_id=finding_id,
            claim_id=claim_id,
        )

    def export_gold_draft(
        self,
        *,
        collection_id: str,
        scope_type: str,
        scope_id: str,
    ) -> dict[str, object]:
        curations = self.list_curations(
            collection_id=collection_id,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        items = [
            {
                "gold_item_id": "gold_" + curation.curation_id.removeprefix("ruc_"),
                "document_id": "",
                "family": "research_understanding_findings",
                "item_key": ":".join(
                    [curation.scope_type, curation.scope_id, curation.finding_id]
                ),
                "payload": {
                    "finding_id": curation.finding_id,
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
                },
            }
            for curation in curations
        ]
        return {
            "collection_id": collection_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "gold_id": _gold_draft_id(collection_id, scope_type, scope_id),
            "target_layer": "core",
            "metric_profile": "research_understanding_v1",
            "item_count": len(items),
            "items": items,
        }

    def export_dataset(
        self,
        *,
        collection_id: str,
        scope_type: str,
        scope_id: str,
        label_status: str | None = None,
    ) -> dict[str, object]:
        if label_status and label_status not in DATASET_LABEL_STATUSES:
            raise ValueError(f"unsupported label_status: {label_status}")

        understanding = self.core_fact_repository.read_research_understanding(
            collection_id,
            scope_type,
            scope_id,
        )
        if understanding is None:
            return self._dataset_payload(
                collection_id=collection_id,
                scope_type=scope_type,
                scope_id=scope_id,
                label_status_filter=label_status,
                items=[],
                warnings=["research understanding artifact is not available"],
            )

        understanding_record = (
            self.research_understanding_service.with_presentation(understanding)
            or understanding.to_record()
        )
        feedback = self.list_feedback(
            collection_id=collection_id,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        curations = self.list_curations(
            collection_id=collection_id,
            scope_type=scope_type,
            scope_id=scope_id,
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

        items: list[dict[str, object]] = []
        for finding in self._finding_records(understanding_record):
            sample = self._dataset_sample(
                collection_id=collection_id,
                scope_type=scope_type,
                scope_id=scope_id,
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
            if label_status and sample["label_status"] != label_status:
                continue
            items.append(sample)

        return self._dataset_payload(
            collection_id=collection_id,
            scope_type=scope_type,
            scope_id=scope_id,
            label_status_filter=label_status,
            items=items,
            warnings=[],
        )

    def _dataset_payload(
        self,
        *,
        collection_id: str,
        scope_type: str,
        scope_id: str,
        label_status_filter: str | None,
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
            "dataset_id": _dataset_id(collection_id, scope_type, scope_id),
            "collection_id": collection_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "task_type": DATASET_TASK_TYPE,
            "metric_profile": "research_understanding_v1",
            "label_status_filter": label_status_filter,
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

    def _dataset_sample(
        self,
        *,
        collection_id: str,
        scope_type: str,
        scope_id: str,
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
        raw_feedback = _feedback_for(feedback_index, finding_id, claim_id)
        raw_curations = _curations_for(curation_index, finding_id, claim_id)
        feedback = _aligned_feedback_for_current_finding(
            raw_feedback,
            finding=finding,
            finding_id=finding_id,
        )
        curations = _aligned_curations_for_current_finding(
            raw_curations,
            finding=finding,
            finding_id=finding_id,
        )
        curation = curations[0] if curations else None
        label_status = _label_status(feedback, curation)
        system_prediction = _system_prediction(finding)
        system_prediction["presentation_bucket"] = presentation_bucket
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
        if curation is not None:
            evidence_ref_ids_list = list(
                _strings(
                    [
                        ref_id
                        for ref_id in curation.curated_evidence_ref_ids
                        if ref_id in evidence_refs
                    ]
                    + evidence_ref_ids_list
                )
            )
        evidence_ref_ids = tuple(evidence_ref_ids_list)
        context_ids = _strings(finding.get("context_ids"))
        matched_trace = _matched_trace_for_finding(
            finding,
            evidence_ref_ids=evidence_ref_ids,
            evidence_refs=evidence_refs,
            relations=relations,
            model_traces=model_traces,
        )
        expert_target = (
            _expert_target_from_curation(curation)
            if curation is not None
            else _expert_target_from_feedback(system_prediction, feedback)
        )
        return {
            "sample_id": _sample_id(
                "rus",
                collection_id,
                scope_type,
                scope_id,
                finding_id,
                label_status,
            ),
            "task_type": DATASET_TASK_TYPE,
            "collection_id": collection_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "finding_id": finding_id,
            "claim_id": claim_id,
            "label_status": label_status,
            "presentation_bucket": presentation_bucket,
            "trace_status": _trace_status(matched_trace),
            "input_blocks": _trace_input_blocks(matched_trace),
            "prompt_version": (
                _text(matched_trace.get("prompt_version")) if matched_trace else None
            ),
            "model_output": _trace_model_output(matched_trace),
            "system_prediction": system_prediction,
            "expert_target": expert_target,
            "evidence_refs": [
                _evidence_record(evidence_ref_id, evidence_refs, evidence_items)
                for evidence_ref_id in evidence_ref_ids
            ],
            "context_refs": [
                _context_record(context_id, contexts, context_summaries)
                for context_id in context_ids
            ],
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
                "trace_note": (
                    "matched research-understanding model trace"
                    if matched_trace
                    else "prompt/model trace is not captured for historical samples"
                ),
                "presentation_bucket": presentation_bucket,
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


def _gold_draft_id(collection_id: str, scope_type: str, scope_id: str) -> str:
    payload = "_".join(
        part.strip().replace(" ", "_")
        for part in (collection_id, scope_type, scope_id)
        if part.strip()
    )
    return f"gold_{payload}_research_understanding"


def _dataset_id(collection_id: str, scope_type: str, scope_id: str) -> str:
    payload = "_".join(
        part.strip().replace(" ", "_")
        for part in (collection_id, scope_type, scope_id)
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
        return "gold"
    if any(
        item.review_status == "incorrect" or item.issue_type in _REJECTING_ISSUE_TYPES
        for item in feedback
    ):
        return "rejected"
    if any(item.review_status == "correct" for item in feedback):
        return "gold"
    if any(item.review_status == "partial" for item in feedback):
        return "silver"
    return "candidate"


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
    finding: Mapping[str, Any],
    finding_id: str,
) -> tuple[ResearchUnderstandingFeedback, ...]:
    aligned: list[ResearchUnderstandingFeedback] = []
    has_exact_rejecting_feedback = any(
        record.finding_id == finding_id
        and (
            record.review_status == "incorrect"
            or record.issue_type in _REJECTING_ISSUE_TYPES
        )
        for record in records
    )
    for record in records:
        if record.finding_id == finding_id:
            aligned.append(record)
            continue
        if record.finding_id:
            continue
        if has_exact_rejecting_feedback:
            continue
        if _claim_record_matches_current_finding(
            finding,
            review_status=record.review_status,
            issue_type=record.issue_type,
            evidence_ref_ids=(),
            statement=None,
        ):
            aligned.append(record)
    return tuple(aligned)


def _aligned_curations_for_current_finding(
    records: tuple[ResearchUnderstandingCuration, ...],
    *,
    finding: Mapping[str, Any],
    finding_id: str,
) -> tuple[ResearchUnderstandingCuration, ...]:
    aligned: list[ResearchUnderstandingCuration] = []
    for record in records:
        if record.finding_id == finding_id:
            aligned.append(record)
            continue
        if record.finding_id:
            continue
        if _claim_record_matches_current_finding(
            finding,
            review_status=record.curated_review_status,
            issue_type=None,
            evidence_ref_ids=record.curated_evidence_ref_ids,
            statement=record.curated_statement,
        ):
            aligned.append(record)
    return tuple(aligned)


def _claim_record_matches_current_finding(
    finding: Mapping[str, Any],
    *,
    review_status: str | None,
    issue_type: str | None,
    evidence_ref_ids: tuple[str, ...] | list[str],
    statement: str | None,
) -> bool:
    current_refs = set(_strings(finding.get("evidence_ref_ids")))
    for refs in _mapping(finding.get("evidence_bundle")).values():
        current_refs.update(_strings(refs))
    if current_refs and current_refs & set(_strings(evidence_ref_ids)):
        return True
    statement_terms = set(_meaningful_label_terms(statement))
    current_terms = set(
        _meaningful_label_terms(
            " ".join(
                value
                for value in (
                    _text(finding.get("title")),
                    _text(finding.get("statement")),
                    *_strings(finding.get("variables")),
                    *_strings(finding.get("outcomes")),
                )
                if value
            )
        )
    )
    if statement_terms and current_terms and len(statement_terms & current_terms) >= 2:
        return True
    current_grade = _text(finding.get("support_grade")) or ""
    if current_grade == "insufficient":
        return False
    if (_text(issue_type) or "none") in _REJECTING_ISSUE_TYPES:
        return True
    return _text(review_status) in {"correct", "partial", "unclear", "incorrect"}


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


def _meaningful_label_terms(value: str | None) -> tuple[str, ...]:
    text = _text(value)
    if not text:
        return ()
    terms: list[str] = []
    seen: set[str] = set()
    for raw_term in re.split(r"[^a-z0-9]+", text.lower()):
        if len(raw_term) < 3 or raw_term in _LABEL_TERM_STOPWORDS:
            continue
        if raw_term in seen:
            continue
        seen.add(raw_term)
        terms.append(raw_term)
    return tuple(terms)


def _dataset_quality_summary(items: list[dict[str, object]]) -> dict[str, object]:
    by_label_status = {status: 0 for status in DATASET_LABEL_STATUSES}
    by_review_status: dict[str, int] = {}
    by_issue_type: dict[str, int] = {}
    by_support_grade: dict[str, int] = {}
    by_trace_status: dict[str, int] = {}
    by_evidence_role: dict[str, int] = {}
    by_evidence_traceability_status: dict[str, int] = {}
    by_quality_decision: dict[str, int] = {}
    by_presentation_bucket: dict[str, int] = {}
    by_bucket_quality_decision: dict[str, dict[str, int]] = {}
    warning_counts = {
        "missing_evidence": 0,
        "missing_source_text": 0,
        "missing_context": 0,
        "unavailable_trace": 0,
        "failed_trace": 0,
        "rejected_feedback": 0,
    }
    usable_sample_count = 0
    needs_review_count = 0
    rejected_count = 0
    labeled_sample_count = 0
    accepted_system_sample_count = 0
    curated_correction_count = 0
    system_error_count = 0

    for item in items:
        label_status = _text(item.get("label_status")) or "candidate"
        presentation_bucket = _text(item.get("presentation_bucket")) or "unbucketed"
        _increment_count(by_label_status, label_status)
        _increment_count(by_presentation_bucket, presentation_bucket)
        if label_status in {"gold", "silver"}:
            usable_sample_count += 1
        if label_status != "candidate":
            labeled_sample_count += 1
        if label_status == "rejected":
            rejected_count += 1

        target = _mapping(item.get("expert_target"))
        feedback_records = _mapping_list(item.get("feedback_refs"))
        system_prediction = _mapping(item.get("system_prediction"))

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
        _increment_count(by_issue_type, issue_type)
        _increment_count(
            by_support_grade,
            _text(target.get("support_grade"))
            or _text(system_prediction.get("support_grade"))
            or "unknown",
        )

        target_source = _text(target.get("source"))
        if target_source == "curation":
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
        elif quality_decision == "curated_correction":
            curated_correction_count += 1
        if has_rejecting_feedback:
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
        for record in evidence_records:
            _increment_count(
                by_evidence_role,
                _text(record.get("evidence_role")) or "uncategorized",
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
        "needs_review_count": needs_review_count,
        "rejected_count": rejected_count,
        "labeled_sample_count": labeled_sample_count,
        "accepted_system_sample_count": accepted_system_sample_count,
        "curated_correction_count": curated_correction_count,
        "system_error_count": system_error_count,
        "by_label_status": by_label_status,
        "by_review_status": by_review_status,
        "by_issue_type": by_issue_type,
        "by_support_grade": by_support_grade,
        "by_trace_status": by_trace_status,
        "by_evidence_role": by_evidence_role,
        "by_evidence_traceability_status": by_evidence_traceability_status,
        "by_quality_decision": by_quality_decision,
        "by_presentation_bucket": by_presentation_bucket,
        "by_bucket_quality_decision": by_bucket_quality_decision,
        "warning_counts": warning_counts,
    }


def _increment_count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


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
        "confidence": finding.get("confidence"),
        "paper_count": _int(finding.get("paper_count")),
        "evidence_count": _int(finding.get("evidence_count")),
        "evidence_ref_ids": list(_strings(finding.get("evidence_ref_ids"))),
        "context_ids": list(_strings(finding.get("context_ids"))),
        "relation_ids": list(_strings(finding.get("relation_ids"))),
        "evidence_bundle": _mapping(finding.get("evidence_bundle")),
        "warnings": list(_strings(finding.get("warnings"))),
    }


def _expert_target_from_curation(
    curation: ResearchUnderstandingCuration,
) -> dict[str, Any]:
    return {
        "source": "curation",
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
    if not any(item.review_status == "correct" for item in feedback):
        return None
    return {
        "source": "accepted_system_prediction",
        "statement": system_prediction.get("statement"),
        "system_prediction": dict(system_prediction),
    }


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


def _trace_status(trace: Mapping[str, Any] | None) -> str:
    if not trace:
        return "unavailable"
    return _text(trace.get("trace_status")) or "available"


def _trace_input_blocks(trace: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not trace:
        return []
    return list(_mapping_list(trace.get("input_blocks")))


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
        "quote": _text(item.get("quote")) or _text(ref.get("quote")),
        "source_text": _text(item.get("source_text")),
        "value_summary": _text(item.get("value_summary")),
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
