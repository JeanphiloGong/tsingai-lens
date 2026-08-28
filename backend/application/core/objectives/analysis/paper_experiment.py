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
from domain.core import ResearchObjective

logger = logging.getLogger(__name__)

PAPER_EXPERIMENT_RECONSTRUCTION_VERSION = "paper-experiment-reconstruction.v1"

_OBJECTIVE_PAIRWISE_SCOPE_LIMIT = 48
_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_RESULT_SERIES_MEASUREMENT_PATTERN = re.compile(
    rf"(?P<value>{_NUMBER_PATTERN.pattern})\s*"
    r"(?P<unit>%|[A-Za-z\u00b5\u03bc\u00b0][A-Za-z0-9\u00b5\u03bc\u00b0/^.\-]*)?\s*"
    rf"(?:(?:\u00b1|\+/-)\s*{_NUMBER_PATTERN.pattern}\s*"
    r"(?:%|[A-Za-z\u00b5\u03bc\u00b0][A-Za-z0-9\u00b5\u03bc\u00b0/^.\-]*)?)?\s*"
    r"[([]?\s*$"
)


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
    objectives: tuple[ResearchObjective, ...],
) -> tuple[ExtractedEvidenceDraft, ...]:
    bound = _bind_objective_result_process_context(source_facts)
    paper_facts = _merge_duplicate_paper_facts(bound)
    comparisons = _build_objective_pairwise_comparison_units(
        paper_facts,
        objectives=objectives,
    )
    if comparisons:
        logger.info(
            "Research objective pairwise comparison units generated collection_id=%s comparison_unit_count=%s",
            collection_id,
            len(comparisons),
        )
    return (*paper_facts, *comparisons)


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


def _merge_duplicate_paper_facts(
    units: tuple[ExtractedEvidenceDraft, ...],
) -> tuple[ExtractedEvidenceDraft, ...]:
    candidates_by_fact: dict[
        tuple[Any, ...],
        list[tuple[int, ExtractedEvidenceDraft]],
    ] = {}
    merged_entries: list[tuple[int, ExtractedEvidenceDraft]] = []
    for position, unit in enumerate(units):
        fact_key = _objective_paper_fact_key(unit)
        if fact_key is None:
            merged_entries.append((position, unit))
            continue
        candidates_by_fact.setdefault(fact_key, []).append((position, unit))

    for candidates in candidates_by_fact.values():
        clusters: list[tuple[int, ExtractedEvidenceDraft]] = []
        for position, unit in sorted(
            candidates,
            key=lambda item: (
                -sum(
                    len(values)
                    for values in _objective_fact_context_values(item[1]).values()
                ),
                item[0],
            ),
        ):
            incoming_context = _objective_fact_context_values(unit)
            exact_matches = [
                index
                for index, (_first_position, existing) in enumerate(clusters)
                if _objective_fact_context_values(existing) == incoming_context
            ]
            compatible_matches = [
                index
                for index, (_first_position, existing) in enumerate(clusters)
                if _objective_fact_contexts_compatible(
                    _objective_fact_context_values(existing),
                    incoming_context,
                )
            ]
            matches = exact_matches or compatible_matches
            if len(matches) != 1:
                clusters.append((position, unit))
                continue
            match = matches[0]
            first_position, existing = clusters[match]
            clusters[match] = (
                min(first_position, position),
                _objective_merge_duplicate_paper_fact(existing, unit),
            )
        merged_entries.extend(clusters)

    return tuple(
        unit
        for _position, unit in sorted(
            merged_entries,
            key=lambda item: (item[0], item[1].evidence_id),
        )
    )


def _objective_paper_fact_key(
    unit: ExtractedEvidenceDraft,
) -> tuple[Any, ...] | None:
    result = unit.reported_result
    comparison = unit.comparison
    if (
        unit.selection_status == "failed"
        or result is None
        or result.value in (None, "")
        or comparison is None
        or not comparison.comparable
        or not unit.changed_variables
        or unit.attribution_scope in {"descriptive_only", "not_attributable"}
    ):
        return None

    variables = tuple(
        sorted(
            (
                property_matching.axis_key(variable.name),
                _objective_fact_scalar_key(variable.baseline_value),
                _objective_fact_scalar_key(variable.target_value),
                _objective_fact_text_key(variable.unit),
            )
            for variable in unit.changed_variables
        )
    )
    return (
        unit.objective_id,
        unit.document_id,
        variables,
        _objective_fact_scalar_key(comparison.baseline_label),
        _objective_fact_scalar_key(comparison.target_label),
        tuple(
            sorted(
                property_matching.axis_key(name)
                for name in comparison.axis_names
            )
        ),
        property_matching.axis_key(result.outcome),
        _objective_fact_scalar_key(result.value),
        _objective_fact_scalar_key(result.baseline_value),
        _objective_fact_scalar_key(result.target_value),
        _objective_fact_text_key(result.unit),
        result.direction,
        unit.attribution_scope,
    )


def _objective_fact_context_values(
    unit: ExtractedEvidenceDraft,
) -> dict[tuple[str, str], frozenset[tuple[tuple[str, str], str]]]:
    values: dict[tuple[str, str], set[tuple[tuple[str, str], str]]] = {}
    for section in ("material", "sample", "process", "test"):
        for attribute in getattr(unit.scientific_context, section):
            name = (
                property_matching.normalize_property_label(attribute.name)
                or _objective_column_key(attribute.name)
            )
            values.setdefault((section, name), set()).add(
                (
                    _objective_fact_scalar_key(attribute.value),
                    _objective_fact_text_key(attribute.unit),
                )
            )
    return {key: frozenset(items) for key, items in values.items()}


def _objective_fact_contexts_compatible(
    left: dict[tuple[str, str], frozenset[tuple[tuple[str, str], str]]],
    right: dict[tuple[str, str], frozenset[tuple[tuple[str, str], str]]],
) -> bool:
    return left.items() <= right.items() or right.items() <= left.items()


def _objective_merge_duplicate_paper_fact(
    existing: ExtractedEvidenceDraft,
    incoming: ExtractedEvidenceDraft,
) -> ExtractedEvidenceDraft:
    payload = existing.to_record()
    payload["source_refs"] = list(
        _dedupe_objective_source_refs((existing.source_refs, incoming.source_refs))
    )
    payload["evidence_anchor_ids"] = list(
        dict.fromkeys((*existing.evidence_anchor_ids, *incoming.evidence_anchor_ids))
    )
    payload["confidence"] = min(existing.confidence, incoming.confidence)
    return ExtractedEvidenceDraft.from_mapping(payload)


def _objective_fact_scalar_key(value: Any) -> tuple[str, str]:
    if value is None:
        return ("none", "")
    if isinstance(value, bool):
        return ("bool", str(value).lower())
    if isinstance(value, (int, float)):
        return ("number", format(float(value), ".12g"))
    return ("text", _objective_fact_text_key(value))


def _objective_fact_text_key(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


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

    expanded_units = tuple(
        expanded
        for unit in units
        for expanded in _objective_results_with_registered_condition_comparisons(
            unit,
            process_context_by_sample=process_context_by_sample,
            conflicting_samples=conflicting_samples,
        )
    )
    bound: list[ExtractedEvidenceDraft] = []
    for unit in expanded_units:
        scope = (unit.objective_id, unit.document_id)
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
                _objective_condition_label_key(comparison.baseline_label),
            )
            target_key = (
                unit.objective_id,
                unit.document_id,
                _objective_condition_label_key(comparison.target_label),
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
                    scientific_context = _objective_context_with_bound_conditions(
                        unit,
                        baseline_context=baseline_context,
                        target_context=target_context,
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
            scientific_context = _objective_context_with_bound_conditions(
                unit,
                baseline_context=baseline_context,
                target_context=target_context,
            )
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
        if not sample_identity:
            bound.append(unit)
            continue
        key = (
            unit.objective_id,
            unit.document_id,
            _objective_condition_label_key(sample_identity),
        )
        process_context = process_context_by_sample.get(key)
        if (
            key in conflicting_samples
            or process_context is None
        ):
            bound.append(unit)
            continue
        payload = unit.to_record()
        scientific_context = unit.scientific_context.to_record()
        for context_name in ("material", "sample", "process", "test"):
            if scientific_context[context_name]:
                continue
            scientific_context[context_name] = [
                item.to_record()
                for item in getattr(
                    process_context.scientific_context,
                    context_name,
                )
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
        key = (
            unit.objective_id,
            unit.document_id,
            _objective_condition_label_key(sample_identity),
        )
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


def _objective_results_with_registered_condition_comparisons(
    unit: ExtractedEvidenceDraft,
    *,
    process_context_by_sample: dict[
        tuple[str, str, str], ExtractedEvidenceDraft
    ],
    conflicting_samples: set[tuple[str, str, str]],
) -> tuple[ExtractedEvidenceDraft, ...]:
    if (
        unit.source_kind != "text_window"
        or unit.reported_result is None
        or unit.comparison is not None
        or unit.changed_variables
        or unit.reported_result.direction in {"unknown", "mixed"}
    ):
        return (unit,)

    source_text = "\n".join(
        str(ref.get("source_excerpt") or "").strip()
        for ref in unit.source_refs
        if str(ref.get("source_excerpt") or "").strip()
    )
    if not source_text:
        return (unit,)
    result_position = _objective_exact_label_position(
        source_text,
        unit.reported_result.result_text,
    )
    if result_position < 0:
        return (unit,)
    claim_context = source_text[
        max(0, result_position - 800) : result_position
        + len(unit.reported_result.result_text)
        + 400
    ]
    label_context = (
        claim_context
        if unit.reported_result.direction == "no_change"
        else _objective_directional_result_claim_context(
            source_text,
            result_position=result_position,
            result_text=unit.reported_result.result_text,
        )
    )

    scope = (unit.objective_id, unit.document_id)
    if any(
        key[:2] == scope
        and _objective_exact_label_position(label_context, key[2]) >= 0
        for key in conflicting_samples
    ):
        return (unit,)

    mentioned: list[tuple[int, int, str, ExtractedEvidenceDraft]] = []
    for key, condition in process_context_by_sample.items():
        if key[:2] != scope:
            continue
        label = _objective_explicit_sample_label(condition)
        if label is None:
            continue
        span = _objective_exact_label_span(label_context, label)
        if span is not None:
            mentioned.append((*span, label, condition))
    mentioned.sort(key=lambda item: item[0])
    if len(mentioned) < 2:
        return (unit,)

    measurements = None
    if unit.reported_result.direction != "no_change":
        measurements = _objective_result_series_measurements(
            label_context,
            mentioned,
            fallback_unit=unit.reported_result.unit,
        )
        if measurements is None:
            return (unit,)
        pairs = tuple(zip(mentioned, mentioned[1:]))
    else:
        pairs = ((mentioned[0], mentioned[-1]),)

    generated: list[ExtractedEvidenceDraft] = []
    for pair_index, (baseline_item, target_item) in enumerate(pairs):
        _baseline_start, _baseline_end, baseline_label, baseline = baseline_item
        _target_start, _target_end, target_label, target = target_item
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
            return (unit,)
        changed = [
            target_process[key]
            for key in sorted(baseline_process)
            if (
                baseline_process[key].value != target_process[key].value
                or baseline_process[key].unit != target_process[key].unit
            )
        ]
        if len(changed) != 1:
            return (unit,)

        payload = unit.to_record()
        if len(pairs) > 1:
            identity = json.dumps(
                [unit.evidence_id, baseline_label, target_label],
                ensure_ascii=True,
                separators=(",", ":"),
            )
            payload["evidence_id"] = (
                f"evd_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
            )
        payload["comparison"] = {
            "baseline_label": baseline_label,
            "target_label": target_label,
            "axis_names": [changed[0].name],
            "comparable": True,
            "incomparability_reasons": [],
        }
        if measurements is not None:
            baseline_value, baseline_unit = measurements[pair_index]
            target_value, target_unit = measurements[pair_index + 1]
            pair_direction, comparable_values, _reason = (
                _objective_pairwise_result_direction(
                    baseline_value,
                    target_value,
                )
            )
            source_direction = unit.reported_result.direction
            if not comparable_values or (
                source_direction in {"increase", "decrease"}
                and pair_direction != source_direction
            ):
                return (unit,)
            result_payload = unit.reported_result.to_record()
            result_payload.update(
                {
                    "value": target_value,
                    "baseline_value": baseline_value,
                    "target_value": target_value,
                    "unit": target_unit or baseline_unit,
                    "direction": (
                        source_direction
                        if source_direction in {"improve", "worsen"}
                        else pair_direction
                    ),
                }
            )
            payload["reported_result"] = result_payload
        payload["attribution_scope"] = "association_only"
        payload["resolution_status"] = "partial"
        payload["selection_reason"] = (
            "Result groups were bound to unambiguous same-document experimental "
            "conditions; process attribution awaits deterministic comparison."
        )
        generated.append(ExtractedEvidenceDraft.from_mapping(payload))
    return tuple(generated)


def _objective_directional_result_claim_context(
    source_text: str,
    *,
    result_position: int,
    result_text: str,
) -> str:
    claim_tail = source_text[
        result_position : result_position + len(result_text) + 400
    ]
    sentence_end = re.compile(r"(?<=[.!?])(?:\s+|$)").search(
        claim_tail,
        min(len(result_text), len(claim_tail)),
    )
    if sentence_end is None:
        return claim_tail
    return claim_tail[: sentence_end.start()]


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
    span = _objective_exact_label_span(source_text, label)
    return span[0] if span is not None else -1


def _objective_exact_label_span(
    source_text: str,
    label: str,
) -> tuple[int, int] | None:
    parts = tuple(re.findall(r"[^\W\d_]+|\d+", str(label), flags=re.UNICODE))
    if not parts:
        return None
    patterns = tuple(
        (
            r"\s*".join(re.escape(character) for character in part)
            if part.isdigit() and len(part) > 1
            else re.escape(part)
        )
        for part in parts
    )
    pattern = r"(?<!\w)" + r"[\W_]*".join(patterns) + r"(?!\w)"
    for match in re.finditer(pattern, source_text, flags=re.IGNORECASE):
        preceding = source_text[: match.start()].rstrip()
        following = source_text[match.end() :].lstrip()
        if parts[0].isdigit() and preceding and preceding[-1].isdigit():
            continue
        if parts[-1].isdigit() and following and following[0].isdigit():
            continue
        return match.start(), match.end()
    return None


def _objective_result_series_measurements(
    source_text: str,
    mentioned: list[tuple[int, int, str, ExtractedEvidenceDraft]],
    *,
    fallback_unit: str | None,
) -> tuple[tuple[int | float, str | None], ...] | None:
    measurements: list[tuple[int | float, str | None]] = []
    previous_label_end = 0
    for label_start, label_end, _label, _condition in mentioned:
        segment = source_text[previous_label_end:label_start]
        match = _RESULT_SERIES_MEASUREMENT_PATTERN.search(segment)
        if match is None:
            return None
        value_text = match.group("value")
        value = float(value_text)
        if (
            value.is_integer()
            and "." not in value_text
            and "e" not in value_text.casefold()
        ):
            value = int(value)
        measurements.append((value, match.group("unit") or fallback_unit))
        previous_label_end = label_end
    units = {unit.casefold() for _value, unit in measurements if unit}
    if len(units) > 1:
        return None
    return tuple(measurements)


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


def _objective_context_with_bound_conditions(
    unit: ExtractedEvidenceDraft,
    *,
    baseline_context: ExtractedEvidenceDraft,
    target_context: ExtractedEvidenceDraft,
) -> dict[str, list[dict[str, Any]]]:
    scientific_context = unit.scientific_context.to_record()
    common_context = _objective_common_pairwise_context(
        baseline_context,
        target_context,
    )
    scientific_context["process"] = common_context["process"]
    for context_name in ("material", "sample", "test"):
        if not scientific_context[context_name]:
            scientific_context[context_name] = common_context[context_name]
    return scientific_context


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


def _objective_condition_label_key(value: Any) -> str:
    return "".join(
        character
        for character in str(value or "").strip().casefold()
        if character.isalnum()
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
