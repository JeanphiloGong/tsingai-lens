from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

import pandas as pd

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
    ResultValue,
    build_collection_assessment_input_fingerprint,
    build_comparable_result_id,
    evaluate_comparison_assessment,
)
from domain.shared.enums import TRACEABILITY_STATUS_MISSING
from infra.persistence.backbone_codec import normalize_backbone_value

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


@dataclass(frozen=True)
class ComparisonInputFrames:
    sample_variants: pd.DataFrame
    measurement_results: pd.DataFrame
    test_conditions: pd.DataFrame
    baseline_references: pd.DataFrame


@dataclass(frozen=True)
class ComparisonSemanticTables:
    comparable_results: pd.DataFrame
    collection_comparable_results: pd.DataFrame


class ComparableResultAssembler:
    """Assemble semantic comparison artifacts from paper-facts frames."""

    def assemble_semantic_tables(
        self,
        *,
        collection_id: str,
        frames: ComparisonInputFrames,
    ) -> ComparisonSemanticTables:
        sample_lookup = self.index_by_id(frames.sample_variants, "variant_id")
        test_condition_lookup = self.index_by_id(
            frames.test_conditions,
            "test_condition_id",
        )
        baseline_lookup = self.index_by_id(
            frames.baseline_references,
            "baseline_id",
        )

        comparable_results_by_id: dict[str, ComparableResult] = {}
        scoped_results_by_id: dict[str, CollectionComparableResult] = {}
        for sort_order, (_, result_row) in enumerate(
            frames.measurement_results.iterrows()
        ):
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

        return ComparisonSemanticTables(
            comparable_results=self.normalize_comparable_results_table(
                pd.DataFrame(
                    [
                        record.to_record()
                        for record in comparable_results_by_id.values()
                    ],
                    columns=COMPARABLE_RESULT_COLUMNS,
                )
            ),
            collection_comparable_results=self.normalize_collection_comparable_results_table(
                pd.DataFrame(
                    [record.to_record() for record in scoped_results_by_id.values()],
                    columns=COLLECTION_COMPARABLE_RESULT_COLUMNS,
                )
            ),
        )

    def assemble_comparable_result(
        self,
        *,
        result_row: pd.Series,
        sample_lookup: dict[str, dict[str, Any]],
        test_condition_lookup: dict[str, dict[str, Any]],
        baseline_lookup: dict[str, dict[str, Any]],
    ) -> ComparableResult | None:
        source_document_id = self.safe_text(result_row.get("document_id"))
        if not source_document_id:
            logger.debug("Skipped comparison result without source_document_id")
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
    ) -> CollectionComparableResult:
        assessment = evaluate_comparison_assessment(comparable_result)
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

    def normalize_comparable_results_table(self, results: pd.DataFrame) -> pd.DataFrame:
        if results is None or results.empty:
            return pd.DataFrame(columns=COMPARABLE_RESULT_COLUMNS)

        normalized = results.copy()
        for column in COMPARABLE_RESULT_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = None
        records = [
            ComparableResult.from_mapping(dict(row)).to_record()
            for _, row in normalized.iterrows()
        ]
        return pd.DataFrame(records, columns=COMPARABLE_RESULT_COLUMNS)

    def normalize_collection_comparable_results_table(
        self,
        results: pd.DataFrame,
    ) -> pd.DataFrame:
        if results is None or results.empty:
            return pd.DataFrame(columns=COLLECTION_COMPARABLE_RESULT_COLUMNS)

        normalized = results.copy()
        for column in COLLECTION_COMPARABLE_RESULT_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = None
        records = [
            CollectionComparableResult.from_mapping(dict(row)).to_record()
            for _, row in normalized.iterrows()
        ]
        return pd.DataFrame(records, columns=COLLECTION_COMPARABLE_RESULT_COLUMNS)

    def index_by_id(
        self,
        frame: pd.DataFrame,
        id_column: str,
    ) -> dict[str, dict[str, Any]]:
        if frame is None or frame.empty:
            return {}
        lookup: dict[str, dict[str, Any]] = {}
        for _, row in frame.iterrows():
            item_id = self.safe_text(row.get(id_column))
            if not item_id:
                continue
            lookup[item_id] = dict(row)
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
        method = self.safe_text(payload.get("method"))
        methods = self.normalize_string_list(payload.get("methods"))
        if method:
            parts.append(method)
        elif methods:
            parts.append(", ".join(methods))

        temperatures = payload.get("temperatures_c")
        if isinstance(temperatures, list) and temperatures:
            parts.append(" / ".join(f"{float(value):g} C" for value in temperatures))

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
        temperatures = payload.get("temperatures_c")
        if isinstance(temperatures, list) and temperatures:
            parts.append(" / ".join(f"{float(value):g} C" for value in temperatures))

        durations = self.normalize_string_list(payload.get("durations"))
        if durations:
            parts.append(" / ".join(durations))

        atmosphere = self.safe_text(payload.get("atmosphere"))
        if atmosphere:
            parts.append(f"under {atmosphere}")

        for key, value in payload.items():
            if key in {"temperatures_c", "durations", "atmosphere"}:
                continue
            normalized = self.normalize_scalar_or_text(value)
            if normalized not in (None, "", [], {}):
                parts.append(f"{key}={normalized}")

        return ", ".join(str(part) for part in parts) if parts else "unspecified process"

    def build_supporting_evidence_ids(
        self,
        result_row: pd.Series,
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
            if pd.isna(payload):
                return None
            if payload.is_integer():
                return int(payload)
            return payload
        return self.safe_text(payload)

    def normalize_object(self, value: Any) -> Any:
        return normalize_backbone_value(value)

    def safe_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    def safe_float(self, value: Any) -> float | None:
        try:
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return None
            return float(value)
        except Exception:
            return None


__all__ = [
    "COLLECTION_COMPARABLE_RESULT_COLUMNS",
    "COMPARABLE_RESULT_COLUMNS",
    "ComparableResultAssembler",
    "ComparisonInputFrames",
    "ComparisonSemanticTables",
]
