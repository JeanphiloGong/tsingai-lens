from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

PAPER_OBJECTIVE_CANDIDATE_OUTPUT_LIMITS = {
    "material_scope": (8, 80),
    "process_context": (4, 80),
    "variables": (4, 80),
    "outcomes": (8, 80),
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
