from __future__ import annotations

import json
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

PAPER_OBJECTIVE_CANDIDATE_OUTPUT_LIMITS = {
    "material_scope": (8, 80),
    "process_context": (4, 80),
    "variables": (4, 80),
    "outcomes": (8, 80),
}
_OBJECTIVE_EVIDENCE_ROLES = {
    "direct_result",
    "condition_context",
    "mechanism_context",
    "baseline_context",
    "comparison_context",
    "background_context",
    "contradictory_result",
    "irrelevant",
}
_OBJECTIVE_EVIDENCE_ATTRIBUTION_SCOPES = {
    "isolated_effect",
    "joint_effect",
    "association_only",
    "descriptive_only",
    "not_attributable",
}
_OBJECTIVE_EVIDENCE_RESULT_DIRECTIONS = {
    "increase",
    "decrease",
    "improve",
    "worsen",
    "no_change",
    "mixed",
    "unknown",
}
_OBJECTIVE_EVIDENCE_RESOLUTION_STATUSES = {
    "resolved",
    "partial",
    "unresolved",
    "skipped",
    "unknown",
}
_FINDING_DIRECTIONS = {
    "increase",
    "decrease",
    "improve",
    "worsen",
    "no_change",
    "mixed",
    "unknown",
}
_FINDING_ASSERTION_STRENGTHS = {"causal", "associative", "descriptive"}


def _normalize_underscored_choice(value: object, *, allowed: set[str], default: str) -> str:
    lowered = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return lowered if lowered in allowed else default


def _normalize_list_container(value: object) -> object:
    return [] if value is None else value


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("confidence", mode="before", check_fields=False)
    @classmethod
    def _normalize_default_confidence(cls, value: object) -> object:
        if value is not None:
            return value
        return cls.model_fields["confidence"].get_default(call_default_factory=True)

    @field_validator("epistemic_status", mode="before", check_fields=False)
    @classmethod
    def _normalize_default_epistemic_status(cls, value: object) -> object:
        if value is not None:
            return value
        return cls.model_fields["epistemic_status"].get_default(
            call_default_factory=True
        )


ScientificScalar = str | int | float | bool


class StructuredEvidenceAttribute(_StrictModel):
    name: str
    value: ScientificScalar
    unit: str | None = None


class StructuredEvidenceVariable(_StrictModel):
    name: str
    baseline_value: ScientificScalar | None = None
    target_value: ScientificScalar | None = None
    unit: str | None = None


class StructuredEvidenceComparison(_StrictModel):
    baseline_label: str
    target_label: str
    axis_names: list[str] = Field(min_length=1)
    comparable: bool
    incomparability_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_comparability(self) -> "StructuredEvidenceComparison":
        if not self.comparable and not self.incomparability_reasons:
            raise ValueError("incomparable evidence requires reasons")
        if self.comparable and self.incomparability_reasons:
            raise ValueError("comparable evidence cannot have incomparability reasons")
        return self


class StructuredEvidenceResult(_StrictModel):
    outcome: str
    value: ScientificScalar | None = None
    unit: str | None = None
    direction: Literal[
        "increase",
        "decrease",
        "improve",
        "worsen",
        "no_change",
        "mixed",
        "unknown",
    ] = "unknown"
    result_text: str

    @field_validator("direction", mode="before")
    @classmethod
    def _normalize_direction(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_RESULT_DIRECTIONS,
            default="unknown",
        )


class StructuredEvidenceContext(_StrictModel):
    material: list[StructuredEvidenceAttribute] = Field(default_factory=list)
    sample: list[StructuredEvidenceAttribute] = Field(default_factory=list)
    process: list[StructuredEvidenceAttribute] = Field(default_factory=list)
    test: list[StructuredEvidenceAttribute] = Field(default_factory=list)

    @field_validator("material", "sample", "process", "test", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object, info: ValidationInfo) -> object:
        items = _normalize_list_container(value)
        if not isinstance(items, list):
            return items
        normalized_items: list[object] = []
        for item in items:
            if isinstance(item, StructuredEvidenceAttribute):
                normalized_items.append(item)
                continue
            if isinstance(item, (str, int, float, bool)):
                normalized_items.append(
                    {"name": info.field_name, "value": item, "unit": None}
                )
                continue
            if not isinstance(item, dict):
                normalized_items.append(item)
                continue

            name = str(item.get("name") or info.field_name).strip()
            unit = item.get("unit")
            if "value" in item:
                attribute_value = item["value"]
                if isinstance(attribute_value, (dict, list)):
                    attribute_value = json.dumps(
                        attribute_value,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                normalized_items.append(
                    {"name": name, "value": attribute_value, "unit": unit}
                )
                continue

            details = {
                key: detail
                for key, detail in item.items()
                if key not in {"name", "unit"}
            }
            normalized_items.append(
                {
                    "name": name if details else info.field_name,
                    "value": (
                        json.dumps(
                            details,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                        if details
                        else name
                    ),
                    "unit": unit,
                }
            )
        return normalized_items


class StructuredEvidenceExtraction(_StrictModel):
    evidence_role: Literal[
        "direct_result",
        "condition_context",
        "mechanism_context",
        "baseline_context",
        "comparison_context",
        "background_context",
        "contradictory_result",
        "irrelevant",
    ] = "irrelevant"
    changed_variables: list[StructuredEvidenceVariable] = Field(
        default_factory=list,
        max_length=12,
    )
    comparison: StructuredEvidenceComparison | None = None
    reported_result: StructuredEvidenceResult | None = None
    attribution_scope: Literal[
        "isolated_effect",
        "joint_effect",
        "association_only",
        "descriptive_only",
        "not_attributable",
    ] = "not_attributable"
    scientific_context: StructuredEvidenceContext = Field(
        default_factory=StructuredEvidenceContext
    )
    resolution_status: Literal[
        "resolved",
        "partial",
        "unresolved",
        "skipped",
        "unknown",
    ] = "partial"
    confidence: float = 0.0

    @field_validator("evidence_role", mode="before")
    @classmethod
    def _normalize_evidence_role(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_ROLES,
            default="irrelevant",
        )

    @field_validator("attribution_scope", mode="before")
    @classmethod
    def _normalize_attribution_scope(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_ATTRIBUTION_SCOPES,
            default="not_attributable",
        )

    @field_validator("resolution_status", mode="before")
    @classmethod
    def _normalize_resolution_status(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_OBJECTIVE_EVIDENCE_RESOLUTION_STATUSES,
            default="partial",
        )

    @field_validator("changed_variables", mode="before")
    @classmethod
    def _normalize_changed_variables(cls, value: object) -> object:
        return _normalize_list_container(value)

    @model_validator(mode="after")
    def _validate_scientific_contract(self) -> "StructuredEvidenceExtraction":
        result_role = self.evidence_role in {"direct_result", "contradictory_result"}
        if result_role and self.reported_result is None:
            raise ValueError("result evidence requires one reported result")
        if not result_role and self.reported_result is not None:
            raise ValueError("context evidence cannot report an experimental result")
        if not result_role and self.attribution_scope in {
            "isolated_effect",
            "joint_effect",
        }:
            raise ValueError("context evidence cannot claim experimental attribution")
        if self.comparison is not None and not self.comparison.comparable:
            if self.attribution_scope != "not_attributable":
                raise ValueError("incomparable evidence cannot be attributed")
        variable_names = [
            item.name.casefold() for item in self.changed_variables
        ]
        if len(variable_names) != len(set(variable_names)):
            raise ValueError(
                "changed variable names must be unique per extraction"
            )
        if any(
            item.baseline_value is not None
            and item.target_value is not None
            and item.baseline_value == item.target_value
            for item in self.changed_variables
        ):
            raise ValueError(
                "changed variables require distinct baseline and target values"
            )
        if self.attribution_scope in {"isolated_effect", "joint_effect"}:
            if self.comparison is None or not self.comparison.comparable:
                raise ValueError("experimental attribution requires comparison")
            variables = set(variable_names)
            axes = {item.casefold() for item in self.comparison.axis_names}
            if variables != axes:
                raise ValueError("comparison axes must match changed variables")
            if any(
                item.baseline_value is None or item.target_value is None
                for item in self.changed_variables
            ):
                raise ValueError(
                    "experimental attribution requires baseline and target values"
                )
            if self.attribution_scope == "isolated_effect" and len(variables) != 1:
                raise ValueError("isolated effect requires one changed variable")
            if self.attribution_scope == "joint_effect" and len(variables) < 2:
                raise ValueError("joint effect requires multiple changed variables")
        return self


class StructuredEvidenceExtractions(_StrictModel):
    extractions: list[StructuredEvidenceExtraction] = Field(
        default_factory=list,
        max_length=1,
    )

    @field_validator("extractions", mode="before")
    @classmethod
    def _normalize_extractions(cls, value: object) -> object:
        return _normalize_list_container(value)


class StructuredFindingMechanism(_StrictModel):
    source_term: str = Field(min_length=1)
    relation_type: str = Field(min_length=1)
    target_term: str = Field(min_length=1)
    direction: str | None = None
    assertion_strength: Literal["causal", "associative", "descriptive"] = (
        "descriptive"
    )
    supporting_evidence_ids: list[str] = Field(min_length=1, max_length=16)

    @field_validator("source_term", "relation_type", "target_term")
    @classmethod
    def _require_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("finding mechanism terms cannot be blank")
        return text

    @field_validator("supporting_evidence_ids")
    @classmethod
    def _require_unique_evidence(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("finding mechanism evidence ids must be unique")
        return value

    @field_validator("assertion_strength", mode="before")
    @classmethod
    def _normalize_assertion_strength(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_FINDING_ASSERTION_STRENGTHS,
            default="descriptive",
        )


class StructuredFindingSynthesisItem(_StrictModel):
    assertion_strength: Literal["causal", "associative", "descriptive"] = (
        "descriptive"
    )
    context_evidence_ids: list[str] = Field(default_factory=list, max_length=24)
    mechanisms: list[StructuredFindingMechanism] = Field(
        default_factory=list, max_length=8
    )

    @field_validator("assertion_strength", mode="before")
    @classmethod
    def _normalize_assertion_strength(cls, value: object) -> str:
        return _normalize_underscored_choice(
            value,
            allowed=_FINDING_ASSERTION_STRENGTHS,
            default="descriptive",
        )

    @field_validator("context_evidence_ids")
    @classmethod
    def _require_unique_evidence(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("finding evidence ids must be unique within each role")
        return value


class StructuredFindingSynthesis(_StrictModel):
    findings: list[StructuredFindingSynthesisItem] = Field(
        default_factory=list,
        max_length=1,
    )

    @field_validator("findings", mode="before")
    @classmethod
    def _normalize_findings(cls, value: object) -> object:
        return _normalize_list_container(value)
