from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from hashlib import sha1
from typing import Any, Mapping

from application.core.objectives import property_matching
from application.core.objectives.extraction import ObjectiveExtractor
from domain.core import (
    Finding,
    FindingPaperContribution,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
    ResearchObjective,
    directions_contradict,
)


_MAX_CONTEXT_EVIDENCE_PER_SET = 8
_MAX_RESULT_EVIDENCE_REPRESENTATIVES = 16
_MAX_EXCERPT_CHARS = 320
_CONTEXT_ROLES = {
    "condition_context",
    "mechanism_context",
    "baseline_context",
    "comparison_context",
}
_DIRECTION_PRIORITY = (
    "increase",
    "decrease",
    "improve",
    "worsen",
    "no_change",
    "mixed",
)
logger = logging.getLogger(__name__)
_J_PER_CUBIC_MM_RE = re.compile(
    r"\bj\s*/\s*mm\s*(?:\^\s*)?(?:3|\u00b3)\b",
    re.IGNORECASE,
)


class FindingSynthesisService:
    """Synthesize one-outcome, source-backed Findings for an analysis version."""

    def __init__(self, finding_extractor: Any | None = None) -> None:
        self.finding_extractor = finding_extractor or ObjectiveExtractor()

    def synthesize(
        self,
        *,
        collection_id: str,
        objective: ResearchObjective,
        analysis: ObjectiveAnalysis,
        contributions: tuple[PaperContribution, ...],
        evidence_records: tuple[ObjectiveEvidence, ...],
    ) -> tuple[Finding, ...]:
        self._validate_scope(
            collection_id=collection_id,
            objective=objective,
            analysis=analysis,
            contributions=contributions,
            evidence_records=evidence_records,
        )
        result_sets = self._result_sets(objective, evidence_records)
        if not result_sets:
            eligible_evidence = tuple(
                evidence
                for evidence in evidence_records
                if self._eligible_result_evidence(evidence)
            )
            logger.warning(
                "Finding synthesis found no in-scope result sets "
                "objective_variables=%s objective_outcomes=%s "
                "eligible_result_count=%s eligible_axes=%s",
                objective.variables,
                objective.outcomes,
                len(eligible_evidence),
                sorted(
                    {
                        (
                            tuple(
                                variable.name
                                for variable in evidence.changed_variables
                            ),
                            evidence.reported_result.outcome,
                        )
                        for evidence in eligible_evidence
                        if evidence.reported_result is not None
                    }
                )[:12],
            )
            return ()
        evidence_by_id = {
            evidence.evidence_id: evidence for evidence in evidence_records
        }
        contribution_payloads = [
            self._contribution_payload(contribution)
            for contribution in contributions
        ]
        objective_payload = {
            "objective_id": objective.objective_id,
            "question": objective.question,
            "material_scope": list(objective.material_scope),
            "variables": list(objective.variables),
            "outcomes": list(objective.outcomes),
            "mechanisms": list(objective.mechanisms),
            "constraints": list(objective.constraints),
            "requested_comparator": objective.requested_comparator,
        }
        findings: list[Finding] = []
        for result_set in result_sets:
            result_documents = {
                str(item["document_id"])
                for item in _mapping_list(result_set.get("result_evidence"))
            }
            context_evidence = self._context_evidence_for_documents(
                evidence_records,
                result_documents,
            )
            expected_result_set_id = str(result_set["result_set_id"])
            synthesis_payload = {
                "objective": objective_payload,
                "paper_contributions": contribution_payloads,
                "result_set": self._result_set_prompt_payload(result_set),
                "context_evidence": [
                    self._evidence_payload(evidence) for evidence in context_evidence
                ],
            }
            candidate_rejection: dict[str, Any] | None = None
            for semantic_attempt in range(2):
                request_payload = dict(synthesis_payload)
                if candidate_rejection is not None:
                    request_payload["candidate_rejection"] = candidate_rejection
                try:
                    parsed = self.finding_extractor.synthesize_findings(
                        request_payload
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Finding synthesis failed result_set_id=%s semantic_attempt=%s",
                        expected_result_set_id,
                        semantic_attempt + 1,
                    )
                    break
                parsed_record = (
                    parsed.model_dump()
                    if hasattr(parsed, "model_dump")
                    else dict(parsed)
                )
                candidates = _mapping_list(parsed_record.get("findings"))
                if not candidates:
                    logger.warning(
                        "Finding synthesis returned no candidate result_set_id=%s "
                        "factors=%s outcome=%s result_evidence=%s",
                        expected_result_set_id,
                        _strings(result_set.get("factors")),
                        _text(result_set.get("outcome")),
                        [
                            {
                                "evidence_id": _text(item.get("evidence_id")),
                                "document_id": _text(item.get("document_id")),
                                "direction": _text(
                                    (
                                        item.get("reported_result")
                                        if isinstance(
                                            item.get("reported_result"), Mapping
                                        )
                                        else {}
                                    ).get("direction")
                                ),
                                "attribution_scope": _text(
                                    item.get("attribution_scope")
                                ),
                            }
                            for item in _mapping_list(
                                result_set.get("result_evidence")
                            )
                        ],
                    )
                    break
                candidate = candidates[0]
                logger.debug(
                    "Inspecting Finding synthesis candidate result_set_id=%s "
                    "result_evidence_count=%s assertion_strength=%s factors=%s "
                    "outcome=%s",
                    expected_result_set_id,
                    len(_mapping_list(result_set.get("result_evidence"))),
                    _text(candidate.get("assertion_strength")),
                    _strings(result_set.get("factors")),
                    _text(result_set.get("outcome")),
                )
                try:
                    finding = self._finding_from_candidate(
                        collection_id=collection_id,
                        objective=objective,
                        analysis=analysis,
                        candidate=candidate,
                        result_set=result_set,
                        context_evidence=context_evidence,
                        contributions=contributions,
                        evidence_by_id=evidence_by_id,
                        display_rank=len(findings),
                    )
                except ValueError as exc:
                    rejection_reason = str(exc)
                    logger.warning(
                        "Rejected Finding candidate result_set_id=%s reason=%s "
                        "semantic_repair_attempted=%s",
                        expected_result_set_id,
                        rejection_reason,
                        semantic_attempt > 0,
                    )
                    if semantic_attempt == 0:
                        candidate_rejection = {
                            "reason": rejection_reason,
                            "previous_candidate": candidate,
                        }
                        continue
                    break
                findings.append(finding)
                break
        return tuple(findings)

    @staticmethod
    def _validate_scope(
        *,
        collection_id: str,
        objective: ResearchObjective,
        analysis: ObjectiveAnalysis,
        contributions: tuple[PaperContribution, ...],
        evidence_records: tuple[ObjectiveEvidence, ...],
    ) -> None:
        expected = (collection_id, objective.objective_id, analysis.analysis_version)
        if (
            analysis.collection_id,
            analysis.objective_id,
            analysis.analysis_version,
        ) != expected:
            raise ValueError("analysis does not belong to the requested objective")
        if objective.collection_id != collection_id:
            raise ValueError("objective belongs to another collection")
        for record in (*contributions, *evidence_records):
            actual = (
                record.collection_id,
                record.objective_id,
                record.analysis_version,
            )
            if actual != expected:
                raise ValueError("analysis child belongs to another objective version")
        contribution_documents = {item.document_id for item in contributions}
        evidence_documents = {item.document_id for item in evidence_records}
        if not evidence_documents <= contribution_documents:
            raise ValueError("Objective Evidence lacks a PaperContribution")

    def _result_sets(
        self,
        objective: ResearchObjective,
        evidence_records: tuple[ObjectiveEvidence, ...],
    ) -> tuple[dict[str, Any], ...]:
        grouped: dict[tuple[tuple[str, ...], str], list[ObjectiveEvidence]] = (
            defaultdict(list)
        )
        factor_labels: dict[tuple[str, ...], tuple[str, ...]] = {}
        outcome_labels: dict[str, str] = {}
        for evidence in evidence_records:
            if not self.is_comparable_result_evidence(objective, evidence):
                continue
            factors = tuple(
                sorted(
                    (
                        self._canonical_objective_axis(
                            item.name,
                            objective.variables,
                        )
                        for item in evidence.changed_variables
                    ),
                    key=lambda value: _normalize_term(value),
                )
            )
            factor_key = tuple(property_matching.axis_key(value) for value in factors)
            outcome = self._canonical_objective_axis(
                evidence.reported_result.outcome,
                objective.outcomes,
            )
            outcome_key = property_matching.axis_key(outcome)
            grouped[(factor_key, outcome_key)].append(evidence)
            factor_labels.setdefault(
                factor_key,
                tuple(_normalize_scientific_typography(value) for value in factors),
            )
            outcome_labels.setdefault(outcome_key, outcome)

        result_sets: list[dict[str, Any]] = []
        for factor_key, outcome_key in sorted(grouped):
            factors = factor_labels[factor_key]
            outcome = outcome_labels[outcome_key]
            for primary_direction, evidence_items in self._direction_result_groups(
                tuple(grouped[(factor_key, outcome_key)])
            ):
                result_sets.append(
                    {
                        "result_set_id": self._result_set_id(
                            factors,
                            outcome,
                            primary_direction,
                        ),
                        "factors": list(factors),
                        "outcome": outcome,
                        "primary_direction": primary_direction,
                        "result_evidence": [
                            self._evidence_payload(evidence)
                            for evidence in evidence_items
                        ],
                    }
                )
        return tuple(result_sets)

    @staticmethod
    def _direction_result_groups(
        evidence_items: tuple[ObjectiveEvidence, ...],
    ) -> tuple[tuple[str, tuple[ObjectiveEvidence, ...]], ...]:
        by_direction: dict[str, list[ObjectiveEvidence]] = defaultdict(list)
        for evidence in evidence_items:
            assert evidence.reported_result is not None
            by_direction[evidence.reported_result.direction].append(evidence)

        priority = {
            direction: position
            for position, direction in enumerate(_DIRECTION_PRIORITY)
        }
        groups: list[tuple[str, tuple[ObjectiveEvidence, ...]]] = []
        remaining = set(by_direction)
        while remaining:
            primary_direction = min(
                remaining,
                key=lambda direction: (
                    -len(
                        {
                            evidence.document_id
                            for evidence in by_direction[direction]
                        }
                    ),
                    -len(by_direction[direction]),
                    -max(
                        evidence.confidence
                        for evidence in by_direction[direction]
                    ),
                    priority.get(direction, len(priority)),
                    direction,
                ),
            )
            grouped_directions = {
                direction
                for direction in remaining
                if direction == primary_direction
                or directions_contradict(primary_direction, direction)
            }
            grouped_evidence = tuple(
                sorted(
                    (
                        evidence
                        for direction in grouped_directions
                        for evidence in by_direction[direction]
                    ),
                    key=lambda item: (
                        -item.confidence,
                        item.document_id,
                        item.evidence_id,
                    ),
                )
            )
            groups.append((primary_direction, grouped_evidence))
            remaining -= grouped_directions
        return tuple(groups)

    @staticmethod
    def _canonical_objective_axis(
        value: str,
        objective_axes: tuple[str, ...],
    ) -> str:
        resolved = property_matching.resolve_objective_axis(value, objective_axes)
        if resolved is not None:
            return resolved
        return _normalize_scientific_typography(value)

    @staticmethod
    def _result_set_prompt_payload(
        result_set: Mapping[str, Any],
    ) -> dict[str, Any]:
        result_evidence = _mapping_list(result_set.get("result_evidence"))
        representatives = FindingSynthesisService._document_balanced_evidence(
            result_evidence,
            limit=_MAX_RESULT_EVIDENCE_REPRESENTATIVES,
        )
        is_condition_series = FindingSynthesisService._result_set_is_condition_series(
            result_set
        )
        compact_evidence: list[dict[str, Any]] = []
        for item in representatives:
            if not is_condition_series and len(result_evidence) == 1:
                compact_evidence.append(dict(item))
                continue
            reported_result = (
                item.get("reported_result")
                if isinstance(item.get("reported_result"), Mapping)
                else {}
            )
            compact_evidence.append(
                {
                    "evidence_id": item.get("evidence_id"),
                    "document_id": item.get("document_id"),
                    "changed_variables": item.get("changed_variables") or [],
                    "reported_result": {
                        "outcome": reported_result.get("outcome"),
                        "value": reported_result.get("value"),
                        "unit": reported_result.get("unit"),
                        "direction": reported_result.get("direction"),
                    },
                    "attribution_scope": item.get("attribution_scope"),
                }
            )
        evidence_by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in result_evidence:
            evidence_by_document[str(item.get("document_id") or "")].append(item)
        document_summaries: list[dict[str, Any]] = []
        for document_id, items in sorted(evidence_by_document.items()):
            direction_counts: dict[str, int] = defaultdict(int)
            attribution_scope_counts: dict[str, int] = defaultdict(int)
            for item in items:
                result = (
                    item.get("reported_result")
                    if isinstance(item.get("reported_result"), Mapping)
                    else {}
                )
                direction = str(result.get("direction") or "").strip()
                if direction:
                    direction_counts[direction] += 1
                attribution_scope = str(item.get("attribution_scope") or "").strip()
                if attribution_scope:
                    attribution_scope_counts[attribution_scope] += 1
            document_summaries.append(
                {
                    "document_id": document_id,
                    "evidence_count": len(items),
                    "direction_counts": dict(sorted(direction_counts.items())),
                    "attribution_scope_counts": dict(
                        sorted(attribution_scope_counts.items())
                    ),
                }
            )
        return {
            "factors": result_set.get("factors") or [],
            "outcome": result_set.get("outcome"),
            "primary_direction": result_set.get("primary_direction"),
            "total_evidence_count": len(result_evidence),
            "is_condition_series": is_condition_series,
            "result_evidence": compact_evidence,
            "document_evidence_summaries": document_summaries,
        }

    @staticmethod
    def _document_balanced_evidence(
        evidence_items: list[dict[str, Any]],
        *,
        limit: int,
    ) -> tuple[dict[str, Any], ...]:
        by_document_and_direction: dict[
            str,
            dict[str, list[dict[str, Any]]],
        ] = defaultdict(lambda: defaultdict(list))
        for item in evidence_items:
            result = (
                item.get("reported_result")
                if isinstance(item.get("reported_result"), Mapping)
                else {}
            )
            by_document_and_direction[str(item.get("document_id") or "")][
                str(result.get("direction") or "")
            ].append(item)

        document_sequences: list[list[dict[str, Any]]] = []
        for document_id in sorted(by_document_and_direction):
            direction_groups = by_document_and_direction[document_id]
            for items in direction_groups.values():
                items.sort(
                    key=lambda item: (
                        -float(item.get("confidence") or 0.0),
                        str(item.get("evidence_id") or ""),
                    )
                )
            direction_names = sorted(direction_groups)
            sequence = [
                direction_groups[direction][position]
                for position in range(
                    max(
                        (len(direction_groups[name]) for name in direction_names),
                        default=0,
                    )
                )
                for direction in direction_names
                if position < len(direction_groups[direction])
            ]
            document_sequences.append(sequence)

        return tuple(
            sequence[position]
            for position in range(
                max((len(sequence) for sequence in document_sequences), default=0)
            )
            for sequence in document_sequences
            if position < len(sequence)
        )[:limit]

    @staticmethod
    def _result_set_is_condition_series(result_set: Mapping[str, Any]) -> bool:
        interval_signatures = {
            tuple(
                sorted(
                    (
                        _normalize_term(variable.get("name")),
                        _scalar_key(variable.get("baseline_value")),
                        _scalar_key(variable.get("target_value")),
                        _normalize_term(variable.get("unit")),
                    )
                    for variable in _mapping_list(item.get("changed_variables"))
                )
            )
            for item in _mapping_list(result_set.get("result_evidence"))
        }
        return len(interval_signatures) > 1

    @staticmethod
    def _eligible_result_evidence(evidence: ObjectiveEvidence) -> bool:
        return bool(
            evidence.supports_finding
            and evidence.evidence_role in {"direct_result", "contradictory_result"}
            and evidence.reported_result is not None
            and evidence.reported_result.direction != "unknown"
            and evidence.changed_variables
            and evidence.attribution_scope != "not_attributable"
        )

    @classmethod
    def is_comparable_result_evidence(
        cls,
        objective: ResearchObjective,
        evidence: ObjectiveEvidence,
    ) -> bool:
        if not cls._eligible_result_evidence(evidence):
            return False
        assert evidence.reported_result is not None
        return cls._within_objective_scope(
            factors=tuple(item.name for item in evidence.changed_variables),
            outcome=evidence.reported_result.outcome,
            objective=objective,
        )

    @staticmethod
    def _within_objective_scope(
        *,
        factors: tuple[str, ...],
        outcome: str,
        objective: ResearchObjective,
    ) -> bool:
        return bool(
            factors
            and any(
                _axis_matches(factor, objective_factor)
                for factor in factors
                for objective_factor in objective.variables
            )
            and any(
                _axis_matches(outcome, objective_outcome)
                for objective_outcome in objective.outcomes
            )
        )

    @staticmethod
    def _context_evidence_for_documents(
        evidence_records: tuple[ObjectiveEvidence, ...],
        document_ids: set[str],
    ) -> tuple[ObjectiveEvidence, ...]:
        candidates = tuple(
            sorted(
                (
                    evidence
                    for evidence in evidence_records
                    if evidence.document_id in document_ids
                    and evidence.supports_finding
                    and evidence.evidence_role in _CONTEXT_ROLES
                ),
                key=lambda item: (-item.confidence, item.document_id, item.evidence_id),
            )
        )
        selected: list[ObjectiveEvidence] = []
        seen_documents: set[str] = set()
        selected_ids: set[str] = set()
        for evidence in candidates:
            if evidence.document_id in seen_documents:
                continue
            selected.append(evidence)
            selected_ids.add(evidence.evidence_id)
            seen_documents.add(evidence.document_id)
            if len(selected) >= _MAX_CONTEXT_EVIDENCE_PER_SET:
                return tuple(selected)
        for evidence in candidates:
            if evidence.evidence_id in selected_ids:
                continue
            selected.append(evidence)
            if len(selected) >= _MAX_CONTEXT_EVIDENCE_PER_SET:
                break
        return tuple(selected)

    def _finding_from_candidate(
        self,
        *,
        collection_id: str,
        objective: ResearchObjective,
        analysis: ObjectiveAnalysis,
        candidate: Mapping[str, Any],
        result_set: Mapping[str, Any],
        context_evidence: tuple[ObjectiveEvidence, ...],
        contributions: tuple[PaperContribution, ...],
        evidence_by_id: Mapping[str, ObjectiveEvidence],
        display_rank: int,
    ) -> Finding:
        result_ids = tuple(
            evidence_id
            for item in _mapping_list(result_set.get("result_evidence"))
            if (evidence_id := _text(item.get("evidence_id")))
        )
        direction = _text(result_set.get("primary_direction")) or "unknown"
        if not result_ids or any(
            evidence_by_id[evidence_id].reported_result is None
            for evidence_id in result_ids
        ):
            raise ValueError("result set lacks complete reported-result Evidence")
        supporting_ids = tuple(
            evidence_id
            for evidence_id in result_ids
            if evidence_by_id[evidence_id].reported_result.direction == direction
        )
        contradicting_ids = tuple(
            evidence_id
            for evidence_id in result_ids
            if directions_contradict(
                direction,
                evidence_by_id[evidence_id].reported_result.direction,
            )
        )
        classified_ids = {*supporting_ids, *contradicting_ids}
        if classified_ids != set(result_ids):
            raise ValueError(
                "result set contains a direction that is neither support nor an "
                "explicit contradiction"
            )
        if not supporting_ids:
            raise ValueError(
                f"candidate direction {direction} has no supporting result Evidence"
            )
        if any(
            evidence_by_id[evidence_id].evidence_role
            not in {"direct_result", "contradictory_result"}
            for evidence_id in (*supporting_ids, *contradicting_ids)
        ):
            raise ValueError("candidate references non-result Evidence as direct support")

        allowed_context_ids = {item.evidence_id for item in context_evidence}
        context_ids = self._candidate_evidence_ids(candidate, "context_evidence_ids")
        if context_ids is None:
            raise ValueError("candidate context_evidence_ids are malformed")
        if not set(context_ids) <= allowed_context_ids:
            raise ValueError("candidate references unavailable context Evidence")
        mechanisms: list[dict[str, Any]] = []
        mechanism_ids: list[str] = []
        for mechanism in _mapping_list(candidate.get("mechanisms")):
            ids = self._candidate_evidence_ids(
                mechanism, "supporting_evidence_ids"
            )
            if not ids:
                continue
            if not set(ids) <= allowed_context_ids:
                continue
            if any(
                evidence_by_id[evidence_id].evidence_role != "mechanism_context"
                for evidence_id in ids
            ):
                continue
            mechanisms.append(mechanism)
            mechanism_ids.extend(ids)
        context_ids = tuple(dict.fromkeys((*context_ids, *mechanism_ids)))

        factors = _strings(result_set.get("factors"))
        outcome = _text(result_set.get("outcome"))
        if not factors or not outcome:
            raise ValueError("result set lacks factors or outcome")
        supporting_evidence = tuple(
            evidence_by_id[evidence_id] for evidence_id in supporting_ids
        )
        contradicting_evidence = tuple(
            evidence_by_id[evidence_id] for evidence_id in contradicting_ids
        )
        expected_direction = self._direction_for(supporting_evidence)
        if expected_direction is None or direction != expected_direction:
            raise ValueError(
                "backend primary direction does not match one consistent supporting "
                "Evidence direction"
            )
        statement = self._finding_statement(
            factors=factors,
            outcome=outcome,
            direction=direction,
            contradicting_evidence=contradicting_evidence,
        )
        boundary_ids = self._condition_boundary_evidence_ids(
            supporting_evidence,
            contradicting_evidence,
        )

        paper_bindings = self._paper_bindings(
            contributions=contributions,
            supporting_ids=supporting_ids,
            contradicting_ids=contradicting_ids,
            context_ids=context_ids,
            boundary_ids=boundary_ids,
            evidence_by_id=evidence_by_id,
        )
        synthesis_status = Finding.synthesis_status_for(paper_bindings)
        attribution_scope = Finding.attribution_scope_for(
            factors, supporting_evidence
        )
        assertion_strength = _text(candidate.get("assertion_strength")) or (
            "descriptive"
        )
        if assertion_strength == "causal" and attribution_scope != "isolated_effect":
            raise ValueError(
                "candidate causal assertion lacks isolated-effect attribution"
            )
        if assertion_strength == "causal" and any(
            evidence.source_kind != "table"
            or evidence.selection_reason
            != "Deterministic comparison of rows from the same result table."
            or evidence.comparison is None
            or not evidence.comparison.comparable
            or len(evidence.changed_variables) != 1
            or len(
                {
                    ref.get("row_index")
                    for ref in evidence.related_source_refs
                    if isinstance(ref.get("row_index"), int)
                }
            )
            < 2
            for evidence in supporting_evidence
        ):
            assertion_strength = "associative"
        if attribution_scope == "descriptive_only" and assertion_strength != (
            "descriptive"
        ):
            raise ValueError(
                "candidate assertion strength exceeds descriptive-only attribution"
            )
        direct_evidence = supporting_evidence + contradicting_evidence
        certainty = Finding.certainty_for(synthesis_status, direct_evidence)
        limitations = self._limitations(
            factors=factors,
            synthesis_status=synthesis_status,
            attribution_scope=attribution_scope,
            supporting_evidence=supporting_evidence,
            contradicting_evidence=contradicting_evidence,
        )
        finding_id = self._finding_id(
            objective_id=objective.objective_id,
            analysis_version=analysis.analysis_version,
            factors=factors,
            outcome=outcome,
            supporting_ids=supporting_ids,
            contradicting_ids=contradicting_ids,
        )
        try:
            finding = Finding.from_mapping(
                {
                    "collection_id": collection_id,
                    "objective_id": objective.objective_id,
                    "analysis_version": analysis.analysis_version,
                    "finding_id": finding_id,
                    "statement": statement,
                    "factors": factors,
                    "outcome": outcome,
                    "direction": direction,
                    "assertion_strength": assertion_strength,
                    "attribution_scope": attribution_scope,
                    "synthesis_status": synthesis_status,
                    "certainty": certainty,
                    "display_rank": display_rank,
                    "mechanisms": mechanisms,
                    "scientific_context": Finding.common_scientific_context_for(
                        supporting_evidence
                    ).to_record(),
                    "limitations": limitations,
                    "paper_contributions": [
                        item.to_record() for item in paper_bindings
                    ],
                }
            )
            finding.validate_sources(tuple(evidence_by_id.values()), contributions)
        except ValueError as exc:
            raise ValueError(f"candidate violates the Finding contract: {exc}") from exc
        return finding

    @staticmethod
    def _finding_statement(
        *,
        factors: tuple[str, ...],
        outcome: str,
        direction: str,
        contradicting_evidence: tuple[ObjectiveEvidence, ...],
    ) -> str:
        factor_phrase = (
            factors[0]
            if len(factors) == 1
            else f"{', '.join(factors[:-1])} and {factors[-1]}"
        )
        subject = (
            f"Changes in {factor_phrase}"
            if len(factors) == 1
            else f"Joint changes in {factor_phrase}"
        )
        direction_phrases = {
            "increase": "an increase",
            "decrease": "a decrease",
            "improve": "an improvement",
            "worsen": "a worsening",
            "no_change": "no reported change",
            "mixed": "a source-reported mixed change",
        }
        primary_phrase = direction_phrases[direction]
        if not contradicting_evidence:
            return f"{subject} were associated with {primary_phrase} in {outcome}."

        opposing_directions = tuple(
            dict.fromkeys(
                evidence.reported_result.direction
                for evidence in contradicting_evidence
                if evidence.reported_result is not None
            )
        )
        opposing_phrases = " and ".join(
            direction_phrases[item] for item in opposing_directions
        )
        return (
            f"Across the reported comparisons, {subject[:1].lower() + subject[1:]} "
            "showed opposing "
            f"directions in {outcome}: {primary_phrase} versus {opposing_phrases}."
        )

    @staticmethod
    def _candidate_evidence_ids(
        candidate: Mapping[str, Any], field: str
    ) -> tuple[str, ...] | None:
        raw_ids = candidate.get(field, ())
        if not isinstance(raw_ids, (list, tuple)):
            return None
        values: list[str] = []
        for raw_id in raw_ids:
            if not isinstance(raw_id, str) or not raw_id.strip():
                return None
            evidence_id = raw_id.strip()
            if evidence_id in values:
                return None
            values.append(evidence_id)
        return tuple(values)

    @staticmethod
    def _direction_for(
        supporting_evidence: tuple[ObjectiveEvidence, ...],
    ) -> str | None:
        directions = {
            evidence.reported_result.direction
            for evidence in supporting_evidence
            if evidence.reported_result is not None
        }
        return next(iter(directions)) if len(directions) == 1 else None

    @staticmethod
    def _condition_boundary_evidence_ids(
        supporting_evidence: tuple[ObjectiveEvidence, ...],
        contradicting_evidence: tuple[ObjectiveEvidence, ...],
    ) -> tuple[str, ...]:
        supporting_documents = {item.document_id for item in supporting_evidence}
        contradicting_documents = {item.document_id for item in contradicting_evidence}
        if (
            not supporting_documents
            or not contradicting_documents
            or not supporting_documents.isdisjoint(contradicting_documents)
        ):
            return ()

        def context_values(
            evidence: tuple[ObjectiveEvidence, ...],
        ) -> dict[tuple[str, str, str], set[str]]:
            values: dict[tuple[str, str, str], set[str]] = defaultdict(set)
            for item in evidence:
                for section in ("material", "sample", "process", "test"):
                    for attribute in getattr(item.scientific_context, section):
                        values[
                            (
                                section,
                                _normalize_term(attribute.name),
                                _normalize_term(attribute.unit),
                            )
                        ].add(_scalar_key(attribute.value))
            return values

        supporting_values = context_values(supporting_evidence)
        contradicting_values = context_values(contradicting_evidence)
        boundary_keys = {
            key
            for key in set(supporting_values) & set(contradicting_values)
            if supporting_values[key]
            and contradicting_values[key]
            and supporting_values[key].isdisjoint(contradicting_values[key])
        }
        if not boundary_keys:
            return ()
        return tuple(
            item.evidence_id
            for item in (*supporting_evidence, *contradicting_evidence)
            if any(
                (
                    section,
                    _normalize_term(attribute.name),
                    _normalize_term(attribute.unit),
                )
                in boundary_keys
                for section in ("material", "sample", "process", "test")
                for attribute in getattr(item.scientific_context, section)
            )
        )

    @staticmethod
    def _paper_bindings(
        *,
        contributions: tuple[PaperContribution, ...],
        supporting_ids: tuple[str, ...],
        contradicting_ids: tuple[str, ...],
        context_ids: tuple[str, ...],
        boundary_ids: tuple[str, ...],
        evidence_by_id: Mapping[str, ObjectiveEvidence],
    ) -> tuple[FindingPaperContribution, ...]:
        def ids_for(document_id: str, values: tuple[str, ...]) -> tuple[str, ...]:
            return tuple(
                value
                for value in values
                if evidence_by_id[value].document_id == document_id
            )

        return tuple(
            FindingPaperContribution(
                document_id=contribution.document_id,
                analysis_status=contribution.analysis_status,
                supporting_evidence_ids=ids_for(
                    contribution.document_id, supporting_ids
                ),
                contradicting_evidence_ids=ids_for(
                    contribution.document_id, contradicting_ids
                ),
                context_evidence_ids=ids_for(contribution.document_id, context_ids),
                condition_boundary_evidence_ids=ids_for(
                    contribution.document_id, boundary_ids
                ),
            )
            for contribution in contributions
        )

    @staticmethod
    def _limitations(
        *,
        factors: tuple[str, ...],
        synthesis_status: str,
        attribution_scope: str,
        supporting_evidence: tuple[ObjectiveEvidence, ...],
        contradicting_evidence: tuple[ObjectiveEvidence, ...],
    ) -> tuple[str, ...]:
        deterministic: list[str] = []
        if len(factors) > 1:
            deterministic.append(
                "The reported comparison changes the complete factor set; "
                "individual-factor effects are not identifiable."
            )
        if synthesis_status == "insufficient_confirmation":
            deterministic.append(
                "Cross-paper confirmation is absent for this atomic result."
            )
        if synthesis_status == "conflict":
            deterministic.append(
                "Comparable direct results report opposing directions."
            )
        if synthesis_status == "condition_dependent":
            deterministic.append(
                "The reported relationship changes across an explicit condition boundary."
            )
        if contradicting_evidence and (
            {item.document_id for item in supporting_evidence}
            & {item.document_id for item in contradicting_evidence}
        ):
            deterministic.append(
                "Within-paper condition comparisons report opposing directions."
            )
        if attribution_scope == "association_only":
            deterministic.append(
                "The available evidence supports association, not isolated causation."
            )
        return _strings(deterministic)

    @staticmethod
    def _contribution_payload(contribution: PaperContribution) -> dict[str, Any]:
        return {
            "document_id": contribution.document_id,
            "analysis_status": contribution.analysis_status,
            "relevance": contribution.relevance,
            "paper_role": contribution.paper_role,
            "changed_variables": list(contribution.changed_variables),
            "measured_property_scope": list(contribution.measured_property_scope),
            "test_environment_scope": list(contribution.test_environment_scope),
            "summary": contribution.contribution_summary,
            "exclusion_reason": contribution.exclusion_reason,
            "warnings": list(contribution.warnings),
        }

    @staticmethod
    def _evidence_payload(evidence: ObjectiveEvidence) -> dict[str, Any]:
        changed_variables = []
        for variable in evidence.changed_variables:
            record = variable.to_record()
            record["name"] = _normalize_scientific_typography(record["name"])
            if record["unit"]:
                record["unit"] = _normalize_scientific_typography(record["unit"])
            changed_variables.append(record)
        return {
            "evidence_id": evidence.evidence_id,
            "document_id": evidence.document_id,
            "evidence_role": evidence.evidence_role,
            "source_excerpt": evidence.source_excerpt[:_MAX_EXCERPT_CHARS],
            "changed_variables": changed_variables,
            "comparison": (
                evidence.comparison.to_record() if evidence.comparison else None
            ),
            "reported_result": (
                evidence.reported_result.to_record()
                if evidence.reported_result
                else None
            ),
            "attribution_scope": evidence.attribution_scope,
            "scientific_context": evidence.scientific_context.to_record(),
            "confidence": evidence.confidence,
        }

    @staticmethod
    def _result_set_id(
        factors: tuple[str, ...],
        outcome: str,
        primary_direction: str,
    ) -> str:
        identity = json.dumps(
            [factors, outcome, primary_direction],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return f"result_set_{sha1(identity.encode('utf-8')).hexdigest()[:16]}"

    @staticmethod
    def _finding_id(
        *,
        objective_id: str,
        analysis_version: int,
        factors: tuple[str, ...],
        outcome: str,
        supporting_ids: tuple[str, ...],
        contradicting_ids: tuple[str, ...],
    ) -> str:
        identity = json.dumps(
            [
                objective_id,
                analysis_version,
                factors,
                outcome,
                supporting_ids,
                contradicting_ids,
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return f"finding_{sha1(identity.encode('utf-8')).hexdigest()[:20]}"


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, (list, tuple, set)) else (value,)
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _text(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return tuple(result)


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _normalize_term(value: Any) -> str:
    value = _normalize_scientific_typography(value)
    return " ".join(
        part
        for part in "".join(
            character.lower() if character.isalnum() else " "
            for character in (_text(value) or "")
        ).split()
    )


def _normalize_scientific_typography(value: Any) -> str:
    text = _text(value) or ""
    text = _J_PER_CUBIC_MM_RE.sub("J/mm3", text)
    return re.sub(r"\s+([)\]])", r"\1", text)


def _scalar_key(value: Any) -> str:
    if value is None:
        return ""
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return _normalize_term(value)
    return str(number.normalize())


def _axis_matches(left: Any, right: Any) -> bool:
    if property_matching.axis_values_match(str(left or ""), str(right or "")):
        return True
    left_term = _normalize_term(left)
    right_term = _normalize_term(right)
    if not left_term or not right_term:
        return False
    if left_term == right_term:
        return True
    if {left_term, right_term} == {"densification", "relative density"}:
        return True
    if _axis_acronym(left_term) == right_term or _axis_acronym(right_term) == left_term:
        return True
    left_tokens = {_singular_axis_token(token) for token in left_term.split()}
    right_tokens = {_singular_axis_token(token) for token in right_term.split()}
    broad_structure_subject = right_tokens - {"structure"}
    if "structure" in right_tokens and broad_structure_subject <= left_tokens:
        return True
    return min(len(left_tokens), len(right_tokens)) >= 2 and (
        left_tokens <= right_tokens or right_tokens <= left_tokens
    )


def _axis_acronym(value: str) -> str:
    return "".join(token[0] for token in value.split() if token)


def _singular_axis_token(value: str) -> str:
    if len(value) > 4 and value.endswith("ies"):
        return f"{value[:-3]}y"
    if len(value) > 3 and value.endswith("s"):
        return value[:-1]
    return value
