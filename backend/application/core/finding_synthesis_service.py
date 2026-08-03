from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from hashlib import sha1
from typing import Any, Mapping

from application.core.semantic_build.llm.extractor import CoreLLMStructuredExtractor
from domain.core import (
    Finding,
    FindingPaperContribution,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
    ResearchObjective,
)


_MAX_CONTEXT_EVIDENCE_PER_SET = 8
_MAX_EXCERPT_CHARS = 320
_CONTEXT_ROLES = {
    "condition_context",
    "mechanism_context",
    "baseline_context",
    "comparison_context",
}
logger = logging.getLogger(__name__)
_NUMBER_RE = re.compile(
    r"(?<![\w.])[-+]?(?:\d+(?:[.,]\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?![\w.])"
)


class FindingSynthesisService:
    """Synthesize one-outcome, source-backed Findings for an analysis version."""

    def __init__(self, structured_extractor: Any | None = None) -> None:
        self.structured_extractor = structured_extractor or CoreLLMStructuredExtractor()

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
            try:
                parsed = self.structured_extractor.synthesize_findings(
                    {
                        "objective": objective_payload,
                        "paper_contributions": contribution_payloads,
                        "result_set": result_set,
                        "context_evidence": [
                            self._evidence_payload(evidence)
                            for evidence in context_evidence
                        ],
                    }
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Finding synthesis failed result_set_id=%s",
                    result_set["result_set_id"],
                )
                continue
            parsed_record = (
                parsed.model_dump() if hasattr(parsed, "model_dump") else dict(parsed)
            )
            expected_result_set_id = str(result_set["result_set_id"])
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
                        for item in _mapping_list(result_set.get("result_evidence"))
                    ],
                )
            for candidate in candidates:
                logger.debug(
                    "Inspecting Finding synthesis candidate result_set_id=%s "
                    "result_evidence_count=%s direction=%s assertion_strength=%s "
                    "factors=%s outcome=%s statement=%r",
                    expected_result_set_id,
                    len(_mapping_list(result_set.get("result_evidence"))),
                    _text(candidate.get("direction")),
                    _text(candidate.get("assertion_strength")),
                    _strings(result_set.get("factors")),
                    _text(result_set.get("outcome")),
                    _text(candidate.get("statement")),
                )
                if _text(candidate.get("result_set_id")) != expected_result_set_id:
                    continue
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
                if finding is not None:
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
        grouped: dict[
            tuple[tuple[str, ...], str, tuple[Any, ...]],
            list[ObjectiveEvidence],
        ] = defaultdict(list)
        factor_labels: dict[tuple[str, ...], tuple[str, ...]] = {}
        outcome_labels: dict[str, str] = {}
        for evidence in evidence_records:
            if not self._eligible_result_evidence(evidence):
                continue
            factors = tuple(
                sorted(
                    (item.name for item in evidence.changed_variables),
                    key=lambda value: _normalize_term(value),
                )
            )
            factor_key = tuple(_normalize_term(value) for value in factors)
            outcome = evidence.reported_result.outcome
            outcome_key = _normalize_term(outcome)
            if not self._within_objective_scope(
                factors=factors,
                outcome=outcome,
                objective=objective,
            ):
                continue
            interval_key = self._comparison_interval_key(evidence)
            grouped[(factor_key, outcome_key, interval_key)].append(evidence)
            factor_labels.setdefault(factor_key, factors)
            outcome_labels.setdefault(outcome_key, outcome)

        result_sets: list[dict[str, Any]] = []
        for factor_key, outcome_key, interval_key in sorted(grouped):
            evidence_items = tuple(
                sorted(
                    grouped[(factor_key, outcome_key, interval_key)],
                    key=lambda item: (
                        -item.confidence,
                        item.document_id,
                        item.evidence_id,
                    ),
                )
            )
            factors = factor_labels[factor_key]
            outcome = outcome_labels[outcome_key]
            result_sets.append(
                {
                    "result_set_id": self._result_set_id(
                        factors, outcome, interval_key
                    ),
                    "factors": list(factors),
                    "outcome": outcome,
                    "result_evidence": [
                        self._evidence_payload(evidence) for evidence in evidence_items
                    ],
                }
            )
        return tuple(result_sets)

    @staticmethod
    def _comparison_interval_key(
        evidence: ObjectiveEvidence,
    ) -> tuple[tuple[str, str, str, str], ...]:
        return tuple(
            sorted(
                (
                    _normalize_term(variable.name),
                    _scalar_key(variable.baseline_value),
                    _scalar_key(variable.target_value),
                    _normalize_term(variable.unit),
                )
                for variable in evidence.changed_variables
            )
        )

    @staticmethod
    def _eligible_result_evidence(evidence: ObjectiveEvidence) -> bool:
        return bool(
            evidence.supports_finding
            and evidence.evidence_role in {"direct_result", "contradictory_result"}
            and evidence.reported_result is not None
            and evidence.changed_variables
            and evidence.attribution_scope != "not_attributable"
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
    ) -> Finding | None:
        result_ids = tuple(
            evidence_id
            for item in _mapping_list(result_set.get("result_evidence"))
            if (evidence_id := _text(item.get("evidence_id")))
        )
        direction = _text(candidate.get("direction")) or "unknown"
        if not result_ids or any(
            evidence_by_id[evidence_id].reported_result is None
            for evidence_id in result_ids
        ):
            return None
        supporting_ids = tuple(
            evidence_id
            for evidence_id in result_ids
            if evidence_by_id[evidence_id].reported_result.direction == direction
        )
        contradicting_ids = tuple(
            evidence_id
            for evidence_id in result_ids
            if evidence_by_id[evidence_id].reported_result.direction != direction
        )
        if not supporting_ids:
            return None
        if any(
            evidence_by_id[evidence_id].evidence_role
            not in {"direct_result", "contradictory_result"}
            for evidence_id in (*supporting_ids, *contradicting_ids)
        ):
            return None

        allowed_context_ids = {item.evidence_id for item in context_evidence}
        context_ids = self._candidate_evidence_ids(candidate, "context_evidence_ids")
        if context_ids is None:
            return None
        if not set(context_ids) <= allowed_context_ids:
            return None
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
        statement = _text(candidate.get("statement"))
        if not factors or not outcome or not statement:
            return None
        if not self._statement_covers_atomic_result(statement, factors, outcome):
            return None
        if self._statement_mentions_unbound_objective_factor(
            statement,
            factors,
            objective.variables,
        ):
            return None
        supporting_evidence = tuple(
            evidence_by_id[evidence_id] for evidence_id in supporting_ids
        )
        if not self._statement_numbers_bind_to_one_source(
            statement,
            supporting_evidence,
        ):
            return None
        contradicting_evidence = tuple(
            evidence_by_id[evidence_id] for evidence_id in contradicting_ids
        )
        boundary_ids = self._condition_boundary_evidence_ids(
            supporting_evidence,
            contradicting_evidence,
        )
        expected_direction = self._direction_for(supporting_evidence)
        if expected_direction is None or direction != expected_direction:
            return None

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
            return None
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
            return None
        direct_evidence = supporting_evidence + contradicting_evidence
        certainty = Finding.certainty_for(synthesis_status, direct_evidence)
        limitations = self._limitations(
            candidate=candidate,
            factors=factors,
            synthesis_status=synthesis_status,
            attribution_scope=attribution_scope,
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
        except ValueError:
            logger.warning(
                "Rejected invalid Finding candidate result_set_id=%s",
                result_set["result_set_id"],
                exc_info=True,
            )
            return None
        return finding

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
    def _statement_covers_atomic_result(
        statement: str,
        factors: tuple[str, ...],
        outcome: str,
    ) -> bool:
        statement_term = _normalize_term(statement)
        outcome_term = _normalize_term(outcome)
        outcome_covered = outcome_term in statement_term
        if not outcome_covered:
            outcome_tokens = outcome_term.split()
            experimental_tokens = {"experiment", "experimental"}
            qualifiers = [
                token for token in outcome_tokens if token in experimental_tokens
            ]
            base_outcome = " ".join(
                token for token in outcome_tokens if token not in experimental_tokens
            )
            outcome_covered = bool(qualifiers and base_outcome in statement_term)
        return bool(
            outcome_covered
            and all(_normalize_term(factor) in statement_term for factor in factors)
        )

    @staticmethod
    def _statement_numbers_bind_to_one_source(
        statement: str,
        supporting_evidence: tuple[ObjectiveEvidence, ...],
    ) -> bool:
        statement_numbers = _numbers(statement)
        return not statement_numbers or any(
            set(statement_numbers) <= set(_numbers(_evidence_result_values(evidence)))
            for evidence in supporting_evidence
        )

    @staticmethod
    def _statement_mentions_unbound_objective_factor(
        statement: str,
        factors: tuple[str, ...],
        objective_variables: tuple[str, ...],
    ) -> bool:
        for variable in objective_variables:
            if not _statement_mentions_axis(statement, variable):
                continue
            matching_factors = tuple(
                factor for factor in factors if _axis_matches(variable, factor)
            )
            if not matching_factors or all(
                _axis_is_strictly_broader(factor, variable)
                for factor in matching_factors
            ):
                return True
        return False

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
        candidate: Mapping[str, Any],
        factors: tuple[str, ...],
        synthesis_status: str,
        attribution_scope: str,
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
        if attribution_scope == "association_only":
            deterministic.append(
                "The available evidence supports association, not isolated causation."
            )
        return _strings([*_strings(candidate.get("limitations")), *deterministic])

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
        return {
            "evidence_id": evidence.evidence_id,
            "document_id": evidence.document_id,
            "evidence_role": evidence.evidence_role,
            "source_excerpt": evidence.source_excerpt[:_MAX_EXCERPT_CHARS],
            "changed_variables": [
                variable.to_record() for variable in evidence.changed_variables
            ],
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
        interval_key: tuple[Any, ...],
    ) -> str:
        identity = json.dumps(
            [factors, outcome, interval_key],
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
    return " ".join(
        part
        for part in "".join(
            character.lower() if character.isalnum() else " "
            for character in (_text(value) or "")
        ).split()
    )


def _scalar_key(value: Any) -> str:
    if value is None:
        return ""
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return _normalize_term(value)
    return str(number.normalize())


def _numbers(value: Any) -> tuple[Decimal, ...]:
    numbers: list[Decimal] = []
    for token in _NUMBER_RE.findall((_text(value) or "").replace("−", "-")):
        try:
            number = Decimal(token.replace(",", ""))
        except InvalidOperation:
            continue
        if number not in numbers:
            numbers.append(number)
    return tuple(numbers)


def _evidence_result_values(evidence: ObjectiveEvidence) -> str:
    result = evidence.reported_result
    values = [
        *(str(variable.baseline_value or "") for variable in evidence.changed_variables),
        *(str(variable.target_value or "") for variable in evidence.changed_variables),
    ]
    if result is not None:
        values.extend((str(result.value or ""), result.result_text))
    return "\n".join(values)


def _axis_matches(left: Any, right: Any) -> bool:
    left_term = _normalize_term(left)
    right_term = _normalize_term(right)
    if not left_term or not right_term:
        return False
    if left_term == right_term:
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


def _axis_is_strictly_broader(candidate: Any, expected: Any) -> bool:
    candidate_tokens = {
        _singular_axis_token(token) for token in _normalize_term(candidate).split()
    }
    expected_tokens = {
        _singular_axis_token(token) for token in _normalize_term(expected).split()
    }
    return len(candidate_tokens) >= 2 and candidate_tokens < expected_tokens


def _axis_acronym(value: str) -> str:
    return "".join(token[0] for token in value.split() if token)


def _statement_mentions_axis(statement: str, axis: str) -> bool:
    statement_term = _normalize_term(statement)
    axis_term = _normalize_term(axis)
    if not statement_term or not axis_term:
        return False
    statement_tokens = {
        _singular_axis_token(token) for token in statement_term.split()
    }
    axis_tokens = {_singular_axis_token(token) for token in axis_term.split()}
    return axis_tokens <= statement_tokens or _axis_acronym(axis_term) in (
        statement_term.split()
    )


def _singular_axis_token(value: str) -> str:
    if len(value) > 4 and value.endswith("ies"):
        return f"{value[:-3]}y"
    if len(value) > 3 and value.endswith("s"):
        return value[:-1]
    return value
