from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from domain.core.comparison import (
    COMPARISON_ROW_PROJECTION_VERSION,
    CollectionComparableResult,
    ComparableResult,
    ComparisonRowRecord,
    build_comparison_row_id,
)

logger = logging.getLogger(__name__)


COMPARISON_ROW_COLUMNS = [
    "row_id",
    "collection_id",
    "comparable_result_id",
    "source_document_id",
    "variant_id",
    "variant_label",
    "variable_axis",
    "variable_value",
    "baseline_reference",
    "result_source_type",
    "result_type",
    "result_summary",
    "supporting_evidence_ids",
    "supporting_anchor_ids",
    "characterization_observation_ids",
    "structure_feature_ids",
    "material_system_normalized",
    "process_normalized",
    "property_normalized",
    "baseline_normalized",
    "test_condition_normalized",
    "comparability_status",
    "comparability_warnings",
    "comparability_basis",
    "requires_expert_review",
    "assessment_epistemic_status",
    "missing_critical_context",
    "value",
    "unit",
]


class ComparisonRowProjector:
    """Project collection-scoped semantic comparison artifacts into row records."""

    def project_rows_from_semantic_artifacts(
        self,
        *,
        collection_id: str,
        comparable_results: pd.DataFrame,
        scoped_results: pd.DataFrame,
    ) -> pd.DataFrame:
        if comparable_results.empty or scoped_results.empty:
            return pd.DataFrame(columns=COMPARISON_ROW_COLUMNS)

        comparable_lookup = {
            record.comparable_result_id: record
            for record in (
                ComparableResult.from_mapping(dict(row))
                for _, row in comparable_results.iterrows()
            )
            if record.comparable_result_id
        }

        row_records_by_id: dict[str, ComparisonRowRecord] = {}
        scoped_view = scoped_results.copy()
        if "collection_id" in scoped_view.columns:
            scoped_view = scoped_view[
                scoped_view["collection_id"].apply(
                    lambda value: self.safe_text(value) == collection_id
                )
            ]
        if "included" in scoped_view.columns:
            scoped_view = scoped_view[scoped_view["included"].astype(bool)]
        scoped_view = scoped_view.assign(
            _sort_order_key=scoped_view["sort_order"].apply(
                lambda value: (
                    1_000_000_000
                    if value is None or (isinstance(value, float) and pd.isna(value))
                    else int(value)
                )
            )
            if "sort_order" in scoped_view.columns
            else 1_000_000_000
        ).sort_values(
            by=["_sort_order_key", "comparable_result_id"],
            kind="stable",
        )

        for _, row in scoped_view.iterrows():
            scoped_result = CollectionComparableResult.from_mapping(dict(row))
            comparable_result = comparable_lookup.get(scoped_result.comparable_result_id)
            if comparable_result is None:
                logger.warning(
                    "Comparison projection skipped scoped_result without semantic payload collection_id=%s comparable_result_id=%s",
                    collection_id,
                    scoped_result.comparable_result_id,
                )
                continue
            row_record = self.project_row(
                comparable_result=comparable_result,
                scoped_result=scoped_result,
            )
            existing_row = row_records_by_id.get(row_record.row_id)
            row_records_by_id[row_record.row_id] = (
                self.merge_row_records(existing_row, row_record)
                if existing_row is not None
                else row_record
            )

        return self.normalize_rows_table(
            pd.DataFrame(
                [record.to_record() for record in row_records_by_id.values()],
                columns=COMPARISON_ROW_COLUMNS,
            ),
            collection_id,
        )

    def project_row(
        self,
        *,
        comparable_result: ComparableResult,
        scoped_result: CollectionComparableResult,
    ) -> ComparisonRowRecord:
        assessment = scoped_result.assessment
        return ComparisonRowRecord(
            row_id=build_comparison_row_id(
                collection_id=scoped_result.collection_id,
                comparable_result_id=comparable_result.comparable_result_id,
                projection_version=COMPARISON_ROW_PROJECTION_VERSION,
            ),
            collection_id=scoped_result.collection_id,
            comparable_result_id=comparable_result.comparable_result_id,
            source_document_id=comparable_result.source_document_id,
            variant_id=comparable_result.binding.variant_id,
            variant_label=comparable_result.variant_label,
            variable_axis=comparable_result.axis.axis_name,
            variable_value=comparable_result.axis.axis_value,
            baseline_reference=comparable_result.baseline_reference,
            result_source_type=comparable_result.result_source_type,
            result_type=comparable_result.value.result_type,
            result_summary=comparable_result.value.summary,
            supporting_evidence_ids=comparable_result.evidence.evidence_ids,
            supporting_anchor_ids=comparable_result.evidence.direct_anchor_ids,
            characterization_observation_ids=comparable_result.evidence.characterization_observation_ids,
            structure_feature_ids=comparable_result.evidence.structure_feature_ids,
            material_system_normalized=comparable_result.normalized_context.material_system_normalized,
            process_normalized=comparable_result.normalized_context.process_normalized
            or "unspecified process",
            property_normalized=comparable_result.value.property_normalized,
            baseline_normalized=comparable_result.normalized_context.baseline_normalized
            or "unspecified baseline",
            test_condition_normalized=comparable_result.normalized_context.test_condition_normalized
            or "unspecified test condition",
            comparability_status=assessment.comparability_status,
            comparability_warnings=assessment.comparability_warnings,
            comparability_basis=assessment.comparability_basis,
            requires_expert_review=assessment.requires_expert_review,
            assessment_epistemic_status=assessment.assessment_epistemic_status,
            missing_critical_context=assessment.missing_critical_context,
            value=comparable_result.value.numeric_value,
            unit=comparable_result.value.unit,
        )

    def merge_row_records(
        self,
        existing: ComparisonRowRecord,
        incoming: ComparisonRowRecord,
    ) -> ComparisonRowRecord:
        return ComparisonRowRecord(
            row_id=existing.row_id,
            collection_id=existing.collection_id,
            comparable_result_id=existing.comparable_result_id,
            source_document_id=existing.source_document_id,
            variant_id=existing.variant_id,
            variant_label=existing.variant_label,
            variable_axis=existing.variable_axis,
            variable_value=existing.variable_value,
            baseline_reference=existing.baseline_reference,
            result_source_type=existing.result_source_type,
            result_type=existing.result_type,
            result_summary=existing.result_summary,
            supporting_evidence_ids=tuple(
                self.dedupe_strings(
                    [
                        *existing.supporting_evidence_ids,
                        *incoming.supporting_evidence_ids,
                    ]
                )
            ),
            supporting_anchor_ids=tuple(
                self.dedupe_strings(
                    [
                        *existing.supporting_anchor_ids,
                        *incoming.supporting_anchor_ids,
                    ]
                )
            ),
            characterization_observation_ids=tuple(
                self.dedupe_strings(
                    [
                        *existing.characterization_observation_ids,
                        *incoming.characterization_observation_ids,
                    ]
                )
            ),
            structure_feature_ids=tuple(
                self.dedupe_strings(
                    [
                        *existing.structure_feature_ids,
                        *incoming.structure_feature_ids,
                    ]
                )
            ),
            material_system_normalized=existing.material_system_normalized,
            process_normalized=existing.process_normalized,
            property_normalized=existing.property_normalized,
            baseline_normalized=existing.baseline_normalized,
            test_condition_normalized=existing.test_condition_normalized,
            comparability_status=existing.comparability_status,
            comparability_warnings=existing.comparability_warnings,
            comparability_basis=existing.comparability_basis,
            requires_expert_review=existing.requires_expert_review,
            assessment_epistemic_status=existing.assessment_epistemic_status,
            missing_critical_context=existing.missing_critical_context,
            value=existing.value,
            unit=existing.unit,
        )

    def normalize_rows_table(
        self,
        rows: pd.DataFrame,
        collection_id: str | None,
    ) -> pd.DataFrame:
        if rows is None or rows.empty:
            return pd.DataFrame(columns=COMPARISON_ROW_COLUMNS)

        normalized = rows.copy()
        if collection_id is not None and "collection_id" not in normalized.columns:
            normalized["collection_id"] = collection_id
        for column in COMPARISON_ROW_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = None
        records = [
            ComparisonRowRecord.from_mapping(dict(row)).to_record()
            for _, row in normalized.iterrows()
        ]
        return pd.DataFrame(records, columns=COMPARISON_ROW_COLUMNS)

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

    def safe_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        text = str(value).strip()
        return text or None


__all__ = [
    "COMPARISON_ROW_COLUMNS",
    "ComparisonRowProjector",
]
