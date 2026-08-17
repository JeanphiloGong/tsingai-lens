from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from application.core.objectives.extraction import ObjectiveExtractor

RESEARCH_AXIS_CANONICALIZATION_PROMPT_VERSION = (
    "research_axis_canonicalization.v1"
)

_MAX_COMPLETION_TOKENS = 1024
_SYSTEM_PROMPT = """
You are building research-objective records for an evidence-backed literature comparison backend.

Non-negotiable rules:
- This is research-map extraction, not final fact extraction.
- Return exactly one JSON object and nothing else.
- Do not emit measurement results, sample variants, evidence anchors, backend ids, or source locators.
- Do not infer material systems from filenames.
- Prefer fewer, higher-signal outputs over speculative coverage.
- Research objectives must be question-shaped. Do not return a plain material list.
""".strip()


class _AxisEquivalenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class StructuredAxisPairDecision(_AxisEquivalenceResponse):
    pair_id: str = Field(min_length=1, max_length=80)
    equivalent: bool


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
        "Classify whether each candidate label pair names exactly the same neutral "
        "scientific axis before collection objective grouping. This is pair "
        "classification, not "
        "property-family clustering, causal interpretation, objective discovery, or "
        "evidence synthesis.\n\n"
        "INPUT SCHEMA\n"
        "- `collection_id` identifies the request and must not appear in output.\n"
        "- `axis_pairs` contains backend-selected possible aliases. Each item has an "
        "opaque `pair_id`, one `axis_type`, and exact `left` and `right` labels.\n"
        "- `material` pairs are material identities; `variable` pairs are changed "
        "factors; `outcome` pairs are measured or predicted responses.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "DECISION PROCESS\n"
        "1. Judge every pair independently within its supplied axis_type.\n"
        "2. Set `equivalent=true` only when substituting one label for the other preserves "
        "the exact scientific question. Acronyms, spelling variants, and grammatical "
        "variants can qualify.\n"
        "3. Set `equivalent=false` when the labels are merely related, inverse, causal, "
        "broad/narrow, jointly reported, different material grades, or different "
        "process parameters.\n"
        "4. Set `equivalent=false` when uncertain. This keeps both source labels.\n\n"
        "HARD RULES\n"
        "- Return one decision for every input pair, in input order.\n"
        "- Copy each input `pair_id` exactly once; do not omit, repeat, or invent IDs.\n"
        "- Each decision contains only `pair_id` and boolean `equivalent`.\n"
        "- Do not return labels, canonical names, groups, explanations, or confidence.\n\n"
        "BOUNDARY EXAMPLES\n"
        "- VED and volumetric energy density: select; they are the same variable.\n"
        "- SS316L and 316L stainless steel: select; they are the same material grade.\n"
        "- SS316 and 316L stainless steel are different grades: reject.\n"
        "- scan speed and laser scanning speed: select when both denote the scan-speed "
        "factor; laser power and energy density: reject.\n"
        "- porosity and relative density are scientifically related but distinct "
        "measured outcomes: reject.\n"
        "- mechanical properties is a broad property family, not an alias for yield "
        "strength, elongation, hardness, fatigue, corrosion, or microstructure: reject.\n"
        "- microstructure and grain size, or porosity and defect size: reject; one is "
        "broader than the other.\n"
        "- tensile strength and ultimate tensile strength: reject without source "
        "context explicitly defining them as the same measurement.\n"
        "- surface hardness and hardness: reject; surface scope is meaningful.\n"
        "\n"
        "OUTPUT CONTRACT\n"
        "Return only schema-valid structured data with one `decisions` array. "
        "The array must account for every input pair even when all decisions are false.\n"
    )
    return _SYSTEM_PROMPT, user_prompt


class ResearchAxisEquivalenceClassifier:
    """Classify backend-selected scientific label pairs as equal or different."""

    def __init__(self, response_client: ObjectiveExtractor) -> None:
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
                "input order, without omissions or duplicates. Set equivalent=true "
                "only when both labels name exactly the same scientific axis. Related, "
                "inverse, broad, narrow, or uncertain pairs require equivalent=false. "
                "Return only compact JSON."
            )

        def complete_json(**kwargs: Any) -> tuple[BaseModel, str | None]:
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
            json_text_parser=complete_json,
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
        raise ValueError("axis pair selection requires axis_pairs")
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
