from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import logging
import math
from typing import Any

from domain.core.comparison import (
    COMPARABLE_RESULT_NORMALIZATION_VERSION,
    COLLECTION_COMPARISON_POLICY_FAMILY,
    COLLECTION_COMPARISON_POLICY_VERSION,
    DEFAULT_COLLECTION_REASSESSMENT_TRIGGERS,
    CollectionComparableResult,
    ComparableResult,
    ComparisonAxis,
    ContextBinding,
    EvidenceTrace,
    NormalizedComparisonContext,
    PairwiseComparisonRelation,
    ResultValue,
    build_collection_assessment_input_fingerprint,
    build_comparable_result_id,
    build_pairwise_comparison_relation_id,
    evaluate_comparison_assessment,
)
from domain.core.evidence_backbone import (
    BaselineReference,
    MeasurementResult,
    SampleVariant,
    TestCondition,
)
from domain.shared.enums import (
    EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
    TRACEABILITY_STATUS_MISSING,
)
from domain.shared.record_normalization import normalize_record_value

logger = logging.getLogger(__name__)


COMPARABLE_RESULT_COLUMNS = [
    "comparable_result_id",
    "source_result_id",
    "source_document_id",
    "binding",
    "normalized_context",
    "axis",
    "value",
    "evidence",
    "variant_label",
    "baseline_reference",
    "result_source_type",
    "epistemic_status",
    "normalization_version",
]
COLLECTION_COMPARABLE_RESULT_COLUMNS = [
    "collection_id",
    "comparable_result_id",
    "assessment",
    "epistemic_status",
    "included",
    "sort_order",
    "policy_family",
    "policy_version",
    "comparable_result_normalization_version",
    "assessment_input_fingerprint",
    "reassessment_triggers",
]
PAIRWISE_RELATION_COMPARABLE_PROPERTIES = frozenset(
    {"density", "relative_density", "yield_strength", "tensile_strength", "elongation"}
)
PAIRWISE_RELATION_AXIS_KEYS = (
    "scan_strategy",
    "scan_speed_mm_s",
    "energy_density_j_mm3",
)
PAIRWISE_RELATION_TENSILE_PROPERTIES = (
    "yield_strength",
    "tensile_strength",
)
PAIRWISE_RELATION_DUCTILITY_PROPERTY = "elongation"
PAIRWISE_RELATION_DENSITY_PROPERTY = "density"
PAIRWISE_RELATION_DENSITY_MIN_DELTA = 2.0
PAIRWISE_RELATION_ELONGATION_MIN_DELTA = 3.4


@dataclass(frozen=True)
class ComparisonInputRecords:
    sample_variants: tuple[SampleVariant, ...]
    measurement_results: tuple[MeasurementResult, ...]
    test_conditions: tuple[TestCondition, ...]
    baseline_references: tuple[BaselineReference, ...]


@dataclass(frozen=True)
class ComparisonSemanticRecords:
    comparable_results: tuple[ComparableResult, ...]
    collection_comparable_results: tuple[CollectionComparableResult, ...]
    pairwise_comparison_relations: tuple[PairwiseComparisonRelation, ...] = ()


class ComparableResultAssembler:
    """Assemble semantic comparison artifacts from paper-facts records."""

    def assemble_semantic_records(
        self,
        *,
        collection_id: str,
        records: ComparisonInputRecords,
    ) -> ComparisonSemanticRecords:
        sample_lookup = self.index_by_id(records.sample_variants, "variant_id")
        test_condition_lookup = self.index_by_id(
            records.test_conditions,
            "test_condition_id",
        )
        baseline_lookup = self.index_by_id(
            records.baseline_references,
            "baseline_id",
        )

        comparable_results_by_id: dict[str, ComparableResult] = {}
        scoped_results_by_id: dict[str, CollectionComparableResult] = {}
        for sort_order, result_record in enumerate(records.measurement_results):
            result_row = result_record.to_record()
            assessment_context = self.build_assessment_context(
                result_row=result_row,
                sample_lookup=sample_lookup,
                test_condition_lookup=test_condition_lookup,
                baseline_lookup=baseline_lookup,
            )
            comparable_result = self.assemble_comparable_result(
                result_row=result_row,
                sample_lookup=sample_lookup,
                test_condition_lookup=test_condition_lookup,
                baseline_lookup=baseline_lookup,
            )
            if comparable_result is None:
                continue
            scoped_result = self.build_collection_comparable_result(
                collection_id=collection_id,
                comparable_result=comparable_result,
                sort_order=sort_order,
                assessment_context=assessment_context,
            )
            existing_comparable_result = comparable_results_by_id.get(
                comparable_result.comparable_result_id
            )
            comparable_results_by_id[comparable_result.comparable_result_id] = (
                self.merge_comparable_results(
                    existing_comparable_result,
                    comparable_result,
                )
                if existing_comparable_result is not None
                else comparable_result
            )
            existing_scoped_result = scoped_results_by_id.get(
                comparable_result.comparable_result_id
            )
            scoped_results_by_id[comparable_result.comparable_result_id] = (
                self.merge_collection_comparable_results(
                    existing_scoped_result,
                    scoped_result,
                )
                if existing_scoped_result is not None
                else scoped_result
            )

        return ComparisonSemanticRecords(
            comparable_results=tuple(comparable_results_by_id.values()),
            collection_comparable_results=tuple(scoped_results_by_id.values()),
            pairwise_comparison_relations=self.build_pairwise_comparison_relations(
                collection_id=collection_id,
                records=records,
            ),
        )

    def build_pairwise_comparison_relations(
        self,
        *,
        collection_id: str,
        records: ComparisonInputRecords,
    ) -> tuple[PairwiseComparisonRelation, ...]:
        table_results = [
            result.to_record()
            for result in records.measurement_results
            if self.safe_text(result.result_source_type) == "table"
            and self.safe_text(result.claim_scope) == "current_work"
            and self.safe_text(result.variant_id)
        ]
        result_lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
        for result in table_results:
            property_name = self.safe_text(result.get("property_normalized")) or ""
            if property_name not in PAIRWISE_RELATION_COMPARABLE_PROPERTIES:
                continue
            _, numeric_value = self.summarize_result(
                result_type=self.safe_text(result.get("result_type")) or "scalar",
                value_payload=result.get("value_payload"),
                unit=self.safe_text(result.get("unit")),
            )
            if numeric_value is None:
                continue
            key = (
                self.safe_text(result.get("document_id")) or "",
                self.safe_text(result.get("variant_id")) or "",
                property_name,
            )
            if not all(key):
                continue
            existing = result_lookup.get(key)
            if existing is None:
                result_lookup[key] = result
                continue
            _, existing_value = self.summarize_result(
                result_type=self.safe_text(existing.get("result_type")) or "scalar",
                value_payload=existing.get("value_payload"),
                unit=self.safe_text(existing.get("unit")),
            )
            if existing_value is None:
                result_lookup[key] = result

        relations_by_id: dict[str, PairwiseComparisonRelation] = {}
        samples_by_document: dict[str, list[dict[str, Any]]] = {}
        for sample in records.sample_variants:
            row = sample.to_record()
            document_id = self.safe_text(row.get("document_id"))
            variant_id = self.safe_text(row.get("variant_id"))
            if document_id and variant_id:
                samples_by_document.setdefault(document_id, []).append(row)

        for document_id, samples in samples_by_document.items():
            allowed_relation_specs = self._select_pairwise_relation_specs(
                document_id=document_id,
                samples=samples,
                result_lookup=result_lookup,
            )
            for left_index, left in enumerate(samples):
                for right in samples[left_index + 1:]:
                    comparison_axis = self._single_pairwise_comparison_axis(
                        left.get("process_context"),
                        right.get("process_context"),
                    )
                    if comparison_axis is None:
                        continue
                    for property_name in sorted(PAIRWISE_RELATION_COMPARABLE_PROPERTIES):
                        left_result = result_lookup.get(
                            (
                                document_id,
                                self.safe_text(left.get("variant_id")) or "",
                                property_name,
                            )
                        )
                        right_result = result_lookup.get(
                            (
                                document_id,
                                self.safe_text(right.get("variant_id")) or "",
                                property_name,
                            )
                        )
                        if left_result is None or right_result is None:
                            continue
                        relation_spec = self._pairwise_relation_spec_key(
                            left,
                            right,
                            property_name,
                        )
                        if relation_spec not in allowed_relation_specs:
                            continue
                        relation = self._build_pairwise_comparison_relation(
                            collection_id=collection_id,
                            document_id=document_id,
                            comparison_axis=comparison_axis,
                            left_sample=left,
                            right_sample=right,
                            left_result=left_result,
                            right_result=right_result,
                        )
                        if relation is not None:
                            relations_by_id[relation.relation_id] = relation
        return tuple(relations_by_id.values())

    def _select_pairwise_relation_specs(
        self,
        *,
        document_id: str,
        samples: list[dict[str, Any]],
        result_lookup: dict[tuple[str, str, str], dict[str, Any]],
    ) -> set[tuple[str, str, str]]:
        all_specs: set[tuple[str, str, str]] = set()
        for left_index, left in enumerate(samples):
            for right in samples[left_index + 1:]:
                if (
                    self._single_pairwise_comparison_axis(
                        left.get("process_context"),
                        right.get("process_context"),
                    )
                    is None
                ):
                    continue
                for property_name in PAIRWISE_RELATION_COMPARABLE_PROPERTIES:
                    if self._pairwise_result_value(
                        document_id=document_id,
                        sample=left,
                        property_name=property_name,
                        result_lookup=result_lookup,
                    ) is None or self._pairwise_result_value(
                        document_id=document_id,
                        sample=right,
                        property_name=property_name,
                        result_lookup=result_lookup,
                    ) is None:
                        continue
                    all_specs.add(
                        self._pairwise_relation_spec_key(left, right, property_name)
                    )
        if len(samples) <= 3:
            return all_specs

        pbf_samples: list[dict[str, Any]] = []
        density_values: dict[str, float] = {}
        for sample in samples:
            process_context = self.normalize_object(sample.get("process_context"))
            if not isinstance(process_context, dict):
                return all_specs
            scan_strategy = self.safe_text(process_context.get("scan_strategy"))
            scan_speed = self._numeric_process_value(process_context, "scan_speed_mm_s")
            energy_density = self._numeric_process_value(
                process_context,
                "energy_density_j_mm3",
            )
            variant_id = self.safe_text(sample.get("variant_id")) or ""
            density_value = self._pairwise_result_value(
                document_id=document_id,
                sample=sample,
                property_name=PAIRWISE_RELATION_DENSITY_PROPERTY,
                result_lookup=result_lookup,
            )
            if (
                not variant_id
                or not scan_strategy
                or scan_speed is None
                or energy_density is None
                or density_value is None
            ):
                return all_specs
            density_values[variant_id] = density_value
            pbf_samples.append(
                {
                    "sample": sample,
                    "variant_id": variant_id,
                    "scan_strategy": scan_strategy,
                    "scan_speed_mm_s": scan_speed,
                    "energy_density_j_mm3": energy_density,
                }
            )

        primary = max(
            pbf_samples,
            key=lambda item: density_values.get(item["variant_id"], -math.inf),
        )
        primary_strategy = self.safe_text(primary.get("scan_strategy")) or ""
        if not primary_strategy:
            return all_specs

        selected_specs: set[tuple[str, str, str]] = set()
        speed_groups: dict[tuple[float, str], list[dict[str, Any]]] = {}
        strategy_groups: dict[tuple[float, float], list[dict[str, Any]]] = {}
        for item in pbf_samples:
            speed_groups.setdefault(
                (item["energy_density_j_mm3"], item["scan_strategy"]),
                [],
            ).append(item)
            strategy_groups.setdefault(
                (item["energy_density_j_mm3"], item["scan_speed_mm_s"]),
                [],
            ).append(item)

        for (_, strategy), group in speed_groups.items():
            if strategy != primary_strategy or len(group) < 2:
                continue
            for left_index, left in enumerate(group):
                for right in group[left_index + 1:]:
                    if (
                        self._single_pairwise_comparison_axis(
                            left["sample"].get("process_context"),
                            right["sample"].get("process_context"),
                        )
                        != "scan_speed_mm_s"
                    ):
                        continue
                    for property_name in PAIRWISE_RELATION_TENSILE_PROPERTIES:
                        self._add_pairwise_relation_spec_if_numeric_delta(
                            selected_specs,
                            document_id=document_id,
                            left=left["sample"],
                            right=right["sample"],
                            property_name=property_name,
                            result_lookup=result_lookup,
                        )
                    self._add_pairwise_relation_spec_if_numeric_delta(
                        selected_specs,
                        document_id=document_id,
                        left=left["sample"],
                        right=right["sample"],
                        property_name=PAIRWISE_RELATION_DUCTILITY_PROPERTY,
                        result_lookup=result_lookup,
                        min_abs_delta=PAIRWISE_RELATION_ELONGATION_MIN_DELTA,
                    )
                    self._add_pairwise_relation_spec_if_numeric_delta(
                        selected_specs,
                        document_id=document_id,
                        left=left["sample"],
                        right=right["sample"],
                        property_name=PAIRWISE_RELATION_DENSITY_PROPERTY,
                        result_lookup=result_lookup,
                        min_abs_delta=PAIRWISE_RELATION_DENSITY_MIN_DELTA,
                    )

        eligible_strategy_groups = [
            (key, group)
            for key, group in strategy_groups.items()
            if len(group) >= 2
            and any(item["scan_strategy"] == primary_strategy for item in group)
        ]
        if eligible_strategy_groups:
            first_group_key, first_group = sorted(
                eligible_strategy_groups,
                key=lambda item: (item[0][0], -item[0][1]),
            )[0]
            primary_group_key = next(
                (
                    key
                    for key, group in strategy_groups.items()
                    if any(item["variant_id"] == primary["variant_id"] for item in group)
                ),
                None,
            )
            primary_group = (
                strategy_groups.get(primary_group_key, [])
                if primary_group_key is not None
                else []
            )

            self._add_first_strategy_group_specs(
                selected_specs,
                document_id=document_id,
                group=first_group,
                primary_strategy=primary_strategy,
                density_values=density_values,
                result_lookup=result_lookup,
            )
            if primary_group and primary_group_key != first_group_key:
                self._add_primary_strategy_group_specs(
                    selected_specs,
                    document_id=document_id,
                    group=primary_group,
                    primary_variant_id=primary["variant_id"],
                    result_lookup=result_lookup,
                )

        return selected_specs or all_specs

    def _add_first_strategy_group_specs(
        self,
        selected_specs: set[tuple[str, str, str]],
        *,
        document_id: str,
        group: list[dict[str, Any]],
        primary_strategy: str,
        density_values: dict[str, float],
        result_lookup: dict[tuple[str, str, str], dict[str, Any]],
    ) -> None:
        density_ordered = sorted(
            group,
            key=lambda item: density_values.get(item["variant_id"], -math.inf),
        )
        for lower, higher in zip(density_ordered, density_ordered[1:]):
            self._add_pairwise_relation_spec_if_numeric_delta(
                selected_specs,
                document_id=document_id,
                left=lower["sample"],
                right=higher["sample"],
                property_name=PAIRWISE_RELATION_DENSITY_PROPERTY,
                result_lookup=result_lookup,
            )

        primary_sample = next(
            (
                item
                for item in group
                if self.safe_text(item.get("scan_strategy")) == primary_strategy
            ),
            None,
        )
        secondary_sample = next(
            (
                item
                for item in sorted(group, key=lambda item: item["scan_strategy"])
                if self.safe_text(item.get("scan_strategy")) != primary_strategy
            ),
            None,
        )
        if primary_sample is None or secondary_sample is None:
            return
        for property_name in (
            *PAIRWISE_RELATION_TENSILE_PROPERTIES,
            PAIRWISE_RELATION_DUCTILITY_PROPERTY,
        ):
            self._add_pairwise_relation_spec_if_current_higher(
                selected_specs,
                document_id=document_id,
                current=primary_sample["sample"],
                reference=secondary_sample["sample"],
                property_name=property_name,
                result_lookup=result_lookup,
            )

    def _add_primary_strategy_group_specs(
        self,
        selected_specs: set[tuple[str, str, str]],
        *,
        document_id: str,
        group: list[dict[str, Any]],
        primary_variant_id: str,
        result_lookup: dict[tuple[str, str, str], dict[str, Any]],
    ) -> None:
        primary_sample = next(
            (item for item in group if item["variant_id"] == primary_variant_id),
            None,
        )
        if primary_sample is None:
            return
        for reference_sample in group:
            if reference_sample["variant_id"] == primary_variant_id:
                continue
            for property_name in (
                "yield_strength",
                PAIRWISE_RELATION_DUCTILITY_PROPERTY,
            ):
                self._add_pairwise_relation_spec_if_current_higher(
                    selected_specs,
                    document_id=document_id,
                    current=primary_sample["sample"],
                    reference=reference_sample["sample"],
                    property_name=property_name,
                    result_lookup=result_lookup,
                )

    def _add_pairwise_relation_spec_if_current_higher(
        self,
        selected_specs: set[tuple[str, str, str]],
        *,
        document_id: str,
        current: dict[str, Any],
        reference: dict[str, Any],
        property_name: str,
        result_lookup: dict[tuple[str, str, str], dict[str, Any]],
    ) -> None:
        current_value = self._pairwise_result_value(
            document_id=document_id,
            sample=current,
            property_name=property_name,
            result_lookup=result_lookup,
        )
        reference_value = self._pairwise_result_value(
            document_id=document_id,
            sample=reference,
            property_name=property_name,
            result_lookup=result_lookup,
        )
        if current_value is None or reference_value is None:
            return
        if current_value <= reference_value:
            return
        selected_specs.add(
            self._pairwise_relation_spec_key(current, reference, property_name)
        )

    def _add_pairwise_relation_spec_if_numeric_delta(
        self,
        selected_specs: set[tuple[str, str, str]],
        *,
        document_id: str,
        left: dict[str, Any],
        right: dict[str, Any],
        property_name: str,
        result_lookup: dict[tuple[str, str, str], dict[str, Any]],
        min_abs_delta: float = 0.0,
    ) -> None:
        left_value = self._pairwise_result_value(
            document_id=document_id,
            sample=left,
            property_name=property_name,
            result_lookup=result_lookup,
        )
        right_value = self._pairwise_result_value(
            document_id=document_id,
            sample=right,
            property_name=property_name,
            result_lookup=result_lookup,
        )
        if left_value is None or right_value is None:
            return
        if math.isclose(left_value, right_value):
            return
        if abs(left_value - right_value) < min_abs_delta:
            return
        selected_specs.add(self._pairwise_relation_spec_key(left, right, property_name))

    def _pairwise_result_value(
        self,
        *,
        document_id: str,
        sample: dict[str, Any],
        property_name: str,
        result_lookup: dict[tuple[str, str, str], dict[str, Any]],
    ) -> float | None:
        result = result_lookup.get(
            (
                document_id,
                self.safe_text(sample.get("variant_id")) or "",
                property_name,
            )
        )
        if result is None:
            return None
        _, value = self.summarize_result(
            result_type=self.safe_text(result.get("result_type")) or "scalar",
            value_payload=result.get("value_payload"),
            unit=self.safe_text(result.get("unit")),
        )
        return value

    def _pairwise_relation_spec_key(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
        property_name: str,
    ) -> tuple[str, str, str]:
        left_variant_id = self.safe_text(left.get("variant_id")) or ""
        right_variant_id = self.safe_text(right.get("variant_id")) or ""
        first, second = sorted((left_variant_id, right_variant_id))
        return first, second, property_name

    def _numeric_process_value(
        self,
        process_context: dict[str, Any],
        key: str,
    ) -> float | None:
        value = self.normalize_scalar_or_text(process_context.get(key))
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
        if isinstance(value, str):
            try:
                parsed = float(value)
            except ValueError:
                return None
            return parsed if math.isfinite(parsed) else None
        return None

    def _single_pairwise_comparison_axis(
        self,
        left_process_context: Any,
        right_process_context: Any,
    ) -> str | None:
        left_payload = self.normalize_object(left_process_context)
        right_payload = self.normalize_object(right_process_context)
        if not isinstance(left_payload, dict) or not isinstance(right_payload, dict):
            return None
        changed_axes = []
        for key in PAIRWISE_RELATION_AXIS_KEYS:
            left_value = self.normalize_scalar_or_text(left_payload.get(key))
            right_value = self.normalize_scalar_or_text(right_payload.get(key))
            if left_value != right_value:
                changed_axes.append(key)
        if len(changed_axes) != 1:
            return None
        return changed_axes[0]

    def _build_pairwise_comparison_relation(
        self,
        *,
        collection_id: str,
        document_id: str,
        comparison_axis: str,
        left_sample: dict[str, Any],
        right_sample: dict[str, Any],
        left_result: dict[str, Any],
        right_result: dict[str, Any],
    ) -> PairwiseComparisonRelation | None:
        _, left_value = self.summarize_result(
            result_type=self.safe_text(left_result.get("result_type")) or "scalar",
            value_payload=left_result.get("value_payload"),
            unit=self.safe_text(left_result.get("unit")),
        )
        _, right_value = self.summarize_result(
            result_type=self.safe_text(right_result.get("result_type")) or "scalar",
            value_payload=right_result.get("value_payload"),
            unit=self.safe_text(right_result.get("unit")),
        )
        if left_value is None or right_value is None or left_value == right_value:
            return None

        current_sample = left_sample if left_value > right_value else right_sample
        reference_sample = right_sample if left_value > right_value else left_sample
        current_result = left_result if left_value > right_value else right_result
        reference_result = right_result if left_value > right_value else left_result
        current_value = max(left_value, right_value)
        reference_value = min(left_value, right_value)
        property_name = self.safe_text(current_result.get("property_normalized")) or "qualitative"
        current_variant_id = self.safe_text(current_sample.get("variant_id")) or ""
        reference_variant_id = self.safe_text(reference_sample.get("variant_id")) or ""
        current_result_id = self.safe_text(current_result.get("result_id")) or ""
        reference_result_id = self.safe_text(reference_result.get("result_id")) or ""
        if not all((current_variant_id, reference_variant_id, current_result_id, reference_result_id)):
            return None

        relation_id = build_pairwise_comparison_relation_id(
            collection_id=collection_id,
            document_id=document_id,
            current_variant_id=current_variant_id,
            reference_variant_id=reference_variant_id,
            property_normalized=property_name,
            comparison_axis=comparison_axis,
            current_result_id=current_result_id,
            reference_result_id=reference_result_id,
        )
        return PairwiseComparisonRelation(
            relation_id=relation_id,
            collection_id=collection_id,
            document_id=document_id,
            current_variant_id=current_variant_id,
            reference_variant_id=reference_variant_id,
            comparison_axis=comparison_axis,
            property_normalized=property_name,
            current_result_id=current_result_id,
            reference_result_id=reference_result_id,
            current_value=current_value,
            reference_value=reference_value,
            unit=self.safe_text(current_result.get("unit"))
            or self.safe_text(reference_result.get("unit")),
            direction="increase",
            evidence_anchor_ids=tuple(
                self.dedupe_strings(
                    [
                        *self.normalize_string_list(
                            current_result.get("evidence_anchor_ids")
                        ),
                        *self.normalize_string_list(
                            reference_result.get("evidence_anchor_ids")
                        ),
                    ]
                )
            ),
            relation_payload={
                "current_variant_label": self.safe_text(
                    current_sample.get("variant_label")
                ),
                "reference_variant_label": self.safe_text(
                    reference_sample.get("variant_label")
                ),
                "comparison_axis": comparison_axis,
            },
            confidence=0.84,
            epistemic_status=EPISTEMIC_NORMALIZED_FROM_EVIDENCE,
        )

    def assemble_comparable_result(
        self,
        *,
        result_row: dict[str, Any],
        sample_lookup: dict[str, dict[str, Any]],
        test_condition_lookup: dict[str, dict[str, Any]],
        baseline_lookup: dict[str, dict[str, Any]],
    ) -> ComparableResult | None:
        source_document_id = self.safe_text(result_row.get("document_id"))
        if not source_document_id:
            logger.debug("Skipped comparison result without source_document_id")
            return None
        claim_scope = self.safe_text(result_row.get("claim_scope")) or "current_work"
        if claim_scope != "current_work":
            logger.debug(
                "Skipped comparison result outside current_work claim scope result_id=%s claim_scope=%s",
                self.safe_text(result_row.get("result_id")),
                claim_scope,
            )
            return None

        variant_id = self.safe_text(result_row.get("variant_id"))
        variant = sample_lookup.get(variant_id or "", {})
        test_condition_id = self.safe_text(result_row.get("test_condition_id"))
        test_condition = test_condition_lookup.get(test_condition_id or "", {})
        baseline_id = self.safe_text(result_row.get("baseline_id"))
        baseline = baseline_lookup.get(baseline_id or "", {})

        supporting_anchor_ids = self.normalize_string_list(
            result_row.get("evidence_anchor_ids")
        )
        supporting_evidence_ids = self.build_supporting_evidence_ids(result_row)
        characterization_observation_ids = self.normalize_string_list(
            result_row.get("characterization_observation_ids")
        )
        structure_feature_ids = self.normalize_string_list(
            result_row.get("structure_feature_ids")
        )

        result_type = self.safe_text(result_row.get("result_type")) or "scalar"
        unit = self.safe_text(result_row.get("unit"))
        result_summary, numeric_value = self.summarize_result(
            result_type=result_type,
            value_payload=result_row.get("value_payload"),
            unit=unit,
        )

        baseline_reference = self.safe_text(baseline.get("baseline_label"))
        material_system_normalized = self.normalize_material_system(
            variant.get("host_material_system")
        )
        process_normalized = self.normalize_process(variant.get("process_context"))
        property_normalized = (
            self.safe_text(result_row.get("property_normalized")) or "qualitative"
        )
        baseline_normalized = baseline_reference or "unspecified baseline"
        test_condition_normalized = self.summarize_test_condition(test_condition)
        traceability_status = (
            self.safe_text(result_row.get("traceability_status"))
            or TRACEABILITY_STATUS_MISSING
        )

        normalized_variant_payload = {
            "variant_label": self.safe_text(variant.get("variant_label")),
            "variable_axis": self.safe_text(variant.get("variable_axis_type")),
            "variable_value": self.normalize_scalar_or_text(variant.get("variable_value")),
            "material_system_normalized": material_system_normalized,
            "process_normalized": process_normalized,
            "host_material_system": self.normalize_object(
                variant.get("host_material_system")
            ),
            "process_context": self.normalize_object(variant.get("process_context")),
        }
        normalized_baseline_payload = {
            "baseline_label": baseline_reference,
            "baseline_type": self.safe_text(baseline.get("baseline_type")),
            "baseline_scope": self.safe_text(baseline.get("baseline_scope")),
        }
        normalized_test_condition_payload = {
            "condition_payload": self.normalize_object(
                test_condition.get("condition_payload")
            ),
            "condition_normalized": test_condition_normalized,
        }
        direct_anchor_ids = tuple(supporting_anchor_ids)
        contextual_anchor_ids = tuple(
            self.dedupe_strings(
                [
                    *self.normalize_string_list(variant.get("source_anchor_ids")),
                    *self.normalize_string_list(test_condition.get("evidence_anchor_ids")),
                    *self.normalize_string_list(baseline.get("evidence_anchor_ids")),
                ]
            )
        )
        evidence_ids = tuple(supporting_evidence_ids)
        comparable_result_id = build_comparable_result_id(
            source_document_id=source_document_id,
            property_normalized=property_normalized,
            result_type=result_type,
            value_payload=self.normalize_object(result_row.get("value_payload")),
            unit=unit,
            result_source_type=self.safe_text(result_row.get("result_source_type")),
            traceability_status=traceability_status,
            variant_payload=normalized_variant_payload,
            baseline_payload=normalized_baseline_payload,
            test_condition_payload=normalized_test_condition_payload,
            normalization_version=COMPARABLE_RESULT_NORMALIZATION_VERSION,
        )
        return ComparableResult(
            comparable_result_id=comparable_result_id,
            source_result_id=self.safe_text(result_row.get("result_id")) or "",
            source_document_id=source_document_id,
            binding=ContextBinding(
                variant_id=variant_id,
                baseline_id=baseline_id,
                test_condition_id=test_condition_id,
            ),
            normalized_context=NormalizedComparisonContext(
                material_system_normalized=material_system_normalized,
                process_normalized=process_normalized,
                baseline_normalized=baseline_normalized,
                test_condition_normalized=test_condition_normalized,
            ),
            axis=ComparisonAxis(
                axis_name=normalized_variant_payload["variable_axis"],
                axis_value=normalized_variant_payload["variable_value"],
                axis_unit=None,
            ),
            value=ResultValue(
                property_normalized=property_normalized,
                result_type=result_type,
                numeric_value=numeric_value,
                unit=unit,
                summary=result_summary,
            ),
            evidence=EvidenceTrace(
                direct_anchor_ids=direct_anchor_ids,
                contextual_anchor_ids=contextual_anchor_ids,
                evidence_ids=evidence_ids,
                structure_feature_ids=tuple(structure_feature_ids),
                characterization_observation_ids=tuple(
                    characterization_observation_ids
                ),
                traceability_status=traceability_status,
            ),
            variant_label=normalized_variant_payload["variant_label"],
            baseline_reference=baseline_reference,
            result_source_type=self.safe_text(result_row.get("result_source_type")),
            epistemic_status=self.safe_text(result_row.get("epistemic_status")) or "",
            normalization_version=COMPARABLE_RESULT_NORMALIZATION_VERSION,
        )

    def build_collection_comparable_result(
        self,
        *,
        collection_id: str,
        comparable_result: ComparableResult,
        sort_order: int | None,
        assessment_context: dict[str, Any] | None = None,
    ) -> CollectionComparableResult:
        assessment = evaluate_comparison_assessment(
            comparable_result,
            assessment_context=assessment_context,
        )
        return CollectionComparableResult(
            collection_id=collection_id,
            comparable_result_id=comparable_result.comparable_result_id,
            assessment=assessment,
            epistemic_status=assessment.assessment_epistemic_status,
            included=True,
            sort_order=sort_order,
            policy_family=COLLECTION_COMPARISON_POLICY_FAMILY,
            policy_version=COLLECTION_COMPARISON_POLICY_VERSION,
            comparable_result_normalization_version=comparable_result.normalization_version,
            assessment_input_fingerprint=build_collection_assessment_input_fingerprint(
                comparable_result
            ),
            reassessment_triggers=DEFAULT_COLLECTION_REASSESSMENT_TRIGGERS,
        )

    def build_assessment_context(
        self,
        *,
        result_row: dict[str, Any],
        sample_lookup: dict[str, dict[str, Any]],
        test_condition_lookup: dict[str, dict[str, Any]],
        baseline_lookup: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        variant_id = self.safe_text(result_row.get("variant_id"))
        test_condition_id = self.safe_text(result_row.get("test_condition_id"))
        baseline_id = self.safe_text(result_row.get("baseline_id"))
        return {
            "variant": sample_lookup.get(variant_id or "", {}),
            "test_condition": test_condition_lookup.get(test_condition_id or "", {}),
            "baseline": baseline_lookup.get(baseline_id or "", {}),
            "measurement_result": dict(result_row),
        }

    def normalize_comparable_results(
        self,
        results: Iterable[ComparableResult | dict[str, Any]],
    ) -> tuple[ComparableResult, ...]:
        return tuple(
            record
            if isinstance(record, ComparableResult)
            else ComparableResult.from_mapping(record)
            for record in results
        )

    def normalize_collection_comparable_results(
        self,
        results: Iterable[CollectionComparableResult | dict[str, Any]],
    ) -> tuple[CollectionComparableResult, ...]:
        return tuple(
            record
            if isinstance(record, CollectionComparableResult)
            else CollectionComparableResult.from_mapping(record)
            for record in results
        )

    def index_by_id(
        self,
        records: Iterable[Any],
        id_field: str,
    ) -> dict[str, dict[str, Any]]:
        lookup: dict[str, dict[str, Any]] = {}
        for record in records:
            item_id = self.safe_text(getattr(record, id_field, None))
            if not item_id:
                continue
            lookup[item_id] = record.to_record()
        return lookup

    def merge_comparable_results(
        self,
        existing: ComparableResult,
        incoming: ComparableResult,
    ) -> ComparableResult:
        return ComparableResult(
            comparable_result_id=existing.comparable_result_id,
            source_result_id=existing.source_result_id or incoming.source_result_id,
            source_document_id=existing.source_document_id or incoming.source_document_id,
            binding=existing.binding,
            normalized_context=existing.normalized_context,
            axis=existing.axis,
            value=existing.value,
            evidence=EvidenceTrace(
                direct_anchor_ids=tuple(
                    self.dedupe_strings(
                        [
                            *existing.evidence.direct_anchor_ids,
                            *incoming.evidence.direct_anchor_ids,
                        ]
                    )
                ),
                contextual_anchor_ids=tuple(
                    self.dedupe_strings(
                        [
                            *existing.evidence.contextual_anchor_ids,
                            *incoming.evidence.contextual_anchor_ids,
                        ]
                    )
                ),
                evidence_ids=tuple(
                    self.dedupe_strings(
                        [
                            *existing.evidence.evidence_ids,
                            *incoming.evidence.evidence_ids,
                        ]
                    )
                ),
                structure_feature_ids=tuple(
                    self.dedupe_strings(
                        [
                            *existing.evidence.structure_feature_ids,
                            *incoming.evidence.structure_feature_ids,
                        ]
                    )
                ),
                characterization_observation_ids=tuple(
                    self.dedupe_strings(
                        [
                            *existing.evidence.characterization_observation_ids,
                            *incoming.evidence.characterization_observation_ids,
                        ]
                    )
                ),
                traceability_status=existing.evidence.traceability_status,
            ),
            variant_label=existing.variant_label or incoming.variant_label,
            baseline_reference=existing.baseline_reference or incoming.baseline_reference,
            result_source_type=existing.result_source_type or incoming.result_source_type,
            epistemic_status=existing.epistemic_status or incoming.epistemic_status,
            normalization_version=existing.normalization_version
            or incoming.normalization_version,
        )

    def merge_collection_comparable_results(
        self,
        existing: CollectionComparableResult,
        incoming: CollectionComparableResult,
    ) -> CollectionComparableResult:
        sort_order: int | None
        if existing.sort_order is None:
            sort_order = incoming.sort_order
        elif incoming.sort_order is None:
            sort_order = existing.sort_order
        else:
            sort_order = min(existing.sort_order, incoming.sort_order)
        return CollectionComparableResult(
            collection_id=existing.collection_id,
            comparable_result_id=existing.comparable_result_id,
            assessment=existing.assessment,
            epistemic_status=existing.epistemic_status or incoming.epistemic_status,
            included=existing.included or incoming.included,
            sort_order=sort_order,
            policy_family=existing.policy_family or incoming.policy_family,
            policy_version=existing.policy_version or incoming.policy_version,
            comparable_result_normalization_version=(
                existing.comparable_result_normalization_version
                or incoming.comparable_result_normalization_version
            ),
            assessment_input_fingerprint=(
                existing.assessment_input_fingerprint
                or incoming.assessment_input_fingerprint
            ),
            reassessment_triggers=(
                existing.reassessment_triggers or incoming.reassessment_triggers
            ),
        )

    def summarize_result(
        self,
        *,
        result_type: str,
        value_payload: Any,
        unit: str | None,
    ) -> tuple[str, float | None]:
        payload = self.normalize_object(value_payload)
        if not isinstance(payload, dict):
            payload = {}
        statement = self.safe_text(payload.get("statement"))

        if result_type == "retention":
            numeric = self.safe_float(
                payload.get("retention_percent", payload.get("value"))
            )
            if numeric is not None:
                unit_text = unit or "%"
                return f"{numeric:g} {unit_text} retention", numeric
            return statement or "Retention reported", None

        if result_type == "range":
            minimum = self.safe_float(payload.get("min"))
            maximum = self.safe_float(payload.get("max"))
            if minimum is not None and maximum is not None:
                span = f"{minimum:g}-{maximum:g}"
                if unit:
                    span = f"{span} {unit}"
                return span, None
            return statement or "Range reported", None

        if result_type == "trend":
            direction = self.safe_text(payload.get("direction"))
            if direction and statement:
                return statement, None
            if direction:
                return direction, None
            return statement or "Trend reported", None

        numeric = self.safe_float(payload.get("value"))
        if numeric is not None:
            summary = f"{numeric:g}"
            if unit:
                summary = f"{summary} {unit}"
            return summary, numeric
        return statement or "Result reported", None

    def summarize_test_condition(self, condition_row: dict[str, Any]) -> str:
        if not condition_row:
            return "unspecified test condition"

        payload = self.normalize_object(condition_row.get("condition_payload"))
        if not isinstance(payload, dict) or not payload:
            return "unspecified test condition"

        parts: list[str] = []
        method = self.safe_text(payload.get("test_method")) or self.safe_text(
            payload.get("method")
        )
        methods = self.normalize_string_list(payload.get("methods"))
        if method:
            parts.append(method)
        elif methods:
            parts.append(", ".join(methods))

        test_temperature = self.safe_float(payload.get("test_temperature_c"))
        if test_temperature is not None:
            parts.append(f"{test_temperature:g} C")
        else:
            temperatures = payload.get("temperatures_c")
            if isinstance(temperatures, list) and temperatures:
                parts.append(" / ".join(f"{float(value):g} C" for value in temperatures))

        strain_rate = (
            payload.get("strain_rate_s-1")
            or payload.get("strain_rate_s_1")
            or payload.get("strain_rate")
        )
        strain_rate_value = self.normalize_scalar_or_text(strain_rate)
        if strain_rate_value not in (None, "", [], {}):
            parts.append(f"strain_rate={strain_rate_value} s^-1")

        loading_direction = self.safe_text(payload.get("loading_direction"))
        if loading_direction:
            parts.append(f"loading={loading_direction}")

        sample_orientation = self.safe_text(payload.get("sample_orientation"))
        if sample_orientation:
            parts.append(f"sample={sample_orientation}")

        frequency = self.safe_float(payload.get("frequency_hz"))
        if frequency is not None:
            parts.append(f"f={frequency:g} Hz")

        environment = self.safe_text(payload.get("environment"))
        if environment:
            parts.append(f"env={environment}")

        surface_state = self.safe_text(payload.get("surface_state"))
        if surface_state:
            parts.append(f"surface={surface_state}")

        specimen_geometry = self.safe_text(payload.get("specimen_geometry"))
        if specimen_geometry:
            parts.append(f"specimen={specimen_geometry}")

        durations = self.normalize_string_list(payload.get("durations"))
        if durations:
            parts.append(" / ".join(durations))

        atmosphere = self.safe_text(payload.get("atmosphere"))
        if atmosphere:
            parts.append(f"under {atmosphere}")

        if not parts:
            fallback = [
                f"{key}={value}"
                for key, value in payload.items()
                if value not in (None, "", [], {})
            ]
            if fallback:
                return ", ".join(str(item) for item in fallback)
            return "unspecified test condition"
        return ", ".join(parts)

    def normalize_material_system(self, material_system: Any) -> str:
        payload = self.normalize_object(material_system) or {}
        if not isinstance(payload, dict):
            return str(payload)
        family = self.safe_text(payload.get("family"))
        composition = self.safe_text(payload.get("composition"))
        if family and composition and composition != family:
            return f"{family} ({composition})"
        if family:
            return family
        if composition:
            return composition
        return "unspecified material system"

    def normalize_process(self, process_context: Any) -> str:
        payload = self.normalize_object(process_context) or {}
        if not isinstance(payload, dict) or not payload:
            return "unspecified process"

        parts: list[str] = []
        consumed_keys: set[str] = set()
        pbf_key_specs = (
            ("laser_power_w", "P", "W"),
            ("scan_speed_mm_s", "v", "mm/s"),
            ("hatch_spacing_um", "h", "um"),
            ("layer_thickness_um", "t", "um"),
            ("spot_size_um", "spot", "um"),
            ("energy_density_j_mm3", "VED", "J/mm3"),
            ("preheat_temperature_c", "preheat", "C"),
            ("oxygen_level_ppm", "O2", "ppm"),
        )
        for key, label, unit in pbf_key_specs:
            numeric = self.safe_float(payload.get(key))
            if numeric is not None:
                parts.append(f"{label}={numeric:g} {unit}")
                consumed_keys.add(key)

        energy_density_origin = self.safe_text(payload.get("energy_density_origin"))
        if energy_density_origin:
            parts.append(f"VED_origin={energy_density_origin}")
            consumed_keys.add("energy_density_origin")

        for key, label in (
            ("scan_strategy", "scan"),
            ("build_orientation", "build"),
            ("shielding_gas", "gas"),
            ("powder_size_distribution_um", "powder"),
        ):
            value = self.normalize_scalar_or_text(payload.get(key))
            if value not in (None, "", [], {}):
                parts.append(f"{label}={value}")
                consumed_keys.add(key)

        post_treatment = self.safe_text(payload.get("post_treatment_summary"))
        if post_treatment:
            parts.append(post_treatment)
            consumed_keys.add("post_treatment_summary")

        temperatures = payload.get("temperatures_c")
        if isinstance(temperatures, list) and temperatures:
            parts.append(" / ".join(f"{float(value):g} C" for value in temperatures))
            consumed_keys.add("temperatures_c")

        durations = self.normalize_string_list(payload.get("durations"))
        if durations:
            parts.append(" / ".join(durations))
            consumed_keys.add("durations")

        atmosphere = self.safe_text(payload.get("atmosphere"))
        if atmosphere:
            parts.append(f"under {atmosphere}")
            consumed_keys.add("atmosphere")

        for key, value in payload.items():
            if key in consumed_keys:
                continue
            normalized = self.normalize_scalar_or_text(value)
            if normalized not in (None, "", [], {}):
                parts.append(f"{key}={normalized}")

        return ", ".join(str(part) for part in parts) if parts else "unspecified process"

    def build_supporting_evidence_ids(
        self,
        result_row: dict[str, Any],
    ) -> list[str]:
        result_id = self.safe_text(result_row.get("result_id"))
        if not result_id:
            return []
        return [f"ev_result_{result_id}"]

    def normalize_string_list(self, value: Any) -> list[str]:
        payload = self.normalize_object(value)
        if payload is None:
            return []
        if isinstance(payload, list):
            return [str(item) for item in payload if self.safe_text(item)]
        text = self.safe_text(payload)
        return [text] if text else []

    def dedupe_strings(self, values: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = self.safe_text(value)
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
        return deduped

    def normalize_scalar_or_text(self, value: Any) -> str | float | int | None:
        payload = self.normalize_object(value)
        if payload is None:
            return None
        if isinstance(payload, bool):
            return str(payload).lower()
        if isinstance(payload, int):
            return payload
        if isinstance(payload, float):
            if math.isnan(payload):
                return None
            if payload.is_integer():
                return int(payload)
            return payload
        return self.safe_text(payload)

    def normalize_object(self, value: Any) -> Any:
        return normalize_record_value(value)

    def safe_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        text = str(value).strip()
        return text or None

    def safe_float(self, value: Any) -> float | None:
        try:
            if value is None or (isinstance(value, float) and math.isnan(value)):
                return None
            return float(value)
        except Exception:
            return None


__all__ = [
    "COLLECTION_COMPARABLE_RESULT_COLUMNS",
    "COMPARABLE_RESULT_COLUMNS",
    "ComparableResultAssembler",
    "ComparisonInputRecords",
    "ComparisonSemanticRecords",
]
