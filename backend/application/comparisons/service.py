from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from application.backbone_codec import (
    normalize_backbone_value,
    prepare_frame_for_storage,
    restore_frame_from_storage,
)
from application.collections.service import CollectionService
from application.evidence.service import EvidenceCardService, EvidenceCardsNotReadyError
from application.workspace.artifact_registry_service import ArtifactRegistryService


_COMPARISON_ROWS_FILE = "comparison_rows.parquet"
_COMPARISON_JSON_COLUMNS = (
    "supporting_evidence_ids",
    "comparability_warnings",
)
_VALUE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(MPa|GPa|Pa|%|S/cm|mS/cm|W/mK|wt%|vol%)\b",
    re.IGNORECASE,
)

_PROPERTY_MAP = {
    "strength": "strength",
    "flexural": "flexural_strength",
    "modulus": "modulus",
    "conductivity": "conductivity",
    "fatigue": "fatigue_life",
    "density": "density",
    "porosity": "porosity",
    "hardness": "hardness",
    "stability": "stability",
}


class ComparisonRowsNotReadyError(RuntimeError):
    """Raised when a collection cannot yet serve comparison rows."""

    def __init__(self, collection_id: str, output_dir: Path) -> None:
        self.collection_id = collection_id
        self.output_dir = output_dir
        super().__init__(f"comparison rows not ready: {collection_id}")


class ComparisonService:
    """Generate and serve collection-scoped comparison row artifacts."""

    def __init__(
        self,
        collection_service: CollectionService | None = None,
        artifact_registry_service: ArtifactRegistryService | None = None,
        evidence_card_service: EvidenceCardService | None = None,
    ) -> None:
        self.collection_service = collection_service or CollectionService()
        self.artifact_registry_service = (
            artifact_registry_service or ArtifactRegistryService()
        )
        self.evidence_card_service = evidence_card_service or EvidenceCardService(
            collection_service=self.collection_service,
            artifact_registry_service=self.artifact_registry_service,
        )

    def list_comparison_rows(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        rows = self.read_comparison_rows(collection_id)
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

    def read_comparison_rows(self, collection_id: str) -> pd.DataFrame:
        output_dir = self._resolve_output_dir(collection_id)
        path = output_dir / _COMPARISON_ROWS_FILE
        if path.is_file():
            rows = restore_frame_from_storage(
                pd.read_parquet(path),
                _COMPARISON_JSON_COLUMNS,
            )
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

        try:
            cards = self.evidence_card_service.read_evidence_cards(collection_id)
        except EvidenceCardsNotReadyError as exc:
            raise ComparisonRowsNotReadyError(collection_id, exc.output_dir) from exc

        rows = [self._build_row_from_card(row) for _, row in cards.iterrows()]
        table = pd.DataFrame(
            rows,
            columns=[
                "row_id",
                "collection_id",
                "source_document_id",
                "supporting_evidence_ids",
                "material_system_normalized",
                "process_normalized",
                "property_normalized",
                "baseline_normalized",
                "test_condition_normalized",
                "comparability_status",
                "comparability_warnings",
                "value",
                "unit",
            ],
        )
        table = self._normalize_rows_table(table, collection_id)
        if not table.empty:
            base_dir.mkdir(parents=True, exist_ok=True)
            prepare_frame_for_storage(
                table,
                _COMPARISON_JSON_COLUMNS,
            ).to_parquet(base_dir / _COMPARISON_ROWS_FILE, index=False)
            self.artifact_registry_service.upsert(collection_id, base_dir)
        return table

    def _resolve_output_dir(self, collection_id: str) -> Path:
        self.collection_service.get_collection(collection_id)
        try:
            artifacts = self.artifact_registry_service.get(collection_id)
        except FileNotFoundError:
            artifacts = None
        if artifacts and artifacts.get("output_path"):
            return Path(str(artifacts["output_path"])).expanduser().resolve()
        return self.collection_service.get_paths(collection_id).output_dir.resolve()

    def _build_row_from_card(self, row: pd.Series) -> dict[str, Any]:
        evidence_id = str(row.get("evidence_id") or "")
        claim_text = str(row.get("claim_text") or "")
        claim_type = str(row.get("claim_type") or "qualitative")
        condition_context = self._normalize_object(row.get("condition_context")) or {}
        material_system = self._normalize_object(row.get("material_system")) or {}
        evidence_anchors = self._normalize_object(row.get("evidence_anchors")) or []
        baseline = condition_context.get("baseline") or {}
        test_context = condition_context.get("test") or {}
        process_context = condition_context.get("process") or {}
        traceability_status = str(row.get("traceability_status") or "missing")

        value, unit = self._extract_value_and_unit(claim_text, evidence_anchors)
        property_normalized = self._normalize_property(claim_type, claim_text, test_context)
        material_system_normalized = self._normalize_material_system(material_system)
        process_normalized = self._normalize_process(process_context)
        baseline_normalized, baseline_missing = self._normalize_baseline(baseline, claim_type)
        test_condition_normalized, test_missing = self._normalize_test(test_context, claim_type)

        warnings: list[str] = []
        if traceability_status != "direct":
            warnings.append("Traceability is partial or indirect.")
        if baseline_missing and claim_type in {"property", "mechanism"}:
            warnings.append("Baseline definition is missing or ambiguous.")
        if test_missing and claim_type in {"property", "mechanism", "microstructure"}:
            warnings.append("Test or measurement conditions are missing.")
        if claim_type in {"process", "characterization"}:
            warnings.append("This row reflects process or characterization context rather than a direct property benchmark.")
        if value is None and claim_type == "property":
            warnings.append("Property claim is qualitative and lacks a normalized numeric value.")

        status = self._derive_comparability_status(
            claim_type=claim_type,
            traceability_status=traceability_status,
            baseline_missing=baseline_missing,
            test_missing=test_missing,
            has_value=value is not None,
        )

        return {
            "row_id": f"cmp_{uuid4().hex[:12]}",
            "collection_id": str(row.get("collection_id") or ""),
            "source_document_id": str(row.get("document_id") or ""),
            "supporting_evidence_ids": [evidence_id] if evidence_id else [],
            "material_system_normalized": material_system_normalized,
            "process_normalized": process_normalized,
            "property_normalized": property_normalized,
            "baseline_normalized": baseline_normalized,
            "test_condition_normalized": test_condition_normalized,
            "comparability_status": status,
            "comparability_warnings": warnings,
            "value": value,
            "unit": unit,
        }

    def _derive_comparability_status(
        self,
        claim_type: str,
        traceability_status: str,
        baseline_missing: bool,
        test_missing: bool,
        has_value: bool,
    ) -> str:
        if traceability_status == "missing":
            return "insufficient"
        if claim_type in {"process", "characterization"}:
            return "limited"
        if claim_type == "mechanism":
            return "insufficient" if (baseline_missing and test_missing) else "limited"
        if claim_type == "property":
            if baseline_missing and test_missing:
                return "not_comparable"
            if baseline_missing or test_missing or not has_value or traceability_status != "direct":
                return "limited"
            return "comparable"
        return "limited"

    def _normalize_material_system(self, material_system: Any) -> str:
        payload = self._normalize_object(material_system) or {}
        if not isinstance(payload, dict):
            return str(payload)
        family = str(payload.get("family") or "").strip()
        composition = str(payload.get("composition") or "").strip()
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
        if payload.get("temperatures_c"):
            temps = payload["temperatures_c"]
            if isinstance(temps, list):
                parts.append(" / ".join(f"{temp:g} C" for temp in temps))
        if payload.get("durations"):
            durations = payload["durations"]
            if isinstance(durations, list):
                parts.append(" / ".join(str(item) for item in durations))
        if payload.get("atmosphere"):
            parts.append(f"under {payload['atmosphere']}")
        if not parts:
            fallback_parts = [
                f"{key}={value}"
                for key, value in payload.items()
                if value not in (None, "", [], {})
            ]
            if not fallback_parts:
                return "unspecified process"
            parts.extend(fallback_parts)
        return ", ".join(str(part) for part in parts)

    def _normalize_property(
        self,
        claim_type: str,
        claim_text: str,
        test_context: dict[str, Any],
    ) -> str:
        lowered = claim_text.lower()
        for token, normalized in _PROPERTY_MAP.items():
            if token in lowered:
                return normalized
        if claim_type == "characterization":
            methods = test_context.get("methods") or []
            if methods:
                return f"characterization:{'+'.join(str(item).lower() for item in methods)}"
            return "characterization_method"
        if claim_type == "process":
            return "process_route"
        return claim_type or "qualitative"

    def _normalize_baseline(
        self,
        baseline_context: Any,
        claim_type: str,
    ) -> tuple[str, bool]:
        payload = self._normalize_object(baseline_context) or {}
        if not isinstance(payload, dict) or not payload:
            return ("not_applicable" if claim_type in {"process", "characterization"} else "unspecified baseline", claim_type not in {"process", "characterization"})
        control = str(payload.get("control") or "").strip()
        if control:
            return control, False
        return ("not_applicable" if claim_type in {"process", "characterization"} else "unspecified baseline", claim_type not in {"process", "characterization"})

    def _normalize_test(
        self,
        test_context: Any,
        claim_type: str,
    ) -> tuple[str, bool]:
        payload = self._normalize_object(test_context) or {}
        if not isinstance(payload, dict) or not payload:
            return ("process context" if claim_type == "process" else "unspecified test condition", claim_type not in {"process"})
        methods = payload.get("methods") or []
        if methods:
            method_text = ", ".join(str(item) for item in methods)
            return method_text, False
        method = str(payload.get("method") or "").strip()
        if method:
            return method, False
        return ("process context" if claim_type == "process" else "unspecified test condition", claim_type not in {"process"})

    def _extract_value_and_unit(
        self,
        claim_text: str,
        evidence_anchors: list[dict[str, Any]],
    ) -> tuple[float | None, str | None]:
        search_space = [claim_text]
        for anchor in evidence_anchors:
            quote = str(anchor.get("quote_span") or "").strip()
            if quote:
                search_space.append(quote)
        for text in search_space:
            match = _VALUE_PATTERN.search(text)
            if match:
                return float(match.group(1)), match.group(2)
        return None, None

    def _normalize_rows_table(
        self,
        rows: pd.DataFrame,
        collection_id: str | None,
    ) -> pd.DataFrame:
        if rows is None or rows.empty:
            return pd.DataFrame(
                columns=[
                    "row_id",
                    "collection_id",
                    "source_document_id",
                    "supporting_evidence_ids",
                    "material_system_normalized",
                    "process_normalized",
                    "property_normalized",
                    "baseline_normalized",
                    "test_condition_normalized",
                    "comparability_status",
                    "comparability_warnings",
                    "value",
                    "unit",
                ]
            )
        normalized = rows.copy()
        if collection_id is not None and "collection_id" not in normalized.columns:
            normalized["collection_id"] = collection_id
        for column in ("supporting_evidence_ids", "comparability_warnings"):
            if column in normalized.columns:
                normalized[column] = normalized[column].apply(self._normalize_list)
        return normalized[
            [
                "row_id",
                "collection_id",
                "source_document_id",
                "supporting_evidence_ids",
                "material_system_normalized",
                "process_normalized",
                "property_normalized",
                "baseline_normalized",
                "test_condition_normalized",
                "comparability_status",
                "comparability_warnings",
                "value",
                "unit",
            ]
        ]

    def _serialize_row(self, row: pd.Series) -> dict[str, Any]:
        value = row.get("value")
        normalized_value = None if value is None or (isinstance(value, float) and pd.isna(value)) else float(value)
        unit = row.get("unit")
        normalized_unit = None if unit is None or (isinstance(unit, float) and pd.isna(unit)) else str(unit)
        return {
            "row_id": str(row.get("row_id") or ""),
            "collection_id": str(row.get("collection_id") or ""),
            "source_document_id": str(row.get("source_document_id") or ""),
            "supporting_evidence_ids": self._normalize_list(row.get("supporting_evidence_ids")),
            "material_system_normalized": str(row.get("material_system_normalized") or "unspecified material system"),
            "process_normalized": str(row.get("process_normalized") or "unspecified process"),
            "property_normalized": str(row.get("property_normalized") or "qualitative"),
            "baseline_normalized": str(row.get("baseline_normalized") or "unspecified baseline"),
            "test_condition_normalized": str(row.get("test_condition_normalized") or "unspecified test condition"),
            "comparability_status": str(row.get("comparability_status") or "insufficient"),
            "comparability_warnings": self._normalize_list(row.get("comparability_warnings")),
            "value": normalized_value,
            "unit": normalized_unit,
        }

    def _normalize_object(self, value: Any) -> Any:
        return normalize_backbone_value(value)

    def _normalize_list(self, value: Any) -> list[str]:
        payload = self._normalize_object(value)
        if payload is None:
            return []
        if isinstance(payload, list):
            return [str(item) for item in payload if str(item).strip()]
        return [str(payload)]
