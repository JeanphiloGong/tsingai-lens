from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Final, Mapping


CORE_NEUTRAL_DOMAIN_PROFILE: Final[str] = "core_neutral"


@dataclass(frozen=True)
class TestCondition:
    test_condition_id: str
    document_id: str
    collection_id: str
    domain_profile: str
    property_type: str
    template_type: str
    scope_level: str
    condition_payload: dict[str, Any]
    condition_completeness: str
    missing_fields: tuple[str, ...]
    confidence: float
    epistemic_status: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TestCondition":
        return cls(
            test_condition_id=_normalize_text(payload.get("test_condition_id")) or "",
            document_id=_normalize_text(payload.get("document_id")) or "",
            collection_id=_normalize_text(payload.get("collection_id")) or "",
            domain_profile=_normalize_text(payload.get("domain_profile")) or CORE_NEUTRAL_DOMAIN_PROFILE,
            property_type=_normalize_text(payload.get("property_type")) or "",
            template_type=_normalize_text(payload.get("template_type")) or "",
            scope_level=_normalize_text(payload.get("scope_level")) or "",
            condition_payload=_normalize_mapping(payload.get("condition_payload")),
            condition_completeness=_normalize_text(payload.get("condition_completeness")) or "unresolved",
            missing_fields=_normalize_string_tuple(payload.get("missing_fields")),
            confidence=_normalize_confidence(payload.get("confidence")),
            epistemic_status=_normalize_text(payload.get("epistemic_status")) or "",
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "test_condition_id": self.test_condition_id,
            "document_id": self.document_id,
            "collection_id": self.collection_id,
            "domain_profile": self.domain_profile,
            "property_type": self.property_type,
            "template_type": self.template_type,
            "scope_level": self.scope_level,
            "condition_payload": dict(self.condition_payload),
            "condition_completeness": self.condition_completeness,
            "missing_fields": list(self.missing_fields),
            "confidence": self.confidence,
            "epistemic_status": self.epistemic_status,
        }


@dataclass(frozen=True)
class MethodFact:
    method_id: str
    document_id: str
    collection_id: str
    domain_profile: str
    method_role: str
    method_name: str
    method_payload: dict[str, Any]
    confidence: float
    epistemic_status: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "MethodFact":
        return cls(
            method_id=_normalize_text(payload.get("method_id")) or "",
            document_id=_normalize_text(payload.get("document_id")) or "",
            collection_id=_normalize_text(payload.get("collection_id")) or "",
            domain_profile=_normalize_text(payload.get("domain_profile")) or CORE_NEUTRAL_DOMAIN_PROFILE,
            method_role=_normalize_text(payload.get("method_role")) or "",
            method_name=_normalize_text(payload.get("method_name")) or "",
            method_payload=_normalize_mapping(payload.get("method_payload")),
            confidence=_normalize_confidence(payload.get("confidence")),
            epistemic_status=_normalize_text(payload.get("epistemic_status")) or "",
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "document_id": self.document_id,
            "collection_id": self.collection_id,
            "domain_profile": self.domain_profile,
            "method_role": self.method_role,
            "method_name": self.method_name,
            "method_payload": dict(self.method_payload),
            "confidence": self.confidence,
            "epistemic_status": self.epistemic_status,
        }


@dataclass(frozen=True)
class SampleVariant:
    variant_id: str
    document_id: str
    collection_id: str
    domain_profile: str
    variant_label: str
    host_material_system: dict[str, Any]
    composition: str | None
    variable_axis_type: str | None
    variable_value: Any
    process_context: dict[str, Any]
    profile_payload: dict[str, Any]
    confidence: float
    epistemic_status: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SampleVariant":
        return cls(
            variant_id=_normalize_text(payload.get("variant_id")) or "",
            document_id=_normalize_text(payload.get("document_id")) or "",
            collection_id=_normalize_text(payload.get("collection_id")) or "",
            domain_profile=_normalize_text(payload.get("domain_profile")) or CORE_NEUTRAL_DOMAIN_PROFILE,
            variant_label=_normalize_text(payload.get("variant_label")) or "",
            host_material_system=_normalize_mapping(payload.get("host_material_system")),
            composition=_normalize_text(payload.get("composition")),
            variable_axis_type=_normalize_text(payload.get("variable_axis_type")),
            variable_value=_normalize_scalar(payload.get("variable_value")),
            process_context=_normalize_mapping(payload.get("process_context")),
            profile_payload=_normalize_mapping(payload.get("profile_payload")),
            confidence=_normalize_confidence(payload.get("confidence")),
            epistemic_status=_normalize_text(payload.get("epistemic_status")) or "",
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "document_id": self.document_id,
            "collection_id": self.collection_id,
            "domain_profile": self.domain_profile,
            "variant_label": self.variant_label,
            "host_material_system": dict(self.host_material_system),
            "composition": self.composition,
            "variable_axis_type": self.variable_axis_type,
            "variable_value": self.variable_value,
            "process_context": dict(self.process_context),
            "profile_payload": dict(self.profile_payload),
            "confidence": self.confidence,
            "epistemic_status": self.epistemic_status,
        }


@dataclass(frozen=True)
class MeasurementResult:
    result_id: str
    document_id: str
    collection_id: str
    domain_profile: str
    variant_id: str | None
    property_normalized: str
    result_type: str
    claim_scope: str
    value_payload: dict[str, Any]
    unit: str | None
    test_condition_id: str | None
    traceability_status: str
    result_source_type: str
    epistemic_status: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "MeasurementResult":
        return cls(
            result_id=_normalize_text(payload.get("result_id")) or "",
            document_id=_normalize_text(payload.get("document_id")) or "",
            collection_id=_normalize_text(payload.get("collection_id")) or "",
            domain_profile=_normalize_text(payload.get("domain_profile")) or CORE_NEUTRAL_DOMAIN_PROFILE,
            variant_id=_normalize_text(payload.get("variant_id")),
            property_normalized=_normalize_text(payload.get("property_normalized")) or "",
            result_type=_normalize_text(payload.get("result_type")) or "",
            claim_scope=_normalize_text(payload.get("claim_scope")) or "current_work",
            value_payload=_normalize_mapping(payload.get("value_payload")),
            unit=_normalize_text(payload.get("unit")),
            test_condition_id=_normalize_text(payload.get("test_condition_id")),
            traceability_status=_normalize_text(payload.get("traceability_status")) or "",
            result_source_type=_normalize_text(payload.get("result_source_type")) or "",
            epistemic_status=_normalize_text(payload.get("epistemic_status")) or "",
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "document_id": self.document_id,
            "collection_id": self.collection_id,
            "domain_profile": self.domain_profile,
            "variant_id": self.variant_id,
            "property_normalized": self.property_normalized,
            "result_type": self.result_type,
            "claim_scope": self.claim_scope,
            "value_payload": dict(self.value_payload),
            "unit": self.unit,
            "test_condition_id": self.test_condition_id,
            "traceability_status": self.traceability_status,
            "result_source_type": self.result_source_type,
            "epistemic_status": self.epistemic_status,
        }


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            value = value.item()
        except Exception:
            pass
    text = str(value).strip()
    return text or None


def _normalize_confidence(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        if isinstance(value, float) and math.isnan(value):
            return 0.0
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def _normalize_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray, dict)):
        value = value.tolist()
    if isinstance(value, dict):
        return dict(value)
    return {}


def _normalize_string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray)):
        value = value.tolist()
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return tuple(items)
    text = _normalize_text(value)
    return (text,) if text else ()


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            value = value.item()
        except Exception:
            pass
    return value


__all__ = [
    "CORE_NEUTRAL_DOMAIN_PROFILE",
    "MethodFact",
    "MeasurementResult",
    "SampleVariant",
    "TestCondition",
]
