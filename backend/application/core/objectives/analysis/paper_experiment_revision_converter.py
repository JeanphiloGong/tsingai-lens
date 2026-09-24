"""Convert the legacy extraction aggregate into the durable experiment model.

The source extractor still emits the older in-process records while the hard
switch is being completed.  This module is the only boundary allowed to
translate those records into a reusable ``PaperExperimentRevision``.  It does
not copy Objective or Collection ownership into the revision and it never
uses a database id as a scientific key.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Any, Mapping

from domain.core.paper_experiment import (
    ExperimentComparison,
    ExperimentMeasurementResult,
    ExperimentTestCondition,
    ExperimentalVariant,
    PaperExperimentRevision,
    ReportedInterpretation,
    SourceReference,
)
from domain.core.research_process import (
    PaperExperiment as LegacyPaperExperiment,
    SourceObservation,
)
from domain.core.scientific_fact import ScientificAttribute, ScientificVariable


_KEY_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
_COMPARISON_DIRECTIONS = frozenset(
    {"increase", "decrease", "no_change", "mixed", "unknown"}
)
_RESULT_KINDS = frozenset(
    {"measured", "observed", "simulated", "predicted", "unknown"}
)


@dataclass(frozen=True)
class ConvertedPaperExperiment:
    """A revision plus the local mappings needed by the selection writer."""

    revision: PaperExperimentRevision
    measurement_key_by_observation_id: Mapping[str, str]
    comparison_key_by_observation_id: Mapping[str, str]


def stable_experiment_id(experiment: LegacyPaperExperiment) -> str:
    """Derive an Objective-independent identity from paper Source anchors.

    Source coordinates alone are insufficient when one table contains multiple
    explicitly labelled result series. Include the source-grounded context and
    comparison shape, while omitting Objective and observation identities so a
    reread can still resolve to the same paper-owned experiment.
    """

    anchors = []
    for observation in experiment.source_observations:
        context = observation.scientific_context.to_record()
        canonical_context = {
            section: sorted(
                values,
                key=lambda value: json.dumps(
                    value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
                ),
            )
            for section, values in context.items()
        }
        anchors.append(
            {
                "document_id": observation.document_id,
                "source_kind": observation.source_kind,
                "source_ref": observation.source_ref,
                "observation_role": observation.observation_role,
                "context": canonical_context,
                "changed_variables": sorted(
                    (item.to_record() for item in observation.changed_variables),
                    key=lambda value: json.dumps(
                        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
                    ),
                ),
                "comparison": (
                    observation.comparison.to_record()
                    if observation.comparison is not None
                    else None
                ),
            }
        )
    if not anchors:
        anchors = [
            {
                "document_id": experiment.document_id,
                "study_id": experiment.study_id,
                "source_id": value,
            }
            for value in experiment.source_observation_ids
        ]
    if not anchors:
        anchors = [
            {
                "document_id": experiment.document_id,
                "study_id": experiment.study_id,
                "fallback": True,
            }
        ]
    canonical_anchors = {
        json.dumps(
            anchor,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ): anchor
        for anchor in anchors
    }
    identity = json.dumps(
        [canonical_anchors[key] for key in sorted(canonical_anchors)],
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "pexp_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:28]


def convert_paper_experiment(
    experiment: LegacyPaperExperiment,
    *,
    source_fingerprint: str,
    experiment_version: int = 1,
    experiment_id: str | None = None,
) -> ConvertedPaperExperiment:
    """Convert one assembled legacy experiment without inventing missing facts."""

    if not source_fingerprint.strip():
        raise ValueError("paper experiment conversion requires source_fingerprint")
    if experiment_version < 1:
        raise ValueError("paper experiment version must be positive")

    observations = {item.observation_id: item for item in experiment.source_observations}
    measurements_by_id = {item.result_id: item for item in experiment.measurements}
    conditions_by_id = {item.test_condition_id: item for item in experiment.test_conditions}

    measurement_keys: dict[str, str] = {}
    for result_id in measurements_by_id:
        measurement_keys[result_id] = _local_key("m", result_id)

    variant_keys: dict[str, str] = {}
    for variant in experiment.sample_variants:
        variant_keys[variant.variant_id] = _local_key("v", variant.variant_id)

    test_keys: dict[str, str] = {}
    for condition in experiment.test_conditions:
        test_keys[condition.test_condition_id] = _local_key("t", condition.test_condition_id)

    # A measurement can legitimately have an unresolved sample label.  Keep a
    # visible local variant so the graph remains connected instead of dropping
    # the result or assigning it to another group.
    for result_id, measurement in measurements_by_id.items():
        if measurement.variant_id and measurement.variant_id not in variant_keys:
            variant_keys[measurement.variant_id] = _local_key("v", measurement.variant_id)
        if measurement.variant_id is None:
            variant_keys.setdefault(result_id, _local_key("v", result_id))
        else:
            # Comparison parents are identified by their observation/result
            # keys, while measurements point to the legacy variant id.  Keep
            # both local aliases aimed at the same graph node.
            variant_keys.setdefault(result_id, variant_keys[measurement.variant_id])
        if measurement.test_condition_id and measurement.test_condition_id not in test_keys:
            test_keys[measurement.test_condition_id] = _local_key("t", measurement.test_condition_id)

    variants = _convert_variants(
        experiment,
        observations=observations,
        variant_keys=variant_keys,
        source_fingerprint=source_fingerprint,
    )
    tests = _convert_tests(
        experiment,
        test_keys=test_keys,
        source_fingerprint=source_fingerprint,
    )
    converted_measurements = _convert_measurements(
        experiment,
        observations=observations,
        measurement_keys=measurement_keys,
        variant_keys=variant_keys,
        test_keys=test_keys,
        source_fingerprint=source_fingerprint,
    )
    comparisons, comparison_key_by_observation_id = _convert_comparisons(
        experiment,
        observations=observations,
        measurement_keys=measurement_keys,
        variant_keys=variant_keys,
        source_fingerprint=source_fingerprint,
    )
    (
        endpoint_variants,
        endpoint_measurements,
        reported_comparisons,
        reported_comparison_keys,
    ) = _convert_inline_reported_comparisons(
        experiment,
        observations=observations,
        measurements=converted_measurements,
        measurement_keys=measurement_keys,
        source_fingerprint=source_fingerprint,
    )
    variants = _merge_variants(variants, endpoint_variants)
    converted_measurements = _merge_measurements(
        converted_measurements,
        endpoint_measurements,
    )
    comparisons = (*comparisons, *reported_comparisons)
    comparison_key_by_observation_id = {
        **comparison_key_by_observation_id,
        **reported_comparison_keys,
    }
    interpretations = _convert_interpretations(
        experiment,
        observations=observations,
        comparison_key_by_observation_id=comparison_key_by_observation_id,
        measurement_keys=measurement_keys,
        source_fingerprint=source_fingerprint,
    )

    all_sources = _source_refs(
        experiment.source_observations,
        source_fingerprint=source_fingerprint,
    )
    unresolved = list(experiment.uncertainties)
    for measurement in converted_measurements:
        if measurement.variant_key is None:
            unresolved.append(f"Measurement {measurement.measurement_key} has no confirmed variant.")
        if measurement.test_key is None:
            unresolved.append(f"Measurement {measurement.measurement_key} has no confirmed test condition.")

    revision = PaperExperimentRevision.from_mapping(
        {
            "experiment_id": experiment_id or stable_experiment_id(experiment),
            "document_id": experiment.document_id,
            "experiment_version": experiment_version,
            "source_fingerprint": source_fingerprint,
            "label": _experiment_label(experiment, converted_measurements),
            "scope_description": _scope_description(experiment, converted_measurements),
            "design_type": _design_type(comparisons),
            "identity_status": "identified" if variants and converted_measurements else "partial",
            "binding_status": _binding_status(converted_measurements, comparisons),
            "variants": [item.to_record() for item in variants],
            "test_conditions": [item.to_record() for item in tests],
            "measurements": [item.to_record() for item in converted_measurements],
            "comparisons": [item.to_record() for item in comparisons],
            "reported_interpretations": [item.to_record() for item in interpretations],
            "source_refs": [item.to_record() for item in all_sources],
            "unresolved_issues": _unresolved_records(unresolved),
        }
    )
    return ConvertedPaperExperiment(
        revision=revision,
        measurement_key_by_observation_id=measurement_keys,
        comparison_key_by_observation_id=comparison_key_by_observation_id,
    )


def _convert_inline_reported_comparisons(
    experiment: LegacyPaperExperiment,
    *,
    observations: Mapping[str, SourceObservation],
    measurements: tuple[ExperimentMeasurementResult, ...],
    measurement_keys: Mapping[str, str],
    source_fingerprint: str,
) -> tuple[
    tuple[ExperimentalVariant, ...],
    tuple[ExperimentMeasurementResult, ...],
    tuple[ExperimentComparison, ...],
    Mapping[str, str],
]:
    """Materialize endpoints when one Source reports both values inline.

    Extractors commonly return one result such as ``2.4% -> 0.8%``.  That is
    still two reported measurements and one comparison; keeping only the
    target scalar would make the new experiment graph unable to synthesize a
    Finding.  The baseline endpoint is copied from the same Source reference,
    never inferred from an absent value.
    """

    measurements_by_key = {item.measurement_key: item for item in measurements}
    variants: list[ExperimentalVariant] = []
    endpoint_measurements: list[ExperimentMeasurementResult] = []
    comparisons: list[ExperimentComparison] = []
    comparison_keys: dict[str, str] = {}

    for observation in experiment.source_observations:
        comparison = observation.comparison
        result = observation.reported_result
        if (
            observation.derived_from_observation_ids
            or comparison is None
            or result is None
            or result.baseline_value is None
            or result.target_value is None
        ):
            continue
        target_measurement_key = measurement_keys.get(observation.observation_id)
        target_measurement = measurements_by_key.get(target_measurement_key or "")
        if target_measurement is None:
            continue

        baseline_measurement_key = _local_key(
            "m",
            f"{observation.observation_id}:baseline",
        )
        baseline_variant_key = _local_key(
            "v",
            f"{observation.observation_id}:baseline",
        )
        target_variant_key = _local_key(
            "v",
            f"{observation.observation_id}:target",
        )
        source_refs = _source_refs(
            (observation,),
            source_fingerprint=source_fingerprint,
        )
        binding_status = _binding_relation_status(observation)
        baseline_process = _endpoint_process_attributes(
            observation,
            endpoint="baseline",
        )
        target_process = _endpoint_process_attributes(
            observation,
            endpoint="target",
        )
        variants.extend(
            (
                ExperimentalVariant(
                    variant_key=baseline_variant_key,
                    variant_label=comparison.baseline_label,
                    subject_attributes=_attributes_from_context(observation, "material"),
                    intervention_attributes=baseline_process,
                    state=_attributes_from_context(observation, "sample"),
                    source_refs=source_refs,
                    binding_source_refs=source_refs,
                    binding_status=binding_status,
                    notes=("Endpoint reported inline with the Source result.",),
                ),
                ExperimentalVariant(
                    variant_key=target_variant_key,
                    variant_label=comparison.target_label,
                    subject_attributes=_attributes_from_context(observation, "material"),
                    intervention_attributes=target_process,
                    state=_attributes_from_context(observation, "sample"),
                    source_refs=source_refs,
                    binding_source_refs=source_refs,
                    binding_status=binding_status,
                    notes=("Endpoint reported inline with the Source result.",),
                ),
            )
        )
        endpoint_measurements.append(
            ExperimentMeasurementResult(
                measurement_key=baseline_measurement_key,
                outcome=target_measurement.outcome,
                variant_key=baseline_variant_key,
                test_key=target_measurement.test_key,
                value=result.baseline_value,
                unit=target_measurement.unit or result.unit,
                result_text=(
                    f"{result.outcome}: {result.baseline_value}"
                    + (f" {result.unit}" if result.unit else "")
                ),
                statistics={},
                measurement_scope={
                    **target_measurement.measurement_scope,
                    "reported_endpoint": "baseline",
                },
                result_kind=target_measurement.result_kind,
                source_refs=source_refs,
                binding_source_refs=source_refs,
                binding_status=binding_status,
                notes=("Endpoint reported inline with the Source result.",),
            )
        )
        measurements_by_key[target_measurement.measurement_key] = replace(
            target_measurement,
            variant_key=target_variant_key,
            measurement_scope={
                **target_measurement.measurement_scope,
                "reported_endpoint": "target",
            },
        )
        comparison_key = _local_key("c", observation.observation_id)
        comparison_keys[observation.observation_id] = comparison_key
        direction = _direction(result.direction)
        if direction == "unknown":
            direction = _numeric_direction(
                SourceObservation.from_mapping(
                    {
                        **observation.to_record(),
                        "observation_id": f"{observation.observation_id}:baseline",
                        "reported_result": {
                            **result.to_record(),
                            "value": result.baseline_value,
                        },
                    }
                ),
                observation,
                result.outcome,
            )
        comparisons.append(
            ExperimentComparison(
                comparison_key=comparison_key,
                baseline_variant_key=baseline_variant_key,
                target_variant_key=target_variant_key,
                outcome=result.outcome,
                baseline_measurement_keys=(baseline_measurement_key,),
                target_measurement_keys=(target_measurement_key,),
                changed_variables=tuple(observation.changed_variables),
                basis="reported",
                direction=direction,
                reported_statement=result.result_text,
                attribution_scope=(
                    observation.attribution_scope
                    if observation.attribution_scope != "not_attributable"
                    else "undetermined"
                ),
                status=("ready" if comparison.comparable else "non_comparable"),
                reasons=comparison.incomparability_reasons,
                source_refs=source_refs,
                binding_source_refs=source_refs,
                relation_status=binding_status,
            )
        )

    replaced_measurements = tuple(
        measurements_by_key[item.measurement_key] for item in measurements
    )
    return (
        tuple(variants),
        (*replaced_measurements, *endpoint_measurements),
        tuple(comparisons),
        comparison_keys,
    )


def _merge_variants(
    existing: tuple[ExperimentalVariant, ...],
    additional: tuple[ExperimentalVariant, ...],
) -> tuple[ExperimentalVariant, ...]:
    by_key = {item.variant_key: item for item in existing}
    for item in additional:
        by_key.setdefault(item.variant_key, item)
    return tuple(by_key.values())


def _merge_measurements(
    existing: tuple[ExperimentMeasurementResult, ...],
    additional: tuple[ExperimentMeasurementResult, ...],
) -> tuple[ExperimentMeasurementResult, ...]:
    by_key = {item.measurement_key: item for item in existing}
    for item in additional:
        by_key[item.measurement_key] = item
    return tuple(by_key.values())


def _endpoint_process_attributes(
    observation: SourceObservation,
    *,
    endpoint: str,
) -> tuple[ScientificAttribute, ...]:
    """Overlay reported factor endpoints on the shared process context."""

    values = list(_attributes_from_context(observation, "process"))
    for variable in observation.changed_variables:
        value = (
            variable.baseline_value
            if endpoint == "baseline"
            else variable.target_value
        )
        if value is None:
            continue
        replacement = ScientificAttribute(
            name=variable.name,
            value=value,
            unit=variable.unit,
        )
        for index, attribute in enumerate(values):
            if attribute.name.casefold() == variable.name.casefold():
                values[index] = replacement
                break
        else:
            values.append(replacement)
    return tuple(values)


def _convert_variants(
    experiment: LegacyPaperExperiment,
    *,
    observations: Mapping[str, SourceObservation],
    variant_keys: Mapping[str, str],
    source_fingerprint: str,
) -> tuple[ExperimentalVariant, ...]:
    records: dict[str, ExperimentalVariant] = {}
    for variant in experiment.sample_variants:
        if not any(
            measurement.variant_id == variant.variant_id
            for measurement in experiment.measurements
        ):
            # The legacy assembler may attach a context row for a derived
            # comparison.  It is not a separate experimental population.
            continue
        key = variant_keys[variant.variant_id]
        records[key] = ExperimentalVariant(
            variant_key=key,
            variant_label=variant.variant_label or variant.variant_id,
            subject_attributes=_attributes_from_mapping(variant.host_material_system),
            intervention_attributes=_attributes_from_mapping(variant.process_context),
            state=_attributes_from_mapping(variant.profile_payload),
            source_refs=_source_refs(
                _observations_for_variant(experiment, variant.variant_id),
                source_fingerprint=source_fingerprint,
            ),
            binding_source_refs=_source_refs(
                _observations_for_variant(experiment, variant.variant_id),
                source_fingerprint=source_fingerprint,
            ),
            binding_status="direct" if variant.epistemic_status == "validated" else "uncertain",
            notes=(
                f"Legacy variant {variant.variant_id} converted at the new authoring boundary.",
            ),
        )

    for result_id, measurement in (
        (item.result_id, item) for item in experiment.measurements
    ):
        raw_id = measurement.variant_id or result_id
        key = variant_keys.get(raw_id)
        if key is None or key in records:
            continue
        observation = observations.get(result_id)
        label = _observation_variant_label(observation) if observation else raw_id
        records[key] = ExperimentalVariant(
            variant_key=key,
            variant_label=label or raw_id,
            subject_attributes=(
                _attributes_from_context(observation, "material") if observation else ()
            ),
            intervention_attributes=(
                _attributes_from_context(observation, "process") if observation else ()
            ),
            state=(
                _attributes_from_context(observation, "sample") if observation else ()
            ),
            source_refs=_source_refs(
                (observation,) if observation else (),
                source_fingerprint=source_fingerprint,
            ),
            binding_source_refs=_source_refs(
                (observation,) if observation else (),
                source_fingerprint=source_fingerprint,
            ),
            binding_status="direct" if observation and observation.status == "validated" else "uncertain",
            notes=("Variant identity was unresolved in the source extraction.",),
        )
    return tuple(records.values())


def _convert_tests(
    experiment: LegacyPaperExperiment,
    *,
    test_keys: Mapping[str, str],
    source_fingerprint: str,
) -> tuple[ExperimentTestCondition, ...]:
    records: list[ExperimentTestCondition] = []
    for condition in experiment.test_conditions:
        if not any(
            measurement.test_condition_id == condition.test_condition_id
            for measurement in experiment.measurements
        ):
            continue
        records.append(
            ExperimentTestCondition(
                test_key=test_keys[condition.test_condition_id],
                test_type=condition.property_type or condition.template_type or "unknown test",
                parameters=_attributes_from_mapping(condition.condition_payload),
                source_refs=_source_refs(
                    _observations_for_test(experiment, condition.test_condition_id),
                    source_fingerprint=source_fingerprint,
                ),
                binding_status=(
                    "direct"
                    if condition.epistemic_status in {"validated", "normalized_from_evidence"}
                    else "uncertain"
                ),
                notes=tuple(condition.missing_fields),
            )
        )
    return tuple(records)


def _convert_measurements(
    experiment: LegacyPaperExperiment,
    *,
    observations: Mapping[str, SourceObservation],
    measurement_keys: Mapping[str, str],
    variant_keys: Mapping[str, str],
    test_keys: Mapping[str, str],
    source_fingerprint: str,
) -> tuple[ExperimentMeasurementResult, ...]:
    records: list[ExperimentMeasurementResult] = []
    for measurement in experiment.measurements:
        observation = observations.get(measurement.result_id)
        result = observation.reported_result if observation else None
        payload = dict(measurement.value_payload)
        value = payload.get("value")
        if value is None and result is not None:
            value = result.value
        result_text = result.result_text if result is not None else None
        if value is None and not result_text:
            result_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        statistics = {
            key: payload[key]
            for key in ("baseline_value", "target_value")
            if payload.get(key) is not None
        }
        records.append(
            ExperimentMeasurementResult(
                measurement_key=measurement_keys[measurement.result_id],
                outcome=measurement.property_normalized,
                variant_key=(
                    variant_keys.get(measurement.variant_id or measurement.result_id)
                ),
                test_key=(
                    test_keys.get(measurement.test_condition_id)
                    if measurement.test_condition_id
                    else None
                ),
                value=value,
                unit=measurement.unit or (result.unit if result else None),
                result_text=result_text,
                statistics=statistics,
                measurement_scope={
                    "claim_scope": measurement.claim_scope,
                    "source_observation_id": measurement.result_id,
                },
                result_kind=_result_kind(
                    measurement.result_type or (result.result_kind if result else None)
                ),
                source_refs=_source_refs(
                    (observation,) if observation else (),
                    source_fingerprint=source_fingerprint,
                ),
                binding_source_refs=_source_refs(
                    (observation,) if observation else (),
                    source_fingerprint=source_fingerprint,
                ),
                binding_status=_binding_relation_status(observation),
                notes=(
                    tuple(observation.selection_reason for _ in [0] if observation and observation.selection_reason)
                ),
            )
        )
    return tuple(records)


def _convert_comparisons(
    experiment: LegacyPaperExperiment,
    *,
    observations: Mapping[str, SourceObservation],
    measurement_keys: Mapping[str, str],
    variant_keys: Mapping[str, str],
    source_fingerprint: str,
) -> tuple[tuple[ExperimentComparison, ...], dict[str, str]]:
    comparisons: list[ExperimentComparison] = []
    keys_by_observation: dict[str, str] = {}
    for observation in experiment.source_observations:
        parents = observation.derived_from_observation_ids
        if len(parents) < 2 or observation.reported_result is None:
            continue
        baseline_id, target_id = parents[:2]
        baseline_measurement = measurement_keys.get(baseline_id)
        target_measurement = measurement_keys.get(target_id)
        if not baseline_measurement or not target_measurement:
            continue
        baseline = observations.get(baseline_id)
        target = observations.get(target_id)
        outcome = observation.reported_result.outcome
        if not outcome:
            continue
        comparison_key = _local_key("c", observation.observation_id)
        keys_by_observation[observation.observation_id] = comparison_key
        comparable = bool(observation.comparison and observation.comparison.comparable)
        status = "ready" if comparable else (
            "non_comparable" if observation.comparison is not None else "insufficient_context"
        )
        baseline_variant = _variant_key_for_observation(
            baseline, variant_keys, fallback=baseline_id
        )
        target_variant = _variant_key_for_observation(
            target, variant_keys, fallback=target_id
        )
        direction = _direction(observation.reported_result.direction)
        if direction == "unknown":
            direction = _numeric_direction(baseline, target, outcome)
        attribution = observation.attribution_scope
        if attribution == "not_attributable":
            attribution = "undetermined"
        reasons = ()
        if observation.comparison is not None:
            reasons = tuple(observation.comparison.incomparability_reasons)
        comparisons.append(
            ExperimentComparison(
                comparison_key=comparison_key,
                baseline_variant_key=baseline_variant,
                target_variant_key=target_variant,
                outcome=outcome,
                baseline_measurement_keys=(baseline_measurement,),
                target_measurement_keys=(target_measurement,),
                changed_variables=tuple(observation.changed_variables),
                basis="derived",
                direction=direction,
                reported_statement=observation.reported_result.result_text,
                attribution_scope=attribution,
                status=status,
                reasons=reasons,
                source_refs=_source_refs(
                    (observation,), source_fingerprint=source_fingerprint
                ),
                binding_source_refs=_source_refs(
                    tuple(item for item in (baseline, target) if item is not None),
                    source_fingerprint=source_fingerprint,
                ),
                relation_status=(
                    "direct" if observation.status == "validated" else "uncertain"
                ),
            )
        )
    return tuple(comparisons), keys_by_observation


def _convert_interpretations(
    experiment: LegacyPaperExperiment,
    *,
    observations: Mapping[str, SourceObservation],
    comparison_key_by_observation_id: Mapping[str, str],
    measurement_keys: Mapping[str, str],
    source_fingerprint: str,
) -> tuple[ReportedInterpretation, ...]:
    records: list[ReportedInterpretation] = []
    seen: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
    for observation in experiment.source_observations:
        result = observation.reported_result
        if result is None or not result.result_text:
            continue
        comparison_key = comparison_key_by_observation_id.get(observation.observation_id)
        measurement_key = measurement_keys.get(observation.observation_id)
        comparison_keys = (comparison_key,) if comparison_key else ()
        measurement_keys_for_record = (measurement_key,) if measurement_key else ()
        # Derived contrast prose is the strongest unambiguous author/result
        # statement available in the legacy stream.  Direct values remain
        # measurements and are not duplicated as interpretations unless the
        # source extractor explicitly marked them as a comparison.
        if not comparison_keys and observation.observation_role not in {
            "comparison_context",
            "background_context",
        }:
            continue
        identity = (result.result_text, measurement_keys_for_record, comparison_keys)
        if identity in seen:
            continue
        seen.add(identity)
        records.append(
            ReportedInterpretation(
                statement=result.result_text,
                kind=(
                    "mechanism_hypothesis"
                    if observation.observation_role == "background_context"
                    else "result_summary"
                ),
                measurement_keys=measurement_keys_for_record,
                comparison_keys=comparison_keys,
                source_refs=_source_refs(
                    (observation,), source_fingerprint=source_fingerprint
                ),
            )
        )
    return tuple(records)


def _source_refs(
    observations: tuple[SourceObservation, ...] | list[SourceObservation] | Any,
    *,
    source_fingerprint: str,
) -> tuple[SourceReference, ...]:
    refs: list[SourceReference] = []
    seen: set[tuple[str, str, str]] = set()
    for observation in observations or ():
        raw_refs = observation.source_refs or (
            {
                "source_kind": observation.source_kind,
                "source_ref": observation.source_ref,
                "quote": observation.source_excerpt,
            },
        )
        for raw in raw_refs:
            if not isinstance(raw, Mapping):
                continue
            source_kind = str(raw.get("source_kind") or observation.source_kind).strip()
            source_ref = str(raw.get("source_ref") or observation.source_ref).strip()
            quote = str(
                raw.get("quote")
                or raw.get("source_excerpt")
                or observation.source_excerpt
                or (
                    observation.reported_result.result_text
                    if observation.reported_result is not None
                    else ""
                )
            ).strip()
            if not source_kind or not source_ref or not quote:
                continue
            identity = (source_kind, source_ref, quote)
            if identity in seen:
                continue
            seen.add(identity)
            refs.append(
                SourceReference(
                    document_id=observation.document_id,
                    source_fingerprint=source_fingerprint,
                    source_kind=source_kind,
                    source_ref=source_ref,
                    quote=quote,
                )
            )
    return tuple(refs)


def _attributes_from_mapping(value: Mapping[str, Any] | None) -> tuple[ScientificAttribute, ...]:
    records: list[ScientificAttribute] = []
    for name, raw in (value or {}).items():
        if isinstance(raw, Mapping):
            scalar = raw.get("value")
            unit = raw.get("unit")
            scope = raw.get("context_scope", "unknown")
            outcomes = raw.get("applies_to_outcomes", ())
        else:
            scalar = raw
            unit = None
            scope = "unknown"
            outcomes = ()
        if isinstance(scalar, (dict, list, tuple, set)):
            scalar = json.dumps(scalar, ensure_ascii=False, sort_keys=True)
        if scalar is None or not str(name).strip():
            continue
        try:
            records.append(
                ScientificAttribute(
                    name=str(name).strip(),
                    value=scalar,
                    unit=str(unit).strip() if unit else None,
                    context_scope=str(scope or "unknown"),
                    applies_to_outcomes=tuple(str(item).strip() for item in outcomes if str(item).strip()),
                )
            )
        except ValueError:
            continue
    return tuple(records)


def _attributes_from_context(
    observation: SourceObservation | None,
    section: str,
) -> tuple[ScientificAttribute, ...]:
    if observation is None:
        return ()
    context = observation.scientific_context
    return tuple(getattr(context, section, ()) or ())


def _observations_for_variant(
    experiment: LegacyPaperExperiment,
    variant_id: str,
) -> tuple[SourceObservation, ...]:
    return tuple(
        observation
        for observation in experiment.source_observations
        if observation.reported_result is not None
        and any(
            measurement.result_id == observation.observation_id
            and measurement.variant_id == variant_id
            for measurement in experiment.measurements
        )
    )


def _observations_for_test(
    experiment: LegacyPaperExperiment,
    test_id: str,
) -> tuple[SourceObservation, ...]:
    return tuple(
        observation
        for observation in experiment.source_observations
        if any(
            measurement.result_id == observation.observation_id
            and measurement.test_condition_id == test_id
            for measurement in experiment.measurements
        )
    )


def _observation_variant_label(observation: SourceObservation | None) -> str:
    if observation is None:
        return "unresolved variant"
    for attribute in observation.scientific_context.sample:
        if str(attribute.value).strip():
            return str(attribute.value).strip()
    return f"variant {observation.observation_id}"


def _variant_key_for_observation(
    observation: SourceObservation | None,
    variant_keys: Mapping[str, str],
    *,
    fallback: str,
) -> str:
    if observation is not None:
        for measurement_id, key in variant_keys.items():
            if measurement_id == observation.observation_id:
                return key
    return variant_keys.get(fallback) or _local_key("v", fallback)


def _source_result_value(
    observation: SourceObservation | None,
) -> Any:
    if observation is None or observation.reported_result is None:
        return None
    return observation.reported_result.value


def _numeric_direction(
    baseline: SourceObservation | None,
    target: SourceObservation | None,
    outcome: str,
) -> str:
    left = _source_result_value(baseline)
    right = _source_result_value(target)
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return "unknown"
    if right > left:
        return "increase"
    if right < left:
        return "decrease"
    return "no_change"


def _direction(value: str | None) -> str:
    value = str(value or "unknown").strip().lower()
    if value in _COMPARISON_DIRECTIONS:
        return value
    return {
        "improve": "increase",
        "worsen": "decrease",
        "changed": "mixed",
    }.get(value, "unknown")


def _result_kind(value: str | None) -> str:
    value = str(value or "unknown").strip().lower()
    if value in _RESULT_KINDS:
        return value
    if value == "modeled":
        return "predicted"
    return "unknown"


def _binding_relation_status(observation: SourceObservation | None) -> str:
    if observation is None:
        return "uncertain"
    if observation.status == "validated":
        return "direct"
    if observation.status == "rejected":
        return "conflict"
    return "uncertain"


def _binding_status(
    measurements: tuple[ExperimentMeasurementResult, ...],
    comparisons: tuple[ExperimentComparison, ...],
) -> str:
    if measurements and all(item.binding_status == "direct" for item in measurements):
        return "bound"
    if measurements or comparisons:
        return "partial"
    return "draft"


def _design_type(comparisons: tuple[ExperimentComparison, ...]) -> str:
    if any(len(item.changed_variables) > 1 for item in comparisons):
        return "factorial"
    if comparisons:
        return "parallel"
    return "unknown"


def _experiment_label(
    experiment: LegacyPaperExperiment,
    measurements: tuple[ExperimentMeasurementResult, ...],
) -> str:
    outcomes = list(dict.fromkeys(item.outcome for item in measurements if item.outcome))
    return (
        f"{outcomes[0]} experiment series"
        if len(outcomes) == 1
        else f"Paper experiment {experiment.document_id}"
    )


def _scope_description(
    experiment: LegacyPaperExperiment,
    measurements: tuple[ExperimentMeasurementResult, ...],
) -> str:
    variants = [item.variant_label for item in experiment.sample_variants if item.variant_label]
    outcomes = list(dict.fromkeys(item.outcome for item in measurements if item.outcome))
    pieces = []
    if variants:
        pieces.append("variants: " + ", ".join(variants))
    if outcomes:
        pieces.append("outcomes: " + ", ".join(outcomes))
    if not pieces:
        pieces.append("experiment boundary remains partial")
    return "; ".join(pieces)


def _unresolved_records(values: list[str]) -> tuple[dict[str, str], ...]:
    seen: set[str] = set()
    records: list[dict[str, str]] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        records.append(
            {
                "target_ref": "experiment",
                "description": text,
            }
        )
    return tuple(records)


def _local_key(prefix: str, value: str) -> str:
    normalized = _KEY_RE.sub("_", str(value).strip()).strip("_") or "item"
    normalized = normalized[:72]
    digest = hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{normalized}_{digest}"


__all__ = [
    "ConvertedPaperExperiment",
    "convert_paper_experiment",
    "stable_experiment_id",
]
