"""Reconstruct comparable experiments from facts across one paper's Sources."""

from __future__ import annotations

import json
import logging
import re
from hashlib import sha1
from typing import Any

from application.core.objectives import property_matching
from application.core.objectives.analysis.source_extraction import (
    ExtractedEvidenceDraft,
)
from domain.core import PaperSkim, ResearchObjective

logger = logging.getLogger(__name__)

_OBJECTIVE_PAIRWISE_SCOPE_LIMIT = 48
_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _objective_pairwise_attribution_scope(
    changed_variables: list[dict[str, Any]],
    *,
    comparable: bool,
) -> str:
    if not comparable:
        return "not_attributable"
    if len(changed_variables) > 1:
        return "joint_effect"

    axis = property_matching.normalize_property_label(
        changed_variables[0].get("name")
    )
    if axis in {
        "condition",
        "material state",
        "post processing condition",
        "processing condition",
        "sample state",
    }:
        return "association_only"
    return "isolated_effect"


def reconstruct_paper_experiments(
    *,
    collection_id: str,
    source_facts: tuple[ExtractedEvidenceDraft, ...],
    paper_skims: tuple[PaperSkim, ...],
    objectives: tuple[ResearchObjective, ...],
) -> tuple[ExtractedEvidenceDraft, ...]:
    enriched = _enrich_objective_scope_context(
        source_facts,
        paper_skims=paper_skims,
    )
    bound = _bind_objective_result_process_context(enriched)
    comparisons = _build_objective_pairwise_comparison_units(
        bound,
        objectives=objectives,
    )
    if comparisons:
        logger.info(
            "Research objective pairwise comparison units generated collection_id=%s comparison_unit_count=%s",
            collection_id,
            len(comparisons),
        )
    return (*bound, *comparisons)


def _enrich_objective_scope_context(
    units: tuple[ExtractedEvidenceDraft, ...],
    *,
    paper_skims: tuple[PaperSkim, ...],
) -> tuple[ExtractedEvidenceDraft, ...]:
    skim_by_document_id = {item.document_id: item for item in paper_skims}
    enriched: list[ExtractedEvidenceDraft] = []
    for unit in units:
        if unit.selection_status == "failed":
            enriched.append(unit)
            continue
        paper_skim = skim_by_document_id.get(unit.document_id)
        context = unit.scientific_context.to_record()
        if not context["material"]:
            material_values = _paper_skim_source_values(
                paper_skim,
                unit=unit,
                field_name="material_scope",
            )
            context["material"] = [
                {"name": "material", "value": value, "unit": None}
                for value in material_values
            ]
        if context == unit.scientific_context.to_record():
            enriched.append(unit)
            continue
        record = unit.to_record()
        record["scientific_context"] = context
        enriched.append(ExtractedEvidenceDraft.from_mapping(record))
    return tuple(enriched)


def _dedupe_objective_source_refs(
    source_ref_groups: Any,
) -> tuple[dict[str, Any], ...]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for refs in source_ref_groups:
        for ref in refs:
            key = json.dumps(ref, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(dict(ref))
    return tuple(deduped)


def _objective_source_refs_with_supports(
    source_refs: tuple[dict[str, Any], ...],
    *supports: str,
) -> tuple[dict[str, Any], ...]:
    annotated: list[dict[str, Any]] = []
    for source_ref in source_refs:
        record = dict(source_ref)
        record["supports"] = list(
            dict.fromkeys(
                (
                    *(support for support in supports if support),
                    *(
                        str(value)
                        for value in source_ref.get("supports", ())
                        if str(value).strip()
                    ),
                )
            )
        )
        annotated.append(record)
    return tuple(annotated)


def _objective_descriptive_result(
    unit: ExtractedEvidenceDraft,
    *,
    reason: str,
) -> ExtractedEvidenceDraft:
    payload = unit.to_record()
    payload["changed_variables"] = []
    payload["comparison"] = None
    payload["attribution_scope"] = "descriptive_only"
    payload["resolution_status"] = "partial"
    payload["selection_reason"] = reason
    payload["source_refs"] = [
        {
            **ref,
            "supports": [
                value
                for value in ref.get("supports", ())
                if not str(value).startswith("comparison")
                and value != "changed_variables"
            ],
        }
        for ref in unit.source_refs
    ]
    return ExtractedEvidenceDraft.from_mapping(payload)


def _bind_objective_result_process_context(
    units: tuple[ExtractedEvidenceDraft, ...],
) -> tuple[ExtractedEvidenceDraft, ...]:
    (
        process_context_by_sample,
        process_context_scopes,
        conflicting_samples,
    ) = _objective_condition_registry(units)

    bound: list[ExtractedEvidenceDraft] = []
    for unit in units:
        scope = (unit.objective_id, unit.document_id)
        unit = _objective_result_with_registered_condition_comparison(
            unit,
            process_context_by_sample=process_context_by_sample,
            conflicting_samples=conflicting_samples,
        )
        comparison = unit.comparison
        pending_process_binding = bool(
            unit.source_kind == "text_window"
            and unit.reported_result is not None
            and comparison is not None
            and not unit.changed_variables
        )
        source_claims_effect = bool(
            unit.source_kind == "text_window"
            and unit.reported_result is not None
            and comparison is not None
            and unit.attribution_scope in {"isolated_effect", "joint_effect"}
            and scope in process_context_scopes
        )
        if pending_process_binding or source_claims_effect:
            if scope not in process_context_scopes:
                bound.append(
                    _objective_descriptive_result(
                        unit,
                        reason=(
                            "Grounded result has no same-document process "
                            "context for its comparison groups."
                        ),
                    )
                )
                continue
            baseline_key = (
                unit.objective_id,
                unit.document_id,
                comparison.baseline_label.casefold(),
            )
            target_key = (
                unit.objective_id,
                unit.document_id,
                comparison.target_label.casefold(),
            )
            baseline_context = process_context_by_sample.get(baseline_key)
            target_context = process_context_by_sample.get(target_key)
            groups_are_grounded = bool(
                baseline_context is not None
                and target_context is not None
                and baseline_key not in conflicting_samples
                and target_key not in conflicting_samples
            )
            if not groups_are_grounded:
                if pending_process_binding:
                    bound.append(
                        _objective_descriptive_result(
                            unit,
                            reason=(
                                "Grounded result comparison groups do not bind "
                                "to unambiguous same-document process conditions."
                            ),
                        )
                    )
                    continue
                payload = unit.to_record()
                payload["changed_variables"] = []
                comparison_payload = comparison.to_record()
                comparison_payload.update(
                    {
                        "comparable": False,
                        "incomparability_reasons": [
                            "comparison groups do not bind to source process conditions"
                        ],
                    }
                )
                payload["comparison"] = comparison_payload
                payload["attribution_scope"] = "not_attributable"
                payload["resolution_status"] = "partial"
                bound.append(ExtractedEvidenceDraft.from_mapping(payload))
                continue

            baseline_process = {
                property_matching.normalize_property_label(item.name)
                or _objective_column_key(item.name): item
                for item in baseline_context.scientific_context.process
            }
            target_process = {
                property_matching.normalize_property_label(item.name)
                or _objective_column_key(item.name): item
                for item in target_context.scientific_context.process
            }
            changed_variables: list[dict[str, Any]] = []
            incomparability_reasons: list[str] = []
            for key in sorted(set(baseline_process) | set(target_process)):
                baseline_attribute = baseline_process.get(key)
                target_attribute = target_process.get(key)
                if baseline_attribute is None or target_attribute is None:
                    name = (
                        target_attribute.name
                        if target_attribute is not None
                        else baseline_attribute.name
                    )
                    incomparability_reasons.append(
                        "process comparison is missing one group value for "
                        f"{name}"
                    )
                else:
                    name = target_attribute.name
                    if (
                        baseline_attribute is not None
                        and target_attribute is not None
                        and baseline_attribute.value == target_attribute.value
                        and baseline_attribute.unit == target_attribute.unit
                    ):
                        continue
                changed_variables.append(
                    {
                        "name": name,
                        "baseline_value": (
                            baseline_attribute.value
                            if baseline_attribute is not None
                            else None
                        ),
                        "target_value": (
                            target_attribute.value
                            if target_attribute is not None
                            else None
                        ),
                        "unit": (
                            target_attribute.unit
                            if target_attribute is not None
                            else baseline_attribute.unit
                        ),
                    }
                )
            if not changed_variables:
                source_group_variables = [
                    {
                        "name": axis,
                        "baseline_value": comparison.baseline_label,
                        "target_value": comparison.target_label,
                        "unit": None,
                    }
                    for axis in comparison.axis_names
                    if property_matching.normalize_property_label(axis)
                    not in {
                        "condition",
                        "group",
                        "sample",
                        "sample condition",
                        "sample id",
                    }
                ]
                retain_source_group_comparison = bool(
                    comparison.comparable
                    and (
                        source_claims_effect
                        or (
                            pending_process_binding
                            and unit.attribution_scope == "association_only"
                            and source_group_variables
                        )
                    )
                )
                if retain_source_group_comparison:
                    payload = unit.to_record()
                    if not payload["changed_variables"]:
                        payload["changed_variables"] = source_group_variables
                    payload["attribution_scope"] = "association_only"
                    payload["selection_reason"] = (
                        "Source-grounded result comparison retained as an "
                        "association; linked groups share the recorded process "
                        "context but do not expose quantified process values."
                    )
                    scientific_context = unit.scientific_context.to_record()
                    scientific_context["process"] = (
                        _objective_common_pairwise_context(
                            baseline_context,
                            target_context,
                        )["process"]
                    )
                    payload["scientific_context"] = scientific_context
                    payload["source_refs"] = list(
                        _dedupe_objective_source_refs(
                            (
                                unit.source_refs,
                                baseline_context.source_refs,
                                target_context.source_refs,
                            )
                        )
                    )
                    payload["confidence"] = min(
                        unit.confidence,
                        baseline_context.confidence,
                        target_context.confidence,
                    )
                    bound.append(ExtractedEvidenceDraft.from_mapping(payload))
                    continue
                incomparability_reasons.append(
                    "bound process conditions do not contain a changed variable"
                )
            comparable = not incomparability_reasons
            payload = unit.to_record()
            payload["changed_variables"] = changed_variables
            payload["comparison"] = {
                "baseline_label": comparison.baseline_label,
                "target_label": comparison.target_label,
                "axis_names": [
                    item["name"] for item in changed_variables
                ] or list(comparison.axis_names),
                "comparable": comparable,
                "incomparability_reasons": incomparability_reasons,
            }
            payload["attribution_scope"] = _objective_pairwise_attribution_scope(
                changed_variables,
                comparable=comparable,
            )
            scientific_context = unit.scientific_context.to_record()
            scientific_context["process"] = _objective_common_pairwise_context(
                baseline_context,
                target_context,
            )["process"]
            payload["scientific_context"] = scientific_context
            payload["source_refs"] = list(
                _dedupe_objective_source_refs(
                    (
                        unit.source_refs,
                        _objective_source_refs_with_supports(
                            baseline_context.source_refs,
                            "changed_variables",
                            "comparison.axis_names",
                        ),
                        _objective_source_refs_with_supports(
                            target_context.source_refs,
                            "changed_variables",
                            "comparison.axis_names",
                        ),
                    )
                )
            )
            payload["confidence"] = min(
                unit.confidence,
                baseline_context.confidence,
                target_context.confidence,
            )
            bound.append(ExtractedEvidenceDraft.from_mapping(payload))
            continue
        if (
            unit.reported_result is None
            or unit.attribution_scope != "descriptive_only"
            or unit.scientific_context.process
        ):
            bound.append(unit)
            continue
        sample_identity = _objective_explicit_sample_identity(unit)
        key = (unit.objective_id, unit.document_id, sample_identity)
        process_context = process_context_by_sample.get(key)
        if (
            not sample_identity
            or key in conflicting_samples
            or process_context is None
        ):
            bound.append(unit)
            continue
        payload = unit.to_record()
        scientific_context = unit.scientific_context.to_record()
        scientific_context["process"] = [
            item.to_record()
            for item in process_context.scientific_context.process
        ]
        payload["scientific_context"] = scientific_context
        payload["source_refs"] = list(
            _dedupe_objective_source_refs(
                (unit.source_refs, process_context.source_refs)
            )
        )
        payload["confidence"] = min(unit.confidence, process_context.confidence)
        bound.append(ExtractedEvidenceDraft.from_mapping(payload))
    return tuple(bound)


def _objective_condition_registry(
    units: tuple[ExtractedEvidenceDraft, ...],
) -> tuple[
    dict[tuple[str, str, str], ExtractedEvidenceDraft],
    set[tuple[str, str]],
    set[tuple[str, str, str]],
]:
    registry: dict[tuple[str, str, str], ExtractedEvidenceDraft] = {}
    scopes: set[tuple[str, str]] = set()
    conflicts: set[tuple[str, str, str]] = set()
    for unit in units:
        if (
            unit.evidence_role != "condition_context"
            or not unit.scientific_context.process
        ):
            continue
        sample_identity = _objective_explicit_sample_identity(unit)
        if not sample_identity:
            continue
        key = (unit.objective_id, unit.document_id, sample_identity)
        scopes.add((unit.objective_id, unit.document_id))
        if key in conflicts:
            continue
        existing = registry.get(key)
        if existing is None:
            registry[key] = unit
            continue
        merged = _objective_merge_condition_context(existing, unit)
        if merged is None:
            conflicts.add(key)
            registry.pop(key, None)
        else:
            registry[key] = merged
    return registry, scopes, conflicts


def _objective_merge_condition_context(
    existing: ExtractedEvidenceDraft,
    incoming: ExtractedEvidenceDraft,
) -> ExtractedEvidenceDraft | None:
    context: dict[str, list[dict[str, Any]]] = {}
    added_context = False
    for context_name in ("material", "sample", "process", "test"):
        attributes = [
            item.to_record()
            for item in getattr(existing.scientific_context, context_name)
        ]
        by_name = {
            property_matching.normalize_property_label(item["name"])
            or _objective_column_key(item["name"]): item
            for item in attributes
        }
        for attribute in getattr(incoming.scientific_context, context_name):
            record = attribute.to_record()
            key = (
                property_matching.normalize_property_label(attribute.name)
                or _objective_column_key(attribute.name)
            )
            prior = by_name.get(key)
            if prior is None:
                attributes.append(record)
                by_name[key] = record
                added_context = True
                continue
            if (
                str(prior.get("value")).casefold()
                != str(record.get("value")).casefold()
                or str(prior.get("unit") or "").casefold()
                != str(record.get("unit") or "").casefold()
            ):
                return None
        context[context_name] = attributes

    if not added_context:
        return existing

    payload = existing.to_record()
    payload["scientific_context"] = context
    payload["source_refs"] = list(
        _dedupe_objective_source_refs((existing.source_refs, incoming.source_refs))
    )
    payload["confidence"] = min(existing.confidence, incoming.confidence)
    return ExtractedEvidenceDraft.from_mapping(payload)


def _objective_result_with_registered_condition_comparison(
    unit: ExtractedEvidenceDraft,
    *,
    process_context_by_sample: dict[
        tuple[str, str, str], ExtractedEvidenceDraft
    ],
    conflicting_samples: set[tuple[str, str, str]],
) -> ExtractedEvidenceDraft:
    if (
        unit.source_kind != "text_window"
        or unit.reported_result is None
        or unit.reported_result.direction != "no_change"
        or unit.comparison is not None
        or unit.changed_variables
    ):
        return unit

    source_text = "\n".join(
        str(ref.get("source_excerpt") or "").strip()
        for ref in unit.source_refs
        if str(ref.get("source_excerpt") or "").strip()
    )
    if not source_text:
        return unit
    result_position = _objective_exact_label_position(
        source_text,
        unit.reported_result.result_text,
    )
    if result_position < 0:
        return unit
    claim_context = source_text[
        max(0, result_position - 800) : result_position
        + len(unit.reported_result.result_text)
        + 400
    ]

    scope = (unit.objective_id, unit.document_id)
    if any(
        key[:2] == scope
        and _objective_exact_label_position(claim_context, key[2]) >= 0
        for key in conflicting_samples
    ):
        return unit

    mentioned: list[tuple[int, str, ExtractedEvidenceDraft]] = []
    for key, condition in process_context_by_sample.items():
        if key[:2] != scope:
            continue
        label = _objective_explicit_sample_label(condition)
        if label is None:
            continue
        position = _objective_exact_label_position(claim_context, label)
        if position >= 0:
            mentioned.append((position, label, condition))
    mentioned.sort(key=lambda item: item[0])
    if len(mentioned) < 2:
        return unit

    _baseline_position, baseline_label, baseline = mentioned[0]
    _target_position, target_label, target = mentioned[-1]
    baseline_process = {
        property_matching.normalize_property_label(item.name)
        or _objective_column_key(item.name): item
        for item in baseline.scientific_context.process
    }
    target_process = {
        property_matching.normalize_property_label(item.name)
        or _objective_column_key(item.name): item
        for item in target.scientific_context.process
    }
    if set(baseline_process) != set(target_process):
        return unit
    changed = [
        target_process[key]
        for key in sorted(baseline_process)
        if (
            baseline_process[key].value != target_process[key].value
            or baseline_process[key].unit != target_process[key].unit
        )
    ]
    if len(changed) != 1:
        return unit

    payload = unit.to_record()
    payload["comparison"] = {
        "baseline_label": baseline_label,
        "target_label": target_label,
        "axis_names": [changed[0].name],
        "comparable": True,
        "incomparability_reasons": [],
    }
    payload["attribution_scope"] = "association_only"
    payload["resolution_status"] = "partial"
    payload["selection_reason"] = (
        "Result groups were bound to unambiguous same-document experimental "
        "conditions; process attribution awaits deterministic comparison."
    )
    return ExtractedEvidenceDraft.from_mapping(payload)


def _objective_explicit_sample_label(
    unit: ExtractedEvidenceDraft,
) -> str | None:
    identity = _objective_explicit_sample_identity(unit)
    if identity is None:
        return None
    for attribute in unit.scientific_context.sample:
        if (
            attribute.name != "sample_number"
            and str(attribute.value).strip().casefold() == identity
        ):
            return str(attribute.value).strip()
    return None


def _objective_exact_label_position(source_text: str, label: str) -> int:
    parts = tuple(str(label).split())
    if not parts:
        return -1
    match = re.search(
        r"(?<!\w)" + r"\s+".join(re.escape(part) for part in parts) + r"(?!\w)",
        source_text,
        flags=re.IGNORECASE,
    )
    return match.start() if match is not None else -1


def _objective_explicit_sample_identity(
    unit: ExtractedEvidenceDraft,
) -> str | None:
    sample_values = {
        item.name: item.value
        for item in unit.scientific_context.sample
        if item.name != "sample_number"
    }
    return _objective_sample_identity_key(sample_values) or None


def _build_objective_pairwise_comparison_units(
    units: tuple[ExtractedEvidenceDraft, ...],
    *,
    objectives: tuple[ResearchObjective, ...],
) -> tuple[ExtractedEvidenceDraft, ...]:
    del objectives
    results_by_scope: dict[
        tuple[str, str, str, str | None, str, str],
        list[ExtractedEvidenceDraft],
    ] = {}
    for unit in units:
        result = unit.reported_result
        if result is None or unit.attribution_scope != "descriptive_only":
            continue
        if result.value in (None, "") or not unit.source_refs:
            continue
        primary_source = unit.source_refs[0]
        results_by_scope.setdefault(
            (
                unit.objective_id,
                unit.document_id,
                result.outcome,
                result.unit,
                str(primary_source.get("source_kind") or ""),
                str(primary_source.get("source_ref") or ""),
            ),
            [],
        ).append(unit)

    generated: list[ExtractedEvidenceDraft] = []
    generated_by_scope: dict[tuple[str, str], int] = {}
    for measurements in results_by_scope.values():
        for baseline_index, baseline in enumerate(measurements):
            for target in measurements[baseline_index + 1 :]:
                scope_key = (target.objective_id, target.document_id)
                if generated_by_scope.get(scope_key, 0) >= _OBJECTIVE_PAIRWISE_SCOPE_LIMIT:
                    break
                baseline_process = {
                    item.name.casefold(): item
                    for item in baseline.scientific_context.process
                }
                target_process = {
                    item.name.casefold(): item
                    for item in target.scientific_context.process
                }
                changed_variables: list[dict[str, Any]] = []
                changed_axis_names: list[str] = []
                incomparability_reasons: list[str] = []
                for key in sorted(set(baseline_process) | set(target_process)):
                    baseline_attribute = baseline_process.get(key)
                    target_attribute = target_process.get(key)
                    baseline_value = (
                        baseline_attribute.value if baseline_attribute else None
                    )
                    target_value = target_attribute.value if target_attribute else None
                    if baseline_value == target_value:
                        continue
                    name = (
                        target_attribute.name
                        if target_attribute is not None
                        else baseline_attribute.name
                    )
                    changed_axis_names.append(name)
                    if baseline_attribute is None or target_attribute is None:
                        incomparability_reasons.append(
                            "process comparison is missing one group value for "
                            f"{name}: {baseline_value!s} vs {target_value!s}"
                        )
                    changed_variables.append(
                        {
                            "name": name,
                            "baseline_value": baseline_value,
                            "target_value": target_value,
                            "unit": (
                                target_attribute.unit
                                if target_attribute is not None
                                else baseline_attribute.unit
                            ),
                        }
                    )
                condition_axis_names: list[str] = []
                for context_name in ("material", "test"):
                    baseline_attributes = {
                        item.name.casefold(): item
                        for item in getattr(
                            baseline.scientific_context, context_name
                        )
                    }
                    target_attributes = {
                        item.name.casefold(): item
                        for item in getattr(target.scientific_context, context_name)
                    }
                    for key in sorted(
                        set(baseline_attributes) | set(target_attributes)
                    ):
                        baseline_attribute = baseline_attributes.get(key)
                        target_attribute = target_attributes.get(key)
                        baseline_value = (
                            baseline_attribute.value if baseline_attribute else None
                        )
                        target_value = (
                            target_attribute.value if target_attribute else None
                        )
                        if baseline_value == target_value:
                            continue
                        name = (
                            target_attribute.name
                            if target_attribute is not None
                            else baseline_attribute.name
                        )
                        condition_axis_names.append(name)
                        incomparability_reasons.append(
                            f"{context_name} condition differs for {name}: "
                            f"{baseline_value!s} vs {target_value!s}"
                        )

                baseline_sample = {
                    item.name.casefold(): item
                    for item in baseline.scientific_context.sample
                }
                target_sample = {
                    item.name.casefold(): item
                    for item in target.scientific_context.sample
                }
                for key in sorted(set(baseline_sample) | set(target_sample)):
                    baseline_attribute = baseline_sample.get(key)
                    target_attribute = target_sample.get(key)
                    baseline_value = (
                        baseline_attribute.value if baseline_attribute else None
                    )
                    target_value = target_attribute.value if target_attribute else None
                    if _objective_table_column_is_sample_key(
                        _objective_column_key(key)
                    ) and _objective_sample_values_are_opaque_identifiers(
                        baseline_value,
                        target_value,
                    ):
                        continue
                    if baseline_value == target_value:
                        continue
                    name = (
                        target_attribute.name
                        if target_attribute is not None
                        else baseline_attribute.name
                    )
                    condition_axis_names.append(name)
                    incomparability_reasons.append(
                        f"sample condition differs for {name}: "
                        f"{baseline_value!s} vs {target_value!s}"
                    )

                axis_names = tuple(
                    dict.fromkeys((*changed_axis_names, *condition_axis_names))
                )
                if not axis_names:
                    continue
                baseline_sample_values = {
                    item.name: item.value
                    for item in baseline.scientific_context.sample
                }
                target_sample_values = {
                    item.name: item.value
                    for item in target.scientific_context.sample
                }
                baseline_label = (
                    _objective_sample_identity_key(baseline_sample_values)
                    or baseline.evidence_id
                )
                target_label = (
                    _objective_sample_identity_key(target_sample_values)
                    or target.evidence_id
                )
                baseline_result = baseline.reported_result
                target_result = target.reported_result
                if baseline_result is None or target_result is None:
                    continue
                direction, result_values_comparable, result_reason = (
                    _objective_pairwise_result_direction(
                        baseline_result.value,
                        target_result.value,
                    )
                )
                if result_reason is not None:
                    incomparability_reasons.append(result_reason)
                comparable = (
                    not incomparability_reasons
                    and bool(changed_variables)
                    and result_values_comparable
                )
                attribution_scope = _objective_pairwise_attribution_scope(
                    changed_variables,
                    comparable=comparable,
                )
                source_refs = _dedupe_objective_source_refs(
                    (baseline.source_refs, target.source_refs)
                )
                identity = json.dumps(
                    [
                        baseline.evidence_id,
                        target.evidence_id,
                        axis_names,
                        target_result.outcome,
                    ],
                    ensure_ascii=True,
                    sort_keys=True,
                )
                generated.append(
                    ExtractedEvidenceDraft.from_mapping(
                        {
                            "evidence_id": (
                                "oeu_cmp_"
                                + sha1(identity.encode("utf-8")).hexdigest()[:16]
                            ),
                            "objective_id": target.objective_id,
                            "document_id": target.document_id,
                            "source_kind": target.source_kind,
                            "source_ref": target.source_ref,
                            "evidence_role": "direct_result",
                            "selection_reason": (
                                "Deterministic comparison of rows from the same "
                                "result table."
                            ),
                            "selection_status": "extracted",
                            "changed_variables": changed_variables,
                            "comparison": {
                                "baseline_label": baseline_label,
                                "target_label": target_label,
                                "axis_names": list(axis_names),
                                "comparable": comparable,
                                "incomparability_reasons": (
                                    incomparability_reasons
                                ),
                            },
                            "reported_result": {
                                "outcome": target_result.outcome,
                                "value": target_result.value,
                                "baseline_value": baseline_result.value,
                                "target_value": target_result.value,
                                "unit": target_result.unit,
                                "direction": direction,
                                "result_text": (
                                    f"{target_result.outcome} changed from "
                                    f"{baseline_result.value!s} to "
                                    f"{target_result.value!s}"
                                    + (
                                        f" {target_result.unit}"
                                        if target_result.unit
                                        else ""
                                    )
                                    + f" between {baseline_label} and "
                                    f"{target_label}."
                                ),
                            },
                            "attribution_scope": attribution_scope,
                            "scientific_context": (
                                _objective_common_pairwise_context(
                                    baseline,
                                    target,
                                )
                            ),
                            "source_refs": source_refs,
                            "evidence_anchor_ids": list(
                                dict.fromkeys(
                                    (
                                        *baseline.evidence_anchor_ids,
                                        *target.evidence_anchor_ids,
                                    )
                                )
                            ),
                            "resolution_status": "resolved",
                            "confidence": min(
                                baseline.confidence, target.confidence
                            ),
                        }
                    )
                )
                generated_by_scope[scope_key] = (
                    generated_by_scope.get(scope_key, 0) + 1
                )
    return tuple(generated)


def _objective_pairwise_result_direction(
    baseline_value: Any,
    target_value: Any,
) -> tuple[str, bool, str | None]:
    numeric_types = (int, float)
    baseline_is_number = isinstance(baseline_value, numeric_types) and not isinstance(
        baseline_value, bool
    )
    target_is_number = isinstance(target_value, numeric_types) and not isinstance(
        target_value, bool
    )
    if baseline_is_number and target_is_number:
        direction = (
            "increase"
            if target_value > baseline_value
            else "decrease"
            if target_value < baseline_value
            else "no_change"
        )
        return direction, True, None

    if isinstance(baseline_value, str) and isinstance(target_value, str):
        baseline_text = " ".join(baseline_value.split())
        target_text = " ".join(target_value.split())
        if baseline_text and target_text:
            direction = (
                "no_change"
                if baseline_text.casefold() == target_text.casefold()
                else "changed"
            )
            return direction, True, None

    return (
        "unknown",
        False,
        "result value types differ between baseline and target: "
        f"{type(baseline_value).__name__} vs {type(target_value).__name__}",
    )


def _objective_common_pairwise_context(
    baseline: ExtractedEvidenceDraft,
    target: ExtractedEvidenceDraft,
) -> dict[str, list[dict[str, Any]]]:
    context: dict[str, list[dict[str, Any]]] = {}
    for context_name in ("material", "sample", "process", "test"):
        baseline_attributes = {
            item.name.casefold(): item
            for item in getattr(baseline.scientific_context, context_name)
        }
        target_attributes = {
            item.name.casefold(): item
            for item in getattr(target.scientific_context, context_name)
        }
        common: list[dict[str, Any]] = []
        for key in sorted(set(baseline_attributes) & set(target_attributes)):
            baseline_attribute = baseline_attributes[key]
            target_attribute = target_attributes[key]
            if (
                baseline_attribute.value != target_attribute.value
                or baseline_attribute.unit != target_attribute.unit
            ):
                continue
            if context_name == "sample" and _objective_table_column_is_sample_key(
                _objective_column_key(target_attribute.name)
            ) and _objective_sample_values_are_opaque_identifiers(
                baseline_attribute.value,
                target_attribute.value,
            ):
                continue
            common.append(target_attribute.to_record())
        context[context_name] = common
    return context


def _objective_sample_identity_key(
    sample_attributes: dict[str, Any],
) -> str:
    preferred_keys = (
        "sample_number",
        "sample_no",
        "sample_id",
        "sample",
        "specimen_id",
        "specimen",
        "specimens",
        "case",
        "id",
        "no",
        "printed_316l",
        "condition_number",
        "condition_no",
        "condition",
        "build_orientation",
        "specimen_orientation",
        "orientation",
    )
    normalized_items = {
        _objective_column_key(key): str(value).strip()
        for key, value in sample_attributes.items()
        if str(value).strip()
    }
    for column_key in preferred_keys:
        value_text = normalized_items.get(column_key)
        if value_text:
            return value_text.casefold()
    return "|".join(
        f"{_objective_column_key(key)}={str(value).strip().casefold()}"
        for key, value in sorted(sample_attributes.items())
        if str(value).strip()
    )


def _objective_table_column_is_sample_key(column_key: str) -> bool:
    return column_key in {
        "case",
        "condition",
        "condition_no",
        "condition_number",
        "id",
        "no",
        "printed_316l",
        "sample",
        "sample_id",
        "sample_no",
        "sample_number",
        "specimen",
        "specimen_id",
        "specimens",
    }


def _objective_sample_values_are_opaque_identifiers(*values: Any) -> bool:
    state_terms = (
        "as built",
        "as fabricated",
        "as slm",
        "annealed",
        "aged",
        "heat treated",
        "hip slm",
        "hot isostatic",
        "solution treated",
        "stress relieved",
    )
    normalized = [
        " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))
        for value in values
    ]
    return bool(normalized) and not any(
        term in value for value in normalized for term in state_terms
    )


def _objective_column_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _coerce_number(value: Any) -> float | None:
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    scientific_match = re.search(
        r"([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?:[xX\u00d7]\s*10)\s*\^?\s*([-+]?\d+)",
        text,
    )
    if scientific_match is not None:
        return float(scientific_match.group(1)) * (10 ** int(scientific_match.group(2)))
    match = _NUMBER_PATTERN.search(text)
    if match is None:
        return None
    return float(match.group(0))


def _paper_skim_source_values(
    paper_skim: PaperSkim | None,
    *,
    unit: ExtractedEvidenceDraft,
    field_name: str,
) -> tuple[str, ...]:
    if paper_skim is None:
        return ()
    unit_source_refs = {
        (unit.source_kind or "", unit.source_ref or ""),
        *(
            (
                str(item.get("source_kind") or ""),
                str(item.get("source_ref") or ""),
            )
            for item in unit.source_refs
        ),
    }
    values: list[str] = []
    seen: set[str] = set()
    for study in paper_skim.studies:
        if study.claim_scope != "current_work" or not any(
            (source_ref.source_kind, source_ref.source_ref) in unit_source_refs
            for relationship in study.relationships
            for source_ref in relationship.source_refs
        ):
            continue
        for value in getattr(study, field_name):
            text = str(value or "").strip()
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                values.append(text)
    return tuple(values)
