"""Canonical structured design shared by human and Agent research plans."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PlanVariableRole = Literal["independent", "control", "response", "covariate"]
PlanVariableBasis = Literal[
    "literature_derived",
    "proposed_for_validation",
    "expert_selection_required",
]


class ResearchPlanVariable(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=240)
    role: PlanVariableRole
    planned_values: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1, max_length=12)
    basis: PlanVariableBasis
    basis_evidence_ids: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list, max_length=12)

    @field_validator("planned_values")
    @classmethod
    def _normalize_values(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = value.casefold()
            if key not in seen:
                seen.add(key)
                result.append(value)
        return result

    @field_validator("basis_evidence_ids")
    @classmethod
    def _deduplicate_evidence_ids(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def _require_literature_basis(self) -> "ResearchPlanVariable":
        if self.basis == "literature_derived" and not self.basis_evidence_ids:
            raise ValueError(
                "literature-derived plan variables require at least one Evidence ID"
            )
        return self


class ResearchPlanStructure(BaseModel):
    """A complete proposed experiment, independent of its rendered Markdown."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    hypothesis: str = Field(min_length=1, max_length=2_000)
    variables: list[ResearchPlanVariable] = Field(min_length=1, max_length=12)
    controls: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1, max_length=12)
    fixed_conditions: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1, max_length=16)
    measurements: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1, max_length=16)
    replication: str = Field(min_length=1, max_length=2_000)
    analysis_method: str = Field(min_length=1, max_length=2_000)
    acceptance_criteria: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1, max_length=12)
    feasibility_checks: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1, max_length=12)
    safety_considerations: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1, max_length=12)
    limitations: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1, max_length=12)

    @field_validator(
        "controls",
        "fixed_conditions",
        "measurements",
        "acceptance_criteria",
        "feasibility_checks",
        "safety_considerations",
        "limitations",
    )
    @classmethod
    def _normalize_lists(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = value.casefold()
            if key not in seen:
                seen.add(key)
                result.append(value)
        return result


__all__ = [
    "PlanVariableBasis",
    "PlanVariableRole",
    "ResearchPlanStructure",
    "ResearchPlanVariable",
]
