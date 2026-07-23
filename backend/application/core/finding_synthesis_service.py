from __future__ import annotations

import json
from collections import defaultdict
from hashlib import sha1
from typing import Any, Mapping

from application.core.semantic_build.llm.extractor import CoreLLMStructuredExtractor
from domain.core import (
    Finding,
    ObjectiveAnalysis,
    ObjectiveEvidence,
    PaperContribution,
    ResearchObjective,
)


_MAX_DIRECT_EVIDENCE = 48
_MAX_CONTEXT_EVIDENCE = 24
_MAX_EXCERPT_CHARS = 900


class FindingSynthesisService:
    """Synthesize canonical, source-backed Findings for one analysis version."""

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
        contribution_by_document = {
            contribution.document_id: contribution for contribution in contributions
        }
        evidence_by_id = {
            evidence.evidence_id: evidence for evidence in evidence_records
        }
        direct_candidates = tuple(
            evidence
            for evidence in evidence_records
            if evidence.supports_finding
            and evidence.evidence_role == "direct_result"
            and evidence.property_normalized
        )
        comparison_keys = {
            (evidence.document_id, evidence.property_normalized.casefold())
            for evidence in direct_candidates
            if evidence.evidence_kind == "comparison"
        }
        direct_evidence = tuple(
            sorted(
                (
                    evidence
                    for evidence in direct_candidates
                    if evidence.evidence_kind == "comparison"
                    or (
                        evidence.document_id,
                        evidence.property_normalized.casefold(),
                    )
                    not in comparison_keys
                ),
                key=lambda item: (-item.confidence, item.document_id, item.evidence_id),
            )[:_MAX_DIRECT_EVIDENCE]
        )
        if not direct_evidence:
            return ()

        result_sets = self._result_sets(
            objective=objective,
            contribution_by_document=contribution_by_document,
            direct_evidence=direct_evidence,
            evidence_records=evidence_records,
        )
        if not result_sets:
            return ()
        context_evidence = tuple(
            sorted(
                (
                    evidence
                    for evidence in evidence_records
                    if evidence.supports_finding
                    and evidence.evidence_role
                    in {
                        "condition_context",
                        "mechanism_context",
                        "baseline_context",
                        "comparison_context",
                    }
                ),
                key=lambda item: (-item.confidence, item.document_id, item.evidence_id),
            )[:_MAX_CONTEXT_EVIDENCE]
        )
        objective_payload = {
            "objective_id": objective.objective_id,
            "question": objective.question,
            "material_scope": list(objective.material_scope),
            "process_axes": list(objective.process_axes),
            "property_axes": list(objective.property_axes),
            "comparison_intent": objective.comparison_intent,
        }
        contribution_payloads = [
            self._contribution_payload(contribution)
            for contribution in contributions
            if contribution.analysis_status == "analyzed"
        ]
        findings: list[Finding] = []
        for result_set in result_sets:
            contributing_document_ids = {
                document_id
                for item in _mapping_list(result_set.get("direct_evidence"))
                if (document_id := _text(item.get("document_id")))
            }
            parsed = self.structured_extractor.synthesize_findings(
                {
                    "objective": objective_payload,
                    "paper_contributions": contribution_payloads,
                    "result_sets": [result_set],
                    "context_evidence": [
                        self._evidence_payload(evidence)
                        for evidence in context_evidence
                        if evidence.document_id in contributing_document_ids
                    ],
                }
            )
            parsed_record = (
                parsed.model_dump() if hasattr(parsed, "model_dump") else dict(parsed)
            )
            expected_result_set_id = str(result_set["result_set_id"])
            for candidate in _mapping_list(parsed_record.get("findings")):
                if _text(candidate.get("result_set_id")) != expected_result_set_id:
                    continue
                finding = self._finding_from_candidate(
                    collection_id=collection_id,
                    objective=objective,
                    analysis=analysis,
                    candidate=candidate,
                    result_set=result_set,
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
        if (analysis.collection_id, analysis.objective_id, analysis.analysis_version) != expected:
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

    def _result_sets(
        self,
        *,
        objective: ResearchObjective,
        contribution_by_document: Mapping[str, PaperContribution],
        direct_evidence: tuple[ObjectiveEvidence, ...],
        evidence_records: tuple[ObjectiveEvidence, ...],
    ) -> tuple[dict[str, Any], ...]:
        grouped: dict[tuple[str, ...], list[ObjectiveEvidence]] = defaultdict(list)
        for evidence in direct_evidence:
            variables = self._variables_for(
                evidence,
                objective=objective,
                contribution=contribution_by_document.get(evidence.document_id),
            )
            if variables and any(
                _terms_match(variable, objective_axis)
                for variable in variables
                for objective_axis in objective.process_axes
            ):
                grouped[variables].append(evidence)

        contradictory = tuple(
            evidence
            for evidence in evidence_records
            if evidence.supports_finding
            and evidence.evidence_role == "contradictory_result"
            and evidence.property_normalized
        )
        result_sets: list[dict[str, Any]] = []
        for position, (variables, evidence_items) in enumerate(
            sorted(grouped.items(), key=lambda item: item[0]), start=1
        ):
            properties = _dedupe(
                evidence.property_normalized for evidence in evidence_items
            )
            if not properties:
                continue
            related_conflicts = [
                evidence
                for evidence in contradictory
                if evidence.property_normalized in properties
                and self._variables_overlap(
                    variables,
                    self._variables_for(
                        evidence,
                        objective=objective,
                        contribution=contribution_by_document.get(evidence.document_id),
                    ),
                )
            ]
            result_sets.append(
                {
                    "result_set_id": f"result_set_{position}",
                    "source_axes": list(variables),
                    "outcome_properties": list(properties),
                    "alignment": "same source-axis relationship",
                    "direct_evidence": [
                        self._evidence_payload(evidence) for evidence in evidence_items
                    ],
                    "contradictory_evidence": [
                        self._evidence_payload(evidence) for evidence in related_conflicts
                    ],
                    "document_count": len(
                        {evidence.document_id for evidence in evidence_items}
                    ),
                }
            )
        return tuple(result_sets)

    @staticmethod
    def _variables_for(
        evidence: ObjectiveEvidence,
        *,
        objective: ResearchObjective,
        contribution: PaperContribution | None,
    ) -> tuple[str, ...]:
        explicit = _dedupe(
            [
                *_strings(evidence.join_keys.get("variable_process_axes")),
                *_strings(evidence.join_keys.get("changed_variables")),
                *_strings(evidence.process_context.get("changed_variables")),
                *_strings(evidence.process_context.get("variable")),
            ]
        )
        if explicit:
            return tuple(sorted(explicit, key=str.casefold))
        candidates = _strings(evidence.join_keys.get("comparison_axis"))
        if not candidates:
            candidates = _strings(evidence.value_payload.get("comparison_axis"))
        variables = _dedupe(_text(value) for value in candidates)
        if variables:
            return tuple(sorted(variables, key=str.casefold))
        fallback_candidates: list[Any] = []
        if contribution is not None and len(contribution.changed_variables) == 1:
            fallback_candidates.extend(contribution.changed_variables)
        variables = _dedupe(_text(value) for value in fallback_candidates)
        if variables:
            return tuple(sorted(variables, key=str.casefold))
        if len(objective.process_axes) == 1:
            return objective.process_axes
        return ()

    @staticmethod
    def _variables_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
        left_terms = {_normalize_term(value) for value in left}
        right_terms = {_normalize_term(value) for value in right}
        return bool(left_terms & right_terms)

    @staticmethod
    def _contribution_payload(contribution: PaperContribution) -> dict[str, Any]:
        return {
            "document_id": contribution.document_id,
            "relevance": contribution.relevance,
            "paper_role": contribution.paper_role,
            "changed_variables": list(contribution.changed_variables),
            "measured_property_scope": list(contribution.measured_property_scope),
            "test_environment_scope": list(contribution.test_environment_scope),
            "summary": contribution.contribution_summary,
        }

    @staticmethod
    def _evidence_payload(evidence: ObjectiveEvidence) -> dict[str, Any]:
        return {
            "evidence_id": evidence.evidence_id,
            "document_id": evidence.document_id,
            "evidence_role": evidence.evidence_role,
            "evidence_kind": evidence.evidence_kind,
            "property_normalized": evidence.property_normalized,
            "source_excerpt": evidence.source_excerpt[:_MAX_EXCERPT_CHARS],
            "material_system": dict(evidence.material_system),
            "sample_context": dict(evidence.sample_context),
            "process_context": dict(evidence.process_context),
            "test_condition": dict(evidence.test_condition),
            "resolved_condition": dict(evidence.resolved_condition),
            "value_payload": dict(evidence.value_payload),
            "unit": evidence.unit,
            "baseline_context": dict(evidence.baseline_context),
            "interpretation": evidence.interpretation,
            "join_keys": dict(evidence.join_keys),
            "confidence": evidence.confidence,
        }

    def _finding_from_candidate(
        self,
        *,
        collection_id: str,
        objective: ResearchObjective,
        analysis: ObjectiveAnalysis,
        candidate: Mapping[str, Any],
        result_set: Mapping[str, Any],
        evidence_by_id: Mapping[str, ObjectiveEvidence],
        display_rank: int,
    ) -> Finding | None:
        result_evidence = _mapping_list(result_set.get("direct_evidence"))
        allowed_support_ids = {
            evidence_id
            for item in result_evidence
            if (evidence_id := _text(item.get("evidence_id")))
        }
        outcomes = _mapping_list(candidate.get("outcomes"))
        outcome_names = _dedupe(_text(item.get("concept")) for item in outcomes)
        allowed_outcomes = _strings(result_set.get("outcome_properties"))
        outcome_names = tuple(
            outcome
            for outcome in outcome_names
            if any(_terms_match(outcome, allowed) for allowed in allowed_outcomes)
        )
        if not outcome_names:
            return None
        supporting_ids = tuple(
            evidence_id
            for evidence_id in allowed_support_ids
            if evidence_id in evidence_by_id
            and evidence_by_id[evidence_id].property_normalized
            and any(
                _terms_match(evidence_by_id[evidence_id].property_normalized, outcome)
                for outcome in outcome_names
            )
        )
        if not supporting_ids:
            return None
        supporting_ids = tuple(sorted(supporting_ids))
        contributing_documents = tuple(
            sorted({evidence_by_id[value].document_id for value in supporting_ids})
        )
        finding_level = "cross_paper" if len(contributing_documents) >= 2 else "paper"
        synthesis_status = _text(candidate.get("synthesis_status")) or "insufficient_confirmation"
        if finding_level == "paper":
            synthesis_status = "insufficient_confirmation"
        elif synthesis_status not in {
            "agreement",
            "conflict",
            "condition_dependent",
            "insufficient_confirmation",
        }:
            synthesis_status = "insufficient_confirmation"

        conflict_ids = self._conflict_ids(
            candidate=candidate,
            result_set=result_set,
            evidence_by_id=evidence_by_id,
            supporting_ids=supporting_ids,
        )
        context_ids = self._context_ids(
            candidate=candidate,
            evidence_by_id=evidence_by_id,
            supporting_document_ids=set(contributing_documents),
        )
        variables = tuple(_strings(result_set.get("source_axes")))
        statement = _text(candidate.get("statement"))
        if not variables or not statement:
            return None
        coupled_variables = len(variables) > 1 or any(
            "," in variable or " and " in variable.casefold()
            for variable in variables
        )
        directions = _dedupe(_text(item.get("direction")) for item in outcomes)
        direction = directions[0] if len(directions) == 1 else "mixed"
        if coupled_variables:
            direction = "changes"
            statement = (
                "In the reported comparison, the coupled condition defined by "
                f"{', '.join(variables)} was associated with changes in "
                f"{', '.join(outcome_names)}."
            )
        conditions = _dedupe(_text(value) for value in _strings(candidate.get("common_conditions")))
        limitations = _dedupe(
            [
                *_strings(candidate.get("incomparable_conditions")),
                *_strings(candidate.get("warnings")),
                *(
                    (
                        "The reported comparison changes coupled variables; "
                        "individual-variable effects are not identifiable.",
                    )
                    if coupled_variables
                    else ()
                ),
                *(
                    ("Supported by one paper only; cross-paper confirmation is absent.",)
                    if finding_level == "paper"
                    else ()
                ),
            ]
        )
        supporting_evidence = [evidence_by_id[value] for value in supporting_ids]
        material_system = _first_mapping(
            evidence.material_system for evidence in supporting_evidence
        ) or {"scope": list(objective.material_scope)}
        context_evidence = [
            evidence_by_id[value]
            for value in context_ids
            if value in evidence_by_id
        ]
        context_support_ids = tuple(
            _dedupe([*supporting_ids, *context_ids])
        )
        finding_id = self._finding_id(
            objective_id=objective.objective_id,
            analysis_version=analysis.analysis_version,
            variables=variables,
            outcomes=outcome_names,
            supporting_ids=supporting_ids,
        )
        finding = Finding.from_mapping(
            {
                "collection_id": collection_id,
                "objective_id": objective.objective_id,
                "analysis_version": analysis.analysis_version,
                "finding_id": finding_id,
                "finding_level": finding_level,
                "statement": statement,
                "variables": variables,
                "mediators": _strings(candidate.get("mediator_concepts")),
                "outcomes": outcome_names,
                "direction": direction,
                "scope_summary": "; ".join(conditions)
                or ", ".join(objective.material_scope)
                or objective.question,
                "evidence_strength": {
                    "agreement": "strong",
                    "condition_dependent": "moderate",
                    "conflict": "moderate",
                    "insufficient_confirmation": "weak",
                }[synthesis_status],
                "generalization_status": (
                    "paper_level_only"
                    if finding_level == "paper"
                    else {
                        "agreement": "cross_paper_agreement",
                        "condition_dependent": "condition_dependent",
                        "conflict": "conflict",
                        "insufficient_confirmation": "insufficient_confirmation",
                    }[synthesis_status]
                ),
                "paper_count": len(contributing_documents),
                "confidence": candidate.get("confidence"),
                "display_rank": display_rank,
                "relations": [
                    {
                        "source_term": " and ".join(variables),
                        "relation_type": "associated_with",
                        "target_term": outcome,
                        "direction": (
                            direction
                            if coupled_variables
                            else next(
                                (
                                    _text(item.get("direction"))
                                    for item in outcomes
                                    if _terms_match(_text(item.get("concept")), outcome)
                                ),
                                direction,
                            )
                        ),
                        "assertion_strength": "associative",
                        "supporting_evidence_ids": [
                            evidence_id
                            for evidence_id in supporting_ids
                            if _terms_match(
                                evidence_by_id[evidence_id].property_normalized,
                                outcome,
                            )
                        ],
                    }
                    for outcome in outcome_names
                ],
                "context": {
                    "material_system": material_system,
                    "process_conditions": _distinct_mappings(
                        evidence.process_context
                        for evidence in [*supporting_evidence, *context_evidence]
                    ),
                    "sample_state": _first_mapping(
                        evidence.sample_context for evidence in supporting_evidence
                    ),
                    "test_conditions": _distinct_mappings(
                        evidence.test_condition
                        for evidence in [*supporting_evidence, *context_evidence]
                    ),
                    "comparison_baseline": _first_mapping(
                        evidence.baseline_context for evidence in supporting_evidence
                    ),
                    "limitations": limitations,
                    "supporting_evidence_ids": context_support_ids,
                },
                "derivation": {
                    "synthesis_mode": finding_level,
                    "comparison_status": synthesis_status,
                    "contributing_document_ids": contributing_documents,
                    "supporting_evidence_ids": supporting_ids,
                    "contradicting_evidence_ids": conflict_ids,
                    "rationale": statement,
                },
            }
        )
        finding.validate_evidence(tuple(evidence_by_id.values()))
        return finding

    @staticmethod
    def _conflict_ids(
        *,
        candidate: Mapping[str, Any],
        result_set: Mapping[str, Any],
        evidence_by_id: Mapping[str, ObjectiveEvidence],
        supporting_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        allowed = {
            evidence_id
            for item in _mapping_list(result_set.get("contradictory_evidence"))
            if (evidence_id := _text(item.get("evidence_id")))
        }
        requested = {
            evidence_id
            for outcome in _mapping_list(candidate.get("outcomes"))
            for evidence_id in _strings(outcome.get("conflicting_evidence_ids"))
        }
        return tuple(
            sorted(
                evidence_id
                for evidence_id in allowed & requested
                if evidence_id in evidence_by_id and evidence_id not in supporting_ids
            )
        )

    @staticmethod
    def _context_ids(
        *,
        candidate: Mapping[str, Any],
        evidence_by_id: Mapping[str, ObjectiveEvidence],
        supporting_document_ids: set[str],
    ) -> tuple[str, ...]:
        requested = _dedupe(
            [
                *_strings(candidate.get("context_evidence_ids")),
                *_strings(candidate.get("mechanism_evidence_ids")),
            ]
        )
        return tuple(
            evidence_id
            for evidence_id in requested
            if evidence_id in evidence_by_id
            and evidence_by_id[evidence_id].supports_finding
            and evidence_by_id[evidence_id].document_id in supporting_document_ids
            and evidence_by_id[evidence_id].evidence_role
            in {
                "condition_context",
                "mechanism_context",
                "baseline_context",
                "comparison_context",
            }
        )

    @staticmethod
    def _finding_id(
        *,
        objective_id: str,
        analysis_version: int,
        variables: tuple[str, ...],
        outcomes: tuple[str, ...],
        supporting_ids: tuple[str, ...],
    ) -> str:
        identity = json.dumps(
            [objective_id, analysis_version, variables, outcomes, supporting_ids],
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
    return tuple(_dedupe(_text(item) for item in values))


def _dedupe(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _text(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _normalize_term(value: Any) -> str:
    return " ".join(
        part for part in "".join(
            character.lower() if character.isalnum() else " "
            for character in (_text(value) or "")
        ).split()
    )


def _terms_match(left: Any, right: Any) -> bool:
    left_term = _normalize_term(left)
    right_term = _normalize_term(right)
    if not left_term or not right_term:
        return False
    return left_term == right_term or left_term in right_term or right_term in left_term


def _first_mapping(values: Any) -> dict[str, Any]:
    return next((dict(value) for value in values if value), {})


def _distinct_mappings(values: Any) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        item = dict(value)
        key = json.dumps(item, ensure_ascii=True, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result)
