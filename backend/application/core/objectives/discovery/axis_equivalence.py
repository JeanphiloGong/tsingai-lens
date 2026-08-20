from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from application.core.objectives.llm.structured_response import StructuredResponseClient

RESEARCH_AXIS_CANONICALIZATION_PROMPT_VERSION = "research_axis_canonicalization.v4"

_MAX_COMPLETION_TOKENS = 1024
_SYSTEM_PROMPT = """
You classify scientific-axis relationships for an evidence-backed literature comparison backend.

Non-negotiable rules:
- This is bounded pair classification, not objective generation or final fact extraction.
- Return exactly one JSON object and nothing else.
- Classify only the supplied labels; do not invent canonical labels, groups, or facts.
- Prefer a false relation over combining scientifically distinct interventions.
""".strip()


class _AxisEquivalenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class StructuredAxisPairDecision(_AxisEquivalenceResponse):
    pair_id: str = Field(min_length=1, max_length=80)
    equivalent: bool
    same_research_topic: bool

    @model_validator(mode="after")
    def _validate_relation_levels(self) -> StructuredAxisPairDecision:
        if self.equivalent and not self.same_research_topic:
            raise ValueError("equivalent axes must share one research topic")
        return self


class StructuredAxisCanonicalizationPlan(_AxisEquivalenceResponse):
    decisions: list[StructuredAxisPairDecision] = Field(default_factory=list)

    @field_validator("decisions", mode="before")
    @classmethod
    def _normalize_decisions(cls, value: object) -> object:
        return [] if value is None else value


def build_research_axis_canonicalization_prompt(
    payload: dict[str, Any],
) -> tuple[str, str]:
    user_prompt = (
        "TASK MODEL\n"
        "Classify the relationship between each candidate pair of neutral scientific "
        "axes before collection objective grouping. This is pair classification, not "
        "causal interpretation, direct-comparability judgment, objective wording, or "
        "evidence synthesis.\n\n"
        "INPUT SCHEMA\n"
        "- `collection_id` identifies the request and must not appear in output.\n"
        "- `axis_pairs` contains backend-selected possible aliases. Each item has an "
        "opaque `pair_id`, one `axis_type`, and exact `left` and `right` labels.\n"
        "- `material` pairs are material identities; `variable` pairs are changed "
        "factors; `outcome` pairs are measured or predicted responses.\n"
        "- Variable pairs may include `left_observations` and `right_observations`: "
        "bounded PaperStudy observations showing a limited varied-factor list plus "
        "process and sample context from studies where that exact label occurred. They "
        "help disambiguate scientific meaning and processing stage. They are incomplete, "
        "and co-occurrence is not topic evidence; a context value need not describe the "
        "specific axis.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. Judge every pair independently within its supplied axis_type. For a variable "
        "pair, first identify the controlled quantity and processing or sample stage named "
        "by each label. Use observations only to disambiguate those meanings.\n"
        "2. Set `equivalent=true` only when substituting one label for the other preserves "
        "the exact scientific question. Acronyms, spelling variants, and grammatical "
        "variants can qualify. Exact equivalence always requires "
        "`same_research_topic=true`.\n"
        "3. For `variable` pairs only, set `same_research_topic=true` when both factors "
        "belong to one focused experimental intervention: they describe different "
        "settings or components of the same deliberately controlled process step. A "
        "researcher should be able to place both in one compact question without "
        "combining different processing stages, sample geometry, material identity, "
        "mechanism descriptors, or response variables. This does not mean directly "
        "comparable; exact levels and fixed conditions remain later constraints.\n"
        "4. For non-equivalent `material` or `outcome` pairs, set "
        "`same_research_topic=false`. A candidate Objective keeps one specific outcome; "
        "related but distinct measurements must not be fused into one question.\n"
        "5. Set both fields false when the pair is unrelated or uncertain. Shared "
        "material, shared measured outcome, occurrence in the same paper, or the fact "
        "that both can influence a property is never sufficient topic evidence. A joint "
        "varied-factor list preserves confounding; it does not prove that all listed "
        "factors form one intervention topic.\n\n"
        "HARD RULES\n"
        "- Return one decision for every input pair, in input order.\n"
        "- Copy each input `pair_id` exactly once; do not omit, repeat, or invent IDs.\n"
        "- Each decision contains only `pair_id`, boolean `equivalent`, and boolean "
        "`same_research_topic`.\n"
        "- Do not return labels, canonical names, groups, explanations, or confidence.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- VED and volumetric energy density: equivalent=true and "
        "same_research_topic=true.\n"
        "- SS316L and 316L stainless steel: equivalent=true and "
        "same_research_topic=true.\n"
        "- Ti6Al4V and Ti-6Al-4V: equivalent=true and same_research_topic=true; "
        "Ti-64 is also the same alloy identity when used as that established grade.\n"
        "- SS316 and 316L stainless steel are different grades: reject by setting both "
        "fields false.\n"
        "- annealing temperature and annealing duration: equivalent=false but "
        "same_research_topic=true because both define one annealing schedule.\n"
        "- HIP cooling rate and cooling rate after HIP: equivalent=true when both name "
        "the same cooling-rate intervention.\n"
        "- annealing temperature and base-plate preheating temperature: both are "
        "thermal, but they belong to different processing stages; set both fields "
        "false.\n"
        "- scan speed and laser scanning speed: equivalent=true when both denote the "
        "same scan-speed factor. Laser power and scan speed can share one laser-exposure "
        "settings topic but are not equivalent.\n"
        "- Build orientation and laser speed: set both fields false. Build orientation "
        "and laser power: set both fields false. Alloy composition and post-processing "
        "condition, fabrication process and post-processing condition, and alpha-phase "
        "fraction and aging time also require both fields false. These labels may "
        "co-occur or affect the same outcome but do not name one focused intervention.\n"
        "- porosity and relative density are related but distinct measurements: set both "
        "fields false so each can anchor its own focused outcome.\n"
        "- mechanical properties is a broad property family, not an alias for yield "
        "strength, elongation, hardness, fatigue, corrosion, or microstructure: never "
        "equivalent and never a focused outcome topic.\n"
        "- microstructure and grain size, or porosity and defect size: set both fields "
        "false; the narrower measurement must remain visible.\n"
        "- tensile strength and ultimate tensile strength: not equivalent without source "
        "context explicitly defining the same measurement, so set both fields false.\n"
        "- surface hardness and hardness: not equivalent because surface scope is "
        "meaningful; set both fields false.\n"
        "\n"
        "OUTPUT CONTRACT\n"
        "Return only schema-valid structured data with one `decisions` array. "
        "The array must account for every input pair even when all decisions are false.\n"
    )
    return _SYSTEM_PROMPT, user_prompt


class ResearchAxisEquivalenceClassifier:
    """Classify exact axis identity and focused variable-topic membership."""

    def __init__(self, response_client: StructuredResponseClient) -> None:
        self.response_client = response_client

    def classify(
        self,
        payload: dict[str, Any],
    ) -> StructuredAxisCanonicalizationPlan:
        system_prompt, user_prompt = build_research_axis_canonicalization_prompt(
            payload
        )

        def validate_axis_accounting(response: BaseModel) -> None:
            if not isinstance(response, StructuredAxisCanonicalizationPlan):
                raise TypeError(
                    "unexpected research axis canonicalization response type"
                )
            _validate_axis_candidate_accounting(
                response,
                axis_pairs=payload.get("axis_pairs"),
            )

        def build_repair_instruction(repair_detail: str) -> str:
            return (
                "Previous axis pair classification was invalid: "
                f"{repair_detail}. Return one decision for every input pair_id, in "
                "input order, without omissions or duplicates. Return both booleans. "
                "Set equivalent=true only for the exact same scientific axis, and then "
                "also set same_research_topic=true. Only non-equivalent variable pairs "
                "from one controlled process or sample stage may share a focused topic. "
                "Co-occurrence in observations is not sufficient. Non-equivalent material "
                "and outcome pairs require both booleans false. Return only compact JSON."
            )

        def parse_json_text_with_contract(
            **kwargs: Any,
        ) -> tuple[BaseModel, str | None]:
            return self.response_client.complete_json(
                **kwargs,
                repair_instruction_builder=build_repair_instruction,
                parsed_validator=validate_axis_accounting,
            )

        response = self.response_client.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=StructuredAxisCanonicalizationPlan,
            max_completion_tokens=_MAX_COMPLETION_TOKENS,
            json_text_parser=parse_json_text_with_contract,
            parsed_validator=validate_axis_accounting,
            task_type="research_axis_canonicalization",
            prompt_version=RESEARCH_AXIS_CANONICALIZATION_PROMPT_VERSION,
        )
        if not isinstance(response, StructuredAxisCanonicalizationPlan):
            raise TypeError("unexpected research axis canonicalization response type")
        return response


def _validate_axis_candidate_accounting(
    response: StructuredAxisCanonicalizationPlan,
    *,
    axis_pairs: Any,
) -> None:
    if not isinstance(axis_pairs, list):
        raise TypeError("axis pair selection requires axis_pairs")
    expected_ids = [
        str(pair.get("pair_id") or "").strip()
        for pair in axis_pairs
        if isinstance(pair, Mapping) and str(pair.get("pair_id") or "").strip()
    ]
    decision_ids = [decision.pair_id for decision in response.decisions]
    if decision_ids != expected_ids:
        raise ValueError(
            "axis pair decisions must account for every input pair_id exactly once "
            "and in input order"
        )


__all__ = [
    "ResearchAxisEquivalenceClassifier",
    "StructuredAxisCanonicalizationPlan",
    "StructuredAxisPairDecision",
    "build_research_axis_canonicalization_prompt",
]
