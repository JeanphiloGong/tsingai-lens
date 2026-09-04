"""Reconstruct comparable experiments from facts across one paper's Sources."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from hashlib import sha1
from typing import Any

from application.core.objectives import property_matching
from application.core.objectives.analysis.diagnostics import (
    record_analysis_diagnostic,
)
from application.core.objectives.analysis.source_extraction import (
    ExtractedEvidenceDraft,
    _objective_missing_context_fields,
)
from domain.core import ResearchObjective

logger = logging.getLogger(__name__)

# Group labels are experiment identities, not condition endpoints. Rebuild
# persisted document checkpoints so exact same-paper condition mappings replace
# labels such as R0/R1 with their source-grounded process values.
PAPER_EXPERIMENT_RECONSTRUCTION_VERSION = "paper-experiment-reconstruction.v13"

_OBJECTIVE_PAIRWISE_SCOPE_LIMIT = 48
_OBJECTIVE_MATERIAL_CONTEXT_REF_LIMIT = 8
_OBJECTIVE_GROUP_ALIAS_CONTEXT_REF_LIMIT = 8
_OBJECTIVE_DERIVED_COMPARISON_ID_PREFIX = "oeu_cmp_"
_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_RESULT_SERIES_MEASUREMENT_PATTERN = re.compile(
    rf"(?P<value>{_NUMBER_PATTERN.pattern})\s*"
    r"(?P<unit>%|[A-Za-z\u00b5\u03bc\u00b0][A-Za-z0-9\u00b5\u03bc\u00b0/^.\-]*)?\s*"
    rf"(?:(?:\u00b1|\+/-)\s*{_NUMBER_PATTERN.pattern}\s*"
    r"(?:%|[A-Za-z\u00b5\u03bc\u00b0][A-Za-z0-9\u00b5\u03bc\u00b0/^.\-]*)?)?\s*"
    r"[([]?\s*$"
)
_ENCODED_CONDITION_SCHEMA_PATTERN = re.compile(
    r"(?P<prefix>[A-Za-z][A-Za-z0-9\s,\-]{1,80}?)\s*"
    r"\((?P<body>[^()\n]{3,180})\)"
)
_ENCODED_CONDITION_LABEL_PATTERN = re.compile(r"\((?P<body>[^()]{3,120})\)")


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
    document_contexts: Mapping[str, tuple[Mapping[str, Any], ...]] | None = None,
) -> tuple[ExtractedEvidenceDraft, ...]:
    source_facts = _append_source_grounded_document_context(
        source_facts,
        objectives=objectives,
        document_contexts=document_contexts or {},
    )
    source_facts = _append_source_grounded_group_alias_context(
        source_facts,
        objectives=objectives,
        document_contexts=document_contexts or {},
    )
    bound = _bind_unambiguous_document_context(source_facts)
    bound = _bind_encoded_sample_condition_values(bound)
    bound = _bind_objective_result_process_context(bound)
    bound = _bind_objective_result_material_context(bound)
    paper_facts = _merge_duplicate_paper_facts(bound)
    paper_facts = _merge_duplicate_paper_observations(paper_facts)
    comparisons = _build_objective_pairwise_comparison_units(
        paper_facts,
        objectives=objectives,
    )
    _record_validated_context_closure(
        collection_id=collection_id,
        # Include derived comparison units in the audit so raw result anchors
        # can be marked closed by the same-paper interval that binds them.
        source_facts=(*paper_facts, *comparisons),
        objectives=objectives,
    )
    if comparisons:
        logger.info(
            "Research objective pairwise comparison units generated collection_id=%s comparison_unit_count=%s",
            collection_id,
            len(comparisons),
        )
    return (*paper_facts, *comparisons)


def _is_derived_comparison_unit(unit: ExtractedEvidenceDraft) -> bool:
    """Identify a deterministic comparison derived from source result anchors.

    Derived units are useful outputs, but they are not a second experiment
    result.  Keeping this distinction in the internal trace prevents one
    table's row measurements and its generated pairwise intervals from being
    counted twice.  The identity prefix is an implementation marker, not a
    scientific vocabulary or material-specific rule.
    """

    return unit.evidence_id.startswith(_OBJECTIVE_DERIVED_COMPARISON_ID_PREFIX)


def _source_anchor_keys(unit: ExtractedEvidenceDraft) -> frozenset[tuple[str, str]]:
    refs = list(unit.source_refs)
    if unit.source_kind and unit.source_ref:
        refs.append(
            {
                "source_kind": unit.source_kind,
                "source_ref": unit.source_ref,
            }
        )
    return frozenset(
        (
            str(ref.get("source_kind") or ""),
            str(ref.get("source_ref") or ""),
        )
        for ref in refs
        if str(ref.get("source_kind") or "") and str(ref.get("source_ref") or "")
    )


def _result_anchor_is_covered_by_derived_comparison(
    result: ExtractedEvidenceDraft,
    *,
    derived_comparisons: tuple[ExtractedEvidenceDraft, ...],
    objective: ResearchObjective,
) -> bool:
    """Return whether a raw result row participates in a complete comparison.

    A table row can be a perfectly valid source-local measurement while still
    lacking explicit variable endpoints.  The deterministic pairwise pass
    may establish those endpoints from another row in the same table.  Treat
    the raw row as closed only when the generated comparison has complete
    context and references the same Source and outcome.
    """

    result_payload = result.reported_result
    if result_payload is None:
        return False
    result_outcome = _objective_column_key(result_payload.outcome)
    result_sources = _source_anchor_keys(result)
    if not result_sources:
        return False
    for comparison in derived_comparisons:
        comparison_payload = comparison.reported_result
        if comparison_payload is None:
            continue
        if _objective_column_key(comparison_payload.outcome) != result_outcome:
            continue
        if not result_sources & _source_anchor_keys(comparison):
            continue
        if _objective_missing_context_fields(comparison, objective):
            continue
        return True
    return False


def _record_validated_context_closure(
    *,
    collection_id: str,
    source_facts: tuple[ExtractedEvidenceDraft, ...],
    objectives: tuple[ResearchObjective, ...],
) -> None:
    """Trace the post-binding closure state for each paper and Objective.

    Adaptive routing can only establish that a Source is worth reading.  This
    audit runs after source validation and same-paper reconstruction, so its
    ``closure_complete`` flag means that the retained result has the context a
    researcher needs for the current comparison, not merely that matching text
    was found.  Technical failures are counted separately and never treated as
    scientific results.
    """

    objectives_by_id = {objective.objective_id: objective for objective in objectives}
    facts_by_scope: dict[tuple[str, str], list[ExtractedEvidenceDraft]] = {}
    for fact in source_facts:
        if fact.objective_id not in objectives_by_id:
            continue
        facts_by_scope.setdefault(
            (fact.objective_id, fact.document_id),
            [],
        ).append(fact)

    for (objective_id, document_id), facts in sorted(facts_by_scope.items()):
        objective = objectives_by_id[objective_id]
        result_facts = tuple(
            fact
            for fact in facts
            if (
                fact.selection_status != "failed"
                and fact.reported_result is not None
                and not _is_derived_comparison_unit(fact)
            )
        )
        derived_comparisons = tuple(
            fact
            for fact in facts
            if fact.selection_status != "failed"
            and fact.reported_result is not None
            and _is_derived_comparison_unit(fact)
        )
        failed_count = sum(fact.selection_status == "failed" for fact in facts)
        grounded_facts = tuple(
            fact
            for fact in result_facts
            if fact.selection_status == "extracted" and bool(fact.source_refs)
        )
        incomplete_results: list[dict[str, Any]] = []
        for fact in result_facts:
            missing_fields = sorted(
                _objective_missing_context_fields(fact, objective)
            )
            if missing_fields and _result_anchor_is_covered_by_derived_comparison(
                fact,
                derived_comparisons=derived_comparisons,
                objective=objective,
            ):
                # The source row is now closed by a same-table comparison
                # interval.  Preserve the raw row in the evidence bundle but
                # do not report its pre-comparison incompleteness.
                missing_fields = []
            if missing_fields:
                incomplete_results.append(
                    {
                        "evidence_id": fact.evidence_id,
                        "source_kind": fact.source_kind,
                        "source_ref": fact.source_ref,
                        "missing_fields": missing_fields,
                    }
                )
        closed_result_count = len(result_facts) - len(incomplete_results)
        record_analysis_diagnostic(
            {
                "trace_type": "objective_validated_context_closure",
                "collection_id": collection_id,
                "objective_id": objective_id,
                "document_id": document_id,
                "closure_basis": (
                    "validated_source_grounding_and_same_paper_binding"
                ),
                "result_count": len(result_facts),
                "result_anchor_count": len(result_facts),
                "derived_comparison_count": len(derived_comparisons),
                "result_anchor_ids": [fact.evidence_id for fact in result_facts],
                "source_grounded_result_count": len(grounded_facts),
                "closed_result_count": closed_result_count,
                "incomplete_result_count": len(incomplete_results),
                "technical_failure_count": failed_count,
                "evidence_grounding_complete": bool(result_facts)
                and len(grounded_facts) == len(result_facts),
                "closure_complete": bool(result_facts)
                and closed_result_count == len(result_facts),
                "incomplete_results": incomplete_results,
            }
        )


_OBJECTIVE_CONTEXT_SECTIONS = ("material", "sample", "process", "test")
_OBJECTIVE_CONTEXT_ROLES = {
    "condition_context",
    "mechanism_context",
    "baseline_context",
    "comparison_context",
    "background_context",
}


def _bind_unambiguous_document_context(
    units: tuple[ExtractedEvidenceDraft, ...],
) -> tuple[ExtractedEvidenceDraft, ...]:
    """Attach one source-grounded context value to same-paper result facts.

    A researcher carries a paper-wide fact such as the test standard into a
    result table, but does not choose between two conflicting specimens or
    process states.  Build a conservative registry from context Sources and
    attach only fields with exactly one value for the document.  Group-specific
    process values remain the responsibility of the sample-label registry below.
    """

    values_by_scope: dict[
        tuple[str, str],
        dict[
            tuple[str, str],
            dict[tuple[tuple[str, str], str], dict[str, Any]],
        ],
    ] = {}
    for unit in units:
        if (
            unit.selection_status == "failed"
            or unit.reported_result is not None
            or unit.evidence_role not in _OBJECTIVE_CONTEXT_ROLES
            # A context Source that names a sample/group describes a local
            # experiment condition.  It must be joined by its condition key,
            # never promoted to a document-wide default for every result.
            or _objective_context_has_group_identity(unit)
        ):
            continue
        scope = (unit.objective_id, unit.document_id)
        scope_values = values_by_scope.setdefault(scope, {})
        context_refs = unit.source_refs or (
            {
                "source_kind": unit.source_kind,
                "source_ref": unit.source_ref,
            },
        )
        for section in _OBJECTIVE_CONTEXT_SECTIONS:
            for attribute in getattr(unit.scientific_context, section):
                name = (
                    property_matching.normalize_property_label(attribute.name)
                    or _objective_column_key(attribute.name)
                )
                if not name:
                    continue
                key = (section, name)
                signature = (
                    _objective_fact_scalar_key(attribute.value),
                    _objective_fact_text_key(attribute.unit),
                )
                entry = scope_values.setdefault(key, {}).get(signature)
                if entry is None:
                    scope_values.setdefault(key, {})[signature] = {
                        "attribute": attribute.to_record(),
                        "source_refs": tuple(
                            dict(ref) for ref in context_refs if isinstance(ref, Mapping)
                        ),
                        "confidence": unit.confidence,
                    }
                    continue
                entry["source_refs"] = tuple(
                    _dedupe_objective_source_refs(
                        (entry["source_refs"], context_refs)
                    )
                )
                entry["confidence"] = min(
                    float(entry["confidence"]), unit.confidence
                )

    unique_values_by_scope: dict[
        tuple[str, str],
        dict[tuple[str, str], dict[str, Any]],
    ] = {}
    for scope, fields in values_by_scope.items():
        unique_values: dict[tuple[str, str], dict[str, Any]] = {}
        for key, signatures in fields.items():
            # More than one source-grounded value means the field is not
            # document-wide.  Do not attach a guessed value to a result.
            if len(signatures) != 1:
                continue
            unique_values[key] = next(iter(signatures.values()))
        unique_values_by_scope[scope] = unique_values

    bound: list[ExtractedEvidenceDraft] = []
    for unit in units:
        if unit.selection_status == "failed" or unit.reported_result is None:
            bound.append(unit)
            continue
        fields = unique_values_by_scope.get((unit.objective_id, unit.document_id), {})
        if not fields:
            bound.append(unit)
            continue
        payload = unit.to_record()
        context = unit.scientific_context.to_record()
        source_ref_groups: list[tuple[dict[str, Any], ...]] = [unit.source_refs]
        added = False
        for (section, field_name), entry in fields.items():
            attribute = dict(entry["attribute"])
            existing_names = {
                property_matching.normalize_property_label(item.get("name"))
                or _objective_column_key(item.get("name"))
                for item in context.get(section, [])
            }
            if field_name in existing_names:
                continue
            if any(
                property_matching.axis_values_match(attribute.get("name"), axis.name)
                or property_matching.process_axis_matches_objective_scope(
                    attribute.get("name"),
                    axis.name,
                )
                for axis in unit.changed_variables
            ):
                # A field that is one of the changed axes is not fixed context.
                continue
            context.setdefault(section, []).append(attribute)
            source_ref_groups.append(
                _objective_source_refs_with_supports(
                    tuple(entry["source_refs"]),
                    f"scientific_context.{section}",
                )
            )
            payload["confidence"] = min(
                float(payload.get("confidence") or 0.0),
                float(entry["confidence"]),
            )
            added = True
        if not added:
            bound.append(unit)
            continue
        payload["scientific_context"] = context
        payload["source_refs"] = list(
            _dedupe_objective_source_refs(tuple(source_ref_groups))
        )
        bound.append(ExtractedEvidenceDraft.from_mapping(payload))
    return tuple(bound)


def _append_source_grounded_document_context(
    units: tuple[ExtractedEvidenceDraft, ...],
    *,
    objectives: tuple[ResearchObjective, ...],
    document_contexts: Mapping[str, tuple[Mapping[str, Any], ...]],
) -> tuple[ExtractedEvidenceDraft, ...]:
    """Add only explicit same-paper material context to the fact stream.

    A researcher uses a paper title, abstract, or methods paragraph to identify
    the material before reading a result table.  The result Source often does
    not repeat that identity.  This deterministic bridge keeps that legitimate
    context in the evidence lineage without asking the model to infer a
    material or trusting a paper-level screening hint.
    """

    if not document_contexts:
        return units
    objective_by_id = {objective.objective_id: objective for objective in objectives}
    existing_material_scopes = {
        (unit.objective_id, unit.document_id)
        for unit in units
        if unit.reported_result is None
        and unit.scientific_context.material
    }
    augmented: list[ExtractedEvidenceDraft] = list(units)
    for objective_id, objective in objective_by_id.items():
        if not objective.material_scope:
            continue
        document_ids = {
            unit.document_id
            for unit in units
            if unit.objective_id == objective_id
        }
        for document_id in sorted(document_ids):
            if (objective_id, document_id) in existing_material_scopes:
                continue
            matched_contexts: list[tuple[Mapping[str, Any], str]] = []
            for context in document_contexts.get(document_id, ()):
                if not isinstance(context, Mapping):
                    continue
                source_text = _document_context_text(context)
                if not source_text:
                    continue
                matched_scopes = tuple(
                    scope
                    for scope in objective.material_scope
                    if _document_context_matches_material(source_text, scope)
                )
                if len(matched_scopes) == 1:
                    matched_contexts.append((context, matched_scopes[0]))
            if not matched_contexts:
                continue
            material_values = {scope for _context, scope in matched_contexts}
            if len(material_values) != 1:
                # A paper that names multiple possible materials needs explicit
                # source-local binding; choosing one would create false evidence.
                continue
            material_value = next(iter(material_values))
            source_refs = tuple(
                {
                    **_document_context_source_ref(context),
                    "supports": ["scientific_context.material"],
                }
                for context, _scope in matched_contexts[:_OBJECTIVE_MATERIAL_CONTEXT_REF_LIMIT]
                if _document_context_source_ref(context).get("source_ref")
            )
            if not source_refs:
                continue
            identity = json.dumps(
                [objective_id, document_id, material_value, source_refs],
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            augmented.append(
                ExtractedEvidenceDraft.from_mapping(
                    {
                        "evidence_id": (
                            f"ctx_{sha1(identity.encode('utf-8')).hexdigest()[:24]}"
                        ),
                        "objective_id": objective_id,
                        "document_id": document_id,
                        "source_kind": source_refs[0]["source_kind"],
                        "source_ref": source_refs[0]["source_ref"],
                        "evidence_role": "condition_context",
                        "selection_reason": (
                            "Material identity was explicitly named in a same-paper "
                            "context Source and retained for result binding."
                        ),
                        "selection_status": "extracted",
                        "scientific_context": {
                            "material": [
                                {"name": "material", "value": material_value}
                            ]
                        },
                        "source_refs": list(source_refs),
                        "resolution_status": "resolved",
                        "confidence": 1.0,
                    }
                )
            )
    return tuple(augmented)


def _document_context_text(context: Mapping[str, Any]) -> str:
    return "\n".join(
        str(context.get(field) or "").strip()
        for field in ("text", "source_excerpt", "caption_text", "heading_path")
        if str(context.get(field) or "").strip()
    )


def _document_context_matches_material(text: str, objective_scope: str) -> bool:
    return property_matching.material_value_matches_objective_comparison_scope(
        text,
        objective_scope,
    )


def _document_context_source_ref(context: Mapping[str, Any]) -> dict[str, Any]:
    source_kind = str(context.get("source_kind") or "text_window").strip()
    if source_kind in {"block", "text"}:
        source_kind = "text_window"
    return {
        "source_kind": source_kind,
        "source_ref": str(context.get("source_ref") or "").strip(),
        "source_excerpt": _document_context_text(context),
        **{
            key: context[key]
            for key in ("page", "heading_path")
            if context.get(key) not in (None, "", [], {})
        },
    }


def _append_source_grounded_group_alias_context(
    units: tuple[ExtractedEvidenceDraft, ...],
    *,
    objectives: tuple[ResearchObjective, ...],
    document_contexts: Mapping[str, tuple[Mapping[str, Any], ...]],
) -> tuple[ExtractedEvidenceDraft, ...]:
    """Materialize explicit ``respectively`` group aliases from paper text.

    Methods often define opaque labels once (for example, two specimen sets
    are ``designated by`` short labels) and use only those labels in Results.
    A researcher carries that mapping while reading.  Preserve it as a
    source-grounded condition record so deterministic reconstruction can do
    the same without guessing from list position or general knowledge.
    """

    if not document_contexts:
        return units
    objective_by_id = {objective.objective_id: objective for objective in objectives}
    units = _annotate_explicit_group_alias_contexts(
        units,
        objectives=objectives,
        document_contexts=document_contexts,
    )
    existing_keys = {
        (
            unit.objective_id,
            unit.document_id,
            _objective_condition_label_key(
                _objective_explicit_sample_identity(unit)
            ),
        )
        for unit in units
        if unit.evidence_role == "condition_context"
        and unit.scientific_context.process
        and _objective_explicit_sample_identity(unit)
    }
    augmented = list(units)
    for objective in objective_by_id.values():
        if len(objective.variables) != 1:
            continue
        variable_name = objective.variables[0]
        for document_id, contexts in document_contexts.items():
            mappings: list[tuple[str, str, Mapping[str, Any]]] = []
            for context in contexts:
                if not isinstance(context, Mapping):
                    continue
                source_text = _document_context_text(context)
                if not source_text or not (
                    property_matching.source_text_mentions_objective_variable(
                        source_text,
                        variable_name,
                    )
                ):
                    continue
                for label, condition in _explicit_group_alias_mappings(source_text):
                    mappings.append((label, condition, context))
            if len(mappings) < 2:
                continue
            labels = {label.casefold() for label, _condition, _context in mappings}
            if len(labels) != len(mappings):
                continue
            for label, condition, context in mappings[
                :_OBJECTIVE_GROUP_ALIAS_CONTEXT_REF_LIMIT
            ]:
                key = (
                    objective.objective_id,
                    document_id,
                    _objective_condition_label_key(label),
                )
                if key in existing_keys or not key[2]:
                    continue
                source_ref = _document_context_source_ref(context)
                if not source_ref.get("source_ref"):
                    continue
                source_ref["supports"] = [
                    "scientific_context.sample",
                    "scientific_context.process",
                    "condition_join",
                ]
                identity = json.dumps(
                    [objective.objective_id, document_id, label, condition, source_ref],
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
                augmented.append(
                    ExtractedEvidenceDraft.from_mapping(
                        {
                            "evidence_id": f"ctx_{sha1(identity.encode('utf-8')).hexdigest()[:24]}",
                            "objective_id": objective.objective_id,
                            "document_id": document_id,
                            "source_kind": source_ref["source_kind"],
                            "source_ref": source_ref["source_ref"],
                            "evidence_role": "condition_context",
                            "selection_reason": (
                                "The paper explicitly maps this group label to a "
                                "condition in the same-paper Methods context."
                            ),
                            "selection_status": "extracted",
                            "scientific_context": {
                                "sample": [{"name": "group", "value": label}],
                                "process": [
                                    {
                                        "name": variable_name,
                                        "value": condition,
                                    }
                                ],
                            },
                            "source_refs": [source_ref],
                            "resolution_status": "resolved",
                            "confidence": 1.0,
                        }
                    )
                )
                existing_keys.add(key)
    return tuple(augmented)


def _annotate_explicit_group_alias_contexts(
    units: tuple[ExtractedEvidenceDraft, ...],
    *,
    objectives: tuple[ResearchObjective, ...],
    document_contexts: Mapping[str, tuple[Mapping[str, Any], ...]],
) -> tuple[ExtractedEvidenceDraft, ...]:
    """Attach an explicit paper group label to a descriptive condition Source.

    A result may call the groups ``NP`` and ``P150`` while a Methods Source
    calls them ``non-preheated build platform`` and ``build platform preheated
    to 150 C``.  The paper's explicit alias statement is the authority for
    joining those records.  The original sample wording remains in the
    context; the added ``group`` attribute is only a deterministic join key
    and keeps the alias Source in the lineage.
    """

    objectives_by_id = {objective.objective_id: objective for objective in objectives}
    mappings_by_scope: dict[tuple[str, str], tuple[tuple[str, str, Mapping[str, Any]], ...]] = {}
    for objective in objectives:
        if len(objective.variables) != 1:
            continue
        for document_id, contexts in document_contexts.items():
            mappings: list[tuple[str, str, Mapping[str, Any]]] = []
            for context in contexts:
                if not isinstance(context, Mapping):
                    continue
                text = _document_context_text(context)
                if not text or not property_matching.source_text_mentions_objective_variable(
                    text,
                    objective.variables[0],
                ):
                    continue
                mappings.extend(
                    (label, condition, context)
                    for label, condition in _explicit_group_alias_mappings(text)
                )
            if len(mappings) >= 2:
                mappings_by_scope[(objective.objective_id, document_id)] = tuple(mappings)

    if not mappings_by_scope:
        return units

    annotated: list[ExtractedEvidenceDraft] = []
    for unit in units:
        objective = objectives_by_id.get(unit.objective_id)
        mappings = mappings_by_scope.get((unit.objective_id, unit.document_id), ())
        if (
            objective is None
            or unit.reported_result is not None
            or unit.evidence_role != "condition_context"
            or not mappings
        ):
            annotated.append(unit)
            continue
        sample_identity = _objective_explicit_sample_identity(unit)
        matched: tuple[str, str, Mapping[str, Any]] | None = None
        for label, condition, context in mappings:
            if _objective_condition_label_key(sample_identity) == _objective_condition_label_key(label):
                matched = (label, condition, context)
                break
            if _objective_condition_matches_unit(unit, condition):
                if matched is not None:
                    matched = None
                    break
                matched = (label, condition, context)
        if matched is None:
            annotated.append(unit)
            continue
        label, _condition, alias_context = matched
        payload = unit.to_record()
        scientific_context = payload["scientific_context"]
        sample_attributes = scientific_context.setdefault("sample", [])
        if not any(
            _objective_condition_label_key(attribute.get("name")) == "group"
            and _objective_condition_label_key(attribute.get("value"))
            == _objective_condition_label_key(label)
            for attribute in sample_attributes
        ):
            sample_attributes.append({"name": "group", "value": label, "unit": None})
        alias_ref = _document_context_source_ref(alias_context)
        alias_ref["supports"] = ["condition_join"]
        payload["source_refs"] = list(
            _dedupe_objective_source_refs((unit.source_refs, (alias_ref,)))
        )
        payload["selection_reason"] = (
            (unit.selection_reason or "").strip()
            + " The paper explicitly maps this condition to group "
            + label
            + "."
        ).strip()
        annotated.append(ExtractedEvidenceDraft.from_mapping(payload))
    return tuple(annotated)


def _objective_condition_matches_unit(
    unit: ExtractedEvidenceDraft,
    condition: str,
) -> bool:
    condition_tokens = _objective_condition_tokens(condition)
    if not condition_tokens:
        return False
    candidate_texts = [
        str(attribute.value or "")
        for attribute in unit.scientific_context.sample
        if attribute.value not in (None, "")
    ] + [
        str(attribute.value or "")
        for attribute in unit.scientific_context.process
        if attribute.value not in (None, "")
    ]
    return any(
        _objective_condition_tokens(candidate) == condition_tokens
        for candidate in candidate_texts
    )


def _objective_condition_tokens(value: Any) -> frozenset[str]:
    text = " ".join(str(value or "").casefold().split())
    text = re.sub(r"\b(?:preheated|preheating|preheat)\b", "preheat", text)
    text = re.sub(r"\bwithout\b", "non", text)
    text = re.sub(r"\b(?:with|the|a|an|ones?|specimens?|samples?|sets?|"
                  r"fabricated|produced|prepared|made|to|under|condition)\b", " ", text)
    return frozenset(re.findall(r"[a-z]+|\d+(?:\.\d+)?", text))


def _explicit_group_alias_mappings(text: str) -> tuple[tuple[str, str], ...]:
    """Return explicit condition-to-label mappings stated with ``respectively``."""

    pattern = re.compile(
        r"(?P<conditions>[^.;\n]{5,500}?)\s+"
        r"(?:are|were)\s+(?:(?:designated|denoted)\s+(?:as|by)|"
        r"referred\s+to\s+as)\s+"
        r"(?P<labels>[^.;\n]{1,160}?),?\s+respectively\b",
        flags=re.IGNORECASE,
    )
    mappings: list[tuple[str, str]] = []
    for match in pattern.finditer(text):
        condition_parts = tuple(
            part.strip(" ,:")
            for part in re.split(
                r",\s*(?:and|&)\s+|\s+(?:and|&)\s+",
                match.group("conditions"),
                flags=re.IGNORECASE,
            )
            if part.strip(" ,:")
        )
        label_parts = tuple(
            part.strip(" ,:()[]")
            for part in re.split(
                r",\s*(?:and|&)\s+|\s+(?:and|&)\s+",
                match.group("labels"),
                flags=re.IGNORECASE,
            )
            if part.strip(" ,:()[]")
        )
        if len(condition_parts) != len(label_parts) or len(label_parts) < 2:
            continue
        resolved: list[tuple[str, str]] = []
        for condition, label in zip(condition_parts, label_parts, strict=True):
            condition = re.sub(
                r"^(?:the\s+)?(?:specimens?|samples?|groups?|ones?)\s+"
                r"(?:fabricated|produced|prepared|made)\s+",
                "",
                condition,
                flags=re.IGNORECASE,
            ).strip()
            condition = re.sub(
                r"^.*?(?=(?:the\s+)?(?:specimens?|samples?|groups?|ones?)\s+"
                r"(?:fabricated|produced|prepared|made)\s+)",
                "",
                condition,
                flags=re.IGNORECASE,
            ).strip()
            condition = re.sub(
                r"^(?:the\s+)?(?:specimens?|samples?|groups?|ones?)\s+"
                r"(?:fabricated|produced|prepared|made)\s+",
                "",
                condition,
                flags=re.IGNORECASE,
            ).strip()
            # An unconsumed comma usually means the prose contains more
            # condition arms than the parsed label list. Treat the complete
            # respectively statement atomically instead of binding a merged
            # condition to one label.
            if not condition or not label or "," in condition:
                resolved = []
                break
            resolved.append((label, condition))
        mappings.extend(resolved)
    return tuple(mappings)


def _dedupe_objective_source_refs(
    source_ref_groups: Any,
) -> tuple[dict[str, Any], ...]:
    deduped: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for refs in source_ref_groups:
        for ref in refs:
            if not isinstance(ref, Mapping):
                continue
            locator = {
                key: value
                for key, value in ref.items()
                if key not in {"supports", "source_excerpt"}
            }
            key = json.dumps(locator, ensure_ascii=False, sort_keys=True, default=str)
            existing = seen.get(key)
            if existing is None:
                existing = dict(ref)
                existing["supports"] = list(
                    dict.fromkeys(
                        str(value)
                        for value in ref.get("supports", ())
                        if str(value).strip()
                    )
                )
                seen[key] = existing
                deduped.append(existing)
                continue
            existing["supports"] = list(
                dict.fromkeys(
                    (
                        *existing.get("supports", ()),
                        *(
                            str(value)
                            for value in ref.get("supports", ())
                            if str(value).strip()
                        ),
                    )
                )
            )
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


def _merge_duplicate_paper_observations(
    units: tuple[ExtractedEvidenceDraft, ...],
) -> tuple[ExtractedEvidenceDraft, ...]:
    """Merge repeated qualitative claims from overlapping text Sources.

    A Results sentence is often present in both a section window and a nearby
    conclusion window.  Those are two provenance records for one paper claim,
    not two independent observations.  Numeric rows and explicit comparisons
    stay untouched because their values or condition endpoints may differ.
    """

    merged_by_key: dict[tuple[Any, ...], tuple[int, ExtractedEvidenceDraft]] = {}
    passthrough: list[tuple[int, ExtractedEvidenceDraft]] = []
    for position, unit in enumerate(units):
        result = unit.reported_result
        if (
            unit.selection_status == "failed"
            or result is None
            or result.value not in (None, "")
            or unit.comparison is not None
            or not result.result_text
        ):
            passthrough.append((position, unit))
            continue
        key = (
            unit.objective_id,
            unit.document_id,
            property_matching.axis_key(result.outcome),
            result.direction,
            _objective_fact_text_key(result.result_text),
            tuple(
                sorted(
                    property_matching.axis_key(variable.name)
                    for variable in unit.changed_variables
                )
            ),
            unit.attribution_scope,
        )
        existing = merged_by_key.get(key)
        if existing is None:
            merged_by_key[key] = (position, unit)
            continue
        first_position, prior = existing
        merged_by_key[key] = (
            first_position,
            _objective_merge_duplicate_paper_observation(prior, unit),
        )

    return tuple(
        unit
        for _position, unit in sorted(
            (*passthrough, *merged_by_key.values()),
            key=lambda item: (item[0], item[1].evidence_id),
        )
    )


def _objective_merge_duplicate_paper_observation(
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


def _objective_source_local_association(
    unit: ExtractedEvidenceDraft,
    *,
    reason: str,
) -> ExtractedEvidenceDraft:
    payload = unit.to_record()
    payload["attribution_scope"] = "association_only"
    payload["selection_reason"] = reason
    return ExtractedEvidenceDraft.from_mapping(payload)


def _bind_objective_result_process_context(
    units: tuple[ExtractedEvidenceDraft, ...],
) -> tuple[ExtractedEvidenceDraft, ...]:
    units = _bind_results_by_shared_condition_values(units)
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
        source_uses_group_labels_as_endpoints = bool(
            comparison is not None
            and unit.changed_variables
            and all(
                _objective_condition_label_key(variable.baseline_value)
                == _objective_condition_label_key(comparison.baseline_label)
                and _objective_condition_label_key(variable.target_value)
                == _objective_condition_label_key(comparison.target_label)
                for variable in unit.changed_variables
            )
        )
        pending_process_binding = bool(
            unit.source_kind == "text_window"
            and unit.reported_result is not None
            and comparison is not None
            and (
                not unit.changed_variables
                or (
                    source_uses_group_labels_as_endpoints
                    and unit.attribution_scope == "association_only"
                )
            )
        )
        source_claims_effect = bool(
            unit.source_kind == "text_window"
            and unit.reported_result is not None
            and comparison is not None
            and unit.attribution_scope in {"isolated_effect", "joint_effect"}
        )
        source_local_contrast_is_grounded = any(
            "changed_variables" in ref.get("supports", ())
            and "comparison.labels" in ref.get("supports", ())
            for ref in unit.source_refs
        )
        if pending_process_binding or source_claims_effect:
            if scope not in process_context_scopes:
                if source_claims_effect and source_local_contrast_is_grounded:
                    bound.append(
                        _objective_source_local_association(
                            unit,
                            reason=(
                                "Source-grounded factor contrast retained as an "
                                "association because no same-document condition "
                                "registry establishes the controlled factors."
                            ),
                        )
                    )
                    continue
                if source_claims_effect:
                    bound.append(unit)
                    continue
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
                if source_claims_effect and source_local_contrast_is_grounded:
                    bound.append(
                        _objective_source_local_association(
                            unit,
                            reason=(
                                "Source-grounded factor contrast retained as an "
                                "association because its groups do not bind to "
                                "unambiguous same-document conditions."
                            ),
                        )
                    )
                    continue
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
        added_context = False
        for context_name in ("material", "sample", "process", "test"):
            existing_attributes = scientific_context[context_name]
            existing_by_name = {
                property_matching.normalize_property_label(item.get("name"))
                or _objective_column_key(item.get("name")): item
                for item in existing_attributes
            }
            for attribute in getattr(
                process_context.scientific_context,
                context_name,
            ):
                key = (
                    property_matching.normalize_property_label(attribute.name)
                    or _objective_column_key(attribute.name)
                )
                prior = existing_by_name.get(key)
                if prior is not None:
                    if (
                        prior.get("value") != attribute.value
                        or prior.get("unit") != attribute.unit
                    ):
                        # A uniquely sample-bound condition row is the
                        # authoritative process setting. Result extraction may
                        # otherwise carry a paper-level list for the same field,
                        # which would hide a real jointly varied factor.
                        if context_name == "process":
                            position = existing_attributes.index(prior)
                            existing_attributes[position] = attribute.to_record()
                            existing_by_name[key] = existing_attributes[position]
                            added_context = True
                        continue
                    continue
                existing_attributes.append(attribute.to_record())
                existing_by_name[key] = existing_attributes[-1]
                added_context = True
        if not added_context:
            bound.append(unit)
            continue
        payload["scientific_context"] = scientific_context
        payload["source_refs"] = list(
            _dedupe_objective_source_refs(
                (
                    unit.source_refs,
                    _objective_source_refs_with_supports(
                        process_context.source_refs,
                        "scientific_context.process",
                    ),
                )
            )
        )
        payload["confidence"] = min(unit.confidence, process_context.confidence)
        bound.append(ExtractedEvidenceDraft.from_mapping(payload))
    return tuple(bound)


def _bind_results_by_shared_condition_values(
    units: tuple[ExtractedEvidenceDraft, ...],
) -> tuple[ExtractedEvidenceDraft, ...]:
    """Join result rows to condition rows when sample ids are absent.

    Papers often identify a result-table row by the experimental settings
    themselves (for example ``alpha``, ``beta`` and ``theta``) while a separate
    table assigns those settings a sample number.  A researcher uses that
    shared condition key to reconstruct one experiment.  Do the same only when
    at least two source-grounded process attributes match exactly and the
    match is unique; ambiguous rows remain unresolved instead of being guessed.
    """

    condition_units = tuple(
        unit
        for unit in units
        if (
            unit.selection_status != "failed"
            and unit.reported_result is None
            and unit.evidence_role == "condition_context"
            and unit.scientific_context.process
        )
    )
    if not condition_units:
        return units

    bound: list[ExtractedEvidenceDraft] = []
    for unit in units:
        if (
            unit.selection_status == "failed"
            or unit.reported_result is None
            or _objective_context_has_group_identity(unit)
            or not unit.scientific_context.process
        ):
            bound.append(unit)
            continue
        result_conditions = _objective_context_attribute_signatures(
            unit.scientific_context.process
        )
        if len(result_conditions) < 2:
            bound.append(unit)
            continue
        matches: list[ExtractedEvidenceDraft] = []
        for condition in condition_units:
            if (condition.objective_id, condition.document_id) != (
                unit.objective_id,
                unit.document_id,
            ):
                continue
            condition_conditions = _objective_context_attribute_signatures(
                condition.scientific_context.process
            )
            shared = set(result_conditions) & set(condition_conditions)
            if len(shared) < 2:
                continue
            if all(
                result_conditions[key] == condition_conditions[key]
                for key in shared
            ):
                matches.append(condition)
        if len(matches) != 1:
            bound.append(unit)
            continue

        condition = matches[0]
        payload = unit.to_record()
        scientific_context = unit.scientific_context.to_record()
        for section in _OBJECTIVE_CONTEXT_SECTIONS:
            existing = scientific_context[section]
            existing_keys = {
                _objective_context_attribute_key(item.get("name"))
                for item in existing
            }
            for attribute in getattr(condition.scientific_context, section):
                key = _objective_context_attribute_key(attribute.name)
                if key in existing_keys:
                    continue
                existing.append(attribute.to_record())
                existing_keys.add(key)
        payload["scientific_context"] = scientific_context
        payload["source_refs"] = list(
            _dedupe_objective_source_refs(
                (
                    unit.source_refs,
                    _objective_source_refs_with_supports(
                        condition.source_refs,
                        "condition_join",
                    ),
                )
            )
        )
        payload["confidence"] = min(unit.confidence, condition.confidence)
        payload["selection_reason"] = (
            unit.selection_reason
            or ""
        ) + (
            " Bound to a unique same-paper condition row through shared "
            "source-grounded process values."
        )
        bound.append(ExtractedEvidenceDraft.from_mapping(payload))
    return tuple(bound)


def _objective_context_attribute_key(name: Any) -> str:
    return (
        property_matching.normalize_property_label(name)
        or _objective_column_key(name)
    )


def _objective_context_has_group_identity(unit: ExtractedEvidenceDraft) -> bool:
    """Return whether a context Source is explicitly tied to one group."""

    group_keys = {
        "case",
        "condition",
        "condition_no",
        "condition_number",
        "group",
        "sample",
        "sample_id",
        "sample_no",
        "sample_number",
        "specimen",
        "specimen_id",
    }
    for attribute in unit.scientific_context.sample:
        key = _objective_column_key(attribute.name)
        value = " ".join(str(attribute.value or "").casefold().split())
        if key in group_keys:
            return True
        if re.search(
            r"\b(?:first|second|third|fourth|sample|specimen|group|condition)"
            r"(?:\s+|-|#)*[a-z]?\d+\b",
            value,
        ):
            return True
        if value in {"first sample", "second sample", "third sample"}:
            return True
    return False


def _objective_context_attribute_signatures(
    attributes: Any,
) -> dict[str, tuple[tuple[str, str], str]]:
    signatures: dict[str, tuple[tuple[str, str], str]] = {}
    for attribute in attributes or ():
        key = _objective_context_attribute_key(attribute.name)
        if not key:
            continue
        numeric_value = _coerce_number(attribute.value)
        signatures[key] = (
            _objective_fact_scalar_key(
                numeric_value if numeric_value is not None else attribute.value
            ),
            _objective_fact_text_key(
                str(attribute.unit or "")
                .casefold()
                .replace("°", "degree")
                .replace("º", "degree")
                .replace("◦", "degree")
                .replace("degrees", "degree")
            ),
        )
    return signatures


def _bind_objective_result_material_context(
    units: tuple[ExtractedEvidenceDraft, ...],
) -> tuple[ExtractedEvidenceDraft, ...]:
    material_by_scope, conflicting_scopes = _objective_material_context_registry(units)
    bound: list[ExtractedEvidenceDraft] = []
    for unit in units:
        scope = (unit.objective_id, unit.document_id)
        material_context = material_by_scope.get(scope)
        if (
            unit.selection_status == "failed"
            or unit.reported_result is None
            or unit.scientific_context.material
            or material_context is None
            or scope in conflicting_scopes
        ):
            bound.append(unit)
            continue

        payload = unit.to_record()
        scientific_context = unit.scientific_context.to_record()
        scientific_context["material"] = [
            item.to_record() for item in material_context.scientific_context.material
        ]
        payload["scientific_context"] = scientific_context
        payload["source_refs"] = list(
            _dedupe_objective_source_refs(
                (
                    unit.source_refs,
                    _objective_source_refs_with_supports(
                        material_context.source_refs,
                        "scientific_context.material",
                    ),
                )
            )
        )
        payload["confidence"] = min(unit.confidence, material_context.confidence)
        bound.append(ExtractedEvidenceDraft.from_mapping(payload))
    return tuple(bound)


def _objective_material_context_registry(
    units: tuple[ExtractedEvidenceDraft, ...],
) -> tuple[
    dict[tuple[str, str], ExtractedEvidenceDraft],
    set[tuple[str, str]],
]:
    registry: dict[tuple[str, str], ExtractedEvidenceDraft] = {}
    conflicts: set[tuple[str, str]] = set()
    for unit in units:
        if (
            unit.selection_status == "failed"
            or unit.reported_result is not None
            or not unit.scientific_context.material
        ):
            continue
        scope = (unit.objective_id, unit.document_id)
        if scope in conflicts:
            continue
        values = tuple(
            attribute.value
            for attribute in unit.scientific_context.material
            if attribute.value not in (None, "")
        )
        if not values or not _objective_material_values_are_compatible(values):
            conflicts.add(scope)
            registry.pop(scope, None)
            continue
        existing = registry.get(scope)
        if existing is None:
            registry[scope] = unit
            continue
        existing_values = tuple(
            attribute.value
            for attribute in existing.scientific_context.material
            if attribute.value not in (None, "")
        )
        if not all(
            property_matching.material_values_match_for_scope(left, right)
            for left in existing_values
            for right in values
        ):
            conflicts.add(scope)
            registry.pop(scope, None)
            continue
        payload = existing.to_record()
        payload["source_refs"] = list(
            _dedupe_objective_source_refs((existing.source_refs, unit.source_refs))
        )
        payload["confidence"] = min(existing.confidence, unit.confidence)
        registry[scope] = ExtractedEvidenceDraft.from_mapping(payload)
    return registry, conflicts


def _objective_material_values_are_compatible(values: tuple[Any, ...]) -> bool:
    return all(
        property_matching.material_values_match_for_scope(left, right)
        for position, left in enumerate(values)
        for right in values[position + 1 :]
    )


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


def _bind_encoded_sample_condition_values(
    units: tuple[ExtractedEvidenceDraft, ...],
) -> tuple[ExtractedEvidenceDraft, ...]:
    """Bind slash-encoded sample labels to an explicit Methods schema.

    Result tables frequently identify a specimen as ``sample (power/speed)``
    while the Methods section lists the allowed power and speed values.  The
    label is useful only when that source-local schema is explicit.  This
    helper therefore accepts no positional guess: every encoded value must be
    present in the corresponding source-listed value set and every variable
    must have a source-listed unit.  Ambiguous or range-only prose remains
    descriptive Evidence.
    """

    schemas_by_scope: dict[
        tuple[str, str],
        tuple[
            tuple[tuple[str, tuple[tuple[int | float, str], ...]], ...],
            ...,
        ],
    ] = {}
    for scope in {
        (unit.objective_id, unit.document_id)
        for unit in units
        if unit.reported_result is not None
    }:
        candidates: list[
            tuple[tuple[str, tuple[tuple[int | float, str], ...]], ...]
        ] = []
        seen: set[
            tuple[tuple[str, tuple[tuple[int | float, str], ...]], ...]
        ] = set()
        for unit in units:
            if (unit.objective_id, unit.document_id) != scope:
                continue
            for attribute in unit.scientific_context.test:
                text = str(attribute.value or "").strip()
                if not text:
                    continue
                parsed_matches = tuple(
                    (
                        match.start(),
                        match.end(),
                        schema,
                        match.group("prefix"),
                    )
                    for match in _ENCODED_CONDITION_SCHEMA_PATTERN.finditer(text)
                    if (schema := _objective_encoded_condition_schema(match))
                    is not None
                )
                for index, (_start, end, schema, _prefix) in enumerate(parsed_matches):
                    group = [schema]
                    for next_start, next_end, next_schema, next_prefix in parsed_matches[index + 1 :]:
                        between = text[end:next_start] + " " + next_prefix
                        if re.search(r"\band\b|,", between, flags=re.IGNORECASE) and not re.search(
                            r"[.!?;]",
                            between,
                        ):
                            group.append(next_schema)
                            end = next_end
                            continue
                        break
                    if len(group) < 2:
                        continue
                    grouped_schema = tuple(group)
                    if grouped_schema in seen:
                        continue
                    seen.add(grouped_schema)
                    candidates.append(grouped_schema)
        if candidates:
            schemas_by_scope[scope] = tuple(candidates)

    if not schemas_by_scope:
        return units

    bound: list[ExtractedEvidenceDraft] = []
    bound_count = 0
    for unit in units:
        if unit.reported_result is None or unit.selection_status == "failed":
            bound.append(unit)
            continue
        sample_label = _objective_result_sample_label(unit)
        encoded_values = _objective_encoded_condition_label_values(sample_label)
        if encoded_values is None:
            bound.append(unit)
            continue
        schemas = schemas_by_scope.get((unit.objective_id, unit.document_id), ())
        matching_schemas = tuple(
            schema
            for schema in schemas
            if len(schema) == len(encoded_values)
            and all(
                _objective_encoded_value_is_listed(value, schema_values)
                for value, (_variable_name, schema_values) in zip(
                    encoded_values,
                    schema,
                    strict=True,
                )
            )
        )
        if len(matching_schemas) != 1:
            bound.append(unit)
            continue
        schema = matching_schemas[0]
        payload = unit.to_record()
        scientific_context = unit.scientific_context.to_record()
        process_attributes = scientific_context.setdefault("process", [])
        existing_by_name = {
            property_matching.normalize_property_label(item.get("name"))
            or _objective_column_key(item.get("name")): item
            for item in process_attributes
        }
        additions: list[dict[str, Any]] = []
        conflict = False
        for value, (variable_name, schema_values) in zip(
            encoded_values,
            schema,
            strict=True,
        ):
            schema_unit = schema_values[0][1]
            key = property_matching.normalize_property_label(variable_name) or _objective_column_key(
                variable_name
            )
            existing = existing_by_name.get(key)
            if existing is not None:
                if not _objective_encoded_values_equal(
                    existing.get("value"),
                    value,
                ) or str(existing.get("unit") or "").strip().casefold() != schema_unit.casefold():
                    conflict = True
                    break
                continue
            attribute = {
                "name": variable_name,
                "value": value,
                "unit": schema_unit,
            }
            additions.append(attribute)
            existing_by_name[key] = attribute
        if conflict or not additions:
            bound.append(unit)
            continue

        process_attributes.extend(additions)
        payload["scientific_context"] = scientific_context
        schema_refs = _objective_encoded_condition_schema_source_refs(unit, schema)
        payload["source_refs"] = list(
            _dedupe_objective_source_refs(
                (
                    unit.source_refs,
                    _objective_source_refs_with_supports(
                        schema_refs,
                        "scientific_context.process",
                    ),
                )
            )
        )
        payload["selection_reason"] = (
            f"Bound encoded sample label {sample_label!r} to the explicit same-paper "
            "Methods condition schema; variable order, allowed values, and units "
            "are source-grounded."
        )
        bound.append(ExtractedEvidenceDraft.from_mapping(payload))
        bound_count += 1

    if bound_count:
        record_analysis_diagnostic(
            {
                "trace_type": "objective_encoded_condition_binding",
                "document_scopes": sorted(
                    {
                        (unit.objective_id, unit.document_id)
                        for unit in bound
                        if unit.selection_reason
                        and "Bound encoded sample label" in unit.selection_reason
                    }
                ),
                "bound_result_count": bound_count,
                "basis": "same_paper_explicit_variable_order_values_and_units",
            }
        )
    return tuple(bound)


def _objective_encoded_condition_schema(
    match: re.Match[str],
) -> tuple[str, tuple[tuple[int | float, str], ...]] | None:
    body = " ".join(match.group("body").split())
    number_matches = tuple(_NUMBER_PATTERN.finditer(body))
    if len(number_matches) < 2:
        return None
    if any(
        re.search(r"[-\u2010\u2011\u2012\u2013\u2014]", body[left.end() : right.start()])
        for left, right in zip(number_matches[:-1], number_matches[1:], strict=True)
    ):
        return None
    unit_match = re.match(
        r"^\s*(?P<unit>[A-Za-z\u00b5\u03bc\u00b0%][A-Za-z0-9\u00b5\u03bc\u00b0%/^.*\-]*)\s*$",
        body[number_matches[-1].end() :],
    )
    if unit_match is None:
        return None
    variable_name = _objective_encoded_condition_axis_name(match.group("prefix"))
    if not variable_name:
        return None
    unit = unit_match.group("unit")
    values: list[tuple[int | float, str]] = []
    for number_match in number_matches:
        raw = number_match.group(0)
        numeric = float(raw)
        value: int | float = (
            int(numeric)
            if numeric.is_integer()
            and "." not in raw
            and "e" not in raw.casefold()
            else numeric
        )
        values.append((value, unit))
    return variable_name, tuple(values)


def _objective_encoded_condition_axis_name(value: Any) -> str | None:
    text = " ".join(str(value or "").replace("-", " ").split()).strip()
    if not text:
        return None
    text = re.split(r"\b(?:and|or)\b", text, maxsplit=1, flags=re.IGNORECASE)[-1]
    for marker in (" at ", " with ", " under ", " using ", " of ", " including "):
        if marker in text.casefold():
            text = text.rsplit(marker, 1)[-1].strip()
    text = re.sub(
        r"^(?:samples?|specimens?|were|was|fabricated|produced|prepared|made)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(?:(?:at|with|under|using|of|the|a|an|different|various|several|multiple|varying|varied)\s+)+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    words = text.split()
    if not words:
        return None
    last = words[-1].casefold()
    if last.endswith("ies") and len(last) > 3:
        words[-1] = last[:-3] + "y"
    elif last.endswith("s") and not last.endswith(("ss", "us")):
        words[-1] = last[:-1]
    normalized = property_matching.normalize_property_label(" ".join(words))
    return normalized or None


def _objective_result_sample_label(unit: ExtractedEvidenceDraft) -> str:
    for attribute in unit.scientific_context.sample:
        if attribute.name == "sample_number":
            continue
        value = str(attribute.value or "").strip()
        if value:
            return value
    return ""


def _objective_encoded_condition_label_values(
    sample_label: str,
) -> tuple[int | float, ...] | None:
    if not sample_label:
        return None
    for match in _ENCODED_CONDITION_LABEL_PATTERN.finditer(sample_label):
        body = match.group("body")
        if "/" not in body:
            continue
        parts = tuple(part.strip() for part in body.split("/") if part.strip())
        if len(parts) < 2:
            continue
        values: list[int | float] = []
        for part in parts:
            number_match = re.fullmatch(_NUMBER_PATTERN, part)
            if number_match is None:
                break
            raw = number_match.group(0)
            numeric = float(raw)
            values.append(
                int(numeric)
                if numeric.is_integer()
                and "." not in raw
                and "e" not in raw.casefold()
                else numeric
            )
        else:
            return tuple(values)
    return None


def _objective_encoded_value_is_listed(
    value: int | float,
    schema_values: tuple[tuple[int | float, str], ...],
) -> bool:
    return any(_objective_encoded_values_equal(value, candidate) for candidate, _unit in schema_values)


def _objective_encoded_values_equal(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) <= 1e-9
    except (TypeError, ValueError):
        return str(left or "").strip().casefold() == str(right or "").strip().casefold()


def _objective_encoded_condition_schema_source_refs(
    unit: ExtractedEvidenceDraft,
    schema: tuple[tuple[str, tuple[tuple[int | float, str], ...]], ...],
) -> tuple[dict[str, Any], ...]:
    names = {
        variable_name.casefold()
        for variable_name, _values in schema
    }
    refs = tuple(
        ref
        for ref in unit.source_refs
        if (
            "scientific_context.test" in ref.get("supports", ())
            or all(
                name in str(ref.get("source_excerpt") or "").casefold()
                for name in names
            )
        )
    )
    return refs


def _objective_merge_condition_context(
    existing: ExtractedEvidenceDraft,
    incoming: ExtractedEvidenceDraft,
) -> ExtractedEvidenceDraft | None:
    context: dict[str, list[dict[str, Any]]] = {}
    added_context = False
    aliases_match = _objective_condition_aliases_match(existing, incoming)
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
            key = _objective_context_attribute_key(attribute.name)
            prior_key = next(
                (
                    prior_name
                    for prior_name, prior in by_name.items()
                    if _objective_context_attribute_names_match(
                        prior.get("name"),
                        attribute.name,
                    )
                ),
                None,
            )
            prior = by_name.get(prior_key) if prior_key is not None else None
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
                if context_name == "process" and aliases_match:
                    # The paper explicitly states that both labels denote the
                    # same condition. Keep the first source-local value while
                    # merging the alias lineage; an unaliased conflict still
                    # remains non-comparable below.
                    continue
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


def _objective_context_attribute_names_match(left: Any, right: Any) -> bool:
    left_key = _objective_context_attribute_key(left)
    right_key = _objective_context_attribute_key(right)
    return bool(
        left_key
        and right_key
        and (
            left_key == right_key
            or property_matching.axis_values_match(left_key, right_key)
            or property_matching.process_axis_matches_objective_scope(
                left_key,
                right_key,
            )
        )
    )


def _objective_condition_aliases_match(
    existing: ExtractedEvidenceDraft,
    incoming: ExtractedEvidenceDraft,
) -> bool:
    """Return whether both contexts carry the same explicit paper alias."""

    def labels(unit: ExtractedEvidenceDraft) -> frozenset[str]:
        identity_key = _objective_condition_label_key(
            _objective_explicit_sample_identity(unit)
        )
        if not identity_key:
            return frozenset()
        matched: set[str] = set()
        for ref in unit.source_refs:
            text = str(ref.get("source_excerpt") or "").strip()
            if not text:
                continue
            for label, _condition in _explicit_group_alias_mappings(text):
                if _objective_condition_label_key(label) == identity_key:
                    matched.add(identity_key)
        return frozenset(matched)

    return bool(labels(existing) & labels(incoming))


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
        # A partial result may carry labels with an explicitly non-comparable
        # comparison after Source validation. Those labels are precisely what
        # lets the same-paper condition registry bind the result on reread.
        or (
            unit.comparison is not None
            and unit.comparison.comparable
        )
        or (
            unit.changed_variables
            and all(
                variable.baseline_value is not None
                and variable.target_value is not None
                for variable in unit.changed_variables
            )
        )
        or unit.reported_result.direction == "unknown"
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
        if unit.reported_result.direction in {"no_change", "mixed"}
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
    if unit.reported_result.direction in {
        "increase",
        "decrease",
        "improve",
        "worsen",
    }:
        measurements = _objective_result_series_measurements(
            label_context,
            mentioned,
            fallback_unit=unit.reported_result.unit,
        )
        if measurements is None:
            return (unit,)
        pairs = tuple(zip(mentioned, mentioned[1:]))
    else:
        # A qualitative microstructure contrast has no scalar series to
        # recover. The Source still names both groups, and the paper's Methods
        # explicitly maps those labels to process conditions, so the first and
        # last mentioned groups form an honest categorical comparison.
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
        # Any model-proposed variable without endpoints is only a hint. The
        # following deterministic binding pass owns the condition comparison
        # and reconstructs complete endpoints from the registered Methods
        # records.
        payload["changed_variables"] = []
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


def _objective_pairwise_bridged_axis(
    *,
    axis_name: str,
    baseline_process: dict[str, Any],
    target_process: dict[str, Any],
    baseline_value: Any,
    target_value: Any,
    objective_variables: tuple[str, ...],
) -> str | None:
    """Resolve a generic row header through an explicit same-paper contrast.

    Result tables often use a generic header such as ``specimen condition``
    while nearby Methods or Results text names the scientific variable and its
    two endpoints.  The bridge is accepted only when one shared process fact
    uniquely matches an Objective variable and its value explicitly describes
    both row endpoints as a contrast.
    """

    matches: list[str] = []
    axis_tokens = _objective_contrast_tokens(axis_name) - {
        "condition",
        "conditions",
        "group",
        "groups",
        "sample",
        "samples",
        "specimen",
        "specimens",
        "state",
        "states",
    }
    baseline_tokens = _objective_contrast_tokens(baseline_value)
    target_tokens = _objective_contrast_tokens(target_value)
    for absent_tokens, present_tokens in (
        (baseline_tokens, target_tokens),
        (target_tokens, baseline_tokens),
    ):
        treatment_tokens = absent_tokens - {"without"}
        if (
            "without" not in absent_tokens
            or not treatment_tokens
            or treatment_tokens != present_tokens
        ):
            continue
        for objective_variable in objective_variables:
            objective_tokens = _objective_contrast_tokens(objective_variable)
            context_tokens = objective_tokens - treatment_tokens
            if (
                treatment_tokens <= objective_tokens
                and context_tokens
                and context_tokens <= axis_tokens
            ):
                matches.append(objective_variable)

    for key in sorted(set(baseline_process) & set(target_process)):
        baseline_attribute = baseline_process[key]
        target_attribute = target_process[key]
        if (
            baseline_attribute.value != target_attribute.value
            or baseline_attribute.unit != target_attribute.unit
        ):
            continue
        description = str(baseline_attribute.value or "").strip()
        if not _objective_description_covers_contrast(
            description,
            baseline_value=baseline_value,
            target_value=target_value,
        ):
            continue
        for objective_variable in objective_variables:
            if not (
                property_matching.axis_values_match(
                    baseline_attribute.name,
                    objective_variable,
                )
                or property_matching.process_axis_matches_objective_scope(
                    baseline_attribute.name,
                    objective_variable,
                )
            ):
                continue
            matches.append(objective_variable)
    unique_matches = tuple(dict.fromkeys(matches))
    return unique_matches[0] if len(unique_matches) == 1 else None


def _objective_description_covers_contrast(
    description: str,
    *,
    baseline_value: Any,
    target_value: Any,
) -> bool:
    normalized = " ".join(description.casefold().split())
    if not normalized:
        return False

    contrast = re.search(
        r"\b(?:versus|vs\.?|compared\s+(?:to|with))\b|(?:->|→|↔)|\s+/\s+",
        normalized,
    )
    if contrast is not None:
        sides = (normalized[: contrast.start()], normalized[contrast.end() :])
    else:
        between = re.search(r"\bbetween\b", normalized)
        if between is None:
            return False
        tail = normalized[between.end() :]
        conjunction = re.search(r"\band\b", tail)
        if conjunction is None:
            return False
        sides = (tail[: conjunction.start()], tail[conjunction.end() :])

    baseline_tokens = _objective_contrast_tokens(baseline_value)
    target_tokens = _objective_contrast_tokens(target_value)
    left_tokens, right_tokens = (
        _objective_contrast_tokens(side) for side in sides
    )
    if not baseline_tokens or not target_tokens:
        return False
    if (
        baseline_tokens <= left_tokens and target_tokens <= right_tokens
    ) or (
        target_tokens <= left_tokens and baseline_tokens <= right_tokens
    ):
        return True

    # Extractors sometimes preserve an explicit absent-versus-numeric design
    # compactly, for example ``without treatment / 150 C``.  A researcher can
    # bind that design to table rows labelled ``Non-treated`` and ``Treated``.
    # Keep this bridge narrow: the endpoints must be the same lexical treatment
    # with opposite presence, and the other description side must carry a
    # numeric level.  A vague alternative such as ``another route`` is not a
    # grounded endpoint.
    endpoint_pairs = (
        (baseline_tokens, target_tokens),
        (target_tokens, baseline_tokens),
    )
    for absent_tokens, present_tokens in endpoint_pairs:
        if (
            "without" not in absent_tokens
            or absent_tokens - {"without"} != present_tokens
            or not present_tokens
        ):
            continue
        if absent_tokens <= left_tokens and any(
            token.isdigit() for token in right_tokens
        ):
            return True
        if absent_tokens <= right_tokens and any(
            token.isdigit() for token in left_tokens
        ):
            return True
    return False


def _objective_contrast_tokens(value: Any) -> frozenset[str]:
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", str(value or "").casefold()):
        if token == "non":
            tokens.add("without")
            continue
        if len(token) > 5 and token.endswith("ing"):
            token = token[:-3]
        elif len(token) > 4 and token.endswith("ed"):
            token = token[:-2]
        tokens.add(token)
    return frozenset(tokens)


def _objective_series_pair_ids(
    measurements: list[ExtractedEvidenceDraft],
    *,
    objective: ResearchObjective | None,
) -> frozenset[tuple[str, str]]:
    """Select a finite set of source-local contrasts for one result series.

    A result table is an experimental series, not permission to compare every
    row with every other row.  Researchers first hold all other recorded
    conditions fixed and compare neighboring levels of one factor.  If the
    design contains only coupled changes, retain the minimum set of row links
    needed to describe that condition space; those links remain associations.
    """

    candidates: list[dict[str, Any]] = []
    for baseline_index, baseline in enumerate(measurements):
        baseline_process = {
            item.name.casefold(): item for item in baseline.scientific_context.process
        }
        for target_index in range(baseline_index + 1, len(measurements)):
            target = measurements[target_index]
            target_process = {
                item.name.casefold(): item
                for item in target.scientific_context.process
            }
            if set(baseline_process) != set(target_process):
                continue
            if not _objective_pairwise_fixed_conditions_match(baseline, target):
                continue
            changed_keys = tuple(
                key
                for key in sorted(baseline_process)
                if baseline_process[key].value != target_process[key].value
            )
            if not changed_keys:
                continue
            if objective is None:
                if len(changed_keys) > 1 and not (
                    _objective_has_concrete_row_locator(baseline)
                    and _objective_has_concrete_row_locator(target)
                ):
                    continue
            elif not _objective_pair_changes_objective_axis(
                changed_keys=changed_keys,
                baseline_process=baseline_process,
                target_process=target_process,
                objective=objective,
            ):
                continue
            candidates.append(
                {
                    "baseline_index": baseline_index,
                    "target_index": target_index,
                    "changed_keys": changed_keys,
                    "row_distance": abs(
                        _objective_measurement_row_order(target, target_index)
                        - _objective_measurement_row_order(
                            baseline,
                            baseline_index,
                        )
                    ),
                }
            )

    selected_indices: set[tuple[int, int]] = set()
    single_axis_groups: dict[tuple[Any, ...], set[int]] = {}
    for candidate in candidates:
        changed_keys = candidate["changed_keys"]
        if len(changed_keys) != 1:
            continue
        axis_key = changed_keys[0]
        baseline_index = candidate["baseline_index"]
        target_index = candidate["target_index"]
        group_key = (
            axis_key,
            _objective_series_fixed_signature(
                measurements[baseline_index],
                varied_axis_key=axis_key,
            ),
        )
        single_axis_groups.setdefault(group_key, set()).update(
            (baseline_index, target_index)
        )

    for (axis_key, _fixed_signature), indices in single_axis_groups.items():
        ordered = sorted(
            indices,
            key=lambda index: _objective_measurement_level_order(
                measurements[index],
                axis_key=axis_key,
                fallback_index=index,
            ),
        )
        distinct_levels: list[int] = []
        seen_levels: set[tuple[str, str]] = set()
        for index in ordered:
            attribute = {
                item.name.casefold(): item
                for item in measurements[index].scientific_context.process
            }[axis_key]
            level_key = _objective_fact_scalar_key(attribute.value)
            if level_key in seen_levels:
                continue
            seen_levels.add(level_key)
            distinct_levels.append(index)
        selected_indices.update(
            tuple(sorted((left, right)))
            for left, right in zip(distinct_levels, distinct_levels[1:])
        )

    # Controlled one-factor series usually connect a factorial design.  When
    # they do not, retain a minimum spanning set of coupled row contrasts.  The
    # downstream attribution rule labels every such contrast association_only.
    parents = list(range(len(measurements)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> bool:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return False
        parents[right_root] = left_root
        return True

    for left, right in sorted(selected_indices):
        union(left, right)
    for candidate in sorted(
        (item for item in candidates if len(item["changed_keys"]) > 1),
        key=lambda item: (
            len(item["changed_keys"]),
            item["row_distance"],
            item["baseline_index"],
            item["target_index"],
        ),
    ):
        left = candidate["baseline_index"]
        right = candidate["target_index"]
        if union(left, right):
            selected_indices.add((left, right))

    return frozenset(
        tuple(
            sorted(
                (
                    measurements[left].evidence_id,
                    measurements[right].evidence_id,
                )
            )
        )
        for left, right in selected_indices
    )


def _objective_pairwise_fixed_conditions_match(
    baseline: ExtractedEvidenceDraft,
    target: ExtractedEvidenceDraft,
) -> bool:
    for context_name in ("material", "test"):
        baseline_attributes = {
            item.name.casefold(): item
            for item in getattr(baseline.scientific_context, context_name)
        }
        target_attributes = {
            item.name.casefold(): item
            for item in getattr(target.scientific_context, context_name)
        }
        if set(baseline_attributes) != set(target_attributes):
            return False
        if any(
            (
                baseline_attributes[key].value,
                baseline_attributes[key].unit,
            )
            != (
                target_attributes[key].value,
                target_attributes[key].unit,
            )
            for key in baseline_attributes
        ):
            return False

    baseline_sample = {
        item.name.casefold(): item for item in baseline.scientific_context.sample
    }
    target_sample = {
        item.name.casefold(): item for item in target.scientific_context.sample
    }
    for key in set(baseline_sample) | set(target_sample):
        baseline_attribute = baseline_sample.get(key)
        target_attribute = target_sample.get(key)
        baseline_value = baseline_attribute.value if baseline_attribute else None
        target_value = target_attribute.value if target_attribute else None
        if _objective_table_column_is_sample_key(
            _objective_column_key(key)
        ) and _objective_sample_values_are_opaque_identifiers(
            baseline_value,
            target_value,
        ) or (
            _objective_table_column_is_sample_key(_objective_column_key(key))
            and _objective_sample_identity_is_bound_encoded_condition(
                baseline,
                target,
            )
        ):
            continue
        if baseline_attribute is None or target_attribute is None:
            return False
        if (baseline_attribute.value, baseline_attribute.unit) != (
            target_attribute.value,
            target_attribute.unit,
        ):
            return False
    return True


def _objective_pair_changes_objective_axis(
    *,
    changed_keys: tuple[str, ...],
    baseline_process: Mapping[str, Any],
    target_process: Mapping[str, Any],
    objective: ResearchObjective,
) -> bool:
    for key in changed_keys:
        attribute = target_process[key]
        if any(
            property_matching.axis_values_match(attribute.name, objective_variable)
            or property_matching.process_axis_matches_objective_scope(
                attribute.name,
                objective_variable,
            )
            or (
                property_matching.objective_variable_theme(objective_variable)
                is not None
                and property_matching.variable_matches_objective_scope(
                    attribute.name,
                    objective_variable,
                )
            )
            for objective_variable in objective.variables
        ):
            return True
        if (
            _objective_pairwise_bridged_axis(
                axis_name=attribute.name,
                baseline_process=dict(baseline_process),
                target_process=dict(target_process),
                baseline_value=baseline_process[key].value,
                target_value=target_process[key].value,
                objective_variables=objective.variables,
            )
            is not None
        ):
            return True
    return False


def _objective_series_fixed_signature(
    measurement: ExtractedEvidenceDraft,
    *,
    varied_axis_key: str,
) -> tuple[Any, ...]:
    signature: list[Any] = []
    for context_name in ("material", "sample", "process", "test"):
        for attribute in getattr(measurement.scientific_context, context_name):
            attribute_key = attribute.name.casefold()
            if context_name == "process" and attribute_key == varied_axis_key:
                continue
            if context_name == "sample" and _objective_table_column_is_sample_key(
                _objective_column_key(attribute_key)
            ) and (
                _objective_sample_values_are_opaque_identifiers(attribute.value)
                or "Bound encoded sample label"
                in (measurement.selection_reason or "")
            ):
                continue
            signature.append(
                (
                    context_name,
                    attribute_key,
                    _objective_fact_scalar_key(attribute.value),
                    _objective_fact_text_key(attribute.unit),
                )
            )
    return tuple(sorted(signature))


def _objective_measurement_row_order(
    measurement: ExtractedEvidenceDraft,
    fallback_index: int,
) -> float:
    for source_ref in measurement.source_refs:
        for field in ("row_index", "row_start", "row_end"):
            number = _coerce_number(source_ref.get(field))
            if number is not None:
                return number
    return float(fallback_index)


def _objective_measurement_level_order(
    measurement: ExtractedEvidenceDraft,
    *,
    axis_key: str,
    fallback_index: int,
) -> tuple[Any, ...]:
    attribute = {
        item.name.casefold(): item for item in measurement.scientific_context.process
    }[axis_key]
    number = _coerce_number(attribute.value)
    if number is not None:
        value_key: tuple[Any, ...] = (0, number)
    else:
        value_key = (1, _objective_fact_text_key(attribute.value))
    return (
        *value_key,
        _objective_measurement_row_order(measurement, fallback_index),
        measurement.evidence_id,
    )


def _build_objective_pairwise_comparison_units(
    units: tuple[ExtractedEvidenceDraft, ...],
    *,
    objectives: tuple[ResearchObjective, ...],
) -> tuple[ExtractedEvidenceDraft, ...]:
    objectives_by_id = {objective.objective_id: objective for objective in objectives}
    results_by_scope: dict[
        tuple[str, str, str, str | None, str, str, str],
        list[ExtractedEvidenceDraft],
    ] = {}
    for unit in units:
        result = unit.reported_result
        if result is None or unit.attribution_scope != "descriptive_only":
            continue
        if result.value in (None, "") or not unit.source_refs:
            continue
        objective = objectives_by_id.get(unit.objective_id)
        if objective is not None and not property_matching.outcome_matches_objective_scope(
            result.outcome,
            objective.outcomes,
        ):
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
                result.result_kind,
            ),
            [],
        ).append(unit)

    generated: list[ExtractedEvidenceDraft] = []
    generated_by_scope: dict[tuple[str, str], int] = {}
    for scope, measurements in results_by_scope.items():
        objective = objectives_by_id.get(scope[0])
        selected_pair_ids = _objective_series_pair_ids(
            measurements,
            objective=objective,
        )
        for baseline_index, baseline in enumerate(measurements):
            for target in measurements[baseline_index + 1 :]:
                if tuple(sorted((baseline.evidence_id, target.evidence_id))) not in (
                    selected_pair_ids
                ):
                    continue
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
                # A missing process column means the two rows do not describe
                # the same controlled condition space.  Keep both measurements
                # as source-backed descriptive Evidence rather than treating
                # the missing value as a changed factor.
                if set(baseline_process) != set(target_process):
                    continue
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
                if objective is not None:
                    for variable in changed_variables:
                        if any(
                            property_matching.axis_values_match(
                                variable["name"],
                                objective_variable,
                            )
                            or property_matching.process_axis_matches_objective_scope(
                                variable["name"],
                                objective_variable,
                            )
                            for objective_variable in objective.variables
                        ):
                            continue
                        bridged_axis = _objective_pairwise_bridged_axis(
                            axis_name=str(variable.get("name") or ""),
                            baseline_process=baseline_process,
                            target_process=target_process,
                            baseline_value=variable.get("baseline_value"),
                            target_value=variable.get("target_value"),
                            objective_variables=objective.variables,
                        )
                        if bridged_axis is None:
                            continue
                        prior_name = variable["name"]
                        variable["name"] = bridged_axis
                        changed_axis_names = [
                            bridged_axis if name == prior_name else name
                            for name in changed_axis_names
                        ]
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
                    ) or (
                        _objective_table_column_is_sample_key(
                            _objective_column_key(key)
                        )
                        and _objective_sample_identity_is_bound_encoded_condition(
                            baseline,
                            target,
                        )
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
                # A row locator proves where a value was read; it does not prove
                # that the paper designed the two rows as a controlled contrast.
                # We can still preserve an explicit, source-local row contrast as
                # an association when the endpoint values and every changed
                # process factor are present.  The attribution scope below keeps
                # coupled factors out of isolated or causal Findings.  Condition
                # changes (material, sample state, or test) remain excluded here
                # because they do not describe a comparable process series.
                if condition_axis_names or not changed_variables:
                    continue
                if objective is None and len(changed_variables) > 1 and not (
                    _objective_has_concrete_row_locator(baseline)
                    and _objective_has_concrete_row_locator(target)
                ):
                    # The unconfirmed/fallback path has no Objective contract
                    # to tell us which axis matters.  Require explicit row
                    # provenance before retaining a multi-axis association.
                    continue
                if objective is not None and not any(
                    property_matching.axis_values_match(
                        axis_name,
                        objective_variable,
                    )
                    or property_matching.process_axis_matches_objective_scope(
                        axis_name,
                        objective_variable,
                    )
                    or (
                        property_matching.objective_variable_theme(
                            objective_variable
                        )
                        is not None
                        and property_matching.variable_matches_objective_scope(
                            axis_name,
                            objective_variable,
                        )
                    )
                    for axis_name in axis_names
                    for objective_variable in objective.variables
                ):
                    # A table can contain several independent factors.  Do not
                    # manufacture an Objective comparison from a pair that only
                    # differs along unrelated context axes.
                    continue
                baseline_sample_values = {
                    item.name: item.value
                    for item in baseline.scientific_context.sample
                }
                target_sample_values = {
                    item.name: item.value
                    for item in target.scientific_context.sample
                }
                baseline_label = _objective_pairwise_condition_label(
                    baseline,
                    changed_variables=changed_variables,
                    sample_values=baseline_sample_values,
                    value_key="baseline_value",
                )
                target_label = _objective_pairwise_condition_label(
                    target,
                    changed_variables=changed_variables,
                    sample_values=target_sample_values,
                    value_key="target_value",
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
                attribution_scope = (
                    "association_only"
                    if len(changed_variables) > 1
                    else _objective_pairwise_attribution_scope(
                        changed_variables,
                        comparable=comparable,
                    )
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
                                "Deterministic source-local contrast of rows from "
                                "the same result table. Multiple changed factors "
                                "are retained as an association, not an isolated "
                                "effect."
                                if len(changed_variables) > 1
                                else "Deterministic comparison of rows from the "
                                "same result table."
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
                                "result_kind": target_result.result_kind,
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


def _objective_has_concrete_row_locator(unit: ExtractedEvidenceDraft) -> bool:
    return any(
        isinstance(ref, Mapping)
        and (
            ref.get("row_index") is not None
            or ref.get("row_start") is not None
            or ref.get("row_end") is not None
            or ref.get("cell_range") not in (None, "")
        )
        for ref in unit.source_refs
    )


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
            ) and (
                _objective_sample_values_are_opaque_identifiers(
                    baseline_attribute.value,
                    target_attribute.value,
                )
                or _objective_sample_identity_is_bound_encoded_condition(
                    baseline,
                    target,
                )
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
    baseline_process = {
        _objective_context_attribute_key(item.name): item
        for item in baseline_context.scientific_context.process
    }
    target_process = {
        _objective_context_attribute_key(item.name): item
        for item in target_context.scientific_context.process
    }
    varied_process_keys = {
        key
        for key in set(baseline_process) | set(target_process)
        if (
            key not in baseline_process
            or key not in target_process
            or baseline_process[key].value != target_process[key].value
            or baseline_process[key].unit != target_process[key].unit
        )
    }
    process_context: list[dict[str, Any]] = []
    process_by_key: dict[str, dict[str, Any]] = {}
    conflicting_process_keys: set[str] = set()
    for item in (
        *scientific_context["process"],
        *common_context["process"],
    ):
        key = _objective_context_attribute_key(item.get("name"))
        if not key or key in varied_process_keys or key in conflicting_process_keys:
            continue
        prior = process_by_key.get(key)
        if prior is None:
            record = dict(item)
            process_by_key[key] = record
            process_context.append(record)
            continue
        if (
            prior.get("value") == item.get("value")
            and prior.get("unit") == item.get("unit")
        ):
            continue
        # Conflicting source-grounded values are not a fixed condition. Remove
        # the field instead of selecting one side of the conflict.
        process_context.remove(prior)
        process_by_key.pop(key, None)
        conflicting_process_keys.add(key)
    scientific_context["process"] = process_context
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
        "group",
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


def _objective_pairwise_condition_label(
    unit: ExtractedEvidenceDraft,
    *,
    changed_variables: list[dict[str, Any]],
    sample_values: dict[str, Any],
    value_key: str,
) -> str:
    """Prefer source condition values over synthetic row numbers in comparisons.

    Deterministic table extraction adds a row number when a table has no sample
    identifier.  That locator is useful for provenance, but ``1`` and ``2`` are
    not meaningful comparison labels when the same rows explicitly say
    ``Non-preheated`` and ``Preheated`` (or give numeric process levels).
    Explicit sample/condition labels remain authoritative.
    """

    sample_label = _objective_sample_identity_key(sample_values)
    sample_keys = {
        _objective_column_key(key)
        for key, value in sample_values.items()
        if str(value).strip()
    }
    non_row_identity_keys = sample_keys & {
        "case",
        "condition",
        "condition_no",
        "condition_number",
        "group",
        "id",
        "no",
        "sample",
        "sample_id",
        "sample_no",
        "specimen",
        "specimen_id",
        "specimens",
    }
    if "sample_number" in sample_keys and not non_row_identity_keys:
        condition_parts = []
        for variable in changed_variables:
            value = variable.get(value_key)
            if value in (None, ""):
                continue
            unit_text = str(variable.get("unit") or "").strip()
            condition_parts.append(
                f"{value}{(' ' + unit_text) if unit_text else ''}"
            )
        if condition_parts:
            return " / ".join(condition_parts)
    return sample_label or unit.evidence_id


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
        "group",
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


def _objective_sample_identity_is_bound_encoded_condition(
    baseline: ExtractedEvidenceDraft,
    target: ExtractedEvidenceDraft,
) -> bool:
    """Treat a sample label as a locator after its encoded process is bound."""

    marker = "Bound encoded sample label"
    return marker in (baseline.selection_reason or "") and marker in (
        target.selection_reason or ""
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
