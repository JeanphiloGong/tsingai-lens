from __future__ import annotations

import math
import logging
import re
from hashlib import sha1
from typing import Any, Mapping

from application.core.semantic_build.llm.extractor import CoreLLMStructuredExtractor
from domain.core import ResearchUnderstanding
from domain.ports import SourceArtifactRepository
from domain.source import SourceBlock, SourceDocument
from infra.persistence.factory import build_source_artifact_repository

logger = logging.getLogger(__name__)

_RELATION_CONTEXT_LIMIT = 16
_RELATION_EVIDENCE_UNIT_LIMIT = 24
_RELATION_TRACE_TASK_TYPE = "research_understanding_relation"
_FINDING_MATCH_STOPWORDS = {
    "affect",
    "affects",
    "behavior",
    "behaviour",
    "condition",
    "conditions",
    "context",
    "effect",
    "effects",
    "level",
    "levels",
    "material",
    "materials",
    "method",
    "methods",
    "process",
    "processes",
    "properties",
    "property",
    "result",
    "results",
    "sample",
    "samples",
    "specimen",
    "specimens",
    "table",
    "tables",
}


class ResearchUnderstandingService:
    """Project existing Core research views into claim/relation/evidence form."""

    def __init__(
        self,
        source_artifact_repository: SourceArtifactRepository | None = None,
        structured_extractor: Any | None = None,
    ) -> None:
        self.source_artifact_repository = (
            source_artifact_repository or build_source_artifact_repository()
        )
        self.structured_extractor = structured_extractor or CoreLLMStructuredExtractor()

    def with_presentation(
        self,
        understanding: ResearchUnderstanding | Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if understanding is None:
            return None
        record = (
            understanding.to_record()
            if isinstance(understanding, ResearchUnderstanding)
            else dict(understanding)
        )
        record["presentation"] = self._presentation_for(record)
        return ResearchUnderstanding.from_mapping(record).to_record()

    def build_objective_understanding(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._build_goal_or_objective_understanding(
            payload,
            scope_type="objective",
        )

    def build_goal_understanding(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._build_goal_or_objective_understanding(
            payload,
            scope_type="goal",
        )

    def _build_goal_or_objective_understanding(
        self,
        payload: Mapping[str, Any],
        *,
        scope_type: str,
    ) -> dict[str, Any]:
        objective = _mapping(payload.get("objective"))
        context = _mapping(payload.get("objective_context"))
        collection_id = _text(payload.get("collection_id"))
        objective_id = _text(objective.get("objective_id")) or _text(
            context.get("objective_id")
        )
        goal_id = _text(payload.get("goal_id"))
        question = _text(objective.get("question")) or _text(context.get("question"))
        evidence_units = _mapping_list(payload.get("evidence_units"))
        evidence_refs = self._evidence_refs_from_evidence_units(evidence_units)
        blocks_by_id, _documents_by_id = self._source_artifact_lookups(collection_id)
        evidence_refs = self._enrich_evidence_refs_from_source_blocks(
            evidence_refs,
            blocks_by_id=blocks_by_id,
        )
        evidence_ref_ids_by_unit = self._evidence_ref_ids_by_fact(evidence_refs)
        contexts = self._objective_contexts(
            context,
            objective,
            evidence_units=evidence_units,
        )
        context_ids = [item["context_id"] for item in contexts]
        context_ids_by_unit = self._objective_context_ids_by_unit(contexts)
        claims = self._objective_claims(
            payload,
            evidence_units=evidence_units,
            evidence_ref_ids_by_unit=evidence_ref_ids_by_unit,
            context_ids=context_ids,
            context_ids_by_unit=context_ids_by_unit,
        )
        relations, relation_warnings, model_traces = self._objective_relations(
            payload,
            evidence_units,
            claims=claims,
            evidence_ref_ids_by_unit=evidence_ref_ids_by_unit,
            context_ids=context_ids,
            context_ids_by_unit=context_ids_by_unit,
            contexts=contexts,
        )
        state = self._state_for(claims, relations, evidence_refs)
        return self.with_presentation(
            ResearchUnderstanding.from_mapping(
                {
                    "state": state,
                    "scope": {
                        "scope_type": scope_type,
                        "collection_id": collection_id,
                        "goal_id": goal_id if scope_type == "goal" else None,
                        "objective_id": objective_id if scope_type != "goal" else None,
                        "title": question,
                    },
                    "claims": claims,
                    "relations": relations,
                    "evidence_refs": evidence_refs,
                    "contexts": contexts,
                    "warnings": self._understanding_warnings(
                        claims,
                        evidence_refs,
                        extra_warnings=relation_warnings,
                    ),
                    "model_traces": model_traces,
                }
            )
        ) or {}

    def build_material_understanding(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        collection_id = _text(payload.get("collection_id"))
        material_id = _text(payload.get("material_id"))
        canonical_name = _text(payload.get("canonical_name")) or material_id
        evidence_refs = self._material_evidence_refs(payload)
        evidence_ref_ids_by_fact = self._evidence_ref_ids_by_fact(evidence_refs)
        contexts = self._material_contexts(payload)
        context_ids = [item["context_id"] for item in contexts]
        claims = self._material_claims(
            payload,
            evidence_ref_ids_by_fact=evidence_ref_ids_by_fact,
            context_ids=context_ids,
        )
        relations = self._material_relations(
            payload,
            evidence_ref_ids_by_fact=evidence_ref_ids_by_fact,
            context_ids=context_ids,
        )
        state = self._state_for(claims, relations, evidence_refs)
        return self.with_presentation(
            ResearchUnderstanding.from_mapping(
                {
                    "state": state,
                    "scope": {
                        "scope_type": "material",
                        "collection_id": collection_id,
                        "material_id": material_id,
                        "title": canonical_name,
                    },
                    "claims": claims,
                    "relations": relations,
                    "evidence_refs": evidence_refs,
                    "contexts": contexts,
                    "warnings": self._understanding_warnings(claims, evidence_refs),
                    "model_traces": [],
                }
            )
        ) or {}

    def _objective_contexts(
        self,
        context: Mapping[str, Any],
        objective: Mapping[str, Any],
        *,
        evidence_units: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not context and not objective and not evidence_units:
            return []
        contexts = [
            {
                "context_id": "ctx_objective_scope",
                "label": "Objective scope",
                "material_scope": _strings(
                    context.get("material_scope") or objective.get("material_scope")
                ),
                "process_context": {
                    "variable_process_axes": _strings(
                        context.get("variable_process_axes")
                        or objective.get("process_axes")
                    ),
                    "process_context_axes": _strings(
                        context.get("process_context_axes")
                    ),
                },
                "test_condition": {},
                "property_scope": _strings(
                    context.get("target_property_axes")
                    or objective.get("property_axes")
                ),
                "limitations": [],
            }
        ]
        for unit in evidence_units:
            unit_context = self._objective_context_from_evidence_unit(
                unit,
                objective_context=context,
                objective=objective,
            )
            if unit_context:
                contexts.append(unit_context)
        return _dedupe_by_id(contexts, "context_id")

    def _objective_context_ids_by_unit(
        self,
        contexts: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for context in contexts:
            unit_id = _text(context.get("source_evidence_unit_id"))
            context_id = _text(context.get("context_id"))
            if unit_id and context_id:
                result.setdefault(unit_id, []).append(context_id)
        return {key: _dedupe_strings(value) for key, value in result.items()}

    def _context_ids_for_evidence_unit(
        self,
        unit: Mapping[str, Any],
        context_ids: list[str],
        context_ids_by_unit: dict[str, list[str]],
    ) -> list[str]:
        unit_id = _text(unit.get("evidence_unit_id"))
        if unit_id:
            specific = context_ids_by_unit.get(unit_id, [])
            if specific:
                return specific
        return context_ids[:1]

    def _objective_context_from_evidence_unit(
        self,
        unit: Mapping[str, Any],
        *,
        objective_context: Mapping[str, Any],
        objective: Mapping[str, Any],
    ) -> dict[str, Any]:
        unit_id = _text(unit.get("evidence_unit_id"))
        if not unit_id:
            return {}
        material_scope = self._context_material_scope(
            unit,
            objective_context,
            objective,
        )
        process_context = self._context_process_scope(unit)
        test_condition = _mapping(unit.get("test_condition"))
        property_scope = self._context_property_scope(
            unit,
            objective_context,
            objective,
        )
        has_unit_boundary = bool(
            _display_values(_mapping(unit.get("material_system")))
            or _display_values(process_context)
            or _display_values(test_condition)
            or _text(unit.get("property_normalized"))
        )
        if not has_unit_boundary:
            return {}
        return {
            "context_id": f"ctx_{unit_id}_boundary",
            "source_evidence_unit_id": unit_id,
            "label": "Claim applicability",
            "material_scope": material_scope,
            "process_context": process_context,
            "test_condition": test_condition,
            "property_scope": property_scope,
            "limitations": [],
        }

    def _context_material_scope(
        self,
        unit: Mapping[str, Any],
        objective_context: Mapping[str, Any],
        objective: Mapping[str, Any],
    ) -> list[str]:
        material_values = _display_values(_mapping(unit.get("material_system")))
        if material_values:
            return material_values
        return _strings(
            objective_context.get("material_scope") or objective.get("material_scope")
        )

    def _context_process_scope(self, unit: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in (
            "process_context",
            "sample_context",
            "resolved_condition",
            "baseline_context",
        ):
            value = _mapping(unit.get(key))
            if _display_values(value):
                result[key] = value
        return result

    def _context_property_scope(
        self,
        unit: Mapping[str, Any],
        objective_context: Mapping[str, Any],
        objective: Mapping[str, Any],
    ) -> list[str]:
        property_name = _text(unit.get("property_normalized"))
        if property_name:
            return [property_name]
        return _strings(
            objective_context.get("target_property_axes")
            or objective.get("property_axes")
        )

    def _material_contexts(self, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        overview = _mapping(payload.get("overview"))
        return [
            {
                "context_id": "ctx_material_scope",
                "label": "Material scope",
                "material_scope": [_text(payload.get("canonical_name")) or ""],
                "process_context": {
                    "process_families": _strings(
                        overview.get("process_families")
                    ),
                },
                "test_condition": {},
                "property_scope": _strings(
                    overview.get("measured_properties")
                    or [item.get("property") for item in _mapping_list(payload.get("measured_properties"))]
                ),
                "limitations": _strings(payload.get("limitations")),
            }
        ]

    def _objective_claims(
        self,
        payload: Mapping[str, Any],
        *,
        evidence_units: list[dict[str, Any]],
        evidence_ref_ids_by_unit: dict[str, list[str]],
        context_ids: list[str],
        context_ids_by_unit: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        claims: list[dict[str, Any]] = []
        seen: set[str] = set()
        max_claims = 12
        objective_context = _mapping(payload.get("objective_context"))
        objective = _mapping(payload.get("objective"))
        target_axes = self._objective_target_axes_for_claims(
            objective_context,
            objective,
        )
        prioritized_units = [
            unit
            for _, unit in sorted(
                enumerate(evidence_units),
                key=lambda item: self._objective_claim_unit_priority(
                    item[1],
                    item[0],
                ),
            )
        ]
        primary_units = [
            unit
            for unit in prioritized_units
            if (_text(unit.get("unit_kind")) or "").lower() != "measurement"
            and self._objective_unit_can_drive_claim(unit)
        ]
        measurement_units = [
            unit
            for unit in prioritized_units
            if (_text(unit.get("unit_kind")) or "").lower() == "measurement"
            and self._objective_unit_can_drive_claim(unit)
        ]

        for unit in primary_units:
            if len(claims) >= max_claims:
                break
            statement = self._statement_from_evidence_unit(unit)
            if not statement:
                continue
            claim_type = self._reviewable_objective_claim_type(
                unit,
                statement,
                target_axes=target_axes,
            )
            if not claim_type:
                continue
            unit_id = _text(unit.get("evidence_unit_id"))
            evidence_unit_ids = [unit_id] if unit_id else []
            claim_context_ids = self._context_ids_for_evidence_unit(
                unit,
                context_ids,
                context_ids_by_unit,
            )
            _append_claim(
                claims,
                self._claim(
                    claim_type=claim_type,
                    statement=statement,
                    source_object_ids=evidence_unit_ids,
                    evidence_ref_ids=self._ref_ids_for(
                        evidence_unit_ids,
                        evidence_ref_ids_by_unit,
                    ),
                    context_ids=claim_context_ids,
                    confidence=unit.get("confidence"),
                    seen=seen,
                ),
            )

        logic_chain = _mapping(payload.get("logic_chain"))
        summary = _text(logic_chain.get("summary"))
        summary_evidence_unit_ids = _strings(logic_chain.get("evidence_unit_ids"))
        units_by_id = {
            unit_id: unit
            for unit in evidence_units
            if (unit_id := _text(unit.get("evidence_unit_id")))
        }
        summary_claim_units = [
            units_by_id[unit_id]
            for unit_id in summary_evidence_unit_ids
            if unit_id in units_by_id
            and self._objective_unit_can_drive_claim(units_by_id[unit_id])
        ]
        if (
            len(claims) < max_claims
            and summary
            and self._looks_complete_claim_statement(summary)
            and not self._is_aggregate_logic_summary(summary)
            and not self._is_noisy_objective_claim_statement(summary)
            and (not summary_evidence_unit_ids or summary_claim_units)
            and (
                self._objective_statement_mentions_target_axis(summary, target_axes)
                or any(
                    self._objective_unit_matches_claim_target(
                        unit,
                        summary,
                        target_axes,
                    )
                    for unit in summary_claim_units
                )
            )
        ):
            _append_claim(
                claims,
                self._claim(
                    claim_type="finding",
                    statement=summary,
                    source_object_ids=summary_evidence_unit_ids,
                    evidence_ref_ids=self._ref_ids_for(
                        summary_evidence_unit_ids,
                        evidence_ref_ids_by_unit,
                    ),
                    context_ids=context_ids,
                    seen=seen,
                ),
            )
        measurement_limit = min(
            self._objective_measurement_claim_limit(primary_claim_count=len(claims)),
            max_claims - len(claims),
        )
        measurement_count = 0
        for unit in measurement_units:
            if measurement_count >= measurement_limit or len(claims) >= max_claims:
                break
            statement = self._statement_from_evidence_unit(unit)
            if not statement:
                continue
            claim_type = self._reviewable_objective_claim_type(
                unit,
                statement,
                target_axes=target_axes,
            )
            if not claim_type:
                continue
            unit_id = _text(unit.get("evidence_unit_id"))
            evidence_unit_ids = [unit_id] if unit_id else []
            claim_context_ids = self._context_ids_for_evidence_unit(
                unit,
                context_ids,
                context_ids_by_unit,
            )
            before_count = len(claims)
            _append_claim(
                claims,
                self._claim(
                    claim_type=claim_type,
                    statement=statement,
                    source_object_ids=evidence_unit_ids,
                    evidence_ref_ids=self._ref_ids_for(
                        evidence_unit_ids,
                        evidence_ref_ids_by_unit,
                    ),
                    context_ids=claim_context_ids,
                    confidence=unit.get("confidence"),
                    seen=seen,
                ),
            )
            if len(claims) > before_count:
                measurement_count += 1
        return claims

    def _objective_claim_unit_priority(
        self,
        unit: Mapping[str, Any],
        index: int,
    ) -> tuple[int, int]:
        unit_kind = (_text(unit.get("unit_kind")) or "").lower()
        if unit_kind in {
            "comparison",
            "interpretation",
            "characterization",
            "mechanism",
        }:
            return (0, index)
        if unit_kind == "measurement":
            return (1, index)
        return (2, index)

    def _objective_measurement_claim_limit(
        self,
        *,
        primary_claim_count: int,
    ) -> int:
        if primary_claim_count > 0:
            return 0
        return 12

    def _objective_unit_can_drive_claim(self, unit: Mapping[str, Any]) -> bool:
        evidence_role = self._objective_unit_evidence_role(unit)
        return not evidence_role or evidence_role == "direct_support"

    def _objective_unit_evidence_role(self, unit: Mapping[str, Any]) -> str:
        for source_ref in _mapping_list(unit.get("source_refs")):
            evidence_role = _text(source_ref.get("evidence_role"))
            if evidence_role:
                return evidence_role
        return ""

    def _objective_relations(
        self,
        payload: Mapping[str, Any],
        evidence_units: list[dict[str, Any]],
        *,
        claims: list[dict[str, Any]],
        evidence_ref_ids_by_unit: dict[str, list[str]],
        context_ids: list[str],
        context_ids_by_unit: dict[str, list[str]],
        contexts: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
        deterministic_relations = self._deterministic_objective_relations(
            evidence_units,
            evidence_ref_ids_by_unit=evidence_ref_ids_by_unit,
            context_ids=context_ids,
            context_ids_by_unit=context_ids_by_unit,
        )
        relation_payload = self._semantic_relation_payload(
            payload,
            evidence_units=evidence_units,
            claims=claims,
            contexts=contexts,
        )
        try:
            extracted = self.structured_extractor.extract_research_understanding_relations(
                relation_payload
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "research understanding semantic relation extraction failed",
                exc_info=True,
            )
            failed_trace = self._consume_relation_trace(
                relation_payload,
                scope_payload=payload,
                trace_status="failed",
            )
            return deterministic_relations, ["relation_extraction_failed"], failed_trace
        model_traces = self._consume_relation_trace(
            relation_payload,
            scope_payload=payload,
            trace_status="available",
        )
        relations: list[dict[str, Any]] = []
        for item in getattr(extracted, "relations", []):
            relation = self._semantic_relation_from_model(
                item.model_dump(),
                evidence_ref_ids_by_unit=evidence_ref_ids_by_unit,
                context_ids=context_ids,
            )
            if relation:
                relations.append(relation)
        return (
            _dedupe_by_id((*relations, *deterministic_relations), "relation_id"),
            [],
            model_traces,
        )

    def _consume_relation_trace(
        self,
        relation_payload: Mapping[str, Any],
        *,
        scope_payload: Mapping[str, Any],
        trace_status: str,
    ) -> list[dict[str, Any]]:
        consumer = getattr(self.structured_extractor, "consume_last_trace", None)
        if not callable(consumer):
            return []
        trace = consumer()
        if not isinstance(trace, Mapping):
            return []
        input_source_ids = [
            unit_id
            for item in _mapping_list(relation_payload.get("evidence_units"))
            if (unit_id := _text(item.get("evidence_unit_id")))
        ]
        collection_id = _text(scope_payload.get("collection_id"))
        objective = _mapping(scope_payload.get("objective"))
        context = _mapping(scope_payload.get("objective_context"))
        goal_id = _text(scope_payload.get("goal_id"))
        objective_id = _text(objective.get("objective_id")) or _text(
            context.get("objective_id")
        )
        trace_record = dict(trace)
        trace_record["trace_id"] = _trace_id(
            trace_record.get("task_type"),
            collection_id,
            goal_id or objective_id,
            input_source_ids,
        )
        trace_record["task_type"] = _text(trace_record.get("task_type")) or (
            _RELATION_TRACE_TASK_TYPE
        )
        trace_record["trace_status"] = trace_status
        trace_record["collection_id"] = collection_id
        trace_record["scope_type"] = "goal" if goal_id else "objective"
        trace_record["scope_id"] = goal_id or objective_id
        trace_record["input_blocks"] = [
            {
                "source_object_id": unit_id,
                "source_kind": "objective_evidence_unit",
            }
            for unit_id in input_source_ids
        ]
        trace_record["source_object_ids"] = input_source_ids
        return [trace_record]

    def _deterministic_objective_relations(
        self,
        evidence_units: list[dict[str, Any]],
        *,
        evidence_ref_ids_by_unit: dict[str, list[str]],
        context_ids: list[str],
        context_ids_by_unit: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        relations = [
            relation
            for unit in evidence_units
            if (
                relation := self._deterministic_relation_from_evidence_unit(
                    unit,
                    evidence_ref_ids_by_unit=evidence_ref_ids_by_unit,
                    context_ids=context_ids,
                    context_ids_by_unit=context_ids_by_unit,
                )
            )
        ]
        return _dedupe_by_id(relations, "relation_id")

    def _deterministic_relation_from_evidence_unit(
        self,
        unit: Mapping[str, Any],
        *,
        evidence_ref_ids_by_unit: dict[str, list[str]],
        context_ids: list[str],
        context_ids_by_unit: dict[str, list[str]],
    ) -> dict[str, Any]:
        unit_id = _text(unit.get("evidence_unit_id"))
        if not unit_id:
            return {}
        unit_kind = (_text(unit.get("unit_kind")) or "").lower()
        if unit_kind not in {
            "comparison",
            "interpretation",
            "characterization",
            "mechanism",
        }:
            return {}
        predicate = self._deterministic_relation_predicate(unit)
        sample_values = _display_values(_mapping(unit.get("sample_context")))
        baseline_values = _display_values(_mapping(unit.get("baseline_context")))
        process_values = _display_values(_mapping(unit.get("process_context")))
        if (
            unit_kind == "comparison"
            and sample_values
            and baseline_values
            and not process_values
        ):
            return {}
        if unit_kind == "measurement" and predicate in {"reports", ""}:
            return {}
        subject = self._deterministic_relation_subject(unit)
        target = _text(unit.get("property_normalized")) or "observed response"
        statement = self._deterministic_relation_statement(
            unit,
            subject=subject or "process",
            predicate=predicate,
            target=target,
        )
        statement_subject = ""
        statement_predicate = ""
        statement_subject = self._statement_relation_subject(statement)
        statement_predicate = self._statement_relation_predicate(statement)
        if statement_subject and statement_predicate:
            subject = statement_subject
        if target == "observed response" and "density" in statement.lower():
            target = "density"
        if statement_predicate and predicate in {"explains", "reports", ""}:
            predicate = statement_predicate
        statement = self._deterministic_relation_statement(
            unit,
            subject=subject,
            predicate=predicate,
            target=target,
        )
        if not subject or not target or not statement:
            return {}
        if subject.lower() in {"characterization", "interpretation", "mechanism", "comparison"}:
            return {}
        if not _looks_user_facing(subject) or subject.lower() in {"true", "false"}:
            return {}
        if subject.replace(".", "", 1).isdigit():
            return {}
        if not self._looks_complete_claim_statement(statement):
            return {}
        statement_lower = statement.lower()
        if (
            " has the highest " in statement_lower
            or "measurement is relative to" in statement_lower
            or "measurement is " in statement_lower
            or statement_lower.endswith(" explains density.")
            or statement_lower == f"{subject.lower()} explains {target.lower()}."
        ):
            return {}
        evidence_unit_ids = [unit_id]
        evidence_ref_ids = self._ref_ids_for(evidence_unit_ids, evidence_ref_ids_by_unit)
        return {
            "relation_id": _stable_relation_id(
                "deterministic",
                subject,
                target,
                statement,
                evidence_unit_ids,
            ),
            "relation_type": self._presentation_relation_type("comparative", predicate),
            "subject": subject,
            "predicate": predicate or "relates to",
            "object": target,
            "statement": statement,
            "conditions": [],
            "status": "supported" if evidence_ref_ids else "limited",
            "confidence": unit.get("confidence"),
            "evidence_ref_ids": evidence_ref_ids,
            "context_ids": self._context_ids_for_evidence_unit(
                unit,
                context_ids,
                context_ids_by_unit,
            ),
            "source_object_ids": evidence_unit_ids,
            "warnings": ["deterministic_relation"],
        }

    def _deterministic_relation_subject(self, unit: Mapping[str, Any]) -> str:
        value_payload = _mapping(unit.get("value_payload"))
        axis = _text(value_payload.get("comparison_axis"))
        if axis and _looks_user_facing(axis):
            return axis
        process_context = _mapping(unit.get("process_context"))
        for key in (
            "process",
            "process_family",
            "process_type",
            "method",
            "treatment",
            "heat_treatment",
        ):
            text = _text(process_context.get(key))
            if text and _looks_user_facing(text):
                return text
        return ""

    def _deterministic_relation_predicate(self, unit: Mapping[str, Any]) -> str:
        value_payload = _mapping(unit.get("value_payload"))
        for key in ("direction", "trend"):
            text = _text(value_payload.get(key))
            if text and _looks_user_facing(text):
                return _short_text(text, limit=80)
        unit_kind = (_text(unit.get("unit_kind")) or "").lower()
        if unit_kind in {"interpretation", "characterization", "mechanism"}:
            return "explains"
        if _text(value_payload.get("comparison_axis")):
            return "compares"
        return "reports"

    def _statement_relation_subject(self, statement: str) -> str:
        lower = (_text(statement) or "").lower()
        if "density" not in lower:
            return ""
        if "heat treatment" in lower:
            return "heat treatment"
        if "treatment" in lower:
            return "treatment"
        if "process" in lower:
            return "process"
        return ""

    def _statement_relation_predicate(self, statement: str) -> str:
        lower = (_text(statement) or "").lower()
        for predicate in ("reduces", "increases", "decreases", "improves", "affects"):
            if f" {predicate} " in f" {lower} ":
                return predicate
        return ""

    def _deterministic_relation_statement(
        self,
        unit: Mapping[str, Any],
        *,
        subject: str,
        predicate: str,
        target: str,
    ) -> str:
        unit_kind = (_text(unit.get("unit_kind")) or "").lower()
        interpretation = _text(unit.get("interpretation"))
        if (
            unit_kind in {"interpretation", "characterization", "mechanism"}
            and interpretation
            and _looks_user_facing(interpretation)
        ):
            return _short_text(interpretation, limit=220)
        value_payload = _mapping(unit.get("value_payload"))
        for key in ("summary", "statement", "source_value_text"):
            text = _text(value_payload.get(key))
            if text and _looks_user_facing(text):
                return _short_text(text, limit=220)
        if interpretation and _looks_user_facing(interpretation):
            return _short_text(interpretation, limit=220)
        return f"{subject} {predicate or 'relates to'} {target}."

    def _material_claims(
        self,
        payload: Mapping[str, Any],
        *,
        evidence_ref_ids_by_fact: dict[str, list[str]],
        context_ids: list[str],
    ) -> list[dict[str, Any]]:
        claims: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in _mapping_list(payload.get("measured_properties")):
            property_name = _text(item.get("property"))
            display_range = _text(item.get("display_range"))
            if not property_name or not display_range:
                continue
            fact_ids = self._fact_ids_from_refs(_mapping_list(item.get("evidence_refs")))
            _append_claim(
                claims,
                self._claim(
                    claim_type="measurement",
                    statement=f"{property_name} is reported as {display_range}.",
                    source_object_ids=fact_ids,
                    evidence_ref_ids=self._ref_ids_for(
                        fact_ids,
                        evidence_ref_ids_by_fact,
                    ),
                    context_ids=context_ids,
                    seen=seen,
                ),
            )
        for limitation in _strings(payload.get("limitations")):
            _append_claim(
                claims,
                self._claim(
                    claim_type="limitation",
                    statement=limitation,
                    source_object_ids=[],
                    evidence_ref_ids=[],
                    context_ids=context_ids,
                    status="limited",
                    seen=seen,
                ),
            )
        return claims

    def _material_relations(
        self,
        payload: Mapping[str, Any],
        *,
        evidence_ref_ids_by_fact: dict[str, list[str]],
        context_ids: list[str],
    ) -> list[dict[str, Any]]:
        relations: list[dict[str, Any]] = []
        for group in _mapping_list(payload.get("comparison_groups")):
            matrix = _mapping(group.get("matrix"))
            fact_ids = self._fact_ids_from_refs(_mapping_list(group.get("evidence_refs")))
            subject = _text(group.get("variable_axis")) or _text(group.get("process_family"))
            object_text = ", ".join(_strings(group.get("properties"))) or _text(
                group.get("material_system")
            )
            relations.append(
                {
                    "relation_type": "compares",
                    "subject": subject or "Material condition",
                    "predicate": _text(group.get("comparability_status")) or "compares",
                    "object": object_text or "observed response",
                    "status": (
                        "supported"
                        if _text(group.get("comparability_status")) == "comparable"
                        else "limited"
                    ),
                    "confidence": None,
                    "evidence_ref_ids": self._ref_ids_for(
                        fact_ids,
                        evidence_ref_ids_by_fact,
                    ),
                    "context_ids": context_ids,
                    "source_object_ids": fact_ids or [_text(matrix.get("matrix_id")) or ""],
                    "warnings": _strings(group.get("warnings")),
                }
            )
        return relations

    def _semantic_relation_payload(
        self,
        payload: Mapping[str, Any],
        *,
        evidence_units: list[dict[str, Any]],
        claims: list[dict[str, Any]],
        contexts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        objective = _mapping(payload.get("objective"))
        objective_context = _mapping(payload.get("objective_context"))
        return {
            "objective": {
                "question": _text(objective.get("question"))
                or _text(objective_context.get("question")),
                "material_scope": _strings(
                    objective_context.get("material_scope")
                    or objective.get("material_scope")
                ),
                "process_axes": _strings(
                    objective_context.get("variable_process_axes")
                    or objective.get("process_axes")
                ),
                "property_axes": _strings(
                    objective_context.get("target_property_axes")
                    or objective.get("property_axes")
                ),
            },
            "claims": [
                {
                    "statement": _text(claim.get("statement")),
                    "claim_type": _text(claim.get("claim_type")),
                    "evidence_unit_ids": _strings(claim.get("source_object_ids")),
                }
                for claim in claims
                if _text(claim.get("statement"))
            ][:12],
            "contexts": [
                self._semantic_relation_context(context)
                for context in contexts[:_RELATION_CONTEXT_LIMIT]
            ],
            "evidence_units": [
                self._semantic_relation_evidence_unit(unit)
                for unit in self._semantic_relation_evidence_units(
                    evidence_units,
                    claims=claims,
                )
            ],
        }

    def _semantic_relation_context(
        self,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "label": _text(context.get("label")),
            "material_scope": _strings(context.get("material_scope")),
            "process_summary": self._semantic_relation_mapping_summary(
                _mapping(context.get("process_context")),
            ),
            "test_summary": self._semantic_relation_test_condition(
                _mapping(context.get("test_condition")),
            ),
            "property_scope": _strings(context.get("property_scope")),
        }

    def _semantic_relation_evidence_unit(self, unit: Mapping[str, Any]) -> dict[str, Any]:
        value_payload = _mapping(unit.get("value_payload"))
        return {
            "evidence_unit_id": _text(unit.get("evidence_unit_id")),
            "unit_kind": _text(unit.get("unit_kind")),
            "property_normalized": _text(unit.get("property_normalized")),
            "sample_summary": self._semantic_relation_mapping_summary(
                _mapping(unit.get("sample_context")),
            ),
            "process_summary": self._semantic_relation_mapping_summary(
                _mapping(unit.get("process_context")),
            ),
            "test_summary": self._semantic_relation_test_condition(
                _mapping(unit.get("test_condition")),
            ),
            "value_payload": {
                key: _short_text(str(value), limit=240)
                for key, value in value_payload.items()
                if key
                in {
                    "source_value_text",
                    "summary",
                    "statement",
                    "direction",
                    "comparison_axis",
                    "comparison_axis_value",
                    "value",
                    "trend",
                }
                and _text(value)
            },
            "unit": _text(unit.get("unit")),
            "baseline_summary": self._semantic_relation_mapping_summary(
                _mapping(unit.get("baseline_context")),
            ),
            "interpretation": _short_text(_text(unit.get("interpretation")) or "", limit=240),
            "resolution_status": _text(unit.get("resolution_status")),
            "confidence": unit.get("confidence"),
        }

    def _semantic_relation_evidence_units(
        self,
        evidence_units: list[dict[str, Any]],
        *,
        claims: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        eligible = [
            unit
            for unit in evidence_units
            if _text(unit.get("evidence_unit_id"))
        ]
        claim_unit_ids = {
            unit_id
            for claim in claims
            for unit_id in _strings(claim.get("source_object_ids"))
        }
        return [
            unit
            for _, unit in sorted(
                enumerate(eligible),
                key=lambda item: self._semantic_relation_evidence_priority(
                    item[1],
                    claim_unit_ids=claim_unit_ids,
                    index=item[0],
                ),
            )
        ][:_RELATION_EVIDENCE_UNIT_LIMIT]

    def _semantic_relation_evidence_priority(
        self,
        unit: Mapping[str, Any],
        *,
        claim_unit_ids: set[str],
        index: int,
    ) -> tuple[int, int, int]:
        unit_id = _text(unit.get("evidence_unit_id")) or ""
        claim_rank = 0 if unit_id in claim_unit_ids else 1
        unit_kind = (_text(unit.get("unit_kind")) or "").lower()
        if unit_kind in {"comparison", "interpretation", "characterization", "mechanism"}:
            signal_rank = 0
        elif self._semantic_relation_value_text(unit):
            signal_rank = 1
        else:
            signal_rank = 2
        return (claim_rank, signal_rank, index)

    def _semantic_relation_value_text(self, unit: Mapping[str, Any]) -> str:
        value_payload = _mapping(unit.get("value_payload"))
        parts = [
            _text(value_payload.get(key)) or ""
            for key in (
                "comparison_axis",
                "direction",
                "trend",
                "summary",
                "statement",
            )
        ]
        parts.append(_text(unit.get("interpretation")) or "")
        return " ".join(part for part in parts if part)

    def _semantic_relation_mapping_summary(
        self,
        payload: Mapping[str, Any],
    ) -> str:
        return _join_display_values(
            [_short_text(value, limit=80) for value in _display_values(payload)],
            limit=5,
        )

    def _semantic_relation_test_condition(
        self,
        payload: Mapping[str, Any],
    ) -> str:
        compact = {
            key: value
            for key, value in payload.items()
            if str(key).lower() not in {"details", "detail", "notes", "note"}
        }
        return self._semantic_relation_mapping_summary(compact)

    def _semantic_relation_from_model(
        self,
        item: Mapping[str, Any],
        *,
        evidence_ref_ids_by_unit: dict[str, list[str]],
        context_ids: list[str],
    ) -> dict[str, Any]:
        source = _text(item.get("source_concept"))
        target = _text(item.get("target_concept"))
        statement = _text(item.get("statement"))
        evidence_unit_ids = _strings(item.get("evidence_unit_ids"))
        if not source or not target or not statement or not evidence_unit_ids:
            return {}
        if not _looks_user_facing(source) or not _looks_user_facing(target):
            return {}
        relation_type = _text(item.get("relation_type")) or "conditional"
        direction = _text(item.get("direction")) or "unknown"
        mediators = _strings(item.get("mediator_concepts"))
        conditions = _strings(item.get("conditions"))
        return {
            "relation_id": _stable_relation_id(
                relation_type,
                source,
                target,
                statement,
                evidence_unit_ids,
            ),
            "relation_type": self._presentation_relation_type(relation_type, direction),
            "subject": source,
            "predicate": direction if direction != "unknown" else relation_type,
            "object": " -> ".join((*mediators, target)) if mediators else target,
            "statement": statement,
            "conditions": conditions,
            "status": "supported" if self._ref_ids_for(evidence_unit_ids, evidence_ref_ids_by_unit) else "limited",
            "confidence": item.get("confidence"),
            "evidence_ref_ids": self._ref_ids_for(
                evidence_unit_ids,
                evidence_ref_ids_by_unit,
            ),
            "context_ids": context_ids,
            "source_object_ids": evidence_unit_ids,
            "warnings": _strings(item.get("warnings")),
        }

    def _material_evidence_refs(self, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for ref in _mapping_list(payload.get("evidence_refs")):
            refs.append(self._normalize_existing_evidence_ref(ref))
        for item in _mapping_list(payload.get("measured_properties")):
            for ref in _mapping_list(item.get("evidence_refs")):
                refs.append(self._normalize_existing_evidence_ref(ref))
        for group in _mapping_list(payload.get("comparison_groups")):
            for ref in _mapping_list(group.get("evidence_refs")):
                refs.append(self._normalize_existing_evidence_ref(ref))
        return self._sort_evidence_refs_for_review(refs)

    def _normalize_existing_evidence_ref(self, ref: Mapping[str, Any]) -> dict[str, Any]:
        locator = _locator_mapping(ref.get("locator"))
        source_kind = _text(ref.get("source_kind")) or _text(locator.get("source_kind")) or "unknown"
        evidence_ref_id = _text(ref.get("evidence_ref_id"))
        if not evidence_ref_id:
            evidence_ref_id = _stable_ref_id(
                source_kind,
                _text(ref.get("document_id")),
                _strings(ref.get("fact_ids")),
                _strings(ref.get("anchor_ids")),
                locator,
            )
        return {
            "evidence_ref_id": evidence_ref_id,
            "source_kind": source_kind,
            "document_id": _text(ref.get("document_id")),
            "label": _text(ref.get("label")) or _text(locator.get("source_ref")) or evidence_ref_id,
            "locator": locator,
            "fact_ids": _strings(ref.get("fact_ids")),
            "anchor_ids": _strings(ref.get("anchor_ids")),
            "confidence": ref.get("confidence"),
            "traceability_status": _text(ref.get("traceability_status")) or "unknown",
            "evidence_role": _text(ref.get("evidence_role")),
            "quote": _text(ref.get("quote")),
            "href": _text(ref.get("href")),
        }

    def _evidence_refs_from_evidence_units(
        self,
        evidence_units: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for unit in evidence_units:
            unit_id = _text(unit.get("evidence_unit_id"))
            source_refs = _mapping_list(unit.get("source_refs"))
            if not source_refs:
                refs.append(self._evidence_ref_from_unit(unit, source_ref=None))
                continue
            for source_ref in source_refs:
                refs.append(self._evidence_ref_from_unit(unit, source_ref=source_ref))
            if unit_id and _strings(unit.get("evidence_anchor_ids")):
                refs.append(self._evidence_ref_from_unit(unit, source_ref=None))
        return self._sort_evidence_refs_for_review(refs)

    def _sort_evidence_refs_for_review(
        self,
        refs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        deduped = _dedupe_by_id(refs, "evidence_ref_id")
        return [
            ref
            for _, ref in sorted(
                enumerate(deduped),
                key=lambda item: (*self._evidence_ref_priority(item[1]), item[0]),
            )
        ]

    def _evidence_ref_priority(self, ref: Mapping[str, Any]) -> tuple[int, int]:
        source_kind = (_text(ref.get("source_kind")) or "").lower()
        priority = 40
        if "table" in source_kind:
            priority = 0
        elif "figure" in source_kind:
            priority = 1
        text = self._evidence_priority_text(ref).lower()
        if any(term in text for term in ("result", "discussion", "conclusion")):
            priority = min(priority, 2)
        if any(term in text for term in ("table", "figure", "value", "measured")):
            priority = min(priority, 3)
        if any(term in text for term in ("abstract", "introduction", "background")):
            priority = max(priority, 80)
        if not _text(ref.get("quote")) and source_kind in {"unknown", "text_window"}:
            priority = max(priority, 60)
        traceability_status = _text(ref.get("traceability_status")) or ""
        traceability_rank = 0 if traceability_status in {"resolved", "traceable"} else 1
        return (priority, traceability_rank)

    def _evidence_priority_text(self, ref: Mapping[str, Any]) -> str:
        locator = _locator_mapping(ref.get("locator"))
        return " ".join(
            value
            for value in (
                _text(ref.get("label")),
                _text(locator.get("source_ref")),
                _text(locator.get("source_kind")),
                _text(ref.get("quote")),
                _text(ref.get("source_kind")),
            )
            if value
        )

    def _evidence_ref_from_unit(
        self,
        unit: Mapping[str, Any],
        *,
        source_ref: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        source = _mapping(source_ref)
        unit_id = _text(unit.get("evidence_unit_id"))
        source_kind = _text(source.get("source_kind")) or "unknown"
        source_ref_label = (
            _text(source.get("display_label"))
            or _text(source.get("source_ref"))
            or _text(source.get("route_id"))
        )
        evidence_ref_id = _stable_ref_id(
            source_kind,
            _text(unit.get("document_id")),
            [unit_id] if unit_id else [],
            _strings(unit.get("evidence_anchor_ids")),
            source,
        )
        return {
            "evidence_ref_id": evidence_ref_id,
            "source_kind": source_kind,
            "document_id": _text(source.get("document_id")) or _text(unit.get("document_id")),
            "label": source_ref_label or unit_id or evidence_ref_id,
            "locator": {
                key: value
                for key, value in {
                    "source_ref": _text(source.get("source_ref")),
                    "route_id": _text(source.get("route_id")),
                    "source_kind": source_kind,
                }.items()
                if value
            },
            "fact_ids": [unit_id] if unit_id else [],
            "anchor_ids": _strings(unit.get("evidence_anchor_ids")),
            "confidence": unit.get("confidence"),
            "traceability_status": (
                _text(unit.get("resolution_status"))
                or ("traceable" if source or unit.get("evidence_anchor_ids") else "missing")
            ),
            "evidence_role": self._evidence_role_for_unit_source(unit, source),
            "quote": _text(source.get("quote")),
            "href": _text(source.get("href")),
        }

    def _evidence_role_for_unit_source(
        self,
        unit: Mapping[str, Any],
        source: Mapping[str, Any],
    ) -> str | None:
        return _text(source.get("evidence_role")) or _text(unit.get("evidence_role"))

    def _enrich_evidence_refs_from_source_blocks(
        self,
        refs: list[dict[str, Any]],
        *,
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> list[dict[str, Any]]:
        if not refs or not blocks_by_id:
            return refs
        return [
            self._evidence_ref_with_source_block(ref, blocks_by_id=blocks_by_id)
            for ref in refs
        ]

    def _evidence_ref_with_source_block(
        self,
        ref: Mapping[str, Any],
        *,
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> dict[str, Any]:
        locator = _locator_mapping(ref.get("locator"))
        source_ref = _text(locator.get("source_ref"))
        block = blocks_by_id.get(source_ref or "") if source_ref else None
        if block is None:
            return dict(ref)
        enriched = dict(ref)
        enriched_locator = dict(locator)
        if block.page is not None and not _text(enriched_locator.get("page")):
            enriched_locator["page"] = block.page
        enriched["locator"] = enriched_locator
        if not _text(enriched.get("document_id")) and block.document_id:
            enriched["document_id"] = block.document_id
        if not _text(enriched.get("quote")) and _text(block.text):
            enriched["quote"] = _short_text(block.text, limit=420)
        return enriched

    def _statement_from_evidence_unit(self, unit: Mapping[str, Any]) -> str | None:
        unit_kind = _text(unit.get("unit_kind"))
        property_name = _text(unit.get("property_normalized"))
        value_payload = _mapping(unit.get("value_payload"))
        source_value = (
            _text(value_payload.get("source_value_text"))
            or _text(value_payload.get("value"))
            or _text(value_payload.get("statement"))
        )
        summary = _text(value_payload.get("summary"))
        unit_text = _text(unit.get("unit"))
        interpretation = _text(unit.get("interpretation"))
        if unit_kind == "comparison":
            return (
                _text(value_payload.get("summary"))
                or _text(value_payload.get("source_value_text"))
                or interpretation
                or self._comparison_statement(value_payload, property_name)
            )
        if interpretation:
            return interpretation
        if unit_kind in {"characterization", "interpretation", "mechanism"} and summary:
            return summary
        if property_name and source_value:
            suffix = f" {unit_text}" if unit_text and unit_text not in source_value else ""
            return f"{property_name} is reported as {source_value}{suffix}."
        return source_value

    def _reviewable_objective_claim_type(
        self,
        unit: Mapping[str, Any],
        statement: str,
        *,
        target_axes: list[str] | tuple[str, ...] = (),
    ) -> str | None:
        if not self._looks_complete_claim_statement(statement):
            return None
        if not self._objective_unit_matches_claim_target(
            unit,
            statement,
            target_axes,
        ):
            return None
        unit_kind = _text(unit.get("unit_kind"))
        property_name = _text(unit.get("property_normalized"))
        if unit_kind == "measurement":
            return (
                "measurement"
                if property_name and self._has_source_value(unit)
                else None
            )
        if self._is_noisy_objective_claim_statement(statement):
            return None
        if unit_kind == "comparison":
            sample_context = _mapping(unit.get("sample_context"))
            baseline_context = _mapping(unit.get("baseline_context"))
            sample_values = _display_values(sample_context)
            baseline_values = _display_values(baseline_context)
            process_values = _display_values(_mapping(unit.get("process_context")))
            row_level_keys = {
                "sample_number",
                "condition_number",
                "sample_id",
                "condition_id",
            }
            context_keys = {
                _text(key).lower()
                for key in (*sample_context.keys(), *baseline_context.keys())
                if _text(key)
            }
            if (
                sample_values
                and baseline_values
                and not process_values
                and context_keys.intersection(row_level_keys)
            ):
                return None
            return (
                "comparison"
                if property_name and self._has_comparison_signal(unit)
                else None
            )
        if unit_kind in {"characterization", "interpretation", "mechanism"}:
            lower_statement = f" {_text(statement).lower()} "
            mechanism_signals = (
                " improves",
                " improve",
                " reduces",
                " reduce",
                " increases",
                " increase",
                " decreases",
                " decrease",
                " affects",
                " affect",
                " explains",
                " explain",
                " leads to ",
                " led to ",
                " results in ",
                " resulted in ",
                " associated with ",
                " directly linking ",
            )
            return (
                "mechanism"
                if any(signal in lower_statement for signal in mechanism_signals)
                else None
            )
        return None

    def _objective_target_axes_for_claims(
        self,
        objective_context: Mapping[str, Any],
        objective: Mapping[str, Any],
    ) -> list[str]:
        lens = _mapping(objective_context.get("objective_evidence_lens"))
        return _dedupe_strings(
            [
                *(_strings(lens.get("target_outcome_axes"))),
                *(_strings(objective_context.get("target_property_axes"))),
                *(_strings(objective.get("property_axes"))),
            ]
        )

    def _objective_unit_matches_claim_target(
        self,
        unit: Mapping[str, Any],
        statement: str,
        target_axes: list[str] | tuple[str, ...],
    ) -> bool:
        if not target_axes:
            return True
        property_name = _text(unit.get("property_normalized"))
        if property_name and self._objective_statement_mentions_target_axis(
            property_name,
            target_axes,
        ):
            return True
        value_payload = _mapping(unit.get("value_payload"))
        text = " ".join(
            item
            for item in (
                statement,
                _text(value_payload.get("summary")),
                _text(value_payload.get("source_value_text")),
                _text(value_payload.get("statement")),
                _text(unit.get("interpretation")),
            )
            if item
        )
        return self._objective_statement_mentions_target_axis(text, target_axes)

    def _objective_statement_mentions_target_axis(
        self,
        statement: str,
        target_axes: list[str] | tuple[str, ...],
    ) -> bool:
        if not target_axes:
            return True
        return any(
            self._objective_axis_tokens_match(statement, axis)
            for axis in target_axes
        )

    def _objective_axis_tokens_match(self, text: str, axis: str) -> bool:
        axis_tokens = tuple(re.findall(r"[a-z0-9]+", (axis or "").lower()))
        text_tokens = tuple(re.findall(r"[a-z0-9]+", (text or "").lower()))
        if not axis_tokens or not text_tokens:
            return False
        if len(axis_tokens) > 1 and len(axis_tokens) <= len(text_tokens):
            for index in range(0, len(text_tokens) - len(axis_tokens) + 1):
                if text_tokens[index : index + len(axis_tokens)] == axis_tokens:
                    return True
        if axis_tokens == ("relative", "density"):
            axis_tokens = ("density",)
        if len(axis_tokens) != 1:
            return False
        axis_token = axis_tokens[0]
        for index, token in enumerate(text_tokens):
            if token != axis_token:
                continue
            previous = text_tokens[index - 1] if index > 0 else ""
            if axis_token == "density" and previous == "dislocation":
                continue
            return True
        return False

    def _is_noisy_objective_claim_statement(self, statement: str) -> bool:
        text = _text(statement) or ""
        lower = text.lower()
        if not lower:
            return True
        if lower.startswith("sample ") and " has the highest " in lower:
            return True
        if " table-derived " in lower and " has the highest " in lower:
            return True
        if "measurement is relative to" in lower:
            return True
        if lower.startswith(("future work", "further work")):
            return True
        if lower.startswith("further ") and (
            " required" in lower
            or " needed" in lower
            or " should " in lower
        ):
            return True
        if " should be investigated" in lower or " remains to be studied" in lower:
            return True
        if " is assumed " in lower or " are assumed " in lower:
            return True
        if " is reported as " in lower and lower.endswith(" analysis."):
            return True
        return False

    def _is_aggregate_logic_summary(self, statement: str) -> bool:
        text = _text(statement) or ""
        lower = text.lower()
        if not lower:
            return True
        aggregate_signals = (
            " assembled ",
            " measurement unit(s)",
            " across ",
            " density range ",
            " relative density range ",
            " table ",
        )
        signal_count = sum(1 for signal in aggregate_signals if signal in lower)
        return signal_count >= 2 or (len(text) > 220 and ":" in text)

    def _has_source_value(self, unit: Mapping[str, Any]) -> bool:
        value_payload = _mapping(unit.get("value_payload"))
        return bool(
            _text(value_payload.get("source_value_text"))
            or _text(value_payload.get("value"))
            or _text(value_payload.get("statement"))
        )

    def _has_comparison_signal(self, unit: Mapping[str, Any]) -> bool:
        value_payload = _mapping(unit.get("value_payload"))
        return bool(
            _text(value_payload.get("comparison_axis"))
            or _text(value_payload.get("direction"))
            or _text(value_payload.get("trend"))
            or _text(value_payload.get("summary"))
            or _text(value_payload.get("source_value_text"))
            or _text(value_payload.get("statement"))
            or _text(unit.get("interpretation"))
        )

    def _looks_complete_claim_statement(self, statement: str) -> bool:
        text = _text(statement)
        if not text or not _looks_user_facing(text):
            return False
        lower = f" {text.lower()} "
        if lower.strip().startswith(
            (
                "achieved through ",
                "based on ",
                "under ",
                "using ",
                "with ",
                "without ",
            )
        ):
            return False
        claim_signals = (
            " is ",
            " are ",
            " was ",
            " were ",
            " has ",
            " have ",
            " shows ",
            " show ",
            " improves",
            " improve",
            " reduces",
            " reduce",
            " increases",
            " increase",
            " decreases",
            " decrease",
            " affects",
            " affect",
            " correlates",
            " correlate",
            " explains",
            " explain",
            " indicates",
            " indicate",
            " suggests",
            " suggest",
            " leads to ",
            " led to ",
            " results in ",
            " resulted in ",
            " associated with ",
            " reported as ",
            " observed ",
            " formed ",
            " exhibits ",
            " exhibit ",
        )
        return any(signal in lower for signal in claim_signals)

    def _comparison_statement(
        self,
        value_payload: Mapping[str, Any],
        property_name: str | None,
    ) -> str | None:
        axis = _text(value_payload.get("comparison_axis"))
        direction = _text(value_payload.get("direction")) or _text(value_payload.get("trend"))
        if not axis and not property_name:
            return None
        if axis and direction and property_name:
            return f"{axis} is associated with {direction} in {property_name}."
        if axis and property_name:
            return f"{axis} is compared for {property_name}."
        if property_name and direction:
            return f"{property_name} shows {direction}."
        return None

    def _claim(
        self,
        *,
        claim_type: str,
        statement: str,
        source_object_ids: list[str] | tuple[str, ...],
        evidence_ref_ids: list[str],
        context_ids: list[str],
        seen: set[str],
        status: str | None = None,
        strength: str | None = None,
        confidence: Any = None,
    ) -> dict[str, Any]:
        key = statement.strip().lower()
        if key in seen:
            return {}
        seen.add(key)
        return {
            "claim_type": claim_type,
            "statement": statement,
            "status": status or ("supported" if evidence_ref_ids else "limited"),
            "confidence": confidence,
            "strength": strength,
            "evidence_ref_ids": evidence_ref_ids,
            "context_ids": context_ids,
            "source_object_ids": list(source_object_ids),
            "warnings": [] if evidence_ref_ids else ["missing_evidence_ref"],
        }

    def _ref_ids_for(
        self,
        fact_ids: list[str] | tuple[str, ...],
        evidence_ref_ids_by_fact: dict[str, list[str]],
    ) -> list[str]:
        ref_ids: list[str] = []
        for fact_id in fact_ids:
            ref_ids.extend(evidence_ref_ids_by_fact.get(fact_id, []))
        return _dedupe_strings(ref_ids)

    def _fact_ids_from_refs(self, refs: list[dict[str, Any]]) -> list[str]:
        fact_ids: list[str] = []
        for ref in refs:
            fact_ids.extend(_strings(ref.get("fact_ids")))
        return _dedupe_strings(fact_ids)

    def _evidence_ref_ids_by_fact(
        self,
        refs: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for ref in refs:
            ref_id = _text(ref.get("evidence_ref_id"))
            if not ref_id:
                continue
            for fact_id in _strings(ref.get("fact_ids")):
                grouped.setdefault(fact_id, []).append(ref_id)
        return {key: _dedupe_strings(value) for key, value in grouped.items()}

    def _presentation_relation_type(self, relation_type: str, direction: str) -> str:
        normalized_direction = (direction or "").lower()
        if normalized_direction in {"improves", "reduces", "increases", "decreases"}:
            return normalized_direction
        normalized_type = (relation_type or "").lower()
        if normalized_type == "conflicting":
            return "conflicts"
        if normalized_type == "comparative":
            return "compares"
        if normalized_type == "mechanistic":
            return "explains"
        if normalized_type == "correlational":
            return "correlates"
        return "compares"

    def _state_for(
        self,
        claims: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        evidence_refs: list[dict[str, Any]],
    ) -> str:
        claims = [claim for claim in claims if claim]
        if not claims and not relations and not evidence_refs:
            return "empty"
        if any(claim.get("status") == "supported" for claim in claims):
            return "ready"
        if claims or relations:
            return "limited"
        return "partial"

    def _understanding_warnings(
        self,
        claims: list[dict[str, Any]],
        evidence_refs: list[dict[str, Any]],
        *,
        extra_warnings: list[str] | tuple[str, ...] = (),
    ) -> list[str]:
        warnings: list[str] = []
        if claims and not evidence_refs:
            warnings.append("claims_without_evidence_refs")
        if any("missing_evidence_ref" in claim.get("warnings", []) for claim in claims):
            warnings.append("some_claims_missing_evidence_refs")
        warnings.extend(_strings(extra_warnings))
        return _dedupe_strings(warnings)

    def _presentation_for(self, record: Mapping[str, Any]) -> dict[str, Any]:
        claims = _mapping_list(record.get("claims"))
        relations = _mapping_list(record.get("relations"))
        evidence_refs = _mapping_list(record.get("evidence_refs"))
        contexts = _mapping_list(record.get("contexts"))
        scope = _mapping(record.get("scope"))
        evidence_by_id = {
            _text(ref.get("evidence_ref_id")): ref
            for ref in evidence_refs
            if _text(ref.get("evidence_ref_id"))
        }
        contexts_by_id = {
            _text(context.get("context_id")): context
            for context in contexts
            if _text(context.get("context_id"))
        }
        relations_by_id = {
            _text(relation.get("relation_id")): relation
            for relation in relations
            if _text(relation.get("relation_id"))
        }
        blocks_by_id, documents_by_id = self._source_artifact_lookups(
            _text(scope.get("collection_id"))
        )
        effects = [
            self._presentation_effect(
                claim,
                relations=relations,
                evidence_by_id=evidence_by_id,
                contexts_by_id=contexts_by_id,
            )
            for claim in claims
            if _text(claim.get("statement"))
        ]
        covered_relation_ids = {
            relation_id
            for effect in effects
            for relation_id in _strings(effect.get("relation_ids"))
        }
        goal_axes = _dedupe_strings(
            [
                axis
                for context in contexts_by_id.values()
                if (
                    _text(context.get("context_id")) == "ctx_objective_scope"
                    or _normalize_match_text(_text(context.get("label")) or "")
                    in {"objective scope", "goal scope"}
                )
                for process_context in [_mapping(context.get("process_context"))]
                for axis in _strings(process_context.get("variable_process_axes"))
            ]
        )
        relation_effects = [
            self._presentation_relation_effect(
                relation,
                evidence_by_id=evidence_by_id,
                contexts_by_id=contexts_by_id,
            )
            for relation in relations
            if _text(relation.get("relation_id")) not in covered_relation_ids
            and self._reviewable_presentation_relation(relation)
            and self._relation_matches_goal_axis(relation, goal_axes)
        ]
        effects.extend(relation_effects)
        context_summaries = [
            self._presentation_context_summary(context)
            for context in contexts
        ]
        summary_contexts = [
            context
            for context in contexts
            if not _text(context.get("source_evidence_unit_id"))
            and not (_text(context.get("context_id")) or "").endswith("_boundary")
        ] or contexts
        material_scope = _dedupe_strings(
            [
                value
                for context in summary_contexts
                for value in _strings(context.get("material_scope"))
            ]
        )
        property_scope = _dedupe_strings(
            [
                value
                for context in summary_contexts
                for value in _strings(context.get("property_scope"))
            ]
        )
        variable_axes = _dedupe_strings(
            [
                value
                for context in summary_contexts
                for value in _display_values(_mapping(context.get("process_context")))
            ]
        )
        review_queue_count = sum(1 for effect in effects if effect.get("needs_review"))
        findings = [
            self._presentation_finding(
                effect,
                evidence_by_id=evidence_by_id,
                relations_by_id=relations_by_id,
                blocks_by_id=blocks_by_id,
            )
            for effect in effects
        ]
        findings = self._sort_presentation_findings(findings)
        primary_findings, review_queue_findings = self._partition_presentation_findings(
            findings,
            evidence_by_id=evidence_by_id,
            blocks_by_id=blocks_by_id,
        )
        quote_hints_by_ref = self._finding_quote_hints_by_evidence_ref(
            findings,
            relations_by_id=relations_by_id,
        )
        evidence_items = [
            self._presentation_evidence_item(
                ref,
                blocks_by_id=blocks_by_id,
                documents_by_id=documents_by_id,
                quote_hints=quote_hints_by_ref.get(
                    _text(ref.get("evidence_ref_id")) or "",
                    {},
                ),
            )
            for ref in evidence_refs
        ]
        return {
            "summary": {
                "title": _text(scope.get("title")) or "Research understanding",
                "material_scope": material_scope,
                "variable_axes": variable_axes,
                "property_scope": property_scope,
                "claim_count": len(claims),
                "relation_count": len(relations),
                "evidence_count": len(evidence_refs),
                "context_count": len(contexts),
                "review_queue_count": review_queue_count,
                "primary_finding_count": len(primary_findings),
                "review_queue_finding_count": len(review_queue_findings),
            },
            "effects": effects,
            "findings": findings,
            "primary_findings": primary_findings,
            "review_queue_findings": review_queue_findings,
            "evidence_items": evidence_items,
            "context_summaries": context_summaries,
        }

    def _partition_presentation_findings(
        self,
        findings: list[dict[str, Any]],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        primary: list[dict[str, Any]] = []
        review_queue: list[dict[str, Any]] = []
        for finding in findings:
            if self._is_primary_presentation_finding(
                finding,
                evidence_by_id=evidence_by_id,
                blocks_by_id=blocks_by_id,
            ):
                primary.append(finding)
            else:
                review_queue.append(finding)
        return primary, review_queue

    def _is_primary_presentation_finding(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> bool:
        grade = _text(finding.get("support_grade")) or ""
        if grade not in {"strong", "partial"}:
            return False
        bundle = _mapping(finding.get("evidence_bundle"))
        return bool(
            _strings(bundle.get("direct_result"))
            and finding.get("relation_chain")
            and self._finding_has_quote_aligned_direct_result(
                finding,
                evidence_by_id=evidence_by_id,
                blocks_by_id=blocks_by_id,
            )
        )

    def _finding_has_quote_aligned_direct_result(
        self,
        finding: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> bool:
        bundle = _mapping(finding.get("evidence_bundle"))
        direct_ref_ids = _strings(bundle.get("direct_result"))
        if not direct_ref_ids:
            return False
        terms = self._finding_quote_alignment_terms(finding)
        if not terms["variable"] or not terms["outcome"]:
            return False
        quote_hints = {
            "variable": terms["variable"],
            "outcome": terms["outcome"],
            "relation": {
                term
                for value in (
                    _text(finding.get("statement")),
                    _text(finding.get("title")),
                    _text(finding.get("direction")),
                    *_strings(finding.get("mediators")),
                )
                for term in _quote_hint_terms(value)
            },
        }
        for ref_id in direct_ref_ids:
            evidence_ref = evidence_by_id.get(ref_id, {})
            locator = _locator_mapping(evidence_ref.get("locator"))
            block = blocks_by_id.get(_text(locator.get("source_ref")) or "")
            source_text = self._presentation_source_text_for_quote(
                block,
                blocks_by_id=blocks_by_id,
                quote_hints=quote_hints,
            ) or _text(evidence_ref.get("quote"))
            visible_quote = self._presentation_quote_for_ref(
                quote=_text(evidence_ref.get("quote")),
                source_text=source_text,
                quote_hints=quote_hints,
            )
            searchable = _normalize_match_text(_short_text(visible_quote, limit=240))
            if not searchable:
                continue
            bounded = f" {searchable} "
            if not _quote_term_hits(bounded, terms["variable"]):
                continue
            if not _quote_term_hits(bounded, terms["outcome"]):
                continue
            outcome_keys = {
                _normalize_match_text(value)
                for value in _strings(finding.get("outcomes"))
            }
            if "microstructure" in outcome_keys and not _quote_term_hits(
                bounded,
                terms["microstructure_concrete"],
            ):
                continue
            if "mechanical properties" in outcome_keys and not _quote_term_hits(
                bounded,
                terms["mechanical_concrete"],
            ):
                continue
            if (
                "pitting corrosion behavior" in outcome_keys
                and not _quote_term_hits(bounded, terms["corrosion_concrete"])
            ):
                continue
            if (
                "corrosion behavior" in outcome_keys
                and not _quote_term_hits(bounded, terms["corrosion_concrete"])
            ):
                continue
            return True
        return False

    def _finding_quote_alignment_terms(
        self,
        finding: Mapping[str, Any],
    ) -> dict[str, set[str]]:
        variable_terms: set[str] = set()
        for value in _strings(finding.get("variables")):
            tokens = _meaningful_match_tokens(value)
            if not tokens:
                continue
            if len(tokens) == 1:
                variable_terms.update(_target_token_variants(tokens[0]))
            else:
                variable_terms.add(" ".join(tokens))
                for index in range(len(tokens) - 1):
                    left = tokens[index]
                    right = tokens[index + 1]
                    if left in {"and", "with"} or right in {"and", "with"}:
                        continue
                    variable_terms.add(f"{left} {right}")
            token_set = set(tokens)
            if "preheating" in token_set and (
                "platform" in token_set or "plate" in token_set
            ):
                variable_terms.update({"preheating", "build plate", "build platform"})
            if token_set & {"level", "size", "amount", "content"}:
                for token in token_set - {"level", "size", "amount", "content"}:
                    variable_terms.update(_target_token_variants(token))

        outcome_terms: set[str] = set()
        microstructure_concrete = {
            "cellular",
            "grain",
            "grains",
            "melt pool",
            "microstructural",
        }
        mechanical_concrete = {
            "ductility",
            "elongation",
            "strength",
            "tensile",
            "yield",
        }
        corrosion_concrete = {
            "corrosion",
            "electrochemical",
            "passivation",
            "pitting",
            "polarization",
        }
        for value in _strings(finding.get("outcomes")):
            outcome_terms.update(_quote_hint_terms(value))
            normalized = _normalize_match_text(value)
            if normalized == "microstructure":
                outcome_terms.update(microstructure_concrete)
            elif normalized == "mechanical properties":
                outcome_terms.update(mechanical_concrete)
            elif normalized in {"corrosion behavior", "pitting corrosion behavior"}:
                outcome_terms.update(corrosion_concrete)
        return {
            "variable": variable_terms,
            "outcome": outcome_terms,
            "microstructure_concrete": microstructure_concrete,
            "mechanical_concrete": mechanical_concrete,
            "corrosion_concrete": corrosion_concrete,
        }

    def _sort_presentation_findings(
        self,
        findings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grade_rank = {
            "strong": 0,
            "partial": 1,
            "weak": 2,
            "conflict": 3,
            "insufficient": 4,
        }

        def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int]:
            index, finding = item
            bundle = _mapping(finding.get("evidence_bundle"))
            has_direct = bool(_strings(bundle.get("direct_result")))
            has_chain = bool(finding.get("relation_chain"))
            grade = _text(finding.get("support_grade")) or ""
            usable_rank = (
                0 if grade in {"strong", "partial"} and has_direct and has_chain else 1
            )
            return (
                usable_rank,
                grade_rank.get(grade, 5),
                0 if has_direct else 1,
                index,
            )

        return [finding for _, finding in sorted(enumerate(findings), key=sort_key)]

    def _presentation_finding(
        self,
        effect: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        relations_by_id: Mapping[str, dict[str, Any]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> dict[str, Any]:
        claim_id = _text(effect.get("claim_id")) or "claim"
        relations = self._finding_relations(effect, relations_by_id)
        variables = self._finding_variables(effect, relations)
        mediators = self._finding_mediators(relations)
        outcomes = self._finding_outcomes(effect, relations)
        direction = self._finding_direction(effect, relations)
        relation_ids = list(_strings(effect.get("relation_ids")))
        evidence_bundle = self._finding_evidence_bundle(
            effect,
            evidence_by_id=evidence_by_id,
            relations=relations,
            outcomes=outcomes,
        )
        evidence_bundle = self._finding_result_source_bundle(
            effect,
            evidence_bundle=evidence_bundle,
            evidence_by_id=evidence_by_id,
            relations=relations,
            outcomes=outcomes,
            blocks_by_id=blocks_by_id,
        )
        display_variables = self._finding_display_variables(
            variables,
            relations=relations,
            evidence_by_id=evidence_by_id,
            evidence_bundle=evidence_bundle,
        )
        review_status = self._finding_review_status(effect)
        scope_summary = _compact_finding_scope_summary(
            _text(effect.get("context_summary")) or "",
            variables=display_variables,
            outcomes=outcomes,
        )
        return {
            "finding_id": f"finding_{claim_id}",
            "claim_id": claim_id,
            "title": self._finding_title(
                variables=display_variables,
                outcomes=outcomes,
                fallback=_text(effect.get("title")) or _text(effect.get("statement")),
            ),
            "statement": self._finding_statement(
                statement=_text(effect.get("statement")) or "",
                variables=display_variables,
                outcomes=outcomes,
                evidence_by_id=evidence_by_id,
                evidence_bundle=evidence_bundle,
                blocks_by_id=blocks_by_id,
            ),
            "variables": display_variables,
            "mediators": mediators,
            "outcomes": outcomes,
            "direction": direction,
            "relation_chain": self._finding_relation_chain(
                relations,
                variables=display_variables,
                direction=direction,
            ),
            "scope_summary": scope_summary,
            "support_grade": self._finding_support_grade(
                effect,
                evidence_bundle=evidence_bundle,
                outcomes=outcomes,
                relation_ids=relation_ids,
                review_status=review_status,
                scope_summary=scope_summary,
            ),
            "review_status": review_status,
            "confidence": effect.get("confidence"),
            "paper_count": effect.get("paper_count") or 0,
            "evidence_count": effect.get("evidence_count") or 0,
            "evidence_ref_ids": list(_strings(effect.get("evidence_ref_ids"))),
            "context_ids": list(_strings(effect.get("context_ids"))),
            "relation_ids": relation_ids,
            "evidence_bundle": evidence_bundle,
            "warnings": list(_strings(effect.get("warnings"))),
        }

    def _finding_title(
        self,
        *,
        variables: list[str],
        outcomes: list[str],
        fallback: str,
    ) -> str:
        if variables and outcomes:
            return f"{variables[0]} -> {outcomes[0]}"
        if fallback:
            return _short_text(fallback, limit=96)
        if outcomes:
            return outcomes[0]
        if variables:
            return variables[0]
        return "Research finding"

    def _finding_statement(
        self,
        *,
        statement: str,
        variables: list[str],
        outcomes: list[str],
        evidence_by_id: Mapping[str, dict[str, Any]],
        evidence_bundle: Mapping[str, list[str]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> str:
        if not variables or not outcomes:
            return statement
        quote_statement = self._quote_derived_finding_statement(
            variables=variables,
            outcomes=outcomes,
            evidence_by_id=evidence_by_id,
            evidence_bundle=evidence_bundle,
            blocks_by_id=blocks_by_id,
        )
        if self._statement_matches_finding_display(
            statement,
            variables=variables,
            outcomes=outcomes,
        ):
            if quote_statement and self._statement_specificity_score(
                quote_statement
            ) >= self._statement_specificity_score(statement) + 5:
                return quote_statement
            return statement
        if quote_statement:
            return quote_statement
        variable = variables[0]
        outcome = outcomes[0]
        return f"{variable} is associated with {outcome}."

    def _quote_derived_finding_statement(
        self,
        *,
        variables: list[str],
        outcomes: list[str],
        evidence_by_id: Mapping[str, dict[str, Any]],
        evidence_bundle: Mapping[str, list[str]],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> str:
        quote_hints = {
            "variable": {
                term for value in variables for term in _quote_hint_terms(value)
            },
            "outcome": self._finding_statement_outcome_terms(outcomes),
            "relation": set(),
        }
        if not quote_hints["variable"] or not quote_hints["outcome"]:
            return ""
        for ref_id in _strings(evidence_bundle.get("direct_result")):
            evidence_ref = evidence_by_id.get(ref_id, {})
            locator = _locator_mapping(evidence_ref.get("locator"))
            block = blocks_by_id.get(_text(locator.get("source_ref")) or "")
            source_text = self._presentation_source_text_for_quote(
                block,
                blocks_by_id=blocks_by_id,
                quote_hints=quote_hints,
            ) or _text(evidence_ref.get("quote"))
            if not source_text:
                continue
            snippet = self._best_matching_quote_snippet(source_text, quote_hints)
            if not snippet:
                continue
            for sentence in _quote_sentences(snippet):
                if not _quote_has_concrete_result_cue(sentence):
                    continue
                normalized = f" {_normalize_match_text(sentence)} "
                if not _quote_term_hits(normalized, quote_hints["variable"]):
                    continue
                if not _quote_term_hits(normalized, quote_hints["outcome"]):
                    continue
                return sentence
        return ""

    def _statement_specificity_score(self, statement: str) -> int:
        if not statement:
            return 0
        score = 0
        if _quote_has_concrete_result_cue(statement):
            score += 4
        if re.search(r"\d", statement):
            score += 4
        normalized = f" {_normalize_match_text(statement)} "
        for cue in (
            "increased",
            "increases",
            "decreased",
            "decreases",
            "reduced",
            "reduces",
            "improved",
            "improves",
            "affecting",
            "affects",
            "measured",
            "achieved",
            "observed",
            "revealed",
            "sensitive",
        ):
            if f" {cue} " in normalized:
                score += 1
        return score

    def _finding_statement_outcome_terms(self, outcomes: list[str]) -> set[str]:
        terms: set[str] = set()
        for value in outcomes:
            terms.update(_quote_hint_terms(value))
            normalized = _normalize_match_text(value)
            if normalized == "microstructure":
                terms.update(
                    {
                        "cellular",
                        "columnar",
                        "grain",
                        "grains",
                        "melt pool",
                        "microstructural",
                        "structure",
                    }
                )
            elif normalized == "mechanical properties":
                terms.update({"ductility", "elongation", "strength", "tensile", "yield"})
            elif normalized in {"corrosion behavior", "pitting corrosion behavior"}:
                terms.update(
                    {
                        "corrosion",
                        "electrochemical",
                        "passivation",
                        "pitting",
                        "polarization",
                    }
                )
        return terms

    def _statement_matches_finding_display(
        self,
        statement: str,
        *,
        variables: list[str],
        outcomes: list[str],
    ) -> bool:
        if not statement or not variables or not outcomes:
            return False
        normalized = f" {_normalize_match_text(statement)} "
        return bool(
            self._variable_matches_direct_evidence(variables, statement)
            and _quote_term_hits(normalized, _quote_hint_terms(outcomes[0]))
        )

    def _finding_relation_chain(
        self,
        relations: list[dict[str, Any]],
        *,
        variables: list[str] | None = None,
        direction: str = "",
    ) -> list[dict[str, Any]]:
        chain: list[dict[str, Any]] = []
        display_variables = variables or []
        for index, relation in enumerate(relations):
            variable = self._presentation_relation_side(relation.get("subject"))
            object_chain = self._relation_object_chain(relation)
            if not variable or not object_chain:
                continue
            display_variable = (
                display_variables[index]
                if index < len(display_variables)
                else (display_variables[0] if display_variables else variable)
            )
            segment_direction = ""
            for value in (relation.get("predicate"), relation.get("relation_type")):
                text = _text(value)
                if text and _looks_user_facing(text):
                    segment_direction = text
                    break
            chain.append(
                {
                    "relation_id": _text(relation.get("relation_id")) or "",
                    "variable": display_variable,
                    "mediators": object_chain[:-1],
                    "outcome": object_chain[-1],
                    "direction": segment_direction or direction,
                    "statement": self._presentation_relation_summary(relation),
                }
            )
        return chain

    def _finding_relations(
        self,
        effect: Mapping[str, Any],
        relations_by_id: Mapping[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            relations_by_id[relation_id]
            for relation_id in _strings(effect.get("relation_ids"))
            if relation_id in relations_by_id
        ]

    def _finding_variables(
        self,
        effect: Mapping[str, Any],
        relations: list[dict[str, Any]],
    ) -> list[str]:
        variables = _dedupe_strings(
            [
                subject
                for relation in relations
                if (subject := self._presentation_relation_side(relation.get("subject")))
            ]
        )
        if variables:
            return variables
        fallback = _text(effect.get("variable_axis"))
        return [fallback] if fallback else []

    def _finding_display_variables(
        self,
        variables: list[str],
        *,
        relations: list[dict[str, Any]],
        evidence_by_id: Mapping[str, dict[str, Any]],
        evidence_bundle: Mapping[str, list[str]],
    ) -> list[str]:
        broad_process_variables = {
            "additive manufacturing",
            "laser beam powder bed fusion",
            "laser powder bed fusion",
            "lpbf",
            "powder bed fusion",
            "selective laser melting",
            "slm",
        }
        has_broad_variable = any(
            _normalize_match_text(variable) in broad_process_variables
            for variable in variables
        )
        relation_text_parts: list[str] = []
        for relation in relations:
            relation_text_parts.extend(
                [
                    self._presentation_relation_summary(relation),
                    _text(relation.get("statement")) or "",
                ]
            )
        direct_evidence_text = self._direct_evidence_text_for_display_variables(
            evidence_by_id=evidence_by_id,
            evidence_bundle=evidence_bundle,
        )
        direct_concrete_variables = self._concrete_variable_terms(direct_evidence_text)
        concrete_variables = direct_concrete_variables or self._concrete_variable_terms(
            " ".join([*relation_text_parts, direct_evidence_text])
        )
        if not concrete_variables:
            return variables
        if (
            not has_broad_variable
            and direct_concrete_variables
            and not self._variable_matches_direct_evidence(
                variables,
                direct_evidence_text,
            )
        ):
            return direct_concrete_variables
        if not has_broad_variable:
            return variables
        broad_variable_keys = {
            _normalize_match_text(variable)
            for variable in variables
            if _normalize_match_text(variable) in broad_process_variables
        }
        non_broad_variable_keys = {
            _normalize_match_text(variable)
            for variable in variables
            if _normalize_match_text(variable) not in broad_process_variables
        }
        replacement_variables = [
            variable
            for variable in concrete_variables
            if _normalize_match_text(variable) not in non_broad_variable_keys
        ]
        if not replacement_variables:
            return variables
        return _dedupe_strings(
            [
                replacement
                for variable in variables
                for replacement in (
                    replacement_variables
                    if _normalize_match_text(variable) in broad_variable_keys
                    else [variable]
                )
            ]
        )

    def _direct_evidence_text_for_display_variables(
        self,
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        evidence_bundle: Mapping[str, list[str]],
    ) -> str:
        text_parts: list[str] = []
        for ref_id in _strings(evidence_bundle.get("direct_result")):
            evidence_ref = evidence_by_id.get(ref_id, {})
            locator = _locator_mapping(evidence_ref.get("locator"))
            text_parts.extend(
                [
                    _text(evidence_ref.get("quote")) or "",
                    _text(evidence_ref.get("label")) or "",
                    *_display_values(locator),
                ]
            )
        return " ".join(text_parts)

    def _variable_matches_direct_evidence(
        self,
        variables: list[str],
        direct_evidence_text: str,
    ) -> bool:
        normalized = f" {_normalize_match_text(direct_evidence_text)} "
        if not normalized.strip():
            return False
        for variable in variables:
            tokens = _meaningful_match_tokens(variable)
            if not tokens:
                continue
            if len(tokens) == 1 and _quote_term_hits(
                normalized,
                _quote_hint_terms(variable),
            ):
                return True
            phrase = " ".join(tokens)
            if f" {phrase} " in normalized:
                return True
            token_hits = sum(
                1 for token in set(tokens) if f" {token} " in normalized
            )
            if token_hits >= 2:
                return True
        return False

    def _concrete_variable_terms(self, text: str) -> list[str]:
        normalized = f" {_normalize_match_text(text)} "
        variables: list[str] = []
        if " ved " in normalized or " volumetric energy density " in normalized:
            variables.append("VED")
        elif " energy density " in normalized:
            variables.append("energy density")
        phrase_variables = (
            ("laser power", ("laser power",)),
            ("scan speed", ("scan speed", "scanning speed")),
            ("heat treatment time", ("heat treatment time",)),
            ("heat treatment pressure", ("heat treatment pressure",)),
            ("heat treatment temperature", ("heat treatment temperature",)),
            ("preheating temperature", ("preheating temperature",)),
            (
                "build platform preheating temperature",
                ("build platform preheating temperature",),
            ),
            ("build platform preheating", ("build platform preheating",)),
        )
        for display, phrases in phrase_variables:
            if any(f" {phrase} " in normalized for phrase in phrases):
                variables.append(display)
        return _dedupe_strings(variables)

    def _finding_mediators(self, relations: list[dict[str, Any]]) -> list[str]:
        return _dedupe_strings(
            [
                segment
                for relation in relations
                for segment in self._relation_object_chain(relation)[:-1]
            ]
        )

    def _finding_outcomes(
        self,
        effect: Mapping[str, Any],
        relations: list[dict[str, Any]],
    ) -> list[str]:
        outcomes = _dedupe_strings(
            [
                chain[-1]
                for relation in relations
                if (chain := self._relation_object_chain(relation))
            ]
        )
        if outcomes:
            return outcomes
        fallback = _text(effect.get("target_property"))
        return [fallback] if fallback else []

    def _relation_object_chain(self, relation: Mapping[str, Any]) -> list[str]:
        object_text = _text(relation.get("object")) or ""
        return [
            segment
            for segment in (
                self._presentation_relation_side(part)
                for part in object_text.split("->")
            )
            if segment
        ]

    def _finding_direction(
        self,
        effect: Mapping[str, Any],
        relations: list[dict[str, Any]],
    ) -> str:
        for relation in relations:
            for value in (relation.get("predicate"), relation.get("relation_type")):
                text = _text(value)
                if text and _looks_user_facing(text):
                    return text
        return _text(effect.get("effect_direction")) or ""

    def _finding_evidence_bundle(
        self,
        effect: Mapping[str, Any],
        *,
        evidence_by_id: Mapping[str, dict[str, Any]],
        relations: list[dict[str, Any]],
        outcomes: list[str],
    ) -> dict[str, list[str]]:
        bundle: dict[str, list[str]] = {
            "direct_result": [],
            "mechanism": [],
            "condition_context": [],
            "background": [],
            "conflict": [],
            "noise": [],
            "uncategorized": [],
        }
        relation_evidence_ref_ids = {
            ref_id
            for relation in relations
            for ref_id in _strings(relation.get("evidence_ref_ids"))
        }
        target_terms = self._finding_target_terms(effect, outcomes)
        for ref_id in _strings(effect.get("evidence_ref_ids")):
            evidence_ref = evidence_by_id.get(ref_id, {})
            role = _text(evidence_ref.get("evidence_role"))
            bundle_key = self._finding_bundle_key_for_role(
                role,
                fallback_direct=(
                    not role
                    and ref_id in relation_evidence_ref_ids
                    and self._evidence_matches_finding_target(
                        evidence_ref,
                        target_terms,
                    )
                ),
            )
            bundle[bundle_key].append(ref_id)
        return bundle

    def _finding_result_source_bundle(
        self,
        effect: Mapping[str, Any],
        *,
        evidence_bundle: Mapping[str, list[str]],
        evidence_by_id: Mapping[str, dict[str, Any]],
        relations: list[dict[str, Any]],
        outcomes: list[str],
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> dict[str, list[str]]:
        direct_ref_ids = _strings(evidence_bundle.get("direct_result"))
        if not direct_ref_ids:
            return {key: list(value) for key, value in evidence_bundle.items()}
        target_terms = self._finding_target_terms(effect, outcomes)
        variable_terms: set[str] = set()
        relation_terms: set[str] = set()
        for relation in relations:
            variable_terms.update(
                _quote_hint_terms(
                    self._presentation_relation_side(relation.get("subject"))
                )
            )
            for value in (
                _text(relation.get("predicate")),
                _text(relation.get("relation_type")),
                self._presentation_relation_summary(relation),
                " ".join(self._relation_object_chain(relation)),
            ):
                relation_terms.update(_quote_hint_terms(value))
        for value in (
            _text(effect.get("variable_axis")),
            _text(effect.get("statement")),
            _text(effect.get("title")),
            _text(effect.get("effect_direction")),
        ):
            relation_terms.update(_quote_hint_terms(value))
        if not target_terms or not (variable_terms or relation_terms):
            return {key: list(value) for key, value in evidence_bundle.items()}
        current_best_score = max(
            self._evidence_result_source_score(
                evidence_by_id.get(ref_id, {}),
                blocks_by_id=blocks_by_id,
            )
            for ref_id in direct_ref_ids
        )
        if current_best_score >= 4:
            return {key: list(value) for key, value in evidence_bundle.items()}
        def document_id_for(evidence_ref: Mapping[str, Any]) -> str:
            document_id = _text(evidence_ref.get("document_id"))
            if document_id:
                return document_id
            locator = _locator_mapping(evidence_ref.get("locator"))
            block = blocks_by_id.get(_text(locator.get("source_ref")) or "")
            return _text(block.document_id if block else None) or ""

        direct_document_ids = {
            document_id
            for ref_id in direct_ref_ids
            if (document_id := document_id_for(evidence_by_id.get(ref_id, {})))
        }
        candidate_ref_ids = _dedupe_strings(
            [
                ref_id
                for ref_id, ref in evidence_by_id.items()
                if not direct_document_ids or document_id_for(ref) in direct_document_ids
            ]
        )
        candidates: list[tuple[int, int, str]] = []
        for index, ref_id in enumerate(candidate_ref_ids):
            if ref_id in direct_ref_ids:
                continue
            evidence_ref = evidence_by_id.get(ref_id, {})
            score = self._evidence_result_source_score(
                evidence_ref,
                blocks_by_id=blocks_by_id,
            )
            if score < 4 or score <= current_best_score:
                continue
            searchable = self._evidence_ref_source_text(
                evidence_ref,
                blocks_by_id=blocks_by_id,
            )
            if not searchable:
                continue
            bounded = f" {searchable} "
            target_hits = _quote_term_hits(bounded, target_terms)
            variable_hits = _quote_term_hits(bounded, variable_terms)
            relation_hits = _quote_term_hits(bounded, relation_terms)
            if not (target_hits and (variable_hits or relation_hits)):
                continue
            candidates.append((score, -index, ref_id))
        if not candidates:
            return {key: list(value) for key, value in evidence_bundle.items()}
        preferred_ref_id = max(candidates)[2]
        updated = {
            key: [ref_id for ref_id in value if ref_id != preferred_ref_id]
            for key, value in evidence_bundle.items()
        }
        updated["direct_result"] = [preferred_ref_id]
        updated["uncategorized"] = _dedupe_strings(
            [
                *updated.get("uncategorized", []),
                *[
                    ref_id
                    for ref_id in direct_ref_ids
                    if ref_id != preferred_ref_id
                    and ref_id not in updated.get("uncategorized", [])
                ],
            ]
        )
        return updated

    def _finding_target_terms(
        self,
        effect: Mapping[str, Any],
        outcomes: list[str],
    ) -> set[str]:
        target_texts = outcomes or [_text(effect.get("target_property")) or ""]
        terms: set[str] = set()
        for text in target_texts:
            tokens = _meaningful_match_tokens(text)
            if not tokens:
                continue
            phrase = _normalize_match_text(" ".join(tokens))
            if len(tokens) >= 2:
                terms.add(phrase)
                for index in range(len(tokens) - 1):
                    terms.add(f"{tokens[index]} {tokens[index + 1]}")
            for token in tokens:
                terms.update(_target_token_variants(token))
        return {term for term in terms if term}

    def _evidence_matches_finding_target(
        self,
        evidence_ref: Mapping[str, Any],
        target_terms: set[str],
    ) -> bool:
        if not target_terms:
            return False
        searchable = self._evidence_search_text(evidence_ref)
        if not searchable:
            return False
        bounded = f" {searchable} "
        return any(f" {term} " in bounded for term in target_terms)

    def _evidence_search_text(self, evidence_ref: Mapping[str, Any]) -> str:
        locator = _mapping(evidence_ref.get("locator"))
        parts = [
            _text(evidence_ref.get("quote")),
            _text(evidence_ref.get("label")),
            *_display_values(locator),
        ]
        return _normalize_match_text(" ".join(part for part in parts if part))

    def _evidence_result_source_score(
        self,
        evidence_ref: Mapping[str, Any],
        *,
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> int:
        searchable = self._evidence_ref_source_text(
            evidence_ref,
            blocks_by_id=blocks_by_id,
        )
        if not searchable:
            return 0
        score = 0
        locator = _locator_mapping(evidence_ref.get("locator"))
        block = blocks_by_id.get(_text(locator.get("source_ref")) or "")
        heading = _normalize_match_text(_text(block.heading_path if block else None) or "")
        is_background_heading = any(
            term in heading
            for term in ("abstract", "introduction", "background", "references")
        )
        for cue in (
            "result",
            "results",
            "discussion",
            "conclusion",
            "conclusions",
            "show",
            "showed",
            "demonstrate",
            "demonstrated",
            "attributed",
            "increased",
            "decreased",
            "reduced",
            "improved",
        ):
            if f" {cue} " in f" {searchable} ":
                score += 2
        if re.search(r"\b\d+(?:\.\d+)?\s*(?:%|c|k|w|mpa|gpa|hv|mm/s|um)\b", searchable):
            score += 2
        if any(term in heading for term in ("result", "discussion", "conclusion")):
            score += 3
        if is_background_heading:
            score -= 8
        if any(
            f" {cue} " in f" {searchable} "
            for cue in (
                "abstract",
                "introduction",
                "background",
                "aim",
                "aims",
                "objective",
                "objectives",
                "method",
                "methods",
                "study aims",
            )
        ):
            score -= 4
        return score

    def _evidence_ref_source_text(
        self,
        evidence_ref: Mapping[str, Any],
        *,
        blocks_by_id: Mapping[str, SourceBlock],
    ) -> str:
        locator = _locator_mapping(evidence_ref.get("locator"))
        block = blocks_by_id.get(_text(locator.get("source_ref")) or "")
        parts = [
            _text(evidence_ref.get("quote")),
            _text(evidence_ref.get("label")),
            _text(locator.get("source_ref")),
            _text(locator.get("source_kind")),
            _text(evidence_ref.get("source_kind")),
            _text(block.heading_path if block else None),
            _text(block.text if block else None),
        ]
        return _normalize_match_text(" ".join(part for part in parts if part))

    def _finding_bundle_key_for_role(
        self,
        evidence_role: str | None,
        *,
        fallback_direct: bool = False,
    ) -> str:
        normalized = (_text(evidence_role) or "").lower()
        if normalized == "direct_support":
            return "direct_result"
        if normalized in {"mediator_context", "mechanism"}:
            return "mechanism"
        if normalized in {"condition_context", "context"}:
            return "condition_context"
        if normalized in {"background_context", "background"}:
            return "background"
        if normalized in {"conflict", "conflicting"}:
            return "conflict"
        if normalized in {"noise", "irrelevant"}:
            return "noise"
        if fallback_direct:
            return "direct_result"
        return "uncategorized"

    def _finding_support_grade(
        self,
        effect: Mapping[str, Any],
        *,
        evidence_bundle: Mapping[str, list[str]],
        outcomes: list[str],
        relation_ids: list[str],
        review_status: str,
        scope_summary: str,
    ) -> str:
        support_status = (_text(effect.get("support_status")) or "limited").lower()
        direct_count = len(evidence_bundle.get("direct_result", []))
        evidence_count = int(effect.get("evidence_count") or 0)
        has_mechanism = self._finding_has_mechanism_support(evidence_bundle)
        has_direct = self._finding_has_direct_support(evidence_bundle)
        if support_status == "conflicted" or evidence_bundle.get("conflict"):
            return "conflict"
        if support_status == "unsupported" or evidence_count == 0 or not outcomes:
            return "insufficient"
        if not has_direct:
            return "weak" if has_mechanism else "insufficient"
        if not relation_ids or not scope_summary:
            return "weak"
        if review_status == "needs_review":
            return "partial"
        if direct_count >= 2 or has_mechanism:
            return "strong"
        if support_status == "supported":
            return "partial"
        return "weak"

    def _finding_has_direct_support(self, bundle: Mapping[str, list[str]]) -> bool:
        return bool(bundle.get("direct_result"))

    def _finding_has_mechanism_support(self, bundle: Mapping[str, list[str]]) -> bool:
        return bool(bundle.get("mechanism"))

    def _finding_review_status(self, effect: Mapping[str, Any]) -> str:
        return "needs_review" if effect.get("needs_review") else "pending_review"

    def _finding_quote_hints_by_evidence_ref(
        self,
        findings: list[dict[str, Any]],
        *,
        relations_by_id: Mapping[str, dict[str, Any]],
    ) -> dict[str, dict[str, set[str]]]:
        hints_by_ref: dict[str, dict[str, set[str]]] = {}
        for finding in findings:
            direct_ref_ids = _strings(
                _mapping(finding.get("evidence_bundle")).get("direct_result")
            )
            if not direct_ref_ids:
                continue
            hint_terms = {
                "variable": set(),
                "outcome": set(),
                "relation": set(),
            }
            for value in _strings(finding.get("variables")):
                hint_terms["variable"].update(_quote_hint_terms(value))
            for value in _strings(finding.get("outcomes")):
                hint_terms["outcome"].update(_quote_hint_terms(value))
            for value in (
                _text(finding.get("statement")),
                _text(finding.get("title")),
                _text(finding.get("direction")),
                *_strings(finding.get("mediators")),
            ):
                hint_terms["relation"].update(_quote_hint_terms(value))
            for relation_id in _strings(finding.get("relation_ids")):
                relation = relations_by_id.get(relation_id, {})
                hint_terms["variable"].update(
                    _quote_hint_terms(
                        self._presentation_relation_side(relation.get("subject"))
                    )
                )
                object_chain = self._relation_object_chain(relation)
                if object_chain:
                    hint_terms["outcome"].update(_quote_hint_terms(object_chain[-1]))
                    for mediator in object_chain[:-1]:
                        hint_terms["relation"].update(_quote_hint_terms(mediator))
                for value in (
                    _text(relation.get("predicate")),
                    _text(relation.get("relation_type")),
                    self._presentation_relation_summary(relation),
                ):
                    hint_terms["relation"].update(_quote_hint_terms(value))
            if not any(hint_terms.values()):
                continue
            for ref_id in direct_ref_ids:
                ref_hints = hints_by_ref.setdefault(
                    ref_id,
                    {"variable": set(), "outcome": set(), "relation": set()},
                )
                for key, terms in hint_terms.items():
                    ref_hints[key].update(terms)
        return hints_by_ref

    def _presentation_effect(
        self,
        claim: Mapping[str, Any],
        *,
        relations: list[dict[str, Any]],
        evidence_by_id: dict[str, dict[str, Any]],
        contexts_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        claim_id = _text(claim.get("claim_id")) or "claim"
        evidence_ref_ids = _strings(claim.get("evidence_ref_ids"))
        context_ids = _strings(claim.get("context_ids"))
        source_object_ids = _strings(claim.get("source_object_ids"))
        direct_relations = [
            relation
            for relation in relations
            if _intersects(evidence_ref_ids, _strings(relation.get("evidence_ref_ids")))
            or _intersects(source_object_ids, _strings(relation.get("source_object_ids")))
        ]
        related_relations = [
            relation
            for relation in direct_relations
            if self._reviewable_presentation_relation(relation)
        ]
        primary_relation = related_relations[0] if related_relations else {}
        contexts = [
            contexts_by_id[context_id]
            for context_id in context_ids
            if context_id in contexts_by_id
        ]
        variable_axis = self._variable_axis_for(primary_relation, contexts)
        target_property = self._target_property_for(claim, primary_relation, contexts)
        target_properties = _dedupe_strings(
            [
                property_name
                for context in contexts_by_id.values()
                if (
                    _text(context.get("context_id")) == "ctx_objective_scope"
                    or _normalize_match_text(_text(context.get("label")) or "")
                    in {"objective scope", "goal scope"}
                )
                for property_name in _strings(context.get("property_scope"))
            ]
        )
        target_terms: set[str] = set()
        for target_property_name in target_properties:
            target_terms.update(
                self._finding_target_terms(
                    {"target_property": target_property_name},
                    [],
                )
            )
        goal_axes = _dedupe_strings(
            [
                axis
                for context in contexts_by_id.values()
                if (
                    _text(context.get("context_id")) == "ctx_objective_scope"
                    or _normalize_match_text(_text(context.get("label")) or "")
                    in {"objective scope", "goal scope"}
                )
                for process_context in [_mapping(context.get("process_context"))]
                for axis in [
                    *_strings(process_context.get("variable_process_axes")),
                    *_strings(process_context.get("process_context_axes")),
                ]
            ]
        )
        goal_axis_relations = [
            relation
            for relation in related_relations
            if self._relation_matches_goal_axis(relation, goal_axes)
        ]
        if goal_axis_relations:
            related_relations = goal_axis_relations
            primary_relation = related_relations[0]
            variable_axis = self._variable_axis_for(primary_relation, contexts)
            target_property = self._target_property_for(claim, primary_relation, contexts)
        elif goal_axes and any(
            self._reviewable_presentation_relation(relation)
            and self._relation_matches_goal_axis(relation, goal_axes)
            for relation in relations
        ):
            related_relations = []
            primary_relation = {}
            variable_axis = self._variable_axis_for(primary_relation, contexts)
            target_property = self._target_property_for(claim, primary_relation, contexts)
        target_relations = [
            relation
            for relation in related_relations
            if self._relation_matches_finding_target(relation, target_terms)
        ]
        if target_relations:
            related_relations = target_relations
            primary_relation = related_relations[0]
            variable_axis = self._variable_axis_for(primary_relation, contexts)
            target_property = self._target_property_for(claim, primary_relation, [])
        relation_evidence_ref_ids = _dedupe_strings(
            [
                ref_id
                for relation in related_relations
                for ref_id in _strings(relation.get("evidence_ref_ids"))
            ]
        )
        effect_evidence_ref_ids = _dedupe_strings(
            [*evidence_ref_ids, *relation_evidence_ref_ids]
        )
        evidence_refs = [
            evidence_by_id[ref_id]
            for ref_id in effect_evidence_ref_ids
            if ref_id in evidence_by_id
        ]
        paper_count = len(
            {
                _text(ref.get("document_id"))
                for ref in evidence_refs
                if _text(ref.get("document_id"))
            }
        )
        relation_ids = [
            _text(relation.get("relation_id"))
            for relation in related_relations
            if _text(relation.get("relation_id"))
        ]
        statement = _text(claim.get("statement")) or ""
        return {
            "effect_id": f"effect_{claim_id}",
            "claim_id": claim_id,
            "title": self._effect_title(
                variable_axis=variable_axis,
                target_property=target_property,
                fallback=statement,
                relation_count=len(related_relations),
            ),
            "statement": statement,
            "claim_type": _text(claim.get("claim_type")) or "finding",
            "support_status": _text(claim.get("status")) or "limited",
            "confidence": claim.get("confidence"),
            "effect_direction": _text(primary_relation.get("relation_type"))
            or _text(primary_relation.get("predicate"))
            or "",
            "variable_axis": variable_axis,
            "target_property": target_property,
            "paper_count": paper_count,
            "evidence_count": len(evidence_refs),
            "context_summary": self._context_summary_text(contexts),
            "evidence_ref_ids": effect_evidence_ref_ids,
            "context_ids": context_ids,
            "relation_ids": relation_ids,
            "needs_review": self._effect_needs_review(
                claim,
                evidence_count=len(evidence_refs),
                relation_ids=relation_ids,
                context_summary=self._context_summary_text(contexts),
            ),
            "warnings": _strings(claim.get("warnings")),
        }

    def _presentation_relation_effect(
        self,
        relation: Mapping[str, Any],
        *,
        evidence_by_id: dict[str, dict[str, Any]],
        contexts_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        relation_id = _text(relation.get("relation_id")) or "relation"
        context_ids = _strings(relation.get("context_ids"))
        contexts = [
            contexts_by_id[context_id]
            for context_id in context_ids
            if context_id in contexts_by_id
        ]
        variable_axis = self._variable_axis_for(relation, contexts)
        target_property = self._target_property_for({}, relation, contexts)
        evidence_ref_ids = _strings(relation.get("evidence_ref_ids"))
        evidence_refs = [
            evidence_by_id[ref_id]
            for ref_id in evidence_ref_ids
            if ref_id in evidence_by_id
        ]
        paper_count = len(
            {
                _text(ref.get("document_id"))
                for ref in evidence_refs
                if _text(ref.get("document_id"))
            }
        )
        statement = self._presentation_relation_summary(relation)
        return {
            "effect_id": f"effect_{relation_id}",
            "claim_id": f"relation_{relation_id}",
            "title": self._effect_title(
                variable_axis=variable_axis,
                target_property=target_property,
                fallback=statement,
                relation_count=1,
            ),
            "statement": statement,
            "claim_type": "finding",
            "support_status": _text(relation.get("status")) or "limited",
            "confidence": relation.get("confidence"),
            "effect_direction": _text(relation.get("relation_type"))
            or _text(relation.get("predicate"))
            or "",
            "variable_axis": variable_axis,
            "target_property": target_property,
            "paper_count": paper_count,
            "evidence_count": len(evidence_refs),
            "context_summary": self._context_summary_text(contexts),
            "evidence_ref_ids": evidence_ref_ids,
            "context_ids": context_ids,
            "relation_ids": [relation_id],
            "needs_review": self._effect_needs_review(
                {"claim_type": "finding", "status": relation.get("status")},
                evidence_count=len(evidence_refs),
                relation_ids=[relation_id],
                context_summary=self._context_summary_text(contexts),
            ),
            "warnings": _strings(relation.get("warnings")),
        }

    def _effect_needs_review(
        self,
        claim: Mapping[str, Any],
        *,
        evidence_count: int,
        relation_ids: list[str],
        context_summary: str,
    ) -> bool:
        if self._needs_review(claim):
            return True
        claim_type = _text(claim.get("claim_type")) or "finding"
        if evidence_count < 2 and claim_type in {"comparison", "mechanism", "finding"}:
            return True
        if self._claim_type_requires_relation(claim_type) and not relation_ids:
            return True
        if not context_summary:
            return True
        return False

    def _claim_type_requires_relation(self, claim_type: str) -> bool:
        return claim_type in {"comparison", "mechanism", "finding"}

    def _reviewable_presentation_relation(self, relation: Mapping[str, Any]) -> bool:
        subject = self._presentation_relation_side(relation.get("subject"))
        object_chain = self._relation_object_chain(relation)
        return bool(subject and object_chain and self._presentation_relation_summary(relation))

    def _relation_matches_goal_axis(
        self,
        relation: Mapping[str, Any],
        goal_axes: list[str],
    ) -> bool:
        if not goal_axes:
            return False
        searchable = " ".join(
            item
            for item in (
                self._presentation_relation_side(relation.get("subject")),
                " ".join(self._relation_object_chain(relation)),
                self._presentation_relation_summary(relation),
            )
            if item
        )
        return any(
            self._objective_axis_tokens_match(searchable, axis)
            for axis in goal_axes
        )

    def _relation_matches_finding_target(
        self,
        relation: Mapping[str, Any],
        target_terms: set[str],
    ) -> bool:
        if not target_terms:
            return False
        broad_target_terms = {
            "mechanic",
            "mechanical",
            "mechanicals",
            "microstructural",
            "microstructure",
            "microstructureal",
            "microstructures",
            "properties",
        }
        if target_terms <= broad_target_terms:
            return False
        object_terms = self._finding_target_terms(
            {"target_property": " ".join(self._relation_object_chain(relation))},
            [],
        )
        return bool(object_terms & target_terms)

    def _presentation_relation_summary(self, relation: Mapping[str, Any]) -> str:
        statement = _text(relation.get("statement"))
        if statement and _looks_user_facing(statement):
            return statement
        subject = self._presentation_relation_side(relation.get("subject"))
        object_text = self._presentation_relation_side(relation.get("object"))
        predicate = _text(relation.get("predicate")) or _text(relation.get("relation_type"))
        if subject and object_text and _looks_user_facing(predicate):
            return f"{subject} -> {predicate} -> {object_text}"
        return ""

    def _presentation_relation_side(self, value: Any) -> str:
        text = _text(value)
        if not text or not _looks_user_facing(text):
            return ""
        if self._is_placeholder_relation_side(text):
            return ""
        lower = text.lower()
        if (
            "sample_context" in lower
            or "process_context" in lower
            or "test_condition" in lower
            or "source_object_ids" in lower
            or "evidence_ref_ids" in lower
            or lower.startswith(
                (
                    "sample_number:",
                    "condition_number:",
                    "sample id:",
                    "condition id:",
                    "sample number:",
                    "condition number:",
                )
            )
        ):
            return ""
        return text

    def _is_placeholder_relation_side(self, value: Any) -> bool:
        text = (_text(value) or "").strip()
        if not text:
            return True
        lower = text.lower()
        return lower in {
            "none",
            "null",
            "unknown",
            "n/a",
            "na",
            "not available",
            "not specified",
            "true",
            "false",
            "{}",
            "[]",
        }

    def _presentation_evidence_item(
        self,
        ref: Mapping[str, Any],
        *,
        blocks_by_id: Mapping[str, SourceBlock],
        documents_by_id: Mapping[str, SourceDocument],
        quote_hints: Mapping[str, set[str]] | None = None,
    ) -> dict[str, Any]:
        locator = _locator_mapping(ref.get("locator"))
        source_ref = _text(locator.get("source_ref"))
        label = _text(ref.get("label"))
        source_kind = _text(ref.get("source_kind")) or "unknown"
        document_id = _text(ref.get("document_id"))
        block = blocks_by_id.get(source_ref or "") if source_ref else None
        document = (
            documents_by_id.get(block.document_id)
            if block and block.document_id
            else documents_by_id.get(document_id or "")
            if document_id
            else None
        )
        paper_label = _paper_label(document)
        block_label = _block_kind_label(block)
        if paper_label:
            source_label = paper_label
        elif _looks_user_facing(source_ref):
            source_label = source_ref or ""
        elif _looks_user_facing(label):
            source_label = label or ""
        elif block_label:
            source_label = block_label
        else:
            source_label = _source_kind_label(source_kind)
        page = (
            _text(locator.get("page"))
            or _text(locator.get("page_no"))
            or _text(block.page if block else None)
        )
        title_parts = [source_label]
        if page:
            title_parts.append(f"p. {page}")
        title = " / ".join(title_parts)
        quote = _text(ref.get("quote"))
        if not quote and block:
            quote = _short_text(block.text, limit=420)
        source_text = self._presentation_source_text_for_quote(
            block,
            blocks_by_id=blocks_by_id,
            quote_hints=quote_hints or {},
        ) or quote
        quote = self._presentation_quote_for_ref(
            quote=quote,
            source_text=source_text,
            quote_hints=quote_hints or {},
        )
        heading_path = _text(block.heading_path if block else None)
        block_type = _text(block.block_type if block else None)
        value_summary = (
            _block_context_label(block)
            or (label if _looks_user_facing(label) else "")
        )
        return {
            "evidence_ref_id": _text(ref.get("evidence_ref_id")) or "",
            "document_id": document_id or (block.document_id if block else None),
            "title": title,
            "source_label": source_label,
            "source_kind": source_kind,
            "source_ref": source_ref,
            "block_type": block_type,
            "heading_path": heading_path,
            "page": page,
            "quote": quote,
            "source_text": source_text,
            "value_summary": value_summary,
            "traceability_status": _text(ref.get("traceability_status")) or "unknown",
            "evidence_role": _text(ref.get("evidence_role")),
            "confidence": ref.get("confidence"),
            "href": _text(ref.get("href")),
        }

    def _presentation_source_text_for_quote(
        self,
        block: SourceBlock | None,
        *,
        blocks_by_id: Mapping[str, SourceBlock],
        quote_hints: Mapping[str, set[str]],
    ) -> str:
        source_text = _text(block.text if block else None) or ""
        if (
            not block
            or not source_text
            or not quote_hints
            or _quote_has_concrete_result_cue(source_text)
            or not _quote_has_background_cue(source_text)
        ):
            return source_text
        source_heading = _normalize_match_text(_text(block.heading_path) or "")
        candidates = [
            candidate
            for candidate in blocks_by_id.values()
            if candidate.document_id == block.document_id
            and candidate.block_id != block.block_id
            and candidate.block_order is not None
            and block.block_order is not None
            and 0 < candidate.block_order - block.block_order <= 5
            and _normalize_match_text(_text(candidate.heading_path) or "")
            == source_heading
            and _quote_has_concrete_result_cue(_text(candidate.text) or "")
        ]
        best: tuple[int, int, str] | None = None
        for candidate in candidates:
            text = _text(candidate.text) or ""
            snippet = self._best_matching_quote_snippet(text, quote_hints)
            if not snippet:
                continue
            score = _quote_candidate_score(snippet, quote_hints)
            if score <= 0:
                continue
            ranked = (score, -(candidate.block_order or 0), text)
            if best is None or ranked > best:
                best = ranked
        return best[2] if best else source_text

    def _presentation_quote_for_ref(
        self,
        *,
        quote: str | None,
        source_text: str | None,
        quote_hints: Mapping[str, set[str]],
    ) -> str:
        fallback = _text(quote) or ""
        source = _text(source_text) or fallback
        if not source:
            return ""
        snippet = self._best_matching_quote_snippet(source, quote_hints)
        if snippet:
            return snippet
        return fallback or _short_text(source, limit=420)

    def _best_matching_quote_snippet(
        self,
        source_text: str,
        quote_hints: Mapping[str, set[str]],
    ) -> str:
        if not quote_hints:
            return ""
        sentences = _quote_sentences(source_text)
        candidates = _quote_candidates_from_sentences(sentences)
        non_background_candidates = [
            candidate
            for candidate in candidates
            if not _quote_has_background_cue(candidate)
            or _quote_has_concrete_result_cue(candidate)
        ]
        if non_background_candidates:
            candidates = non_background_candidates
        specific_sentences = [
            sentence
            for sentence in sentences
            if sentence in candidates
            and _quote_has_variable_and_outcome(sentence, quote_hints)
        ]
        if specific_sentences:
            best_specific_score = max(
                _quote_candidate_score(sentence, quote_hints)
                for sentence in specific_sentences
            )
            concrete_windows = [
                candidate
                for candidate in candidates
                if candidate not in sentences
                and _quote_has_concrete_result_cue(candidate)
                and _quote_candidate_score(candidate, quote_hints)
                >= best_specific_score + 8
            ]
            candidates = [*specific_sentences, *concrete_windows]
        best: tuple[int, int, str] | None = None
        for index, candidate in enumerate(candidates):
            score = _quote_candidate_score(candidate, quote_hints)
            if score <= 0:
                continue
            ranked = (score, -index, candidate)
            if best is None or ranked > best:
                best = ranked
        if best is None:
            return ""
        return _short_text(best[2], limit=420)

    def _source_artifact_lookups(
        self,
        collection_id: str | None,
    ) -> tuple[dict[str, SourceBlock], dict[str, SourceDocument]]:
        if not collection_id:
            return {}, {}
        try:
            blocks = self.source_artifact_repository.list_blocks(collection_id)
            documents = self.source_artifact_repository.list_documents(collection_id)
        except Exception:  # noqa: BLE001
            return {}, {}
        return (
            {block.block_id: block for block in blocks if block.block_id},
            {document.document_id: document for document in documents if document.document_id},
        )

    def _presentation_context_summary(self, context: Mapping[str, Any]) -> dict[str, Any]:
        context_id = _text(context.get("context_id")) or "context"
        material_scope = _strings(context.get("material_scope"))
        property_scope = _strings(context.get("property_scope"))
        process_values = _display_values(_mapping(context.get("process_context")))
        test_values = _display_values(_mapping(context.get("test_condition")))
        return {
            "context_id": context_id,
            "label": _text(context.get("label")) or "Context",
            "material_scope": material_scope,
            "property_scope": property_scope,
            "process_summary": _join_display_values(process_values),
            "test_summary": _join_display_values(test_values),
            "limitations": _strings(context.get("limitations")),
        }

    def _variable_axis_for(
        self,
        relation: Mapping[str, Any],
        contexts: list[dict[str, Any]],
    ) -> str:
        subject = _text(relation.get("subject"))
        if subject and _looks_user_facing(subject):
            return subject
        predicate = _text(relation.get("predicate"))
        if predicate and _looks_user_facing(predicate):
            return predicate
        for context in contexts:
            values = _display_values(_mapping(context.get("process_context")))
            if values:
                return values[0]
        return ""

    def _target_property_for(
        self,
        claim: Mapping[str, Any],
        relation: Mapping[str, Any],
        contexts: list[dict[str, Any]],
    ) -> str:
        for context in contexts:
            properties = _strings(context.get("property_scope"))
            if properties:
                return properties[0]
        object_text = _text(relation.get("object"))
        if object_text and _looks_user_facing(object_text):
            return object_text
        statement = _text(claim.get("statement")) or ""
        if "density" in statement.lower():
            return "density"
        if "microstructure" in statement.lower():
            return "microstructure"
        return ""

    def _effect_title(
        self,
        *,
        variable_axis: str,
        target_property: str,
        fallback: str,
        relation_count: int = 0,
    ) -> str:
        if relation_count and variable_axis and target_property:
            return f"{variable_axis} -> {target_property}"
        if fallback:
            return _short_text(fallback, limit=96)
        if target_property:
            return target_property
        if variable_axis:
            return variable_axis
        return "Research finding"

    def _context_summary_text(self, contexts: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for context in contexts:
            parts.extend(_strings(context.get("material_scope")))
            parts.extend(_display_values(_mapping(context.get("process_context"))))
            parts.extend(_display_values(_mapping(context.get("test_condition"))))
        return _join_display_values(_dedupe_strings(parts), limit=5)

    def _needs_review(self, claim: Mapping[str, Any]) -> bool:
        status = _text(claim.get("status")) or ""
        confidence = _confidence_or_none(claim.get("confidence"))
        return (
            status in {"limited", "conflicted", "unsupported"}
            or (confidence is not None and confidence < 0.7)
            or bool(_strings(claim.get("warnings")))
            or not bool(_strings(claim.get("evidence_ref_ids")))
        )


def _stable_ref_id(
    source_kind: str | None,
    document_id: str | None,
    fact_ids: list[str] | tuple[str, ...],
    anchor_ids: list[str] | tuple[str, ...],
    locator: Mapping[str, Any],
) -> str:
    parts = [
        source_kind or "",
        document_id or "",
        ",".join(fact_ids),
        ",".join(anchor_ids),
        "|".join(f"{key}:{locator[key]}" for key in sorted(locator, key=str)),
    ]
    from hashlib import sha1

    return f"evref_{sha1('|'.join(parts).encode('utf-8')).hexdigest()[:12]}"


def _stable_relation_id(
    relation_type: str,
    source: str,
    target: str,
    statement: str,
    evidence_unit_ids: list[str] | tuple[str, ...],
) -> str:
    parts = [
        relation_type,
        source,
        target,
        statement,
        ",".join(evidence_unit_ids),
    ]
    from hashlib import sha1

    return f"rel_{sha1('|'.join(parts).encode('utf-8')).hexdigest()[:12]}"


def _dedupe_by_id(items: list[dict[str, Any]], id_key: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        item_id = _text(item.get(id_key))
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return result


def _append_claim(claims: list[dict[str, Any]], claim: dict[str, Any]) -> None:
    if claim:
        claims.append(claim)


def _dedupe_strings(items: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _display_mapping(payload: Mapping[str, Any]) -> str:
    parts = []
    for key, value in payload.items():
        text = _text(value)
        if text:
            parts.append(f"{key}: {text}")
    return ", ".join(parts)


def _display_values(payload: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for value in payload.values():
        if isinstance(value, Mapping):
            values.extend(_display_values(value))
        elif isinstance(value, (list, tuple, set)):
            values.extend(
                text for item in value if (text := _text(item))
            )
        elif text := _text(value):
            values.append(text)
    return _dedupe_strings(values)


def _join_display_values(values: list[str] | tuple[str, ...], *, limit: int = 6) -> str:
    cleaned = [
        value
        for value in _dedupe_strings(values)
        if _looks_user_facing(value)
    ]
    if len(cleaned) > limit:
        return ", ".join((*cleaned[:limit], f"+{len(cleaned) - limit} more"))
    return ", ".join(cleaned)


def _compact_finding_scope_summary(
    raw_scope_summary: str,
    *,
    variables: list[str],
    outcomes: list[str],
) -> str:
    raw = _text(raw_scope_summary) or ""
    if not raw:
        return ""

    raw_tokens = [token.strip() for token in raw.split(",") if token.strip()]
    has_more_marker = any(
        re.fullmatch(r"\+\d+\s+more", token, flags=re.IGNORECASE)
        for token in raw_tokens
    )
    visible_tokens = [
        token
        for token in raw_tokens
        if not re.fullmatch(r"\+\d+\s+more", token, flags=re.IGNORECASE)
    ]
    visible_tokens = [
        token
        for token in visible_tokens
        if not _is_generic_finding_scope_token(token)
    ]
    if not has_more_marker and len(visible_tokens) == len(raw_tokens):
        return raw

    compact: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = _text(value)
        if not text or not _looks_user_facing(text):
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        compact.append(text)

    material_markers = (
        "316l",
        "304l",
        "steel",
        "stainless",
        "alloy",
        "aluminium",
        "aluminum",
        "titanium",
        "nickel",
        "inconel",
        "copper",
        "ti-",
        "ti6",
    )
    context_markers = (
        "lpbf",
        "l-pbf",
        "slm",
        "selective laser melting",
        "laser beam powder bed fusion",
        "powder bed fusion",
        "additive manufacturing",
        "electron beam melting",
        "directed energy deposition",
        "preheat",
        "preheating",
        "hot isostatic",
        "hip",
        "nacl",
        "corrosion",
    )

    for token in visible_tokens:
        lower = token.lower()
        if any(marker in lower for marker in material_markers):
            add(token)
    for variable in variables:
        add(variable)
    for outcome in outcomes:
        add(outcome)
    for token in visible_tokens:
        lower = token.lower()
        if any(marker in lower for marker in context_markers):
            add(token)

    if compact:
        return ", ".join(compact[:5])
    return ", ".join(visible_tokens[:4])


def _short_text(value: str, *, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}..."


def _is_generic_finding_scope_token(value: str) -> bool:
    text = _text(value)
    if not text:
        return True
    return text.lower() in {
        "axis",
        "condition",
        "control",
        "factor",
        "parameter",
        "sample",
        "specimen",
        "test sample",
        "test specimen",
        "variable",
    }


def _intersects(left: list[str] | tuple[str, ...], right: list[str] | tuple[str, ...]) -> bool:
    right_set = set(right)
    return any(item in right_set for item in left)


def _looks_user_facing(value: Any) -> bool:
    text = _text(value)
    if not text:
        return False
    lower = text.lower()
    return not (
        lower.startswith(("blk_", "tbl_", "fig_", "evref_", "claim_", "rel_", "ctx_"))
        or lower.startswith(("sample_number:", "sample_id:", "row_id:", "document_id:"))
        or "sample_context:" in lower
        or "process_context:" in lower
        or "test_condition:" in lower
        or "{" in lower
        or "}" in lower
    )


def _source_kind_label(source_kind: str) -> str:
    normalized = source_kind.replace("_", " ").strip().lower()
    if "table" in normalized:
        return "Table evidence"
    if "figure" in normalized:
        return "Figure evidence"
    if "text" in normalized or "paragraph" in normalized:
        return "Text evidence"
    return "Evidence"


def _paper_label(document: SourceDocument | None) -> str:
    if not document:
        return ""
    for value in (
        document.title,
        document.metadata.get("file_name") if isinstance(document.metadata, Mapping) else None,
        document.metadata.get("filename") if isinstance(document.metadata, Mapping) else None,
        document.document_id,
    ):
        text = _text(value)
        if text and _looks_user_facing(text):
            return _short_text(text, limit=120)
    return ""


def _block_kind_label(block: SourceBlock | None) -> str:
    if not block:
        return ""
    block_type = str(block.block_type or "").replace("_", " ").strip()
    if not block_type:
        return ""
    if block.block_order:
        return f"{block_type.title()} {block.block_order}"
    return block_type.title()


def _block_context_label(block: SourceBlock | None) -> str:
    if not block:
        return ""
    heading = _text(block.heading_path)
    if heading and _looks_user_facing(heading):
        return _short_text(heading, limit=160)
    return _block_kind_label(block)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _locator_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    text = _text(value)
    return {"source_ref": text} if text else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        items = value.values()
    elif isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = (value,)
    return _dedupe_strings([str(item).strip() for item in items if str(item).strip()])


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_match_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _meaningful_match_tokens(value: str) -> list[str]:
    return [
        token
        for token in _normalize_match_text(value).split()
        if len(token) >= 3 and token not in _FINDING_MATCH_STOPWORDS
    ]


def _target_token_variants(token: str) -> set[str]:
    variants = {token}
    domain_variants = {
        "porosity": {"pore", "pores", "porosities"},
        "pore": {"pores", "porosity"},
        "pores": {"pore", "porosity"},
        "density": {"densities"},
        "densities": {"density"},
        "microstructure": {"microstructural"},
        "microstructural": {"microstructure"},
    }
    variants.update(domain_variants.get(token, set()))
    if token.endswith("y") and len(token) > 4:
        variants.add(f"{token[:-1]}ies")
    elif token.endswith("ies") and len(token) > 5:
        variants.add(f"{token[:-3]}y")
    elif token.endswith("s") and len(token) > 4:
        variants.add(token[:-1])
    elif not token.endswith("s"):
        variants.add(f"{token}s")
    if token.endswith("al") and len(token) > 5:
        variants.add(token[:-2])
    else:
        variants.add(f"{token}al")
    return variants


def _quote_hint_terms(value: str | None) -> set[str]:
    terms: set[str] = set()
    tokens = _meaningful_match_tokens(value or "")
    for token in tokens:
        terms.update(_target_token_variants(token))
    for index in range(len(tokens) - 1):
        terms.add(f"{tokens[index]} {tokens[index + 1]}")
    return {term for term in terms if term}


def _quote_sentences(value: str) -> list[str]:
    text = " ".join(value.split())
    if not text:
        return []
    abbreviations = {"Fig.": "Fig<dot>"}
    for source, replacement in abbreviations.items():
        text = text.replace(source, replacement)
    sentences = [
        candidate.replace("Fig<dot>", "Fig.").strip()
        for candidate in re.split(r"(?<=[.!?])\s+", text)
        if candidate.strip()
    ]
    result: list[str] = []
    for sentence in sentences:
        prefix, separator, suffix = sentence.partition(":")
        normalized_prefix = _normalize_match_text(prefix)
        if (
            separator
            and suffix.strip()
            and (
                "following conclusions" in normalized_prefix
                or "based on the results" in normalized_prefix
            )
        ):
            result.append(prefix.strip() + separator)
            result.append(suffix.strip())
            continue
        result.append(sentence)
    return result


def _quote_candidates_from_sentences(sentences: list[str]) -> list[str]:
    if not sentences:
        return []
    windows = [
        f"{left} {right}"
        for left, right in zip(sentences, sentences[1:], strict=False)
    ]
    return [*sentences, *windows]


def _quote_candidate_score(candidate: str, quote_hints: Mapping[str, set[str]]) -> int:
    normalized = f" {_normalize_match_text(candidate)} "
    if not normalized.strip():
        return 0
    variable_hits = _quote_term_hits(normalized, quote_hints.get("variable", set()))
    outcome_hits = _quote_term_hits(normalized, quote_hints.get("outcome", set()))
    relation_hits = _quote_term_hits(normalized, quote_hints.get("relation", set()))
    if not (variable_hits or outcome_hits or relation_hits):
        return 0
    score = variable_hits + outcome_hits * 4 + relation_hits * 2
    if variable_hits and outcome_hits:
        score += 8
    if outcome_hits and relation_hits:
        score += 4
    if _quote_has_concrete_result_cue(candidate):
        score += 12
    has_result_cue = any(
        f" {cue} " in normalized
        for cue in (
            "result",
            "results",
            "show",
            "showed",
            "shown",
            "indicate",
            "indicated",
            "reported",
            "demonstrate",
            "demonstrated",
            "conclusion",
            "conclusions",
        )
    )
    if has_result_cue:
        score += 3
    has_background_cue = _normalized_quote_has_background_cue(normalized)
    if has_background_cue:
        score -= 12 if not has_result_cue else 4
    return score


def _quote_has_concrete_result_cue(candidate: str) -> bool:
    normalized = f" {_normalize_match_text(candidate)} "
    if re.search(r"\b\d+(?:\.\d+)?\s*(?:%|c|k|w|mpa|gpa|hv|mm/s|um)\b", candidate.lower()):
        return True
    return any(
        f" {cue} " in normalized
        for cue in (
            "increased",
            "decreased",
            "reduced",
            "improved",
            "attributed",
            "affected",
            "measured",
            "achieved",
            "observed",
            "revealed",
            "sensitive",
            "prone",
            "formed",
        )
    )


def _quote_has_variable_and_outcome(
    candidate: str,
    quote_hints: Mapping[str, set[str]],
) -> bool:
    normalized = f" {_normalize_match_text(candidate)} "
    return bool(
        _quote_term_hits(normalized, quote_hints.get("variable", set()))
        and _quote_term_hits(normalized, quote_hints.get("outcome", set()))
    )


def _quote_term_hits(normalized_candidate: str, terms: set[str]) -> int:
    return sum(1 for term in terms if f" {term} " in normalized_candidate)


def _quote_has_background_cue(candidate: str) -> bool:
    return _normalized_quote_has_background_cue(
        f" {_normalize_match_text(candidate)} "
    )


def _normalized_quote_has_background_cue(normalized_candidate: str) -> bool:
    return any(
        f" {cue} " in normalized_candidate
        for cue in (
            "aim",
            "aims",
            "objective",
            "objectives",
            "introduction",
            "prior work",
            "study evaluates",
            "study aims",
            "was investigated",
            "were investigated",
            "can be drawn",
        )
    )


def _confidence_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        numeric = float(value)
        if math.isnan(numeric):
            return None
        return round(min(1.0, max(0.0, numeric)), 2)
    except (TypeError, ValueError):
        return None


def _trace_id(
    task_type: Any,
    collection_id: str | None,
    scope_id: str | None,
    source_object_ids: list[str],
) -> str:
    payload = "\x1f".join(
        [
            _text(task_type) or "",
            collection_id or "",
            scope_id or "",
            *source_object_ids,
        ]
    )
    return "rut_" + sha1(payload.encode("utf-8")).hexdigest()[:16]
