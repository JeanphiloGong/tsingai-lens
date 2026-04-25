from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Final, Mapping


CORE_NEUTRAL_DOMAIN_PROFILE: Final[str] = "core_neutral"


@dataclass(frozen=True)
class EvidenceAnchor:
    anchor_id: str
    document_id: str
    locator_type: str
    locator_confidence: str
    source_type: str
    section_id: str | None
    char_range: dict[str, int] | None
    bbox: dict[str, float] | None
    page: int | None
    quote: str | None
    deep_link: str | None
    block_id: str | None
    snippet_id: str | None
    figure_or_table: str | None
    quote_span: str | None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EvidenceAnchor":
        return cls(
            anchor_id=_normalize_text(payload.get("anchor_id")) or "",
            document_id=_normalize_text(payload.get("document_id")) or "",
            locator_type=_normalize_text(payload.get("locator_type")) or "section",
            locator_confidence=_normalize_text(payload.get("locator_confidence")) or "low",
            source_type=_normalize_text(payload.get("source_type")) or "text",
            section_id=_normalize_text(payload.get("section_id")),
            char_range=_normalize_int_dict(payload.get("char_range"), ("start", "end")),
            bbox=_normalize_float_dict(payload.get("bbox"), ("x0", "y0", "x1", "y1")),
            page=_normalize_optional_int(payload.get("page")),
            quote=_normalize_text(payload.get("quote")),
            deep_link=_normalize_text(payload.get("deep_link")),
            block_id=_normalize_text(payload.get("block_id")),
            snippet_id=_normalize_text(payload.get("snippet_id")),
            figure_or_table=_normalize_text(payload.get("figure_or_table")),
            quote_span=_normalize_text(payload.get("quote_span")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "anchor_id": self.anchor_id,
            "document_id": self.document_id,
            "locator_type": self.locator_type,
            "locator_confidence": self.locator_confidence,
            "source_type": self.source_type,
            "section_id": self.section_id,
            "char_range": dict(self.char_range) if self.char_range is not None else None,
            "bbox": dict(self.bbox) if self.bbox is not None else None,
            "page": self.page,
            "quote": self.quote,
            "deep_link": self.deep_link,
            "block_id": self.block_id,
            "snippet_id": self.snippet_id,
            "figure_or_table": self.figure_or_table,
            "quote_span": self.quote_span,
        }


@dataclass(frozen=True)
class CharacterizationObservation:
    observation_id: str
    document_id: str
    collection_id: str
    variant_id: str | None
    characterization_type: str
    observation_text: str
    observed_value: Any
    observed_unit: str | None
    condition_context: dict[str, Any]
    evidence_anchor_ids: tuple[str, ...]
    confidence: float
    epistemic_status: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "CharacterizationObservation":
        return cls(
            observation_id=_normalize_text(payload.get("observation_id")) or "",
            document_id=_normalize_text(payload.get("document_id")) or "",
            collection_id=_normalize_text(payload.get("collection_id")) or "",
            variant_id=_normalize_text(payload.get("variant_id")),
            characterization_type=_normalize_text(payload.get("characterization_type")) or "",
            observation_text=_normalize_text(payload.get("observation_text")) or "",
            observed_value=_normalize_scalar(payload.get("observed_value")),
            observed_unit=_normalize_text(payload.get("observed_unit")),
            condition_context=_normalize_mapping(payload.get("condition_context")),
            evidence_anchor_ids=_normalize_string_tuple(payload.get("evidence_anchor_ids")),
            confidence=_normalize_confidence(payload.get("confidence")),
            epistemic_status=_normalize_text(payload.get("epistemic_status")) or "",
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "document_id": self.document_id,
            "collection_id": self.collection_id,
            "variant_id": self.variant_id,
            "characterization_type": self.characterization_type,
            "observation_text": self.observation_text,
            "observed_value": self.observed_value,
            "observed_unit": self.observed_unit,
            "condition_context": dict(self.condition_context),
            "evidence_anchor_ids": list(self.evidence_anchor_ids),
            "confidence": self.confidence,
            "epistemic_status": self.epistemic_status,
        }


@dataclass(frozen=True)
class StructureFeature:
    feature_id: str
    document_id: str
    collection_id: str
    variant_id: str | None
    feature_type: str
    feature_value: Any
    feature_unit: str | None
    qualitative_descriptor: str | None
    source_observation_ids: tuple[str, ...]
    confidence: float
    epistemic_status: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "StructureFeature":
        return cls(
            feature_id=_normalize_text(payload.get("feature_id")) or "",
            document_id=_normalize_text(payload.get("document_id")) or "",
            collection_id=_normalize_text(payload.get("collection_id")) or "",
            variant_id=_normalize_text(payload.get("variant_id")),
            feature_type=_normalize_text(payload.get("feature_type")) or "",
            feature_value=_normalize_scalar(payload.get("feature_value")),
            feature_unit=_normalize_text(payload.get("feature_unit")),
            qualitative_descriptor=_normalize_text(payload.get("qualitative_descriptor")),
            source_observation_ids=_normalize_string_tuple(payload.get("source_observation_ids")),
            confidence=_normalize_confidence(payload.get("confidence")),
            epistemic_status=_normalize_text(payload.get("epistemic_status")) or "",
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "document_id": self.document_id,
            "collection_id": self.collection_id,
            "variant_id": self.variant_id,
            "feature_type": self.feature_type,
            "feature_value": self.feature_value,
            "feature_unit": self.feature_unit,
            "qualitative_descriptor": self.qualitative_descriptor,
            "source_observation_ids": list(self.source_observation_ids),
            "confidence": self.confidence,
            "epistemic_status": self.epistemic_status,
        }


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
    evidence_anchor_ids: tuple[str, ...]
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
            evidence_anchor_ids=_normalize_string_tuple(payload.get("evidence_anchor_ids")),
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
            "evidence_anchor_ids": list(self.evidence_anchor_ids),
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
    evidence_anchor_ids: tuple[str, ...]
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
            evidence_anchor_ids=_normalize_string_tuple(payload.get("evidence_anchor_ids")),
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
            "evidence_anchor_ids": list(self.evidence_anchor_ids),
            "confidence": self.confidence,
            "epistemic_status": self.epistemic_status,
        }


@dataclass(frozen=True)
class BaselineReference:
    baseline_id: str
    document_id: str
    collection_id: str
    domain_profile: str
    variant_id: str | None
    baseline_type: str
    baseline_label: str
    baseline_scope: str
    evidence_anchor_ids: tuple[str, ...]
    confidence: float
    epistemic_status: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "BaselineReference":
        return cls(
            baseline_id=_normalize_text(payload.get("baseline_id")) or "",
            document_id=_normalize_text(payload.get("document_id")) or "",
            collection_id=_normalize_text(payload.get("collection_id")) or "",
            domain_profile=_normalize_text(payload.get("domain_profile")) or CORE_NEUTRAL_DOMAIN_PROFILE,
            variant_id=_normalize_text(payload.get("variant_id")),
            baseline_type=_normalize_text(payload.get("baseline_type")) or "",
            baseline_label=_normalize_text(payload.get("baseline_label")) or "",
            baseline_scope=_normalize_text(payload.get("baseline_scope")) or "",
            evidence_anchor_ids=_normalize_string_tuple(payload.get("evidence_anchor_ids")),
            confidence=_normalize_confidence(payload.get("confidence")),
            epistemic_status=_normalize_text(payload.get("epistemic_status")) or "",
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "document_id": self.document_id,
            "collection_id": self.collection_id,
            "domain_profile": self.domain_profile,
            "variant_id": self.variant_id,
            "baseline_type": self.baseline_type,
            "baseline_label": self.baseline_label,
            "baseline_scope": self.baseline_scope,
            "evidence_anchor_ids": list(self.evidence_anchor_ids),
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
    structure_feature_ids: tuple[str, ...]
    source_anchor_ids: tuple[str, ...]
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
            structure_feature_ids=_normalize_string_tuple(payload.get("structure_feature_ids")),
            source_anchor_ids=_normalize_string_tuple(payload.get("source_anchor_ids")),
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
            "structure_feature_ids": list(self.structure_feature_ids),
            "source_anchor_ids": list(self.source_anchor_ids),
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
    baseline_id: str | None
    structure_feature_ids: tuple[str, ...]
    characterization_observation_ids: tuple[str, ...]
    evidence_anchor_ids: tuple[str, ...]
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
            baseline_id=_normalize_text(payload.get("baseline_id")),
            structure_feature_ids=_normalize_string_tuple(payload.get("structure_feature_ids")),
            characterization_observation_ids=_normalize_string_tuple(
                payload.get("characterization_observation_ids")
            ),
            evidence_anchor_ids=_normalize_string_tuple(payload.get("evidence_anchor_ids")),
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
            "baseline_id": self.baseline_id,
            "structure_feature_ids": list(self.structure_feature_ids),
            "characterization_observation_ids": list(self.characterization_observation_ids),
            "evidence_anchor_ids": list(self.evidence_anchor_ids),
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


def _normalize_optional_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _normalize_int_dict(
    value: Any,
    keys: tuple[str, ...],
) -> dict[str, int] | None:
    payload = _normalize_mapping(value)
    if not payload:
        return None
    normalized: dict[str, int] = {}
    for key in keys:
        parsed = _normalize_optional_int(payload.get(key))
        if parsed is None:
            return None
        normalized[key] = parsed
    return normalized


def _normalize_float_dict(
    value: Any,
    keys: tuple[str, ...],
) -> dict[str, float] | None:
    payload = _normalize_mapping(value)
    if not payload:
        return None
    normalized: dict[str, float] = {}
    try:
        for key in keys:
            normalized[key] = float(payload.get(key))
    except (TypeError, ValueError):
        return None
    return normalized


__all__ = [
    "BaselineReference",
    "CORE_NEUTRAL_DOMAIN_PROFILE",
    "CharacterizationObservation",
    "EvidenceAnchor",
    "MethodFact",
    "MeasurementResult",
    "SampleVariant",
    "StructureFeature",
    "TestCondition",
]
