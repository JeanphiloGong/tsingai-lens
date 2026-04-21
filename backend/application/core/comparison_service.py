from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from domain.core.comparison import (
    ComparisonRow,
    evaluate_comparison_assessment,
)
from domain.shared.enums import TRACEABILITY_STATUS_MISSING
from application.core.semantic_build.core_semantic_version import (
    core_semantic_rebuild_required,
    write_core_semantic_manifest,
)
from application.source.collection_service import CollectionService
from application.core.semantic_build.paper_facts_service import PaperFactsNotReadyError, PaperFactsService
from application.source.artifact_registry_service import ArtifactRegistryService
from infra.persistence.backbone_codec import (
    normalize_backbone_value,
    prepare_frame_for_storage,
    restore_frame_from_storage,
)

logger = logging.getLogger(__name__)


_COMPARISON_ROWS_FILE = "comparison_rows.parquet"
_SAMPLE_VARIANTS_FILE = "sample_variants.parquet"
_MEASUREMENT_RESULTS_FILE = "measurement_results.parquet"
_TEST_CONDITIONS_FILE = "test_conditions.parquet"
_BASELINE_REFERENCES_FILE = "baseline_references.parquet"
_SAMPLE_VARIANT_JSON_COLUMNS = (
    "host_material_system",
    "process_context",
    "profile_payload",
    "structure_feature_ids",
    "source_anchor_ids",
)
_MEASUREMENT_RESULT_JSON_COLUMNS = (
    "value_payload",
    "structure_feature_ids",
    "characterization_observation_ids",
    "evidence_anchor_ids",
)
_TEST_CONDITION_JSON_COLUMNS = (
    "condition_payload",
    "missing_fields",
    "evidence_anchor_ids",
)
_BASELINE_REFERENCE_JSON_COLUMNS = ("evidence_anchor_ids",)
_COMPARISON_JSON_COLUMNS = (
    "supporting_evidence_ids",
    "supporting_anchor_ids",
    "characterization_observation_ids",
    "structure_feature_ids",
    "comparability_warnings",
    "comparability_basis",
    "missing_critical_context",
)
_COMPARISON_ROW_COLUMNS = [
    "row_id",
    "collection_id",
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
class ComparisonRowsNotReadyError(RuntimeError):
    """Raised when a collection cannot yet serve comparison rows."""

    def __init__(self, collection_id: str, output_dir: Path) -> None:
        self.collection_id = collection_id
        self.output_dir = output_dir
        super().__init__(f"comparison rows not ready: {collection_id}")


class ComparisonRowNotFoundError(FileNotFoundError):
    """Raised when one comparison row is missing from a collection."""

    def __init__(self, collection_id: str, row_id: str) -> None:
        self.collection_id = collection_id
        self.row_id = row_id
        super().__init__(f"comparison row not found: {collection_id}/{row_id}")


class ComparisonService:
    """Generate and serve collection-scoped comparison row artifacts."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        artifact_registry_service: ArtifactRegistryService | None = None,
        paper_facts_service: PaperFactsService | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.artifact_registry_service = (
            artifact_registry_service or ArtifactRegistryService()
        )
        self.paper_facts_service = paper_facts_service or PaperFactsService(
            collection_service=self.collection_service,
            artifact_registry_service=self.artifact_registry_service,
        )

    def list_comparison_rows(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 50,
        material_system_normalized: str | None = None,
        property_normalized: str | None = None,
        test_condition_normalized: str | None = None,
        baseline_normalized: str | None = None,
    ) -> dict[str, Any]:
        rows = self.read_comparison_rows(collection_id)
        rows = self._filter_rows(
            rows,
            material_system_normalized=material_system_normalized,
            property_normalized=property_normalized,
            test_condition_normalized=test_condition_normalized,
            baseline_normalized=baseline_normalized,
        )
        items = [
            self._serialize_row(item)
            for _, item in rows.iloc[offset : offset + limit].iterrows()
        ]
        return {
            "collection_id": collection_id,
            "total": len(rows),
            "count": len(items),
            "items": items,
        }

    def get_comparison_row(
        self,
        collection_id: str,
        row_id: str,
    ) -> dict[str, Any]:
        rows = self.read_comparison_rows(collection_id)
        matched = rows[rows["row_id"].astype(str) == str(row_id)]
        if matched.empty:
            raise ComparisonRowNotFoundError(collection_id, row_id)
        return self._serialize_row(matched.iloc[0])

    def read_comparison_rows(self, collection_id: str) -> pd.DataFrame:
        output_dir = self._resolve_output_dir(collection_id)
        path = output_dir / _COMPARISON_ROWS_FILE
        if path.is_file():
            rows = restore_frame_from_storage(
                pd.read_parquet(path),
                _COMPARISON_JSON_COLUMNS,
            )
            if core_semantic_rebuild_required(output_dir) and (output_dir / "documents.parquet").is_file():
                rows = self.build_comparison_rows(collection_id, output_dir)
        else:
            rows = self.build_comparison_rows(collection_id, output_dir)
        return self._normalize_rows_table(rows, collection_id)

    def build_comparison_rows(
        self,
        collection_id: str,
        output_dir: str | Path | None = None,
    ) -> pd.DataFrame:
        base_dir = (
            Path(output_dir).expanduser().resolve()
            if output_dir is not None
            else self._resolve_output_dir(collection_id)
        )
        frames = self._load_comparison_inputs(collection_id, base_dir)

        sample_variants = frames["sample_variants"]
        measurement_results = frames["measurement_results"]
        test_conditions = frames["test_conditions"]
        baseline_references = frames["baseline_references"]
        logger.info(
            "Comparison assembly started collection_id=%s measurement_results=%s sample_variants=%s test_conditions=%s baselines=%s",
            collection_id,
            len(measurement_results),
            len(sample_variants),
            len(test_conditions),
            len(baseline_references),
        )
        if measurement_results.empty:
            logger.warning(
                "Comparison assembly skipped due to empty measurement_results collection_id=%s",
                collection_id,
            )

        sample_lookup = self._index_by_id(sample_variants, "variant_id")
        test_condition_lookup = self._index_by_id(test_conditions, "test_condition_id")
        baseline_lookup = self._index_by_id(baseline_references, "baseline_id")

        rows = [
            self._build_row_from_result(
                collection_id=collection_id,
                result_row=result_row,
                sample_lookup=sample_lookup,
                test_condition_lookup=test_condition_lookup,
                baseline_lookup=baseline_lookup,
            )
            for _, result_row in measurement_results.iterrows()
        ]
        rows = [row for row in rows if row is not None]

        table = self._normalize_rows_table(
            pd.DataFrame(rows, columns=_COMPARISON_ROW_COLUMNS),
            collection_id,
        )
        if measurement_results.empty:
            logger.warning(
                "Comparison assembly produced zero rows because upstream measurement_results were empty collection_id=%s",
                collection_id,
            )
        elif table.empty:
            logger.warning(
                "Comparison assembly produced zero rows after filtering collection_id=%s measurement_results=%s",
                collection_id,
                len(measurement_results),
            )
        base_dir.mkdir(parents=True, exist_ok=True)
        prepare_frame_for_storage(
            table,
            _COMPARISON_JSON_COLUMNS,
        ).to_parquet(base_dir / _COMPARISON_ROWS_FILE, index=False)
        write_core_semantic_manifest(base_dir)
        self.artifact_registry_service.upsert(collection_id, base_dir)
        logger.info(
            "Comparison assembly finished collection_id=%s comparison_rows=%s",
            collection_id,
            len(table),
        )
        return table

    def _load_comparison_inputs(
        self,
        collection_id: str,
        base_dir: Path,
    ) -> dict[str, pd.DataFrame]:
        required = (
            _SAMPLE_VARIANTS_FILE,
            _MEASUREMENT_RESULTS_FILE,
            _TEST_CONDITIONS_FILE,
            _BASELINE_REFERENCES_FILE,
        )
        if any(not (base_dir / name).is_file() for name in required):
            try:
                self.paper_facts_service.build_paper_facts(collection_id, base_dir)
            except PaperFactsNotReadyError as exc:
                raise ComparisonRowsNotReadyError(collection_id, exc.output_dir) from exc

        missing = [name for name in required if not (base_dir / name).is_file()]
        if missing:
            raise ComparisonRowsNotReadyError(collection_id, base_dir)

        return {
            "sample_variants": restore_frame_from_storage(
                pd.read_parquet(base_dir / _SAMPLE_VARIANTS_FILE),
                _SAMPLE_VARIANT_JSON_COLUMNS,
            ),
            "measurement_results": restore_frame_from_storage(
                pd.read_parquet(base_dir / _MEASUREMENT_RESULTS_FILE),
                _MEASUREMENT_RESULT_JSON_COLUMNS,
            ),
            "test_conditions": restore_frame_from_storage(
                pd.read_parquet(base_dir / _TEST_CONDITIONS_FILE),
                _TEST_CONDITION_JSON_COLUMNS,
            ),
            "baseline_references": restore_frame_from_storage(
                pd.read_parquet(base_dir / _BASELINE_REFERENCES_FILE),
                _BASELINE_REFERENCE_JSON_COLUMNS,
            ),
        }

    def _resolve_output_dir(self, collection_id: str) -> Path:
        self.collection_service.get_collection(collection_id)
        try:
            artifacts = self.artifact_registry_service.get(collection_id)
        except FileNotFoundError:
            artifacts = None
        if artifacts and artifacts.get("output_path"):
            return Path(str(artifacts["output_path"])).expanduser().resolve()
        return self.collection_service.get_paths(collection_id).output_dir.resolve()

    def _index_by_id(
        self,
        frame: pd.DataFrame,
        id_column: str,
    ) -> dict[str, dict[str, Any]]:
        if frame is None or frame.empty:
            return {}
        lookup: dict[str, dict[str, Any]] = {}
        for _, row in frame.iterrows():
            item_id = self._safe_text(row.get(id_column))
            if not item_id:
                continue
            lookup[item_id] = dict(row)
        return lookup

    def _build_row_from_result(
        self,
        *,
        collection_id: str,
        result_row: pd.Series,
        sample_lookup: dict[str, dict[str, Any]],
        test_condition_lookup: dict[str, dict[str, Any]],
        baseline_lookup: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        source_document_id = self._safe_text(result_row.get("document_id"))
        if not source_document_id:
            logger.debug("Skipped comparison result without source_document_id")
            return None

        variant_id = self._safe_text(result_row.get("variant_id"))
        variant = sample_lookup.get(variant_id or "", {})
        test_condition_id = self._safe_text(result_row.get("test_condition_id"))
        test_condition = test_condition_lookup.get(test_condition_id or "", {})
        baseline_id = self._safe_text(result_row.get("baseline_id"))
        baseline = baseline_lookup.get(baseline_id or "", {})

        supporting_anchor_ids = self._normalize_string_list(
            result_row.get("evidence_anchor_ids")
        )
        supporting_evidence_ids = self._build_supporting_evidence_ids(result_row)
        characterization_observation_ids = self._normalize_string_list(
            result_row.get("characterization_observation_ids")
        )
        structure_feature_ids = self._normalize_string_list(
            result_row.get("structure_feature_ids")
        )

        result_type = self._safe_text(result_row.get("result_type")) or "scalar"
        unit = self._safe_text(result_row.get("unit"))
        result_summary, numeric_value = self._summarize_result(
            result_type=result_type,
            value_payload=result_row.get("value_payload"),
            unit=unit,
        )

        baseline_reference = self._safe_text(baseline.get("baseline_label"))
        baseline_normalized = baseline_reference or "unspecified baseline"
        test_condition_normalized = self._summarize_test_condition(test_condition)
        traceability_status = (
            self._safe_text(result_row.get("traceability_status"))
            or TRACEABILITY_STATUS_MISSING
        )

        assessment = evaluate_comparison_assessment(
            variant_id=variant_id,
            baseline_reference=baseline_reference,
            test_condition_id=test_condition_id,
            traceability_status=traceability_status,
            result_type=result_type,
            result_summary=result_summary,
            numeric_value=numeric_value,
            structure_feature_ids=structure_feature_ids,
            characterization_observation_ids=characterization_observation_ids,
        )
        return ComparisonRow.from_mapping(
            {
                "row_id": f"cmp_{uuid4().hex[:12]}",
                "collection_id": collection_id,
                "source_document_id": source_document_id,
                "variant_id": variant_id,
                "variant_label": self._safe_text(variant.get("variant_label")),
                "variable_axis": self._safe_text(variant.get("variable_axis_type")),
                "variable_value": self._normalize_scalar_or_text(variant.get("variable_value")),
                "baseline_reference": baseline_reference,
                "result_source_type": self._safe_text(result_row.get("result_source_type")),
                "result_type": result_type,
                "result_summary": result_summary,
                "supporting_evidence_ids": supporting_evidence_ids,
                "supporting_anchor_ids": supporting_anchor_ids,
                "characterization_observation_ids": characterization_observation_ids,
                "structure_feature_ids": structure_feature_ids,
                "material_system_normalized": self._normalize_material_system(
                    variant.get("host_material_system")
                ),
                "process_normalized": self._normalize_process(variant.get("process_context")),
                "property_normalized": self._safe_text(result_row.get("property_normalized"))
                or "qualitative",
                "baseline_normalized": baseline_normalized,
                "test_condition_normalized": test_condition_normalized,
                "comparability_status": assessment.comparability_status,
                "comparability_warnings": list(assessment.comparability_warnings),
                "comparability_basis": list(assessment.comparability_basis),
                "requires_expert_review": assessment.requires_expert_review,
                "assessment_epistemic_status": assessment.assessment_epistemic_status,
                "missing_critical_context": list(assessment.missing_critical_context),
                "value": numeric_value,
                "unit": unit,
            }
        ).to_record()

    def _summarize_result(
        self,
        *,
        result_type: str,
        value_payload: Any,
        unit: str | None,
    ) -> tuple[str, float | None]:
        payload = self._normalize_object(value_payload)
        if not isinstance(payload, dict):
            payload = {}
        statement = self._safe_text(payload.get("statement"))

        if result_type == "retention":
            numeric = self._safe_float(
                payload.get("retention_percent", payload.get("value"))
            )
            if numeric is not None:
                unit_text = unit or "%"
                return f"{numeric:g} {unit_text} retention", numeric
            return statement or "Retention reported", None

        if result_type == "range":
            minimum = self._safe_float(payload.get("min"))
            maximum = self._safe_float(payload.get("max"))
            if minimum is not None and maximum is not None:
                span = f"{minimum:g}-{maximum:g}"
                if unit:
                    span = f"{span} {unit}"
                return span, None
            return statement or "Range reported", None

        if result_type == "trend":
            direction = self._safe_text(payload.get("direction"))
            if direction and statement:
                return statement, None
            if direction:
                return direction, None
            return statement or "Trend reported", None

        numeric = self._safe_float(payload.get("value"))
        if numeric is not None:
            summary = f"{numeric:g}"
            if unit:
                summary = f"{summary} {unit}"
            return summary, numeric
        return statement or "Result reported", None

    def _summarize_test_condition(self, condition_row: dict[str, Any]) -> str:
        if not condition_row:
            return "unspecified test condition"

        payload = self._normalize_object(condition_row.get("condition_payload"))
        if not isinstance(payload, dict) or not payload:
            return "unspecified test condition"

        parts: list[str] = []
        method = self._safe_text(payload.get("method"))
        methods = self._normalize_string_list(payload.get("methods"))
        if method:
            parts.append(method)
        elif methods:
            parts.append(", ".join(methods))

        temperatures = payload.get("temperatures_c")
        if isinstance(temperatures, list) and temperatures:
            parts.append(" / ".join(f"{float(value):g} C" for value in temperatures))

        durations = self._normalize_string_list(payload.get("durations"))
        if durations:
            parts.append(" / ".join(durations))

        atmosphere = self._safe_text(payload.get("atmosphere"))
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

    def _normalize_material_system(self, material_system: Any) -> str:
        payload = self._normalize_object(material_system) or {}
        if not isinstance(payload, dict):
            return str(payload)
        family = self._safe_text(payload.get("family"))
        composition = self._safe_text(payload.get("composition"))
        if family and composition and composition != family:
            return f"{family} ({composition})"
        if family:
            return family
        if composition:
            return composition
        return "unspecified material system"

    def _normalize_process(self, process_context: Any) -> str:
        payload = self._normalize_object(process_context) or {}
        if not isinstance(payload, dict) or not payload:
            return "unspecified process"

        parts: list[str] = []
        temperatures = payload.get("temperatures_c")
        if isinstance(temperatures, list) and temperatures:
            parts.append(" / ".join(f"{float(value):g} C" for value in temperatures))

        durations = self._normalize_string_list(payload.get("durations"))
        if durations:
            parts.append(" / ".join(durations))

        atmosphere = self._safe_text(payload.get("atmosphere"))
        if atmosphere:
            parts.append(f"under {atmosphere}")

        for key, value in payload.items():
            if key in {"temperatures_c", "durations", "atmosphere"}:
                continue
            normalized = self._normalize_scalar_or_text(value)
            if normalized not in (None, "", [], {}):
                parts.append(f"{key}={normalized}")

        return ", ".join(str(part) for part in parts) if parts else "unspecified process"

    def _normalize_rows_table(
        self,
        rows: pd.DataFrame,
        collection_id: str | None,
    ) -> pd.DataFrame:
        if rows is None or rows.empty:
            return pd.DataFrame(columns=_COMPARISON_ROW_COLUMNS)

        normalized = rows.copy()
        if collection_id is not None and "collection_id" not in normalized.columns:
            normalized["collection_id"] = collection_id
        for column in _COMPARISON_ROW_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = None
        records = [
            ComparisonRow.from_mapping(dict(row)).to_record()
            for _, row in normalized.iterrows()
        ]
        return pd.DataFrame(records, columns=_COMPARISON_ROW_COLUMNS)

    def _filter_rows(
        self,
        rows: pd.DataFrame,
        *,
        material_system_normalized: str | None = None,
        property_normalized: str | None = None,
        test_condition_normalized: str | None = None,
        baseline_normalized: str | None = None,
    ) -> pd.DataFrame:
        filtered = rows
        filters = {
            "material_system_normalized": self._safe_text(material_system_normalized),
            "property_normalized": self._safe_text(property_normalized),
            "test_condition_normalized": self._safe_text(test_condition_normalized),
            "baseline_normalized": self._safe_text(baseline_normalized),
        }
        for column, expected in filters.items():
            if not expected:
                continue
            filtered = filtered[
                filtered[column].apply(lambda value: self._safe_text(value) == expected)
            ]
        return filtered

    def _serialize_row(self, row: pd.Series) -> dict[str, Any]:
        record = ComparisonRow.from_mapping(dict(row))
        missing_critical_context = list(record.missing_critical_context)
        return {
            "row_id": record.row_id,
            "collection_id": record.collection_id,
            "source_document_id": record.source_document_id,
            "display": {
                "material_system_normalized": record.material_system_normalized,
                "process_normalized": record.process_normalized,
                "variant_id": record.variant_id,
                "variant_label": record.variant_label,
                "variable_axis": record.variable_axis,
                "variable_value": record.variable_value,
                "property_normalized": record.property_normalized,
                "result_type": record.result_type,
                "result_summary": record.result_summary,
                "value": record.value,
                "unit": record.unit,
                "test_condition_normalized": record.test_condition_normalized,
                "baseline_reference": record.baseline_reference,
                "baseline_normalized": record.baseline_normalized,
            },
            "evidence_bundle": {
                "result_source_type": record.result_source_type,
                "supporting_evidence_ids": list(record.supporting_evidence_ids),
                "supporting_anchor_ids": list(record.supporting_anchor_ids),
                "characterization_observation_ids": list(
                    record.characterization_observation_ids
                ),
                "structure_feature_ids": list(record.structure_feature_ids),
            },
            "assessment": {
                "comparability_status": record.comparability_status,
                "comparability_warnings": list(record.comparability_warnings),
                "comparability_basis": list(record.comparability_basis),
                "requires_expert_review": record.requires_expert_review,
                "assessment_epistemic_status": record.assessment_epistemic_status,
            },
            "uncertainty": {
                "missing_critical_context": missing_critical_context,
                "unresolved_fields": missing_critical_context,
                "unresolved_baseline_link": "baseline_reference" in missing_critical_context,
                "unresolved_condition_link": "test_condition" in missing_critical_context,
            },
        }

    def _build_supporting_evidence_ids(
        self,
        result_row: pd.Series,
    ) -> list[str]:
        result_id = self._safe_text(result_row.get("result_id"))
        if not result_id:
            return []
        return [f"ev_result_{result_id}"]

    def _normalize_string_list(self, value: Any) -> list[str]:
        payload = self._normalize_object(value)
        if payload is None:
            return []
        if isinstance(payload, list):
            return [str(item) for item in payload if self._safe_text(item)]
        text = self._safe_text(payload)
        return [text] if text else []

    def _normalize_scalar_or_text(self, value: Any) -> str | float | int | None:
        payload = self._normalize_object(value)
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
        text = self._safe_text(payload)
        return text

    def _normalize_object(self, value: Any) -> Any:
        return normalize_backbone_value(value)

    def _safe_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    def _safe_float(self, value: Any) -> float | None:
        try:
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return None
            return float(value)
        except Exception:
            return None


__all__ = [
    "ComparisonRowNotFoundError",
    "ComparisonRowsNotReadyError",
    "ComparisonService",
]
