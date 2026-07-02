from __future__ import annotations

import math
import logging
from typing import Any, Mapping

from application.core.semantic_build.llm.extractor import CoreLLMStructuredExtractor
from domain.core import ResearchUnderstanding
from domain.ports import SourceArtifactRepository
from domain.source import SourceBlock, SourceDocument
from infra.persistence.factory import build_source_artifact_repository

logger = logging.getLogger(__name__)

_RELATION_CONTEXT_LIMIT = 16
_RELATION_EVIDENCE_UNIT_LIMIT = 24


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
        relations, relation_warnings = self._objective_relations(
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
        ]
        measurement_units = [
            unit
            for unit in prioritized_units
            if (_text(unit.get("unit_kind")) or "").lower() == "measurement"
        ]

        for unit in primary_units:
            if len(claims) >= max_claims:
                break
            statement = self._statement_from_evidence_unit(unit)
            if not statement:
                continue
            claim_type = self._reviewable_objective_claim_type(unit, statement)
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
        if (
            len(claims) < max_claims
            and summary
            and self._looks_complete_claim_statement(summary)
            and not self._is_aggregate_logic_summary(summary)
        ):
            evidence_unit_ids = _strings(logic_chain.get("evidence_unit_ids"))
            _append_claim(
                claims,
                self._claim(
                    claim_type="finding",
                    statement=summary,
                    source_object_ids=evidence_unit_ids,
                    evidence_ref_ids=self._ref_ids_for(
                        evidence_unit_ids,
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
            claim_type = self._reviewable_objective_claim_type(unit, statement)
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
    ) -> tuple[list[dict[str, Any]], list[str]]:
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
            logger.warning("research understanding semantic relation extraction failed", exc_info=True)
            return deterministic_relations, ["relation_extraction_failed"]
        relations: list[dict[str, Any]] = []
        for item in getattr(extracted, "relations", []):
            relation = self._semantic_relation_from_model(
                item.model_dump(),
                evidence_ref_ids_by_unit=evidence_ref_ids_by_unit,
                context_ids=context_ids,
            )
            if relation:
                relations.append(relation)
        return _dedupe_by_id((*relations, *deterministic_relations), "relation_id"), []

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

    def _deterministic_relation_statement(
        self,
        unit: Mapping[str, Any],
        *,
        subject: str,
        predicate: str,
        target: str,
    ) -> str:
        value_payload = _mapping(unit.get("value_payload"))
        for key in ("summary", "statement", "source_value_text"):
            text = _text(value_payload.get(key))
            if text and _looks_user_facing(text):
                return _short_text(text, limit=220)
        interpretation = _text(unit.get("interpretation"))
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
            "quote": _text(source.get("quote")),
            "href": _text(source.get("href")),
        }

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
    ) -> str | None:
        if not self._looks_complete_claim_statement(statement):
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
            return "mechanism"
        return None

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
        if " is reported as " in lower and lower.endswith(" analysis."):
            return True
        return False

    def _is_aggregate_logic_summary(self, statement: str) -> bool:
        text = _text(statement) or ""
        lower = text.lower()
        if not lower:
            return True
        aggregate_signals = (
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
        blocks_by_id, documents_by_id = self._source_artifact_lookups(
            _text(scope.get("collection_id"))
        )
        evidence_items = [
            self._presentation_evidence_item(
                ref,
                blocks_by_id=blocks_by_id,
                documents_by_id=documents_by_id,
            )
            for ref in evidence_refs
        ]
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
            },
            "effects": effects,
            "evidence_items": evidence_items,
            "context_summaries": context_summaries,
        }

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
            "evidence_ref_ids": evidence_ref_ids,
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
        return bool(self._presentation_relation_summary(relation))

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

    def _presentation_evidence_item(
        self,
        ref: Mapping[str, Any],
        *,
        blocks_by_id: Mapping[str, SourceBlock],
        documents_by_id: Mapping[str, SourceDocument],
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
        source_text = _text(block.text if block else None) or quote
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
            "confidence": ref.get("confidence"),
            "href": _text(ref.get("href")),
        }

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


def _short_text(value: str, *, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}..."


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
