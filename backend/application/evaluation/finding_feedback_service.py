from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha1, sha256
from typing import (
    Any,
    Mapping,
)

from application.core.objectives.analysis.analysis_record_source import (
    should_read_experiment_projection,
)
from application.core.objectives.analysis.experiment_compatibility_projection import (
    ExperimentCompatibilityProjection,
)
from application.core.objectives.analysis.experiment_query_service import (
    finding_response,
    objective_evidence_response,
)
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
from domain.core.finding import _certainty as finding_certainty
from domain.core.finding import _choice as finding_choice
from domain.core.finding import _non_negative_int as finding_non_negative_int
from domain.core.finding import _positive_int as finding_positive_int
from domain.core.finding import _stable_id as finding_stable_id
from domain.core.finding import _strings as finding_strings
from domain.core.finding import _text as finding_text
from domain.core.research_objective import ObjectiveEvidence, PaperContribution
from domain.core.scientific_fact import (
    SCIENTIFIC_CONTEXT_SCOPES,
    SCIENTIFIC_RESULT_DIRECTIONS,
    ScientificAttribute,
    ScientificContext,
)
from domain.core.scientific_fact import _choice as scientific_choice
from domain.core.scientific_fact import _scientific_scalar as scientific_scalar
from domain.core.scientific_fact import _terms as scientific_terms
from domain.core.scientific_fact import _text as scientific_text
from domain.evaluation import FindingCuration, FindingFeedback
from repositories.finding_review_repository import (
    FindingReviewRepository,
    finding_curation_record,
    finding_feedback_from_record,
)
from repositories.objective_repository import ObjectiveRepository

DATASET_SCHEMA_VERSION = "objective_finding_dataset.v2"
TRAINING_SCHEMA_VERSION = "objective_finding_training.v2"
TRAINING_PROMPT_VERSION = "objective_finding_training_prompt.v2"
_FINDING_PAGE_SIZE = 200
_EVIDENCE_PAGE_SIZE = 500


class FindingFeedbackService:
    """Review and export published, versioned Objective Findings."""

    def __init__(
        self,
        *,
        review_repository: FindingReviewRepository,
        objective_repository: ObjectiveRepository,
        experiment_projection: ExperimentCompatibilityProjection | None = None,
    ) -> None:
        self.review_repository = review_repository
        self.objective_repository = objective_repository
        self.experiment_projection = experiment_projection

    async def record_feedback(
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
        await self._require_published_finding(
            collection_id,
            objective_id,
            analysis_version,
            finding_id,
        )
        created_at = _now_iso()
        feedback = finding_feedback_from_record(
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
        return await self.review_repository.upsert_feedback(feedback)

    async def list_feedback(
        self,
        *,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
    ) -> tuple[FindingFeedback, ...]:
        await self._require_published_finding(
            collection_id,
            objective_id,
            analysis_version,
            finding_id,
        )
        return await self.review_repository.list_feedback(
            collection_id,
            objective_id,
            analysis_version,
            finding_id,
        )

    async def record_curation(
        self,
        *,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
        curated_status: str,
        curated_finding: Finding,
        note: str | None = None,
        reviewer: str | None = None,
    ) -> FindingCuration:
        candidate = await self.validate_curation(
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=analysis_version,
            finding_id=finding_id,
            curated_finding=curated_finding,
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
        return await self.review_repository.upsert_curation(curation)

    async def validate_curation(
        self,
        *,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
        curated_finding: Finding,
    ) -> Finding:
        published = await self._require_published_finding(
            collection_id,
            objective_id,
            analysis_version,
            finding_id,
        )
        candidate = curated_finding
        if candidate.key != published.key:
            raise ValueError("curation cannot change the published Finding identity")
        if tuple(
            (item.document_id, item.analysis_status)
            for item in candidate.paper_contributions
        ) != tuple(
            (item.document_id, item.analysis_status)
            for item in published.paper_contributions
        ):
            raise ValueError("curation cannot change Objective paper coverage")

        evidence = await self._finding_evidence(published)
        candidate.validate_sources(
            evidence,
            await self._list_contributions(
                collection_id,
                objective_id,
                analysis_version,
            ),
        )
        return candidate

    async def list_curations(
        self,
        *,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
    ) -> tuple[FindingCuration, ...]:
        await self._require_published_finding(
            collection_id,
            objective_id,
            analysis_version,
            finding_id,
        )
        return await self.review_repository.list_curations(
            collection_id,
            objective_id,
            analysis_version,
            finding_id,
        )

    async def export_dataset(
        self,
        *,
        collection_id: str,
        objective_id: str,
        label_status: str | None = None,
        dataset_use_status: str | None = None,
    ) -> dict[str, Any]:
        objective = await self.objective_repository.read_objective(
            collection_id, objective_id
        )
        if objective is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        version = objective.published_analysis_version
        if version is None:
            raise ValueError("objective has no published analysis")
        return {
            "schema_version": DATASET_SCHEMA_VERSION,
            "collection_id": collection_id,
            "objective_id": objective_id,
            "items": await self._dataset_items(
                collection_id,
                objective_id,
                version,
                label_status=label_status,
                dataset_use_status=dataset_use_status,
            ),
            "warnings": [],
        }

    async def export_collection_dataset(
        self,
        *,
        collection_id: str,
        label_status: str | None = None,
        dataset_use_status: str | None = None,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for objective in await self.objective_repository.list_objectives(
            collection_id
        ):
            version = objective.published_analysis_version
            if version is None:
                continue
            items.extend(
                await self._dataset_items(
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

    async def export_gold_draft(
        self, *, collection_id: str
    ) -> dict[str, Any]:
        dataset = await self.export_collection_dataset(
            collection_id=collection_id,
            label_status="gold",
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
        self,
        *,
        collection_id: str,
        objective_id: str,
        source_findings: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    ) -> tuple[str, list[str]]:
        try:
            dataset = await self.export_dataset(
                collection_id=collection_id,
                objective_id=objective_id,
            )
        except (FileNotFoundError, ValueError):
            return "stale", ["source_dataset_unavailable"]
        items = dataset.get("items") if isinstance(dataset, Mapping) else None
        if not isinstance(items, list):
            return "stale", ["source_dataset_unavailable"]
        return _source_snapshot_validity(source_findings, items)

    async def _dataset_items(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        *,
        label_status: str | None,
        dataset_use_status: str | None,
    ) -> list[dict[str, Any]]:
        objective = await self.objective_repository.read_objective(
            collection_id, objective_id
        )
        assert objective is not None
        findings = await self._all_findings(
            collection_id, objective_id, analysis_version
        )
        result: list[dict[str, Any]] = []
        for finding in findings:
            evidence = await self._finding_evidence(finding)
            feedback = await self.review_repository.list_feedback(
                collection_id,
                objective_id,
                analysis_version,
                finding.finding_id,
            )
            curations = await self.review_repository.list_curations(
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

            system_prediction = finding_response(finding)
            expert_target = (
                finding_response(current_curation.curated_finding)
                if current_curation is not None
                else None
            )
            training_target = expert_target or system_prediction
            target_finding = (
                current_curation.curated_finding
                if current_curation is not None
                else finding
            )
            evidence_records = [objective_evidence_response(item) for item in evidence]
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
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[Finding, ...]:
        if await self._should_use_experiment_projection(
            collection_id, objective_id, analysis_version
        ):
            findings, _, _ = await self.experiment_projection.read_analysis_records(
                collection_id, objective_id, analysis_version
            )
            return findings
        result: list[Finding] = []
        offset = 0
        while True:
            page, total = await self.objective_repository.list_findings(
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

    async def _finding_evidence(
        self, finding: Finding
    ) -> tuple[ObjectiveEvidence, ...]:
        if await self._should_use_experiment_projection(
            finding.collection_id, finding.objective_id, finding.analysis_version
        ):
            _, evidence, _ = await self.experiment_projection.read_analysis_records(
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
            page, total = await self.objective_repository.list_evidence(
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
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
        finding_id: str,
    ) -> Finding:
        objective = await self.objective_repository.read_objective(
            collection_id, objective_id
        )
        if objective is None:
            raise FileNotFoundError(
                f"research objective not found: {collection_id}/{objective_id}"
            )
        if objective.published_analysis_version != analysis_version:
            raise ValueError("review must reference the published analysis version")
        if await self._should_use_experiment_projection(
            collection_id, objective_id, analysis_version
        ):
            findings, _, _ = await self.experiment_projection.read_analysis_records(
                collection_id, objective_id, analysis_version
            )
            finding = next(
                (item for item in findings if item.finding_id == finding_id), None
            )
        else:
            finding = await self.objective_repository.read_finding(
                collection_id,
                objective_id,
                analysis_version,
                finding_id,
            )
        if finding is None:
            raise ValueError("finding is not present in the published analysis")
        return finding

    async def _list_contributions(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> tuple[PaperContribution, ...]:
        if await self._should_use_experiment_projection(
            collection_id, objective_id, analysis_version
        ):
            _, _, contributions = (
                await self.experiment_projection.read_analysis_records(
                    collection_id, objective_id, analysis_version
                )
            )
            return contributions
        return await self.objective_repository.list_contributions(
            collection_id,
            objective_id,
            analysis_version,
        )

    async def _should_use_experiment_projection(
        self,
        collection_id: str,
        objective_id: str,
        analysis_version: int,
    ) -> bool:
        return await should_read_experiment_projection(
            objective_repository=self.objective_repository,
            experiment_projection=self.experiment_projection,
            collection_id=collection_id,
            objective_id=objective_id,
            analysis_version=analysis_version,
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
    dataset_items: list[Any],
) -> tuple[str, list[str]]:
    if not source_findings:
        return "stale", ["source_finding_snapshot_missing"]
    current_by_finding_id = {
        finding_id: item
        for item in dataset_items
        if isinstance(item, Mapping)
        and (finding_id := _text(item.get("finding_id")))
    }
    reasons: list[str] = []
    for source_finding in source_findings:
        finding_id = _text(source_finding.get("finding_id"))
        current = current_by_finding_id.get(finding_id)
        if current is None:
            reasons.append("source_finding_missing")
            continue
        if current.get("dataset_use_status") != "training_ready":
            reasons.append("source_finding_no_longer_reviewed")
            continue
        if _positive_int(current.get("analysis_version")) != _positive_int(
            source_finding.get("analysis_version")
        ):
            reasons.append("source_analysis_version_changed")
        if _text(current.get("finding_fingerprint")) != _text(
            source_finding.get("finding_fingerprint")
        ):
            reasons.append("source_finding_changed")
        if _text(current.get("evidence_fingerprint")) != _text(
            source_finding.get("evidence_fingerprint")
        ):
            reasons.append("source_evidence_changed")
        if _dataset_evidence_ids(current) != _strings(
            source_finding.get("evidence_ids")
        ):
            reasons.append("source_evidence_ids_changed")
    if reasons:
        return "stale", list(dict.fromkeys(reasons))
    return "current", []


def _dataset_evidence_ids(item: Mapping[str, Any]) -> tuple[str, ...]:
    return _strings(
        evidence.get("evidence_id")
        for evidence in item.get("evidence", [])
        if isinstance(evidence, Mapping)
    )


def _strings(values: Any) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or values is None:
        values = ()
    elif not isinstance(values, (list, tuple)):
        values = tuple(values)
    result: list[str] = []
    for value in values:
        text = _text(value)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _text(value: Any) -> str:
    return str(value or "").strip()


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
    record = objective_evidence_response(evidence)
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
    "FindingFeedbackService",
    "TRAINING_PROMPT_VERSION",
    "TRAINING_SCHEMA_VERSION",
]


def parse_curated_finding(payload: Mapping[str, Any]) -> Finding:
    """Parse the complete canonical Finding submitted for expert review."""
    candidate = Finding(
        collection_id=finding_text(payload.get("collection_id")) or "",
        objective_id=finding_text(payload.get("objective_id")) or "",
        analysis_version=finding_positive_int(payload.get("analysis_version")),
        finding_id=finding_text(payload.get("finding_id"))
        or finding_stable_id(
            "finding",
            payload.get("objective_id"),
            payload.get("analysis_version"),
            finding_strings(payload.get("factors")),
            finding_text(payload.get("outcome")) or "",
            payload.get("supporting_evidence_ids"),
        ),
        statement=finding_text(payload.get("statement")) or "",
        factors=finding_strings(payload.get("factors")),
        outcome=finding_text(payload.get("outcome")) or "",
        direction=finding_choice(
            payload.get("direction"), SCIENTIFIC_RESULT_DIRECTIONS, "unknown"
        ),
        assertion_strength=finding_choice(
            payload.get("assertion_strength"),
            FINDING_ASSERTION_STRENGTHS,
            "descriptive",
        ),
        attribution_scope=finding_choice(
            payload.get("attribution_scope"),
            EVIDENCE_ATTRIBUTION_SCOPES - {"not_attributable"},
            "descriptive_only",
        ),
        synthesis_status=finding_choice(
            payload.get("synthesis_status"),
            FINDING_SYNTHESIS_STATUSES,
            "insufficient_confirmation",
        ),
        certainty=finding_certainty(payload.get("certainty")),
        display_rank=finding_non_negative_int(payload.get("display_rank")),
        mechanisms=tuple(
            (
                FindingMechanismRelation(
                    source_term=finding_text(item.get("source_term")) or "",
                    relation_type=finding_text(item.get("relation_type")) or "",
                    target_term=finding_text(item.get("target_term")) or "",
                    direction=finding_text(item.get("direction")),
                    assertion_strength=finding_choice(
                        item.get("assertion_strength"),
                        FINDING_ASSERTION_STRENGTHS,
                        "descriptive",
                    ),
                    supporting_evidence_ids=finding_strings(
                        item.get("supporting_evidence_ids")
                    ),
                )
                for item in tuple(
                    (
                        dict(item)
                        for item in (
                            payload.get("mechanisms")
                            if isinstance(payload.get("mechanisms"), (list, tuple))
                            else ()
                        )
                        if isinstance(item, Mapping)
                    )
                )
            )
        ),
        scientific_context=_review_scientific_context(
            payload.get("scientific_context")
        ),
        limitations=finding_strings(payload.get("limitations")),
        paper_contributions=tuple(
            (
                FindingPaperContribution(
                    document_id=finding_text(item.get("document_id")) or "",
                    analysis_status=finding_choice(
                        item.get("analysis_status"),
                        PAPER_CONTRIBUTION_STATUSES,
                        "pending",
                    ),
                    supporting_evidence_ids=finding_strings(
                        item.get("supporting_evidence_ids")
                    ),
                    contradicting_evidence_ids=finding_strings(
                        item.get("contradicting_evidence_ids")
                    ),
                    context_evidence_ids=finding_strings(
                        item.get("context_evidence_ids")
                    ),
                    condition_boundary_evidence_ids=finding_strings(
                        item.get("condition_boundary_evidence_ids")
                    ),
                )
                for item in tuple(
                    (
                        dict(item)
                        for item in (
                            payload.get("paper_contributions")
                            if isinstance(
                                payload.get("paper_contributions"), (list, tuple)
                            )
                            else ()
                        )
                        if isinstance(item, Mapping)
                    )
                )
            )
        ),
        origin=finding_choice(
            payload.get("origin"), FINDING_ORIGINS, "system_generated"
        ),
        source_analysis_version=finding_positive_int(
            payload.get("source_analysis_version")
        )
        or None,
        parent_finding_id=finding_text(payload.get("parent_finding_id")),
        created_by_user_id=finding_text(payload.get("created_by_user_id")),
        created_by_tool_call_id=finding_text(payload.get("created_by_tool_call_id")),
        created_at=_finding_creation_time(payload.get("created_at")),
        warnings=finding_strings(payload.get("warnings")),
        selection_ids=finding_strings(payload.get("selection_ids")),
        comparison_group_ids=finding_strings(payload.get("comparison_group_ids")),
    )
    canonical = finding_response(candidate)
    if canonical != dict(payload):
        missing = sorted(set(canonical) - set(payload))
        unexpected = sorted(set(payload) - set(canonical))
        details = []
        if missing:
            details.append("missing keys: " + ", ".join(missing[:8]))
        if unexpected:
            details.append("unexpected keys: " + ", ".join(unexpected[:8]))
        details.append("preserve canonical value types and field names")
        raise ValueError(
            "curated_finding must use the complete canonical Finding contract; "
            + "; ".join(details)
        )
    return candidate


def _context_attributes(records: Any) -> tuple[ScientificAttribute, ...]:
    return tuple(
        ScientificAttribute(
            name=scientific_text(item.get("name")) or "",
            value=(
                scientific_scalar(item.get("value"))
                if scientific_scalar(item.get("value")) is not None
                else ""
            ),
            unit=scientific_text(item.get("unit")),
            context_scope=scientific_choice(
                item.get("context_scope"), SCIENTIFIC_CONTEXT_SCOPES, "unknown"
            ),
            applies_to_outcomes=scientific_terms(item.get("applies_to_outcomes")),
        )
        for item in (records if isinstance(records, (list, tuple)) else ())
        if isinstance(item, Mapping)
    )


def _review_scientific_context(value: Any) -> ScientificContext:
    if not isinstance(value, Mapping):
        return ScientificContext()
    return ScientificContext(
        material=_context_attributes(value.get("material")),
        sample=_context_attributes(value.get("sample")),
        process=_context_attributes(value.get("process")),
        test=_context_attributes(value.get("test")),
    )


def _finding_creation_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = (str(value).strip() or None) if value is not None else None
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid Finding creation time") from exc
