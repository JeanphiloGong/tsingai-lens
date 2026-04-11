from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pandas as pd


PROTOCOL_STEP_PARQUET_COLUMNS = [
    "step_id",
    "paper_id",
    "section_id",
    "block_id",
    "block_type",
    "order",
    "action",
    "raw_text",
    "purpose",
    "expected_output",
    "materials_json",
    "conditions_json",
    "characterization_json",
    "controls_json",
    "evidence_refs_json",
    "confidence_score",
    "validation_status",
    "validation_errors_json",
]


class ProtocolValidateService:
    """Validate extracted steps and prepare a stable parquet payload."""

    def validate_step(self, step: dict[str, Any]) -> dict[str, Any]:
        payload = dict(step)
        payload["step_id"] = str(payload.get("step_id") or uuid4())
        payload["paper_id"] = str(payload.get("paper_id") or "unknown")
        payload["section_id"] = self._optional_str(payload.get("section_id"))
        payload["block_id"] = self._optional_str(payload.get("block_id"))
        payload["block_type"] = self._optional_str(payload.get("block_type"))
        payload["order"] = self._safe_positive_int(payload.get("order"))
        payload["action"] = self._clean_text(payload.get("action")) or ""
        payload["raw_text"] = self._clean_text(payload.get("raw_text")) or ""
        payload["purpose"] = self._optional_text(payload.get("purpose"))
        payload["expected_output"] = self._optional_text(payload.get("expected_output"))
        payload["materials"] = self._ensure_list(payload.get("materials"))
        payload["characterization"] = self._ensure_list(payload.get("characterization"))
        payload["controls"] = self._ensure_list(payload.get("controls"))
        payload["evidence_refs"] = self._ensure_list(payload.get("evidence_refs"))
        payload["conditions"] = self._validate_conditions(payload.get("conditions"))
        payload["confidence_score"] = self._clamp_score(payload.get("confidence_score"))

        errors: list[str] = []
        if not payload["action"]:
            errors.append("missing_action")
        if payload["order"] <= 0:
            errors.append("invalid_order")
        if not payload["raw_text"]:
            errors.append("missing_raw_text")

        payload["validation_errors"] = errors
        payload["validation_status"] = "valid" if not errors else "needs_review"
        return payload

    def validate_steps(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.validate_step(step) for step in steps]

    def to_parquet_frame(self, steps: list[dict[str, Any]]) -> pd.DataFrame:
        rows = []
        for step in self.validate_steps(steps):
            rows.append(
                {
                    "step_id": step["step_id"],
                    "paper_id": step["paper_id"],
                    "section_id": step["section_id"],
                    "block_id": step["block_id"],
                    "block_type": step["block_type"],
                    "order": step["order"],
                    "action": step["action"],
                    "raw_text": step["raw_text"],
                    "purpose": step["purpose"],
                    "expected_output": step["expected_output"],
                    "materials_json": self._to_json(step["materials"]),
                    "conditions_json": self._to_json(step["conditions"]),
                    "characterization_json": self._to_json(step["characterization"]),
                    "controls_json": self._to_json(step["controls"]),
                    "evidence_refs_json": self._to_json(step["evidence_refs"]),
                    "confidence_score": step["confidence_score"],
                    "validation_status": step["validation_status"],
                    "validation_errors_json": self._to_json(step["validation_errors"]),
                }
            )
        return pd.DataFrame(rows, columns=PROTOCOL_STEP_PARQUET_COLUMNS)

    def _validate_conditions(self, conditions: Any) -> dict[str, Any]:
        payload = dict(conditions or {})
        payload["temperature"] = self._validate_scalar(payload.get("temperature"))
        payload["duration"] = self._validate_scalar(payload.get("duration"))
        atmosphere = payload.get("atmosphere")
        if not isinstance(atmosphere, dict):
            atmosphere = {"value": None, "status": "not_reported", "raw_value": None}
        atmosphere.setdefault("value", None)
        atmosphere.setdefault("status", "not_reported")
        atmosphere.setdefault("raw_value", None)
        payload["atmosphere"] = atmosphere
        payload["raw_text"] = self._clean_text(payload.get("raw_text")) or ""
        return payload

    def _validate_scalar(self, value: Any) -> dict[str, Any]:
        payload = dict(value or {})
        payload.setdefault("value", None)
        payload.setdefault("unit", None)
        payload.setdefault("raw_value", None)
        payload.setdefault("status", "not_reported")
        return payload

    def _ensure_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _safe_positive_int(self, value: Any) -> int:
        try:
            parsed = int(value)
        except Exception:
            return 0
        return parsed if parsed > 0 else 0

    def _clamp_score(self, value: Any) -> float:
        try:
            parsed = float(value)
        except Exception:
            return 0.0
        return max(0.0, min(1.0, parsed))

    def _optional_str(self, value: Any) -> str | None:
        text = self._clean_text(value)
        return text or None

    def _optional_text(self, value: Any) -> str | None:
        text = self._clean_text(value)
        return text[:240] if text else None

    def _clean_text(self, value: Any) -> str:
        if value is None:
            return ""
        return " ".join(str(value).split())

    def _to_json(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)
